# zynth-setup

> **A Copier template for starting a new project with the whole engineering framework already wired.**

Stamp out a new repository that ships, on day one, with:

- **AI working contract** — `CLAUDE.md` / `AGENTS.md`, the after-every-change Definition-of-Done ritual, coding standards.
- **Docs-as-code system** — architecture blueprint + as-built page, ADRs, roadmap, lessons log, dual-audience (external/internal) doc skeletons.
- **CI/CD + security gates** — lint, format, strict type-check, SAST (Semgrep), secret scanning (gitleaks), dependency audit, tests, and **doc-consistency guards** that fail the build if docs drift from code.
- **Pre-commit / pre-push gates** — gitleaks, private-key detection, hygiene hooks.
- **A fail-closed backend skeleton** (FastAPI) whose `make check` is **green out of the box**.

Optional modules (prompted): a Next.js **frontend**, a **docs site**, a **deploy** stack (Docker Compose + Caddy), and a **compliance/observability spine** (telemetry → audit → coverage-guards).

## Use it

Install [Copier](https://copier.readthedocs.io/) (`pipx install copier` or `uv tool install copier`), then:

```bash
copier copy --trust gh:ajalcance/zynth-setup my-new-project
cd my-new-project
```

`--trust` is required because the template runs post-generation setup tasks (`git init`, create the
backend venv + install deps, install the pre-commit hook). Answer the prompts (project name, owner,
license, which optional modules); Copier stamps a renamed, ready-to-commit repo and sets it up.

Then verify the gate is green:

```bash
make check && make dod-check   # green on a fresh project (venv already created by --trust)
```

Prefer to set up yourself? Generate without `--trust` is refused when tasks are present — omit them by
running an older ref, or just run the setup manually:

```bash
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt -r requirements-dev.txt
```

## Update an existing project when the template improves

Copier records your answers in `.copier-answers.yml`, so you can pull framework upgrades later:

```bash
copier update --trust   # in the generated project's repo root
```

See [`MAINTAINING.md`](MAINTAINING.md) for how the template is structured and how to evolve it.

## License

This template is licensed under [Apache-2.0](LICENSE). Generated projects get the license you choose at prompt time (Apache-2.0 by default).
