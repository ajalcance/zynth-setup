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
- **A control system that says what it actually enforces** ([ADR-0006](template/docs/decisions/0006-engineering-process-and-control-system.md)) —
  every control carries an honest marker: `[CI]` means a gate catches it today, `[Review]` means
  nothing will. Claiming automation you don't have is itself a build failure.
- **Guard fault tests** — negative tests proving each guard can still fail, because a check that
  silently stops inspecting anything reports green forever.
- **Guard coverage** — every guard must have a fault test *and* something that actually invokes
  it. A guard nobody wired in sits in `scripts/` looking like a control, cited as one, having
  never run.
- **A denominator on every gate** — each one prints what it inspected and fails on an empty
  required set, so "nothing to report" and "nothing was looked at" can never print the same line.
- **One definition of the gate set** — `make policy`, which CI invokes rather than relisting.
  Two lists mean a gate can be added to one and forgotten in the other.
- **A readiness verdict bound to the artifact** ([ADR-0011](template/docs/decisions/0011-readiness-belongs-to-the-artifact.md)) —
  recorded inside the signed release evidence, because a scan run at promotion time describes the
  default branch rather than the release, and a check against the wrong tree looks like a control.
- **An engineering standards suite** with stable, citable rule ids (`BE-004`, `SEC-010`, …), each
  declaring how it is really enforced ([ADR-0009](template/docs/decisions/0009-standards-suite-with-honest-enforcement.md)).
- **An experience-to-control loop** — recorded lessons on a five-rung enforcement ladder, retrieved
  by diff ([ADR-0008](template/docs/decisions/0008-experience-to-control-loop.md)).
- **An agent permission model** — routine work runs unprompted; policy, release and destructive
  actions ask; secret reads are denied ([ADR-0007](template/docs/decisions/0007-agent-permission-model.md)).
- **A release evidence chain** — a fail-closed preflight, build-once signed candidates with SBOMs,
  a digest-pinned signed record of what shipped, and promotion that never rebuilds
  ([ADR-0010](template/docs/decisions/0010-release-evidence-chain.md)).

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

Install [Copier](https://copier.readthedocs.io/). On a clean machine you need the *installer*
first — a fresh macOS box has neither `pipx` nor `uv`:

```bash
# macOS
brew install uv && uv tool install copier

# Linux
sudo apt install pipx && pipx install copier

# no package manager? plain Python works:
python3 -m venv ~/.venvs/copier && ~/.venvs/copier/bin/pip install copier
```

`uv` and `pipx` install binaries to `~/.local/bin`, which is **not** on macOS's default `PATH`.
If you get `copier: command not found`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Copier itself needs Python 3.9+ (separate from the generated project's Python 3.12).

Then generate:

```bash
copier copy --trust gh:ajalcance/zynth-setup my-new-project
cd my-new-project
```

### Non-interactive (headless / AI-driven) generation

The prompts need a TTY, so an agent or a script passes answers with `--data`. Two tiers:

- **The owner tier has no defaults.** Owner, maintainer of record, contact address, license,
  and whether there is one maintainer or two are the *owner's* decisions. `--defaults` will
  not fill them: without them Copier refuses and writes nothing (the self-test proves it).
  Enabling `include_deploy=true` adds `server_host` to that tier.
- **Everything else** has a default or can be inferred from the request (name, slug, package,
  which optional modules).

```bash
copier copy --trust --defaults \
  --data project_name="My New Project" \
  --data github_owner="your-org" \
  --data author_name="Your Name" \
  --data author_email="you@example.com" \
  --data license="Apache-2.0" \
  --data solo_maintainer=true \
  --data include_frontend=false \
  --data include_docs_site=false \
  --data include_deploy=false \
  --data include_compliance_spine=false \
  gh:ajalcance/zynth-setup my-new-project
```

#### If you are an AI agent generating this for someone

The owner-tier answers are not yours to invent, and the template will not let you skip them.
Before running Copier, ask the owner these questions in plain words and pass their answers:

| Ask | Key | What follows from the answer |
|---|---|---|
| Which GitHub org or user will own the repository? | `github_owner` | CODEOWNERS, `gh repo create` |
| Who is the maintainer of record, and where should security reports go? | `author_name`, `author_email` | SECURITY.md, CODE_OF_CONDUCT.md |
| Apache-2.0 or MIT? | `license` | `LICENSE` |
| Are you the only maintainer? | `solo_maintainer` | **yes:** merges gate on green CI, code-owner review is advisory. **no:** every guardrail change needs a second human's review (GitHub forbids approving your own PR) |
| Where does it deploy? (only with `include_deploy=true`) | `server_host` | deploy config and docs |

Do not answer these from the README's examples; `your-org` is a placeholder and a guard test
in the generated project rejects it. Copier prints the same list before the first question,
including under `--defaults`. The answers are recorded in the generated `ONBOARDING.md` and
in `.copier-answers.yml`; the closing message prints the resulting posture.

### Before you generate

Three things that bite on a fresh machine, in the order you meet them:

- **Python 3.12 must be on `PATH` first.** A current macOS may have only 3.14, and the
  virtualenv task picks whatever `python3` resolves to. `uv python install 3.12` and put its
  directory first, or the backend is built against the wrong interpreter.
- **Node 22.** The frontend gate pins it; a machine on 23 fails the build. `nvm use` reads the
  `.nvmrc` the template ships, or install `node@22` and put it on the path.
- **The first push to `main` is the one exception to the branch rule.** The root commit has
  nowhere else to go, and the local hook will refuse it — push that one by hand, then work in
  branches from then on.

`--defaults` fills anything outside the owner tier. Enabling `include_deploy=true` also requires
`--data server_host=<ip-or-domain>`.

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

Projects generated before v3.1.0 may have recorded an empty `author_name` or `author_email`
(those questions had defaults then). The owner tier now refuses an empty answer, so the first
update from such a project must pass them once: `copier update --trust --data
author_name="..." --data author_email="..."`. They are recorded and not asked again.

For this to work, `.copier-answers.yml` must point at the **GitHub source**, not a local path.
Always generate from `gh:{{ github_owner }}/zynth-setup` (a full clone or the `gh:` shorthand) —
generating from a temporary local clone records that path as `_src_path`, and updates break once
the directory is gone. If you must use a local clone, do a **full** clone, not a shallow one, or
Copier can't reason about template version history.

See [`MAINTAINING.md`](MAINTAINING.md) for how the template is structured and how to evolve it.

## Adopting into an existing (non-empty) repository

Copier's post-generation tasks assume a fresh, empty destination — they run `git init` and stage
everything. To add the framework to an existing repo, generate into a **separate empty directory**
first, review the output, then copy in what you want (excluding `.git/` and any build artifacts).
`make check` runs the same either way.

## Local TLS note (deploy module)

The deploy stack's Caddy uses `tls internal` — a self-signed local certificate — so the **first**
browser visit to a local `https://` URL shows a trust warning; accept it for local use. Production
behind a real domain gets a genuine certificate automatically. The ingress binds to `127.0.0.1` by
default (set `BIND_HOST=0.0.0.0` in `.env` to expose it), so a local `docker compose up` is not
reachable from your network.

## License

This template is licensed under [Apache-2.0](LICENSE). Generated projects get the license you choose at prompt time (Apache-2.0 by default).
