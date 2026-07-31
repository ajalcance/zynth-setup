# BE — Backend standards (Python)

Applies to `backend/`. Enforcement markers are explained in [`README.md`](README.md); the
**Mechanism** column names what enforces a rule, and is empty when nothing does.

## Structure

| ID | Rule | Enforcement | Mechanism |
|---|---|---|---|
| BE-001 | A source file targets ≤ 300 lines and must not exceed 400. Over that, split by concern rather than scrolling. | `[Review]` | — |
| BE-002 | A function stays under ~50 lines. A function that needs a section comment inside it wants to be two functions. | `[Review]` | — |
| BE-003 | Cyclomatic complexity per function stays at or below 10. | `[CI]` | ruff C90 in `backend/pyproject.toml` |
| BE-004 | Every public function and method is fully typed; `mypy --strict` passes with no new ignores. | `[CI]` | `backend/pyproject.toml` |
| BE-005 | Business logic lives in a service module and data access in the db layer. Route handlers stay thin. | `[Review]` | — |
| BE-006 | No dead code, commented-out blocks, or `.bak` files are committed. Deleted code is recoverable from git. | `[Review]` | — |
| BE-007 | Helpers that only one caller needs stay private to that module rather than joining a shared utils pile. | `[Review]` | — |

## Language and tooling

| ID | Rule | Enforcement | Mechanism |
|---|---|---|---|
| BE-010 | Formatting is `black` at line length 100. Formatting is never argued about, only run. | `[CI]` | `backend/pyproject.toml` |
| BE-011 | Linting is `ruff` with E, F, I, B, UP, N, S and C90 selected. | `[CI]` | `backend/pyproject.toml` |
| BE-012 | I/O is async-first. A blocking call inside an async handler stalls the event loop for every other request. | `[Review]` | — |
| BE-013 | Prefer the ORM over hand-written SQL; reach for raw SQL only where the ORM genuinely cannot express the query. | `[Review]` | — |
| BE-014 | Raw SQL must not contain `DROP`/`TRUNCATE`, or a `DELETE`/`UPDATE` with no `WHERE` clause. | `[CI]` | `.semgrep/dangerous-ops.yml` |
| BE-015 | Every runtime dependency is exactly pinned — `==` or a hash, never a floating range a resolver could bump silently. | `[CI]` | `scripts/check_pins.py` |
| BE-016 | Configuration is read once through the settings object, never from the environment scattered through the code. | `[Review]` | — |
| BE-017 | Outside `development` the config validator requires real secrets and raises. There is no insecure fallback. | `[Review]` | — |

## Data and migrations

| ID | Rule | Enforcement | Mechanism |
|---|---|---|---|
| BE-020 | A schema change ships as an Alembic migration in the same change as the model edit, never a follow-up. | `[Review]` | — |
| BE-021 | A migration is approved by the owner before merge — it rewrites stored data, and that outlives the PR. | `[CI]` | `scripts/meta_guard.py` |
| BE-022 | A migration fails loudly rather than half-applying, and says what state it expects to find. | `[Review]` | — |
