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

## Add a new prompt

Add the question to `copier.yml`, then use it in the relevant `.jinja` files. Keep sensible
defaults so `--defaults` generation stays green.

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
  - ⬜ **E4** — artifact integrity: cosign keyless sign + SLSA provenance; deploy verifies by digest.
  - ⬜ **E5** — runtime containment for the dev agent + an auth scaffold that populates the spine's
    actor/principal.
