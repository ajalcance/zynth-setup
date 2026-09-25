# 0002. The template repository follows the template it ships

Date: 2026-09-25

## Status

Accepted.

## Context

An audit on 2026-09-25 compared this repository with a fresh v3.2.0 generation. The self-test
proved every project the template generates and nothing about the repository generating them:
`main` unprotected with no ruleset, secret scanning and push protection off on a public repo,
the self-test's own workflow unlinted, its tools unpinned, its history never secret-scanned, its
three root guards without a fault test, no committed agent policy (a local file with 199 allow
rules and no ask or deny), and every maintainer rule held in one machine's private memory.

The owner's framing: if we build the template, the best example of it is this repository
following it — and every defect met while doing so is a question about the template.

## Decision

1. **The shipped standard applies here**, adapted only where this repository differs:
   `make check` (lint, policy, fault tests) run locally and by CI; `ci-complete`; pinned tools;
   the secret scan with canary; pre-commit, Dependabot, Scorecard; a committed agent policy;
   a guard-label check; a ruleset. Each adaptation states its reason where it is made.
2. **One definition, never a second.** A template guard that is location-independent is called
   from `template/scripts/` directly. One that locates the repository from its own path is
   copied byte for byte, and a test fails on drift. The guard-label check imports the template
   meta-guard's `GUARD_FILE_RE` rather than restating it.
3. **The agent-permission split.** Here the product *is* the guards, so nearly every change is
   guard work. Asking at every keystroke on `template/` would be the confirmation fatigue
   template ADR-0007 exists to prevent. So: a change to what judges the agent **here** asks
   locally; a change to what judges **adopters** is gated at the pull request by the owner's
   `guardrail-change` label, which the session hook refuses to let the agent apply.
4. **Session hooks are copies, not pointers into `template/`.** A pointer would let an edit to
   the template change the agent's own live guard mid-session.
5. **Dogfooding feeds the template.** Every defect found here is checked against the template
   and recorded in `docs/BACKLOG.md`. The template pass follows once this repository's setup is
   settled.

## Consequences

- Merges go through pull requests once the ruleset is applied; fast-forward pushes to `main`
  by a maintainer or an agent stop being possible, which is the point.
- The hooks went live in the session that installed them and found two template defects within
  minutes (backlog T7, T8). That is the loop working.
