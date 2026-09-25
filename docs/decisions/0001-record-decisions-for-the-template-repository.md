# 0001. Record decisions about the template repository itself

Date: 2026-09-25

## Status

Accepted.

## Context

`template/docs/decisions/` holds the decisions every generated project inherits — they are part
of the product. Decisions about how *this repository* is built, tested and released had nowhere
to live: they were spread across commit messages, tag messages and one maintainer's private
agent memory, which no other maintainer, agent or machine can read.

## Decision

This repository keeps its own decision log here, in the same format as the template's. Numbering
is independent of `template/docs/decisions/`. A decision that changes what adopters receive
belongs in the template's log; a decision about building, testing or releasing the template
belongs here. Some need both.

## Consequences

- The source-of-truth order in CLAUDE.md puts this log first.
- Private memory may summarise these records; it never replaces them.
