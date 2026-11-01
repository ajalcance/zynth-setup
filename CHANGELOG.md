# Changelog

Releases of the **zynth-setup template**. What an adopter's project receives on `copier update`
is the point of every entry; changes to this repository's own tooling are listed separately.
Each release's annotated tag carries the full notes and names the green self-test run on the
tagged commit. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
[Semantic Versioning](https://semver.org/): copier serves adopters the highest tag, so a
version must sort above the one before it.

## [Unreleased]

### Security — Next.js 16.4.2 in the generated frontend and docs-site

- **Every project generated from 3.2.1 or 3.3.0 with the frontend or docs-site module pins
  Next.js 16.3.5, which has three critical, unauthenticated remote-code-execution advisories**
  (image optimization with SVG files, `use cache` functions returning typed arrays, and
  `next/og`), plus cache poisoning, SSRF and denial-of-service advisories. All are fixed from
  16.4.1. `next` and `eslint-config-next` move to **16.4.2**. A freshly generated project failed
  its own `npm audit --omit=dev --audit-level=high` gate (3 production vulnerabilities, 1
  critical); it passes now.
- Lockfile-only updates close the rest: `sharp` 0.35.5 with libvips 1.3.4 (librsvg), `source-map-js`
  1.2.2, `zod` 4.6.7, and in the frontend's dev tree `vite` 7.3.7 (kept on 7: the 8.x line is a
  major bump, not a security fix), `vitest` and `@vitest/mocker` 4.1.12. A full `npm audit`, dev
  dependencies included, reports 0 in both apps. Every version moved is at least 14 days old.
- **On update:** `package.json` and `package-lock.json` change in both apps; run `npm ci`.
  Nothing else changes. If you cannot update yet, a project on 3.3.0 or earlier should not serve
  Next.js image optimization or `use cache` to untrusted users.

### Security — black 26.10.1 in the generated backend's dev requirements

- `black` 26.5.1 → **26.10.1** (GHSA-cg8m-r9f2-5wm2 / CVE-2026-114134: Black's GitHub Action
  installed whatever version a pull request wrote into `tool.black.required-version`). The
  template installs black from pip and does not use that Action, so the advisory does not reach a
  generated project's CI; the pin moves so no audit of the shipped requirements reports it. No
  shipped file is reformatted: black 26.10.1 leaves all 56 Python files under `template/`
  unchanged. **On update:** re-install the dev requirements.

### Template repository (no change for adopters)

- **`make advisories` audits what the template ships, with no CI in the loop.** It runs
  `npm audit` on a copy of each template lockfile (dev dependencies included) and `pip-audit`
  over every shipped Python pin, prints how many packages and pins it inspected, exits 1 on a
  failing finding and 2 when it could not look. It fails on a high or critical npm advisory
  anywhere, on any severity in a production dependency, and on any Python pin; a moderate or low
  advisory in the dev tree only is a counted, printed *notice* (the line the generated gate
  draws, so an unfixable dev advisory cannot make the check permanently red). The release
  procedure now requires it clean on the commit you tag. Its first run found `black` 26.5.1
  pinned against GHSA-cg8m-r9f2-5wm2. Backlog T25, C5; `scripts/check_advisories.py`, 51 tests,
  45 mutants killed.

## [3.3.0] — 2026-09-26 — no bot approves its own guard change; the hooks read commands as the shell does

### The agent's Bash hooks read a command line as the shell does

- **Far fewer false refusals.** The confinement hook split on `|` and `;` before it read
  quotes, so `grep -n "a\|b" f`, `git log --format='%h|%s'` and `"$(x | y)"` were refused as
  "unbalanced quotes". The dangerous-command hook matched its rules across the whole line, so
  `rm -rf build && cp x .` was a delete of `.`, a PR title containing "main" made a feature
  push a push to main, and a commit message that mentioned `--no-verify` was refused as using
  it. Both now share one quote-aware parser (`.claude/hooks/_shell.py`) and judge one command
  at a time.
- **Changes they used to miss are now caught:** a destructive command inside `$(...)`,
  backticks, `bash -c` or `eval`; one behind `nice`/`nohup`/`time`/`env`; `git commit -n` and
  `-an` (short for `--no-verify`, which the old rule only matched in an impossible position);
  `rm --recursive --force` spelled long; and a push to `main` given as `HEAD:main`.
- **A `cd` moves only the commands after it.** Every command used to be judged against the
  line's LAST `cd`, so `rm -rf build && cd /tmp` was refused and a command before a `cd` was
  judged in the wrong place.
- Unchanged in direction: the confinement hook still refuses a line it cannot parse, and the
  dangerous-command hook still falls back to its raw-line rules — and asks about gh/git.

### Dependabot no longer approves its own guard changes

- Your `.github/dependabot.yml` labelled scanner bumps `guardrail-change` — the owner's consent
  label, which the meta-guard reads and passes. A bot applying it approved its own change to
  what judges every pull request. Bumps to guards (workflows, `requirements-ci.txt`, the hook
  SHAs) are now **flagged `needs-owner`**: they arrive red on the meta-guard and pass once you
  have read them and applied `guardrail-change` yourself.
- Dependabot now updates the **pre-commit hook SHAs** too — the config promised it, and no
  ecosystem did it.
- `scripts/bootstrap-repo.sh` provisions every label Dependabot applies (`needs-owner` and the
  ecosystem labels); GitHub silently drops a label that does not exist.
- `pre-commit` was pinned at 4.6.2 for CI and 4.6.1 for local development; now one version, and
  a guard fails if any tool is pinned at two.
- **On update:** re-run `scripts/bootstrap-repo.sh` once to create `needs-owner`. Any open
  Dependabot PR still carrying `guardrail-change` was never approved by you — review it, or
  close it and let Dependabot re-propose.

## [3.2.1] — 2026-09-25 — dev-dependency advisories, and a repository that follows its template

### Security — dev dependencies in the generated frontend and docs-site

- vitest 3.2.7 → 4.1.11 (GHSA-82fw-gwwq-j7x9, fixed only in 4.x), js-yaml 4.3.0 → 4.3.2,
  browserslist 4.28.6 → 4.29.1 and brace-expansion to patched releases, in both lockfiles. All
  dev-only, so no production bundle changes (one browser-support data table refreshed); a full
  `npm audit`, dev included, now reports 0 in both apps. **On update:** the frontend's
  `vitest` devDependency moves from `^3` to `^4`; the shipped tests and config run unchanged.

### Template repository (no change for adopters)

- The repository now follows the template it ships: `make check` (lint, policy, fault tests)
  runs locally and in CI; a `ci-complete` aggregate check; pinned self-test tools; the secret
  scan with canary over this repository's history; pre-commit hooks, Dependabot and Scorecard;
  a committed agent policy with the template's hooks; a guard-label check; `make verify` for
  generating and gating every variant; CLAUDE.md, ADRs, lessons and a template backlog;
  rulesets for `main` and release tags, applied by `scripts/bootstrap-repo.sh`.
- Dependabot no longer applies `guardrail-change` to its own guard bumps — it flags them
  `needs-owner`, and the guard check stays red until the owner consents. Its updates now cover
  the template's pins too, grouped so a shared bump moves root and template in one PR; a test
  holds every shared tool and hook to the template's version.
- `scripts/check-jinja-syntax.sh` refused nothing without jinja2 installed (it printed SKIPPED
  and passed) and never parsed directory names, where the module toggles live. Both fixed.

## [3.2.0] — 2026-09-25 — the agent cannot approve its own change

- The Claude Code policy reads `gh` and `git push` commands token by token: applying a label CI
  reads as the owner's consent, or removing `release-blocker`, is refused in every spelling; a
  force push is refused wherever the flag sits; deleting a remote ref, publishing a tag and any
  mutating `gh api` call ask. The agent's own settings files are denied, and no shell command
  may change anything under `.claude/`. Venv tools allowed by name, never the interpreter.
- **Behaviour change on update:** commands that ran silently may now ask or be refused.
- Template self-test fixed for pull-request events and for the post-v3.1.0 update gate.

## [3.1.0] — 2026-09-24 — CI integrity at scale

- A live secret scan with a canary; Semgrep community rules that block on new findings;
  actionlint + zizmor + hadolint as `make infra-lint`; runtime-version drift and Dependabot
  coverage tested in the project; post-merge reuse of a proved tree; the owner tier of
  questions has no defaults; the twelve-point quarterly audit.
- **On update:** projects generated with an empty `author_name`/`author_email` must pass them
  once.

## [3.0.2] — 2026-09-21

- No change for generated projects over 3.0.1: the first v3 tag whose own self-test passed.
  Frontend builds pinned to webpack (Turbopack wedged under QEMU).

## [3.0.1] — 2026-09-21

- Next.js 16.3.5 — **3.0.0 carries a critical unauthenticated RCE advisory; do not use it.**
- Secret-write hook fixtures no longer trip the adopter's own secret scanner.

## [3.0.0] — 2026-09-21 — the adopter-feedback pass

- Closes a three-week adopter audit of 2.0.2: six defects live in every generated project
  (a forgeable required check, two fail-open guards, pin-guard holes, ADRs ungated, a ratchet
  counting itself, Edit-only permission rules), CI hardening, structural gates, and the
  permission model (`confine_to_project`, `approved_scope`).
- **Breaking:** `deploy/verify.sh --tag`; the client-events ADR moved 0011 → 0012; `make check`
  gained `policy` and `harness`.

## [2.0.2] — 2026-08-22

- The client-telemetry boundary, hardened by adversarial review (21 findings closed).

## [2.0.1] — 2026-08-21

- Day-one-red frontend advisories fixed; migration fidelity against PostgreSQL; tracked files
  matched by ignore rules no longer vanish from local generations.

## [2.0.0] — 2026-08-01 — engineering process and control system

- Eight phases: contracts and enforcement markers, guard fault tests, static policy and the
  anti-weakening ratchet, memory governance, agent permissions, the experience loop, the
  standards suite, the release evidence chain.

## [1.0.0] — 2026-07-26

- First stable release: fail-closed FastAPI + Next.js skeletons, agent-resistant guardrails,
  signed-image deploys, docs-as-code, and the self-test release gate.
