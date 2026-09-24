# ADR-0013 — A tree is proved once: post-merge reuse

**Status:** accepted · **Date:** 2026-09-24

## Context

GitHub bills Actions per job, rounded up to a full minute, so the number of jobs is the
cost driver ([ADR-0005](0005-trunk-based-branching.md) already limited `push` runs to the
default branch). The run that follows a squash merge still repeats every job the pull-request
run just passed, against the same tree. At a few merges a day that is the larger half of the
bill, spent re-proving what a green check already proved.

The obvious shortcut — skip the post-merge run — removes the run the release evidence chain
points at, and the run that catches an advisory published between review and merge.

## Decision

A `reuse` job runs first on every push to a branch. It computes the tree hash of the new
commit and looks for a merged pull request whose head commit has the same tree hash and a
successful `ci-complete` check run **posted by GitHub Actions itself** (`app.slug`, the same
rule the ruleset applies to the required check — a check by name alone can be declared by
anyone). When it finds one:

- the deterministic jobs stand down: hygiene, SAST, the static guards, and the lint/type/test
  steps of the backend, frontend and docs jobs;
- the audits do **not**: `pip-audit` and `npm audit` read databases that move without us, so
  they run on every push, reuse or not;
- the job prints the proving run's URL, so the record says what was reused and why.

A lookup that fails — an API error, a direct push with no pull request, a tree that differs
because the default branch moved between the PR run and the merge — leaves `verified` unset,
and every job runs. Failing to verify is a full run, never a skipped one.

One run is always full: a **weekly schedule** (Monday 06:00 UTC), because a quiet default
branch could otherwise go unproved against new advisories and new community rules for as long
as nobody merges. On that run the change filter reports everything changed, since there is no
base to diff. Release tags deliberately do **not** trigger CI: a tag names a default-branch
commit whose push run already ran the audits and proved the tree, `release.yml` refuses a tag
that is not on the default branch, and a tag-triggered workflow that restores package caches
is one zizmor reads as a release build open to cache poisoning.

## Why the tree, and why the PR head's tree

A squash merge is a new commit, so commit hashes never match; tree hashes do. The merge ref
the PR run actually tested is gone after the merge, but if the new default-branch tree equals
the PR head's tree, the head already contained everything the base had — so the merge the PR
run tested was this tree too. If the base moved in between, the trees differ and the run is
full. That is the conservative direction.

## Consequences

- A typical post-merge run drops from seven billed job-minutes to about four (the change
  filter, the lookup, and the audit halves of the backend and frontend jobs).
- `tests/guards/test_ci_reuse.py` holds the shape: who stands down, who never does, that the
  lookup demands a real `ci-complete`, that a lookup error cannot redden the default branch,
  and that the weekly run exists.
- A secret committed in an intermediate PR commit and removed before merge is not in the
  merged tree; the PR run scanned the PR's commits, which is where such a secret lives.
