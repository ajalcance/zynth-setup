# CLAUDE.md — working on the zynth-setup TEMPLATE repository

This repository is a Copier template. `template/` is the product: every file an adopter's
project is generated from, including its own CLAUDE.md (`template/CLAUDE.md.jinja`), which is
the contract for work *inside a generated project*. **This** file is the contract for work on
the template itself. `AGENTS.md` points here; `MAINTAINING.md` is the how-to.

The repository holds itself to what it ships. Every rule below either is a rule the template
enforces on adopters, or was learned the hard way here. Where a rule has a check, the check is
named; where it has none, say so rather than assume one exists.

## 1. Source of truth

1. `docs/decisions/` — this repository's own decisions (the template's decisions for adopters
   live in `template/docs/decisions/` and are part of the product).
2. This file.
3. `MAINTAINING.md`, then the code.

If two disagree, the higher one wins and the lower one is a bug — fix it in the same change.

## 2. Rules

1. **Fix first, then commit.** Every known defect is fixed and verified before a commit. Full
   implementations only; close the class of a bug, not the one instance you saw.
2. **Verify before committing.** `make check` for anything. For any change under `template/`,
   also `make verify`: it generates full, minimal and hooks-off from the working tree and runs
   each project's hooks, policy, harness, sast, infra-lint, audit and guard tests. Never
   declare "verified" from a subset — the time the generated project's own hooks were skipped,
   two blank lines reached CI.
3. **A guard change is its own pull request.** Never adjust a guard to make a change pass;
   never bundle a guard fix into the work it blocked. A PR touching a guard needs the owner's
   `guardrail-change` label (`scripts/check_guard_label.py`). **The agent never applies that
   label** — the session hook refuses it — and never removes `release-blocker`.
4. **Every guard gets a fault test, and mutants.** Break the guard on purpose and watch a test
   fail. A surviving mutant is a missing test, not a lucky guard.
5. **Print a denominator.** A check that reports success must say how much it inspected. "OK"
   over zero files is the failure mode every guard here was built against.
6. **Jinja hazards.**
   - A conditional block at the end of a `.jinja` file must not be followed by a newline, or
     the rendered file ends in a blank line and the adopter's first commit is refused.
   - Never interpolate a copier value into a line a formatter or linter checks (Python, TSX):
     use a short constant, or JSON with `| tojson`.
   - `{` followed by `#` opens a Jinja comment — the shell's array-length form is exactly that.
     `scripts/check-jinja-syntax.sh` names the file and line.
7. **ADR numbering stays contiguous in every variant.** A conditional ADR leaves a gap in the
   minimal variant; ship an unconditional stub instead (see 0012 in `template/docs/decisions`).
8. **The owner's decisions have no defaults.** A copier question that is the owner's to answer
   gets no default, a validator, a line in `_message_before_copy` and an answer in
   `.github/self-test-owner.yml`. `scripts/check-owner-questions.py` enforces all four.
9. **GitHub ignores a step's `env:` override of `GITHUB_*` / `RUNNER_*` variables.** Unset one
   with `env -u NAME` in the run line. `tests/test_repo_policy.py` fails on the attempt.
10. **A gate keyed to "the previous release" changes meaning when you tag.** Re-check the
    self-test after every release, not only before it.
11. **Copies of template guards are byte-identical.** `scripts/secret_scan.py`,
    `scripts/check_unicode_hazards.py` and `.claude/hooks/*.py` are copies (they locate the
    repository from their own path). Change the template's, then copy. Tests fail on drift.
12. **Scratch work goes in `.copier-test/`**, inside the project. The confinement hook refuses
    changes outside it. One exception: inside the agent's OS sandbox, `make verify` generates
    under `$TMPDIR`, because the sandbox refuses a generated project's `.git/config`, hooks
    and `*.pem` files anywhere under the project. It prints where it writes.
13. **Every defect found here is a question about the template.** Does an adopter have the same
    weakness? Record it in `docs/BACKLOG.md` in the same change.

## 3. Releasing

- Tag from `main` only, after the push self-test on that exact commit is green. The annotated
  tag's message names the run.
- A version must sort above the latest tag: copier serves adopters the highest tag by default,
  so `v0.3.1` after `v3.1.0` is a release nobody receives. Confirm with a generation from the
  GitHub URL and no `--vcs-ref`: it must record the new tag.
- **A published tag is never re-pointed.** A wrong release is superseded by the next one.
- Record the release in `CHANGELOG.md` and as a GitHub Release. Details: `MAINTAINING.md`.

## 4. The agent's permissions here

`.claude/settings.json` is the template's permission model, split for what this repository
is: a change to what judges the agent **here** (root `.claude/`, `.github/`, `scripts/`,
`tests/`, `Makefile`, pins, hooks) **asks**; a change to what judges **adopters** (the guards
under `template/`) is gated at the pull request by the owner's label. The settings files are
denied; bypass mode is off. ADR 0002 has the reasoning.

## 5. Commits

Conventional commits. The subject says what was wrong, not only what changed. The body says
what was verified and how. End with the co-author trailer the session provides.
