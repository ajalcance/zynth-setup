# 0007. Low-friction agent permission model

Date: 2026-07-31

## Status

Accepted.

## Context

`.claude/settings.json` previously carried only hooks. Everything else fell back to Claude Code's
default prompting, which produces the worst of both worlds: an agent is interrupted constantly for
routine work (running the gate, committing, reading files), and the *interesting* actions — tagging
a release, merging with `--admin`, editing a guard script — arrive as one more prompt in a long
stream of prompts that the operator has been trained to approve reflexively.

Confirmation fatigue is not a cosmetic problem. It is the mechanism by which a genuinely dangerous
action gets waved through, because it looked like the fifty benign ones before it.

## Decision

Classify actions by **authority**, not by risk-of-typo:

- **allow** — routine work with no lasting authority: run the gate, tests, formatters, ordinary
  git (`status`/`diff`/`add`/`commit`/`switch`/`push` of a feature branch), read-only `gh`.
- **ask** — anything that changes policy, releases, or state outside the working tree: edits to
  `.claude/`, `.github/`, `scripts/`, `tests/guards/`, scanner configs, `Makefile`, `CLAUDE.md`,
  `AGENTS.md`, `deploy/`; tagging and releasing; destructive git (`--force`, `reset --hard`,
  `clean`, `rebase`); `rm -rf`; repository/secret/ruleset mutation via `gh`; Docker; `sudo`/`ssh`;
  and installing dependencies.
- **deny** — reading real secret material (`.env`, `*.pem`, `*.key`, SSH private keys). Note
  `.env.example` stays readable: it is the documented placeholder file.

Additionally `permissions.disableBypassPermissionsMode: "disable"`, and
`.claude/settings.local.json` is gitignored.

`--admin` is blocked in the **PreToolUse hook**, not as a permission rule.

## Rationale

- **Precedence is deny → ask → allow, first match wins, and specificity does not reorder it.** A
  broad deny therefore cannot carry an allowlist exception, so deny is reserved for things with no
  legitimate form. Everything conditional is `ask`, where a broad allow plus a targeted ask gives
  exactly the desired result — the ask wins.
- **`--admin` belongs in the hook because permission rules are globs, not regexes.** The flag can
  appear at any position in a command, which a glob cannot reliably match. A `PreToolUse` hook that
  exits 2 is also evaluated *before* permission rules, so an allow rule cannot undo it.
- **The settings gate edits to themselves** (`Edit(./.claude/**)` is `ask`), consistent with
  ADR-0004: an agent should not be able to quietly widen its own authority.
- **`.claude/settings.local.json` is ignored** so a machine-local override can never become
  necessary to the team workflow, nor a quiet way to weaken the shared policy.

## Amendment (v3): the hook does the asking

Two things learned since, both from a project running this model at scale.

**Globs cannot confine an agent.** Precedence is deny → ask → allow and the patterns are
globs, so "everything except this folder" is not expressible: any deny broad enough to protect
the rest of the machine also blocks the project. The dangerous-command hook named `/`, `~` and
`$HOME`, which left every sibling project directory fair game — and changing directory first
issues no single token that looks dangerous. `.claude/hooks/confine_to_project.py` resolves
`~`, `..`, and any `cd` in the same command line *before* deciding. Only changes are confined;
reading elsewhere is how an assistant learns from another project.

**A hook's `allow` loses to a static `ask`.** This is the expensive one. A scope mechanism that
returned `allow` correctly, verified by hand with a hundred passing assertions, waived nothing
for a whole day because a static `ask` rule outranked it — while an ADR and two other documents
described it as live. Its tests ran the hook directly and asserted its verdict; nothing
exercised the path from a real tool call, through the permission system, to a silent edit. A
control tested at the point it is easiest to test rather than the point it has to hold.

So the design is inverted. For the core paths a scope may cover there is **no static `ask` rule
at all**, and `.claude/hooks/approved_scope.py` returns `ask` unless an active scope covers the
path. Its failure direction is inverted from every other hook here: it is the only thing asking
about those paths, so every error must become `ask`.

**Approval moves to the unit of work.** Per-file prompts are right for an unplanned edit to a
guard and wrong for an approved programme: six agents once produced roughly 1,500 prompts for
work the owner had already approved, and approving a thousand prompts is not approving
anything. A scope names the work, cites the decision it serves, gives a reason, lists its paths
and expires. It is stricter than what it replaces — written down and citable, narrower than a
blanket rule, self-lapsing, unable to touch `.claude/`, and unable to reach a system-altering
path except by naming it.

**Choose the failure direction before writing the control.** Every way of being sloppy with a
scope produces *more* asking. A permission mechanism whose bugs produce more asking is one you
can afford to be wrong about.

**Prompts that are always approved are not controls.** Most prompts came from the unlisted, not
the dangerous — file utilities, the venv's own tools, `npx`. Clicking through each one trains
reflexive approval and destroys the signal on the prompts that matter. The rule now: allow what
the gates govern, ask for the core, and deny the never-acceptable so it needs no click either.

## Consequences

- Routine work stops prompting, so a prompt becomes informative again — it means *authority*.
- This policy governs **Claude Code only**. Other agents and tools keep their own host-enforced
  permission systems; they share this repository's GitHub and CI controls, which is where the
  fail-closed enforcement actually lives.
- **This is a strong default, not an unbypassable control.** Project settings sit below
  higher-precedence scopes, so `disableBypassPermissionsMode` here can be overridden by a user's
  own settings or by managed settings. It is `[Review]`-grade, and the control map says so.
  The load-bearing enforcement remains the branch ruleset and `ci-complete`, which live in repo
  settings an agent cannot reach.
- Working in the `.devcontainer` sandbox is the intended place for looser prompting, since its
  default-deny egress firewall bounds the blast radius. Relax it there, not on the host.
