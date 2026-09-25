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

## Releasing

Tag from `main` only. `v3.0.0` is a MAJOR bump: `deploy/verify.sh` takes `--tag` instead of a
list of images and requires the signed evidence beside it, the conditional client-events ADR
moved from 0011 to 0012, and `make check` now includes `policy` and `harness`.
