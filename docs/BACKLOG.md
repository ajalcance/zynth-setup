# Template backlog

What the template itself should gain, found while running this repository on its own standard
(ADR 0002, rule 13 of CLAUDE.md). Each item names where it was found and the adopter-facing
weakness. Items leave this file when they ship, with the release that shipped them.

## Found dogfooding (2026-09-25)

| ID | Adopters' weakness | Found by |
|---|---|---|
| T1 | The shipped ruleset protects `main` only. Tags are unprotected, yet `release.yml` publishes on a tag — a release tag can be deleted or re-pointed. | Auditing this repo's settings |
| T2 | `template/scripts/bootstrap-repo.sh` enables no secret scanning, push protection or Dependabot alerts — every adopter likely has them off. | Same audit (public repo, all three off) |
| T3 | No workflow invariant forbids a step `env:` override of a default `GITHUB_*`/`RUNNER_*` variable. GitHub silently ignores it. | The self-test's policy step, broken on the first PR |
| T4 | Nothing flags `.claude/settings.local.json` growing or picking up broad allows (`git push *`, `Bash(*)`). An audit point, or a hook warning. | This repo's local file: 199 allows |
| T5 | A gate keyed to "the previous release" changes meaning at tag time; the release procedure should re-verify after tagging. | The copier-update gate, broken by the v3.1.0 tag |
| T6 | `template/.pre-commit-config.yaml` says Dependabot updates its hook SHAs, but `template/.github/dependabot.yml` has no `pre-commit` ecosystem. Adopters' hooks never update. | Writing this repo's Dependabot config |
| T7 | `confine_to_project.py` splits on `\|`/`;` before parsing quotes: `grep "a\|b" f`, `"$(x \| y)"` and `--format='a\|b'` are refused as unbalanced quotes — false positives on everyday reads. | The hook, live in this repo's own session |
| T8 | The meta-guard's `GUARD_FILE_RE` does not name `.claude/` (the agent's own policy and hooks), `tests/guards/` or the `Makefile`: an agent can weaken any of them with no owner label. | Writing `scripts/check_guard_label.py` |
| T9 | The confinement hook blocks writes to the agent's session scratch directory, which Claude Code provides outside the project. Consider honouring `permissions.additionalDirectories`. | This repo's session |
| T10 | The shipped ruleset's `pull_request` rule sets `require_extra_approval_for_unattributed_changes`, which GitHub's REST reference does not document: either the bootstrap is refused or the setting is silently ignored. Verify against the live API; keep only documented parameters, with a test. | Writing this repo's ruleset |
| T11 | `block_dangerous_bash.py`'s older regex rules scan the WHOLE command line: `git push -u origin feat/x && gh pr create --title "main takes PRs only"` is refused as a direct push to main, and `feat/main-fix` matches `\bmain\b`. They should run per simple command, like the v3.2 token pass. | The hook, live in this repo's own session |
| T12 | `template/.github/dependabot.yml` labels the scanner bumps `guardrail-change` — the owner's consent label. A bot applying it approves its own guard change and the meta-guard passes. Flag with a label no workflow reads, and let the check stay red until the owner applies consent. | Dependabot's first PRs here arrived pre-approved |
| T13 | The template pins `pre-commit` twice at different versions: 4.6.2 in `requirements-ci.txt`, 4.6.1 in `backend/requirements-dev.txt.jinja`. One version per tool, tested. | Writing `tests/test_shared_pins.py` |

## Carried over

| ID | Item |
|---|---|
| C1 | The frontend multi-arch image build hangs to its 20-minute timeout intermittently (2 of 7 runs) under QEMU. |
| C2 | Image scanning, SBOM and provenance attestations for the deploy module (audit point 12 says they are not shipped). |
| C3 | A separate GitHub identity for the agent — the only complete fix for self-approval; the meta-guard could then check *who* applied a label. |
| C4 | Tell adopters generated before v3.1.0 with an empty `author_name`/`author_email` to pass them once on update. |
