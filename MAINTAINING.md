# Maintaining `zynth-setup`

How this template is structured and how to evolve it.

## Layout

```
copier.yml                 the questionnaire + Copier config (_subdirectory: template)
template/                  the payload — everything stamped into a generated project
  ...                      files ending in .jinja are rendered; others are copied verbatim
LICENSE / README.md        the template repo's own license + usage
MAINTAINING.md             this file
```

- **Rendered files** end in `.jinja` (Copier's `_templates_suffix`). Use `{{ variable }}` and
  `{% if %}` inside them.
- **Verbatim files** have no `.jinja` suffix — used where the content contains `{{ }}` that must
  survive (e.g. GitHub Actions `${{ }}` in `template/.github/workflows/ci.yml`).
- **Dynamic paths** — a directory/file named `{{ python_package }}` is renamed at generation time.

## Add or change a template file

1. Edit under `template/`. If it needs a variable or conditional, give it a `.jinja` suffix.
2. **Test by generating a project** (see below) and running its gates. A generated project must
   pass `make check` + `make dod-check` **out of the box** — that is the acceptance bar.

## Test the template locally

```bash
pipx install copier          # or: uv tool install copier
# generate into a temp dir with sample answers:
copier copy --defaults --trust \
  --data project_name="Demo App" --data github_owner="you" \
  --data author_name="You" --data author_email="you@example.com" \
  . /tmp/gen-demo
cd /tmp/gen-demo/backend && python -m venv .venv && . .venv/bin/activate \
  && pip install -r requirements.txt -r requirements-dev.txt \
  && cd .. && make check && make dod-check
```

Try variants too: a different `--data python_package=svc`, `--data license=MIT`, and the optional
toggles once their payloads exist.

**Before pushing, run the repository's own gate:**

```bash
make venv            # once: a root .venv with the pinned tools (requirements-selftest.txt)
make hooks-install   # once: the same pre-commit hooks the template ships, run on every commit
make check           # hooks + lint + policy + test — the same target CI's `repo` job runs
```

`make check` is what this repository asks of itself, held to the rules it ships: ruff and black
on the root harness, shellcheck, actionlint and zizmor on the workflows, the secret scan with its
canary over this repository's history, unicode hazards, exact pins, the two checks below, the
owner-tier check, and fault tests for every root guard (`tests/`). `scripts/secret_scan.py` and
`scripts/check_unicode_hazards.py` are byte-identical copies of the template's — change the
template's and copy it over; `tests/test_vendored_copies.py` fails on any drift.

The two checks that matter most **before generating from a locally modified tree** (both are
in `make policy`):

```bash
./scripts/check-tracked-ignores.sh
./scripts/check-jinja-syntax.sh
```

Copier's dirty-repo flow re-stages the worktree against an empty index, so a tracked file
matched by any ignore rule (including `template/.gitignore`, whose rules also apply inside this
repo) is silently missing from every local generation — while CI, which generates from a clean
checkout, stays green. This script is the same check CI runs (`template-test.yml`); it caught
`.env.example.jinja` being dropped for weeks. If it fails, un-ignore or rename the file — never
generate around it.

`check-jinja-syntax.sh` parses every template body and every templated path. Copier reports a
broken template as `TemplateSyntaxError: Missing end of comment tag` with no filename and a line
number into the rendered stream, which sends you through 190 files by hand; this names the file
and the line. The trap that motivated it: Jinja opens a comment on `{` immediately followed by
`#`, and the shell's array-length form is exactly that — a valid shell script became an
unterminated comment and generation failed for the whole template. Write a counter variable
instead. Same family as never interpolating a copier value into a linted line.

## Add a new prompt

Add the question to `copier.yml`, then use it in the relevant `.jinja` files. Two kinds:

- **A preference** gets a sensible default, so `--defaults` generation stays green.
- **The owner's decision** gets no default and a validator, joins `OWNER_TIER` in
  `scripts/check-owner-questions.py`, is named in `_message_before_copy`, and gets an answer in
  `.github/self-test-owner.yml`. The check fails, naming the question, if any of those is
  missed — a question with no default that nothing answers breaks every self-test generation,
  including the copier-update gate that only generates from it once it is in a release.

## Update a template lockfile

The frontend and docs-site lockfiles ship to every adopter who enables those modules. Three
traps, each met on 2026-09-25 (T14):

1. **npm cannot run inside the template directory.** Its name contains `{% if ... %}`, and npm
   decodes the `%` as a URI escape ("URI malformed"). Work in a copy under `.copier-test/`:

   ```bash
   mkdir -p .copier-test/fe-work
   cp "template/{% if include_frontend %}frontend{% endif %}/package"*.json .copier-test/fe-work/
   ```

2. **npm 10.9's peer resolver crashes** (`reading 'edgesOut'`) on a major bump such as vitest
   3 → 4. Resolve with npm 11 (`npx --yes npm@11 install`), which writes the same lockfile
   format; then prove the result with the npm adopters run — `npm ci` under Node 22's npm 10,
   in a generated project.
3. **Audit everything, not only production.** The gate runs `npm audit --omit=dev`, so dev-only
   advisories never turn it red; before copying the lockfile back, `npm audit` must report 0
   with dev included. Take a patched version that has been public at least 7 days — Dependabot's
   security updates ignore the cooldown and once proposed a release published that morning.

Copy only `package.json` and `package-lock.json` back, list every version the diff moved
(production entries especially), and run `make verify` plus the frontend and docs-site gates
in the generated full project.

## Check what the template ships for advisories

```bash
make advisories    # needs node on PATH, the network, and `make venv` (for pip-audit)
```

It audits each template lockfile (on a copy, dev dependencies included — npm cannot run in a
`{% %}` directory) and each shipped Python pin file with the Jinja control lines dropped, so
every optional module's pins are checked. It prints how many packages and pins it inspected and
exits 1 on a failing finding, 2 when it could not look (no npm, a registry error, nothing to
inspect); never read a 2 as "fine".

**What fails, and what is a notice.** The line is the generated project's own gate
(`--audit-level=high`, third adopter review): an npm advisory fails the run when it is high or
critical anywhere, or of any severity in a production dependency; a moderate or low advisory in
the dev tree only is a *notice* — printed in full, counted in the verdict, not a failure. Every
Python pin finding fails. A notice is a decision waiting for you, not noise: read it, and if it
has no fix, record why in the backlog (see C5) rather than overriding a dependency's range.
GitHub's own alert count is larger than this list: it raises one alert per manifest, so every
advisory on a package in both apps' `package.json` and `package-lock.json` is four alerts.

**Run it weekly and before every release.** CI cannot be the only thing that tells you: in
October 2026 the template shipped Next.js with three critical RCEs for three weeks because the
one scheduled run that would have noticed could not run (Actions was locked for billing) and
Dependabot's pull requests sat unread. It is not part of `make check` because it needs the
network and the advisory databases move without a commit.

Pins are audited directly (`--no-deps`): the template pins nothing else, and an unpinned
transitive version is the adopter's install. A finding is fixed in its own change with the
7-day rule above; a bump of a guard file needs the owner's `guardrail-change` label.

## Propagate template updates to existing projects

Generated projects record their answers in `.copier-answers.yml`. In such a project:

```bash
copier update      # pulls template improvements, three-way-merging local changes
```

Tag template releases so projects can pin/update to a known version.

## Roadmap

- ✅ **Phase A** — Copier skeleton + always-on framework (docs, CI, gates, backend skeleton, governance).
- ✅ **Phase B** — optional stack modules behind the toggles:
  - `include_deploy` → `deploy/` (Docker Compose + Caddy, parameterized by `server_host`).
  - `include_frontend` → `frontend/` (green Next.js 15 app).
  - `include_docs_site` → `docs-site/` (green Next.js app that renders `../docs` Markdown).
- ✅ **Phase C** — the optional compliance/observability spine (`include_compliance_spine`):
  telemetry → cold store → hash-chained audit + detection/control catalogs, with **four CI
  coverage-guards** and one example instrumented action. Wires conditionally into config, main,
  conftest, models, requirements, and the docs.
- ✅ **Phase D** — Copier post-gen `_tasks` (git init, backend venv + deps, `pre-commit install`)
  + `_message_after_copy`, and a **CI self-test** (`.github/workflows/template-test.yml`) that
  generates minimal **and** full projects and runs their gates on every change. **Note:** because
  the template has tasks, generation requires `copier copy --trust` (Copier's safety model).
- 🚧 **Phase E** — agent-resistant guardrails (ADR-0004), for the "AI writes & deploys, no human
  reviews the diff" workflow. Every item stays green-on-day-one and is proven to fail-closed:
  - ✅ **E1** — enforcement outside the repo: branch ruleset (`template/.github/rulesets/main.json` +
    `scripts/bootstrap-repo.sh`), a `ci-complete` required-check aggregator, and a scoped
    `CODEOWNERS` (review the guardrails, trust the features). One-time setup in `ONBOARDING.md`.
  - ✅ **E2** — erosion watch: OSSF Scorecard (`scorecard.yml` + `scripts/scorecard_gate.py`, curated
    subset, PAT-aware) + a meta-guard (`scripts/meta_guard.py` + `pr-policy` job: suppression ratchet
    & code-without-test, both label-escapable) folded into `ci-complete`, a `pytest --cov` floor
    (70%, in pyproject), and all workflow actions SHA-pinned.
  - ✅ **E3** — dependency integrity: a `deps` pin-guard (`scripts/check_pins.py`, in `ci-complete`)
    enforces exact pins so no floating spec can drift; JS stays deterministic via `npm ci` +
    lockfile integrity. Socket.dev (behavioural analysis, block mode) is a one-click App install
    documented in `ONBOARDING.md` (+ how to make its check required).
  - ✅ **E4** — artifact integrity: `release.yml` builds on a `v*` tag → pushes to GHCR → **cosign**
    keyless sign + SLSA provenance; the deploy stack pulls signed images (`deploy/verify.sh`
    fail-closed) instead of building on the host, with `docker-compose.override.yml` for local builds.
  - ✅ **E5** — runtime containment + auth: a `.devcontainer/` sandbox with a **default-deny egress
    firewall** (`init-firewall.sh`, self-verifying/fail-closed) so agent-run code can't exfiltrate;
    and (spine) an **auth scaffold** (`backend/<package>/auth/`, signed bearer token → `Principal`)
    that records the real actor on every telemetry event — anonymous → `system`, forged token → 401.
- ✅ **Phase F (v3.0.0)** — the adopter-feedback pass. A project generated from v2.0.2 ran for
  three weeks and audited the gap; its findings are the whole of this phase. Six defects live in
  every generated project (a forgeable required check, two guards that passed while inspecting
  nothing, three holes in the pin guard, ADRs gated nowhere, a suppression ratchet counting its
  own source, protected paths guarded against `Edit` only), the CI hardening behind them
  (trigger types, cancellation, cooldown, timeouts, the bandit exclusion that excluded nothing,
  pinned scanners), the structural layer (`check_guard_coverage.py`, `check_unicode_hazards.py`,
  `make policy`, `make harness`, a denominator on every gate, the readiness verdict bound to the
  signed artifact — ADR-0011), and the permission model (`confine_to_project.py`,
  `approved_scope.py`, and the reconciliation test between the lists that answer "which paths
  need a human?").

  Three habits it is all in service of, and the ones to preserve when changing any of it:
  **the denominator rule**, **the experience registry**, and **the meta-guard**.

## Repository settings (owner, once)

`scripts/bootstrap-repo.sh` applies what cannot live in a file an agent can edit: the rulesets
in `.github/rulesets/` (main takes pull requests only, requires `ci-complete` and `guard-label`,
bypassed by nobody; release tags can never be deleted or re-pointed), the labels, secret
scanning with push protection, Dependabot alerts and security updates, and rebase-only merges.
It is idempotent — re-run it after changing a ruleset file. `tests/test_rulesets.py` checks the
files; only running the script changes GitHub.

## Releasing

The policy is ADR [0003](docs/decisions/0003-releases-and-versioning.md); this is the procedure.

1. **Pick the version.** Three components, above the latest tag (`git tag --sort=-version:refname
   | head -1`). Copier serves adopters the highest tag, so anything that sorts lower is a release
   nobody receives. Major when an update needs action beyond `copier update`; minor when an
   adopter will notice behaviour change; patch otherwise.
2. **Run `make advisories` on the commit you mean to tag; it must be clean.** What the template
   ships goes stale without a commit, and a release publishes whatever is stale. (Details below.)
   Then **merge to `main` through a pull request** and wait for the push self-test on that exact
   commit to go green — including the image builds and the copier-update gate, which run on
   push only.
3. **Move `[Unreleased]` in `CHANGELOG.md` under the new version** (its own small PR).
4. **Tag the green commit**, annotated, naming the run:

   ```bash
   git tag -a vX.Y.Z <sha> -m "vX.Y.Z — <one line>" -m "<notes>. Self-test green on this commit (run <id>)."
   git push origin vX.Y.Z
   ```

5. **Publish the GitHub Release** from the tag, with the CHANGELOG entry as the body.
6. **Confirm adopters receive it**: generate from `https://github.com/ajalcance/zynth-setup.git`
   with no `--vcs-ref`; `.copier-answers.yml` must record `_commit: vX.Y.Z`.
7. **Re-check the self-test on `main`** — its copier-update gate now starts from the new tag.

A published tag is never re-pointed or deleted; the tag ruleset refuses it. A bad release is
superseded by the next one.
