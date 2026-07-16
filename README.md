# zynth-setup

> **A Copier template for starting a new project with the whole engineering framework already wired.**

## Why this exists

Most project templates assume a human reviews every line before it ships. This one is built for a
different reality:

> **The AI writes and ships most of the code, and a human does *not* review every line.
> So the safety rails — not the code — are the real product.**

Everything here follows from that. The checks **fail closed** (when in doubt, stop rather than let
something risky through), and the guardrails are made **agent-resistant** — an AI assistant can't
quietly switch them off to make its work pass, because enforcement lives on the server (branch
ruleset + required reviews), not in a file the agent can edit. The full reasoning is in
[ADR-0004](template/docs/decisions/0004-agent-resistant-guardrails.md).

## Who it's for

- **A good fit if:** you're a solo dev or small team building a backend-heavy service with
  AI assistance, where **auditability, compliance, or security matter** and you want the guardrails
  to catch mistakes you won't personally review. Non-technical builders welcome — every generated
  project ships a plain-language [`OVERVIEW`](template/docs/OVERVIEW.md.jinja) and
  [`GLOSSARY`](template/docs/GLOSSARY.md).
- **Probably overkill if:** you're building a throwaway prototype, a one-off script, or a spike you
  intend to delete. The discipline here pays off over a project's life; it's friction on a weekend hack.

## What you get, on day one

- **AI working contract** — `CLAUDE.md` / `AGENTS.md`, the after-every-change Definition-of-Done ritual, coding standards.
- **Docs-as-code system** — architecture blueprint + as-built page, ADRs, roadmap, lessons log, dual-audience (external/internal) doc skeletons.
- **CI/CD + security gates** — lint, format, strict type-check, SAST (Semgrep), secret scanning (gitleaks), dependency audit, tests, and **doc-consistency guards** that fail the build if docs drift from code.
- **Pre-commit / pre-push gates** — gitleaks, private-key detection, hygiene hooks.
- **A fail-closed backend skeleton** (FastAPI) whose `make check` is **green out of the box**.

### Choosing your optional modules

Copier prompts you for these. Defaults are conservative — say yes only to what you need; you can
add a module later with `copier update`. Each one is independent.

| Module | What it adds | Turn it on when… | It commits you to… |
|---|---|---|---|
| **frontend** | A Next.js web UI (`frontend/`) with its own lint/type/build gate | your service needs a user-facing web interface | maintaining JS/TS tooling + its CI gate |
| **docs site** | A published documentation website (`docs-site/`) | you want human-friendly docs hosted for others | a second Next.js app to keep building |
| **deploy** | Docker Compose + Caddy stack, and **signed-image** production deploys (cosign) | you're ready to run this on a real server | a deploy target host + the signing/verify flow |
| **compliance spine** | Tamper-evident audit log + coverage-guards proving every action is recorded, monitored, audited | you must *prove* what the system did (audits, regulated data) | writing each new action to satisfy 4 coverage guards |
| **Claude hooks** *(on by default)* | Local Claude Code convenience hooks: auto-format + block footguns/secret writes | you use Claude Code and want faster feedback | nothing — pure local ergonomics; CI is unchanged |

Not sure? Start minimal (all off except Claude hooks). The base framework — AI contract, docs
system, CI/security gates, backend skeleton — is always included. Every generated project also
ships a plain-language **[`docs/OVERVIEW.md`](template/docs/OVERVIEW.md.jinja)** and
**[`docs/GLOSSARY.md`](template/docs/GLOSSARY.md)** so a non-technical builder (and their AI
assistant) can understand what each part does and why.

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
