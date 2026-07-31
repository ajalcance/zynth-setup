# 0008. Experience-to-control loop

Date: 2026-07-31

## Status

Accepted.

## Context

`docs/LESSONS.md` is a dated narrative — the right shape for "what happened, in order", and the
wrong shape for "what applies to the change I am making now". As it grows, nobody re-reads it, so
a lesson that was expensive to learn stops influencing anything. The usual reactions are both bad:
leave it as prose nobody reads, or promote every lesson to a blocking gate and drown real work in
false positives until people reach for the override label by reflex.

There is a second failure specific to this project's premise: an agent that can turn its own
advice into policy has effectively granted itself authority.

## Decision

Add a normalized **experience registry** (`experience/registry.toml`) with an explicit five-rung
enforcement ladder, and retrieve from it by diff:

`reference` → `context` → `checklist` → `guard` → `production_blocker`

- `make risk-context` matches the paths in the current diff to registry entries and prints only
  what applies. It is advisory and always exits 0.
- `scripts/risk_context.py --validate` runs in CI and **fails** if an entry claims `guard` or
  `production_blocker` enforcement without naming a mechanism that exists on disk.
- `experience/registry.toml` is a guard-defining file in `meta_guard`, so promoting a pattern
  requires the owner-applied `guardrail-change` label.

Promotion to `guard` requires a decidable invariant, an under/over-gating analysis, a negative
test in `tests/guards/`, and the owner's approval.

## Rationale

- **Higher is not better.** A rung above what a lesson can support produces false positives, and
  a control people override by reflex enforces nothing. `checklist` is the honest home for
  anything needing judgement — for example "a passing SQLite test is not evidence of PostgreSQL
  behaviour", which no static check can decide.
- **The registry can lie in exactly the way the control map could**, by asserting automation it
  does not have. So the same remedy applies: the claim is machine-checked. This is why
  `enforced_by` is mandatory at the `guard` rung and verified to exist.
- **Retrieval must be diff-aware to be read at all.** Being shown three relevant patterns beats
  being told to read forty.
- **An agent may recommend a promotion but not perform one.** Reusing the existing guard-file
  mechanism means this needs no new machinery and inherits its negative tests (ADR-0004, ADR-0007).

## Consequences

- Lessons have a home with a stated strength, and the strength is honest.
- Retrieval never overrides code, tests, ADRs or live settings; if the registry and reality
  disagree, reality wins — consistent with the source-of-truth order in `CLAUDE.md`.
- The registry ships seeded with patterns that are **already enforced**, so the ladder is
  demonstrated rather than described. Deploy- and spine-specific entries ship only with those
  modules, so no entry references a file the project does not have.
- Cost: one more file to keep true. Bounded by the validator, which fails the moment an entry
  points at something that no longer exists.
