# 0009. Standards suite with honest enforcement markers

Date: 2026-07-31

## Status

Accepted.

## Context

`docs/CODING_STANDARDS.md` held the engineering rules as one page of prose. That works for a
handful of rules and fails in two specific ways as the set grows.

**Rules cannot be cited.** A review comment, an ADR, or an instruction to a coding agent has to
paraphrase the rule, and paraphrases drift. Two people quoting the same standard end up enforcing
two slightly different things, and neither can point at which one is authoritative.

**Rules cannot be trusted about their own enforcement.** A prose standards page reads as though
everything on it is enforced. In reality some rules are checked by a gate on every PR and most are
not. Anyone reading a green pipeline as "the standards held" is wrong about the majority of them —
and on this project, where an AI writes most of the code and a human does not read every line,
that misreading is the whole risk. This is the same failure the control map's enforcement markers
were introduced to prevent in ADR-0006, and the same one `risk_context.py --validate` prevents for
the experience registry in ADR-0008.

## Decision

Add `docs/standards/`: one file per domain, each rule a table row with a **stable id**, the rule
text, an **enforcement marker**, and the **mechanism** that backs the marker.

Prefixes: `BE` (backend), `API` (HTTP surface), `FE` (TypeScript/Next.js), `TA` (tests and
assurance), `SEC` (security), `OBS` (observability), `REL` (delivery). Ids are append-only — a
retired rule is marked withdrawn in place, never renumbered around, because the value of a stable
id is that a year-old citation still resolves.

Markers reuse the ADR-0006 vocabulary unchanged: `[CI]`, `[Review]`, `[Phase gate — vX.Y]`,
`[Production blocker]`.

`docs/CODING_STANDARDS.md` stays, shortened, as the entry point: the rules worth knowing before
writing anything, each citing its id.

`scripts/standards_check.py` runs in CI and in `make dod-check`, and **fails** when:

- a rule id is malformed, duplicated, or uses an undeclared prefix;
- a marker is outside the vocabulary, or a phase gate names no release;
- a `[CI]` rule names no mechanism, or names a path that does not exist;
- a `[Production blocker]` rule cites a hold that is not in the `prod_readiness` register;
- any document cites a rule id the suite does not define.

## Rationale

- **A marker nobody checks becomes decoration.** The suite's value is entirely in the reader
  believing the markers, so the claim is machine-checked rather than trusted. A `[CI]` rule has to
  name a file that exists, exactly as a `guard`-rung registry entry does.
- **`[Review]` is the honest answer for most rules.** "Handlers stay thin", "log no personal
  data", "a passing SQLite test is not evidence of PostgreSQL behaviour" — none of these are
  mechanically decidable. Marking them `[Review]` says plainly that a green pipeline did not check
  them, which is more useful than a page implying it did. Writing this suite produced a concrete
  instance: `prod_readiness.py --strict` exists but no release path calls it, so REL-021 is
  `[Phase gate — v2.0]` rather than `[CI]`.
- **A malformed id is an error, not a skipped row.** A rule row the parser cannot read would
  silently leave the suite, so the guard fails on anything that was clearly meant to be a rule.
  A check that quietly inspects less is the failure mode `tests/guards/` exists to catch.
- **Citations are checked in the other direction too**, so deleting or renaming a rule cannot
  leave dangling references in the docs that cite it.
- **The suite is deliberately *not* a guard-defining file.** `experience/registry.toml` requires
  the owner's `guardrail-change` label because promoting a lesson to a gate grants authority.
  Editing a standards rule grants none — the gates keep running either way — and adopters are
  expected to add their own rules constantly. Requiring the label for that would make it routine,
  and a label applied every week stops being a signal. `scripts/standards_check.py` itself is
  covered by the guard-file rule, so the checker cannot be softened quietly.
- **No new CI job.** The check is a step in the existing `static` job — GitHub bills per job, so
  job count is the cost driver.

## Consequences

- Rules are citable by id from reviews, ADRs, commit messages, and agent instructions.
- A reader can tell, per rule, what a green pipeline actually proved.
- Promoting a rule from `[Review]` to `[CI]` now means building the gate and giving it a negative
  test in `tests/guards/` — the same promotion discipline as the experience ladder in ADR-0008.
- Module-specific rules ship only with their module, so no rule references a file the project does
  not have.
- Cost: one more record to keep true, bounded by the guard, which fails the moment a rule points
  at something that no longer exists.
