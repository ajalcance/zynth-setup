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

- **Phase B** — optional stack modules (frontend, docs-site, deploy) behind the toggles.
- **Phase C** — the optional compliance/observability spine.
- **Phase D** — Copier post-gen tasks, a CI self-test that generates + gates a project.
