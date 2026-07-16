# 0004. Agent-resistant guardrails

- **Status:** Accepted
- **Date:** initial scaffold
- **Deciders:** project owner

## Context

This project is built for a workflow where an AI assistant writes — and sometimes deploys — most
of the code, and the human owner does **not** review every diff. [ADR-0002](0002-defense-in-depth-against-malicious-code.md)
established layered gates that catch an agent's *mistakes* (dangerous ops, secrets, known-vuln
deps, type/lint/test failures). Those hold. But two assumptions break when no human reads the diff:

1. **The guards live in the repo the agent edits.** An agent trying to make CI green can weaken
   them without malice — add a route to an `EXEMPT` list instead of instrumenting it, sprinkle
   `# nosemgrep` / `# type: ignore`, delete a failing test, or edit a workflow. A guard the agent
   can silently disable is not a guard.
2. **Build-and-run-whatever-is-here** leaves two open flanks: a **poisoned dependency** (invisible
   to CVE-only `pip-audit`/`npm audit`), and a **deployed artifact that was never the reviewed one**.

The guardrails are not a feature of this template — for this workflow they are the product. So they
must resist the agent itself, and enforcement must live where the agent's commits cannot reach.

## Decision

Harden in five layers on top of ADR-0002. **Phase 1 ships in the generated project; later phases
roll out as toggle-able modules** held to the same bar (below).

1. **Enforcement outside the repo (Phase 1 — shipped).** A branch ruleset
   (`.github/rulesets/main.json`, applied once via `scripts/bootstrap-repo.sh`) makes passing CI a
   *repo setting*, not a file: required status check `ci-complete`, required pull request, required
   code-owner review, linear history, no force-push, no branch deletion. The agent can edit
   `.github/workflows/ci.yml`, but it cannot change the rule that the check is required, and it
   cannot merge a red or unreviewed build.
2. **Review the meta, trust the features (Phase 1 — shipped).** `CODEOWNERS` assigns a human owner
   to the **guardrails only** (`.github/`, `.semgrep/`, `scripts/`, dependency manifests, the spine
   decision lists). Feature code ships without a required review; changing a *rule* requires human
   approval.
3. **Watch for erosion (Phase 2).** OSSF Scorecard, scheduled and gating a curated subset (pinned
   actions, branch protection, token permissions, dangerous-workflow), plus a meta-guard that fails
   when suppression comments or `EXEMPT` lists grow, or a workflow file changes. Coverage threshold
   + "code changed without a test change" close the test-theater hole.
4. **Dependency integrity (Phase 3).** Socket.dev (behavioral supply-chain analysis, set to
   **block**) catches a dependency that *newly* runs install scripts or touches network/filesystem —
   the poisoned-update vector CVE scanners miss — paired with lockfile-hash enforcement so a silent
   version bump can't slip in either.
5. **Artifact integrity (Phase 4) and runtime containment (Phase 5).** CI builds, signs
   (**cosign** keyless / OIDC) and attests (SLSA provenance) an image by digest; deploy pulls that
   digest and verifies the signature against the pinned workflow identity before running —
   fail-closed, so only the built-and-signed artifact runs. The dev agent itself runs
   least-privilege with egress allow-listing and no production credentials.

**Acceptance bar for every guardrail.** (a) The minimal and full projects stay green out of the
box; (b) each guard is proven to **fail closed** by fault injection — a check that passes vacuously
is worse than none when no human audits it; (c) it is toggle-able where it adds surface; (d) any
per-repo setup is one line in `ONBOARDING.md`.

## Consequences

- An agent can no longer merge past the gates by weakening them: the gate is required server-side,
  and the gate's *definition* is a code-owner-reviewed path.
- The owner reviews a small, high-signal set of diffs (the rules) instead of all of them — which is
  what makes "the agent writes the code" safe rather than reckless.
- Cost: the owner must run `scripts/bootstrap-repo.sh` once and install a few integrations
  (tracked in `ONBOARDING.md`). A solo owner using a single identity cannot approve their own PR,
  so guardrail changes need a second reviewer or an explicit admin bypass — an accepted trade.

## Alternatives considered

- **In-repo config alone (workflows + CODEOWNERS, no ruleset).** Rejected: the agent can edit those
  files, so nothing makes the check actually required. Enforcement must live in repo settings.
- **Require human review on everything.** Rejected: it contradicts the workflow and trains the owner
  to rubber-stamp. Gating only the rules keeps review scarce and meaningful.
- **Trust a well-behaved model.** Rejected: prompt injection makes the adversarial case realistic,
  and "make CI green" is enough incentive to erode guards without any adversary at all.
