# Template backlog

What the template itself should gain, found while running this repository on its own standard
(ADR 0002, rule 13 of CLAUDE.md). Each item names where it was found and the adopter-facing
weakness. Items leave this file when they ship, with the release that shipped them.

## Found dogfooding (2026-09-25)

| ID | Adopters' weakness | Found by |
|---|---|---|
| T3 | No workflow invariant forbids a step `env:` override of a default `GITHUB_*`/`RUNNER_*` variable. GitHub silently ignores it. | The self-test's policy step, broken on the first PR |
| T4 | Nothing flags `.claude/settings.local.json` growing or picking up broad allows (`git push *`, `Bash(*)`). An audit point, or a hook warning. | This repo's local file: 199 allows |
| T5 | A gate keyed to "the previous release" changes meaning at tag time; the release procedure should re-verify after tagging. | The copier-update gate, broken by the v3.1.0 tag |
| T8 | The meta-guard's `GUARD_FILE_RE` does not name `.claude/` (the agent's own policy and hooks), `tests/guards/` or the `Makefile`: an agent can weaken any of them with no owner label. | Writing `scripts/check_guard_label.py` |
| T9 | The confinement hook blocks writes to the agent's session scratch directory, which Claude Code provides outside the project. Consider honouring `permissions.additionalDirectories`. | This repo's session |
| T15 | Dependabot security updates ignore `cooldown` (GitHub's design), so a security PR can propose a release published hours earlier — #21 proposed vitest 5.0.2, published that morning. Adopters' Dependabot does the same. Document it; the owner-consent flag (T12) is what makes such a PR get read. | Dependabot PR #21 |
| T16 | GitHub moves `ubuntu-latest` to Ubuntu 26 on 2026-10-19. Every shipped workflow and this repository's CI run on it. Pin or test ahead of the switch rather than learn about it from a red scheduled run. | A CI annotation on the v3.2.1 run |
| T17 | `docker/setup-buildx-action` and `docker/setup-qemu-action` target Node 20, which GitHub has deprecated and now forces to Node 24. Bump both where the template ships them (`release.yml`) and here. | A CI annotation on the v3.2.1 run |
| T18 | The confinement hook reads a `sed -i` script as a file path: `sed -i '' 's/a$/b/' f` is refused because the script holds a `$`. Skip the script argument (the first non-option word, or each `-e` value). | Preparing the v3.3.0 release |

## Carried over

| ID | Item |
|---|---|
| C1 | The frontend multi-arch image build hangs to its 20-minute timeout intermittently (2 of 7 runs) under QEMU. |
| C2 | Image scanning, SBOM and provenance attestations for the deploy module (audit point 12 says they are not shipped). |
| C3 | A separate GitHub identity for the agent — the only complete fix for self-approval; the meta-guard could then check *who* applied a label. |
| C4 | Tell adopters generated before v3.1.0 with an empty `author_name`/`author_email` to pass them once on update. |

## Shipped

| ID | What | Release |
|---|---|---|
| T14 | Eight dev-only advisories in the frontend/docs-site lockfiles; vitest ^4. | v3.2.1 |
| T6 | Adopters' Dependabot gains the `pre-commit` ecosystem their hook SHAs were promised. | v3.3.0 |
| T12 | Adopters' Dependabot flags guard bumps `needs-owner` instead of applying the consent label; the flag is provisioned. | v3.3.0 |
| T13 | pre-commit pinned at one version across the template's manifests, and a guard that compares every manifest. | v3.3.0 |
| T7 | Both Bash hooks share a quote-aware parser (`_shell.py`): no more "unbalanced quotes" on ordinary reads; `cd` applied in order; substitutions, wrappers and `sh -c` looked inside. | v3.3.0 |
| T11 | Each dangerous-command rule reads one command's own words. Also caught two missed blocks: `git commit -n`/`-an` and `rm --recursive --force`. | v3.3.0 |
| T1 | Adopters get a tag ruleset: `v*` release tags can never be deleted, updated or force-moved. | next release |
| T2 | Adopters' bootstrap enables secret scanning, push protection and Dependabot alerts + security updates, saying so when the plan does not allow one; merge settings match the ruleset. | next release |
| T10 | The undocumented ruleset parameter is gone, and a test holds the pull-request rule to documented parameters. | next release |
