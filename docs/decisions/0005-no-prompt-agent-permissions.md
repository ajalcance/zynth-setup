# 0005. Nothing asks: the agent's actions run or are refused, and the owner approves at the PR

Date: 2026-09-26

## Status

Accepted. Supersedes point 3 of ADR 0002 (a change to what judges the agent here asks locally).

## Context

Until now a change to what judges the agent here asked first: `.claude/`, `.github/`,
`scripts/`, `tests/`, the `Makefile` and the pins, 44 `ask` rules in all. The hooks asked too,
about a tag push, deleting a remote ref, a mutating `gh api` call, and `gh label`. In practice:

- **A prompt is a control only while someone is watching.** The owner answered prompts all
  day, most of them for edits whose real gate was already the pull request: CI's
  `guard-label` check fails any change to those paths until the owner adds
  `guardrail-change`.
- **The prompts were never the boundary.** Since ADR 0004, every command and every process it
  starts runs inside an OS sandbox. That is what limits reads, writes and the network, prompt
  or no prompt.
- **An ask that is answered unread approves anything.** Confirmation fatigue is how that
  happens, and it is what template ADR-0007 was written to prevent.

The owner's No-Prompt Agent Permissions model, worked out on zynth-creatives on the same day,
names five layers that hold without anyone watching: the OS sandbox, the permission deny list,
the hooks, managed settings, and CI with the branch rules.

## Decision

1. **Nothing asks.** `.claude/settings.json` has no `ask` rules. Its allow list is the tools
   themselves (`Read`, `Glob`, `Grep`, `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, `Bash`),
   bounded by the deny list, the hooks and the sandbox. Bypass-permissions mode is no longer
   disabled.
2. **The owner's acts are refused outright**, not asked about. The owner runs them from their
   own terminal, with commands the agent prepares:
   - tags and releases, including every spelling of a tag push (`--tags`, `--follow-tags`, a
     `refs/tags/` refspec);
   - merging a pull request;
   - every label, whether through `gh label`, a flag, or `gh api`;
   - repository, secret, variable and ruleset settings;
   - dispatching or toggling a workflow;
   - publishing a package.
3. **So are the irreversible and the out-of-scope:**
   - force pushes, deleting a remote ref, `reset --hard`, `git clean`;
   - `--no-verify`, `core.hooksPath` and `--admin`, wherever the flag sits;
   - `ssh`, `scp`, `sudo`, `docker`, and piping `curl` or `wget` into a shell.
4. **The agent's own policy is denied to every write tool:** all of `.claude/`, settings and
   hooks alike. Secret files are denied at any depth.
5. **The hooks never ask** (`CLAUDE_HOOKS_NEVER_ASK=1` in the settings' `env`, template ADR-0007's
   amendment). What they asked about is now refused. The scope hook, which exists to ask, is
   not registered here.
6. **What stopped asking is gated at the pull request.** Every path that used to ask is one
   `scripts/check_guard_label.py` refuses to pass without the owner's label, except `.claude/`,
   which is stricter still: denied.
7. **Held by a test.** `tests/test_agent_policy.py` fails if:
   - an `ask` rule comes back, or the allow list holds anything but whole tools;
   - any of 37 owner-only or irreversible commands would run, or any of 13 everyday
     commands would be refused;
   - a flag rule is anchored at the start of the command, where it can never match;
   - a command rule needs arguments after it (`npm publish *` never matched a bare
     `npm publish`; the test found that on its first run);
   - a path that stopped asking is not label-gated;
   - bypass mode is allowed without the switch, the hooks and the deny list that make it safe.

## Consequences

- The agent works without interrupting the owner. The owner's attention goes to what only the
  owner can do: labels, merges, releases and settings.
- Deny rules are globs over the command line, and the command line is not the only way to act:
  a script the agent writes and runs can still call `gh`. What bounds that is the sandbox (no
  personal credentials, one repository's token, no admin or secrets scope), the rulesets and
  CI. A fine-grained token is still the owner's account to GitHub, and only a separate machine
  account separates the two (backlog C3).
- Some reads are refused along with the writes: `git tag --list`, `gh release list` and
  `gh repo view` all fail. The agent reads the same facts another way (`git describe --tags`,
  `gh api repos/…`) or asks the owner.
- **The template keeps its ask model.** No-prompt is safe only with an OS sandbox, and the
  template cannot assume one. Offering it to adopters as an opt-in is backlog T22.
- **Applying it is the owner's act.** The agent cannot write its own settings. The owner
  copies the file into place, restarts the session, and chooses Bypass permissions; the agent
  then runs the checks both ways.
