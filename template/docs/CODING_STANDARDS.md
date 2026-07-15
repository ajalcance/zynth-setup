# Coding Standards

Enforced by CI (`make check`) and code review. The summary lives in [`../CLAUDE.md`](../CLAUDE.md) §3.

## Structure

- **File length:** target ≤ 300 lines, hard cap **400**. Over → split by concern.
- **Function length:** ≤ 50 lines. Cyclomatic complexity ≤ 10 (ruff `C90`).
- **One router per resource.** Route handlers are thin; business logic lives in `services/`, data
  access in the DB layer. No fat controllers.
- **No dead code, no `.bak` files, no commented-out blocks** committed.

## Python

- **Type everything.** `mypy --strict` passes. No untyped public functions.
- **Formatting:** `black` (line length 100). **Linting:** `ruff` (E, F, I, B, UP, N, S, C90).
- **Security:** `bandit` clean; `pip-audit` clean. Never `eval`/`exec`, `shell=True`, or unsafe
  deserialization (Semgrep `dangerous-ops` blocks these).
- **Async-first** for I/O. Prefer the ORM over raw SQL; scope every `DELETE`/`UPDATE` with `WHERE`.

## Tests

- Every new behaviour has a test; security-relevant code **requires** tests.
- Fast, isolated, deterministic (in-memory SQLite for the DB layer).

## Commits & PRs

- **Conventional Commits.** One logical change per commit.
- PRs run the full gate + doc-consistency guards; the PR template lists the Definition of Done.
