# 0001. Record architecture decisions

- **Status:** Accepted
- **Date:** initial scaffold
- **Deciders:** project owner

## Context

We need a durable, reviewable record of the significant technical decisions we make and *why* —
so future contributors (human and AI) understand the reasoning, and so we don't silently
re-litigate settled choices.

## Decision

We record architecture decisions as **ADRs** — one Markdown file per decision in `docs/decisions/`,
numbered sequentially, following [`template.md`](template.md). An ADR records *why we decided*; the
as-built page (`docs/architecture/current-state.md`) records *what now exists*.

A decision earns an ADR when it shapes structure, security, data, dependencies, or a convention
others must follow. The `CLAUDE.md` Definition of Done requires a new ADR whenever a change
introduces a genuinely new decision (not merely implements an already-decided plan).

## Consequences

- The rationale behind the system is discoverable and reviewable in PRs.
- A small per-decision writing cost, bought back by not re-deriving context later.

## Alternatives considered

- **Decisions in commit messages / a wiki.** Rejected: not versioned with the code, not reviewed,
  and hard to find.
