# 0006. Engineering process and control system

Date: 2026-07-27

## Status

Accepted. Umbrella decision; individual mechanisms are recorded in their own later ADRs and
built in phases (see Consequences).

## Context

This project assumes AI produces a substantial share of the implementation and that a human
does **not** inspect every changed line (ADR-0004). Scattered guardrails already exist — branch
ruleset, `ci-complete`, `meta_guard`, `prod_readiness`, cosign signing — but there was no single
document that (a) states the operating principles they serve, (b) maps each control to how it is
actually enforced, and (c) tells a reader honestly which controls are live versus planned.

Without that, two failures recur: treating a documented intention as if it were an implemented
control, and claiming a semantic or future rule is already automated. Both erode trust in exactly
the guardrails that are the product.

## Decision

Adopt a single named operating model, summarized in
[`../ENGINEERING_PROCESS.md`](../ENGINEERING_PROCESS.md), built on six principles:

1. `main` is protected, linear, and always releasable.
2. Routine development happens on short-lived branches and reaches `main` only through a PR.
3. One required aggregate check, `ci-complete`, fails unless every applicable gate succeeds.
4. The repository — not a chat transcript — is the durable project memory, with an explicit
   source-of-truth order.
5. Prior lessons become proportionate controls through an explicit enforcement ladder.
6. A release promotes already-reviewed, already-built, signed bytes and their evidence; it does
   not rebuild arbitrary source.

Every control states its enforcement truthfully with one of four markers:

- **`[CI]`** — mechanically enforced by a gate that runs today.
- **`[Review]`** — depends on human judgment in review; not automated, and not claimed to be.
- **`[Phase gate — vX.Y]`** — planned for a named release; **not yet enforced**.
- **`[Production blocker]`** — registered in `scripts/prod_readiness.py`; a strict release is
  denied until objective closure evidence exists.

A rule may only carry `[CI]` when a corresponding gate genuinely exists. Promoting a rule from
`[Review]`/`[Phase gate]` to `[CI]` is itself a guardrail change requiring the owner's approval
and a negative test (see [ADR-0004](0004-agent-resistant-guardrails.md) and `scripts/meta_guard.py`).

## Consequences

- One document explains how the whole system fits together, and it cannot lie about enforcement
  without a visible marker mismatch.
- The model is delivered in phases; each phase makes the document *more* true by converting
  `[Phase gate]` markers to `[CI]`/`[Review]` as the mechanism lands, and adds its own ADR:
  memory governance, the Claude Code permission model, the experience-to-control loop, the
  normative standards suite, and the release-evidence chain.
- The source-of-truth order is now stated in [`../../CLAUDE.md`](../../CLAUDE.md); assistant/session
  notes rank below versioned repository records and must be reverified before use.

## Alternatives considered

- **Leave the controls undocumented as a set.** Rejected: the absence of a control map is exactly
  what lets an intention be mistaken for an implemented guarantee.
- **Document the full target model as if implemented.** Rejected outright — it is the specific
  dishonesty this ADR exists to prevent. Hence the mandatory enforcement markers.
