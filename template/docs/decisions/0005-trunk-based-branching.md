# 5. Trunk-based branching

Date: 2026-07-18

## Status

Accepted.

## Context

The project originally documented **git-flow** (`main` + a long-lived `develop`, features
branching off `develop`) while its enforcement was configured for **trunk-based** development.
The two never agreed, and the contradiction produced a series of separate defects rather than
staying contained:

1. **`develop` was completely unguarded.** Only a ruleset for the default branch shipped, so
   direct pushes, force-pushes and deletion were all permitted on the branch where integration
   was supposed to happen — and no status check gated anything there.
2. **`required_linear_history` is incompatible with a long-lived `develop`.** Promotion had to
   squash or rebase, which rewrites SHAs, so after the first promotion `develop` was no longer
   an ancestor of `main`. The branches diverge permanently and every later promotion replays
   shipped changes as conflicts — invisible at release one, expensive by release five.
3. **The first commit could not obey the rules.** Generation runs `git init -b main`, so a fresh
   project has no commits and no `develop`; the documented "never commit directly to `main`" was
   violated at commit #1 with no stated exception.
4. **Dependency PRs silently bypassed `develop`.** `dependabot.yml` had no `target-branch`, so
   every dependency update targeted the default branch. Nobody thought to check that file for a
   branching bug, because it isn't *about* branching.

That last one is the general lesson: **an unreconciled branching model does not stay contained.**
It leaks into every new config file that makes an implicit assumption about where work lands.

## Decision

**Trunk-based development.** `main` is the single long-lived branch and is always releasable.
Short-lived `feat/*`, `fix/*`, `refactor/*`, `docs/*` branches are cut from `main` and
squash-merged back via PR. Release tags are cut from `main`.

The **first commit of a generated project** is the repository's root commit and is pushed
directly to `main`; from then on the no-direct-push rule holds without exception.

## Rationale

- **It is what the enforcement already encodes.** Linear history + required PR + squash-merge
  *is* a trunk-based configuration. Only the prose disagreed, so this is the smaller, safer
  correction — the alternative meant giving up linear history, which is what keeps release
  provenance a clean ancestor walk.
- **It removes an unguarded surface instead of adding a second one to protect.** The security
  model (ADR-0004) is that enforcement lives in repo settings an agent cannot reach. A second
  long-lived branch doubles the surface that must be guarded, and in practice the second one
  was guarded by nothing at all.
- **A `develop` branch buys little under this project's review model.** Feature PRs merge on
  green CI without a required human approval; only guardrail files need review. So `develop`
  adds no review checkpoint — it adds a place for unverified code to accumulate before anything
  is enforced.
- **It fits continuous delivery.** `develop` is a release-train pattern for batched QA cycles.
  This project deploys signed images continuously, and `release.yml` already refuses to sign a
  tag that is not an ancestor of the default branch — an invariant that is trivially true under
  trunk-based and awkward under git-flow.
- **It is simpler to hold correctly.** "Branch → PR → merge → tag" is one sentence, which matters
  for a project whose stated audience includes non-technical builders working through an AI.

## Consequences

- One branch to protect, one ruleset to apply, one place releases come from.
- No permanent divergence between branches; every commit on `main` has passed CI.
- **Lost:** a natural place to batch changes before a release. Accepted — releases are cut by tag
  from `main`, so batching is a tagging decision rather than a branching one.
- **If a staging environment is later deployed continuously from a second branch**, that branch
  becomes load-bearing infrastructure rather than ceremony, and this decision should be revisited
  with a superseding ADR — shipping a ruleset for it, and reconsidering `required_linear_history`.

## Alternatives considered

- **Keep git-flow and guard `develop`.** Requires shipping a second ruleset *and* dropping
  `required_linear_history` to make merge commits legal; otherwise consequence 2 above remains.
  Rejected: more configuration, more surface, and it preserves the divergence trap.
- **Make the branching model a generation-time option.** Rejected: it doubles the conditional
  surface across rulesets, CI triggers, Dependabot and four documents — and conditional branching
  assumptions are exactly what produced the four defects above. An opinionated default is the
  point of the template.
