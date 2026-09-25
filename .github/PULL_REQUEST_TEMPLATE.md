<!-- One logical change. A guard change is its own PR (CLAUDE.md, rule 3). -->

## What & why

## Verification

<!-- Say what ran and what it inspected — a check that reports OK must say over how much. -->

- [ ] `make check` green (hooks, lint, policy, root fault tests)
- [ ] Changes under `template/`: `make verify` green on full, minimal and hooks-off
- [ ] Every new or changed guard has a fault test; mutants run, none survived

## Records

- [ ] `CHANGELOG.md` under `[Unreleased]` — adopter-facing changes first
- [ ] A decision → an ADR (`docs/decisions/` here, or `template/docs/decisions/` if adopters inherit it)
- [ ] A defect found here → asked of the template, recorded in `docs/BACKLOG.md`
- [ ] A mistake worth not repeating → `docs/LESSONS.md`

## Guard change?

<!-- If this touches a guard (scripts/check_guard_label.py decides), the owner reviews it and
applies `guardrail-change`. The agent never applies it. -->
