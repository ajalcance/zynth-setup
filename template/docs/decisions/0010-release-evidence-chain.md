# 0010. Release evidence chain: build once, record it, promote the same bytes

Date: 2026-08-01

## Status

Accepted.

## Context

Every other control in this repository operates on a pull request. Tagging does not: `git tag` and
`git push origin v1.2.3` is an ordinary git command that reaches production without passing
through review, code-owner approval, or `ci-complete`. ADR-0004 closed the worst version of that
hole — the release workflow refuses to sign a tag that is not an ancestor of the default branch —
but three gaps remained.

**The release rebuilt on every trigger.** Building from a tag produces bytes nobody has looked at,
even when the source is identical: a floating base image, a transitive dependency published an
hour ago, a different builder. "Same source" is not "same artifact", and the artifact is what runs.

**There was no record.** After an incident, the answer to "what was in v1.2.3" was a workflow log
inside its retention window and whatever the tag currently resolves to. An image tag is a mutable
pointer, so even `ghcr.io/…:v1.2.3` records a *name*, not bytes.

**There was no way to hold a release.** The label taxonomy listed `release-blocker` as a
phase-gated control, and `prod_readiness.py --strict` existed but no release path ever called it.
An owner who wanted to stop a release had nothing to reach for.

## Decision

Split the release into a **candidate** and a **promotion**, and make the boundary between them an
evidence document.

**Candidate** (on a `v*` tag). The `guard` job runs the ancestor check and then
`scripts/release_preflight.py --mode at-tag`, which is fail-closed: an open `release-blocker`
issue, an open production blocker, a missing changelog entry, drifting docs, or a dishonest
standard all stop the release before anything is built. The `candidate` job then builds each image
**once**, pushes it, signs it keyless with cosign, generates an SBOM, and writes
`release-evidence.json` naming every image **by digest**, with the commit, the workflow run, and
the SBOM hash. The evidence is validated, signed with `cosign sign-blob`, and attached to the
GitHub Release alongside the SBOMs.

**Promotion** (manual `workflow_dispatch`). Requires the tag to be typed twice. It downloads the
evidence, verifies its signature, verifies it is the evidence *for that tag*, verifies each
recorded digest's image signature, and points `:stable` at those same digests. It contains no
build step.

`make release-preflight TAG=vX.Y.Z` runs the same preflight locally, before the tag is cut.
`scripts/bootstrap-repo.sh` now provisions the six protected-change labels, including
`release-blocker`.

## Rationale

- **Promotion that rebuilds is not promotion.** It is a new build with a reassuring name. The
  promote job is asserted to contain no build step by `tests/guards/test_workflow_invariants.py`,
  because that property is one copied step away from silently becoming false.
- **Evidence naming a tag is not evidence.** A tag can be moved; the record would then describe
  whatever it points at today. The validator rejects any image reference that is not a digest,
  which is the single rule that makes the document worth reading later.
- **`--expect-tag` is the check that matters at promotion.** A valid evidence document from a
  *different* release passes every structural test and every signature check. Without binding the
  evidence to the tag being promoted, the correct-looking path promotes the wrong bytes.
- **The preflight fails when it cannot check.** A release-hold lookup that errors, or a missing
  `gh`, is reported as a failure rather than a pass. "I could not tell" read as "all clear" turns
  the owner's hold into something a broken environment can lift.
- **Provenance lives in the signed evidence blob, not an OCI attestation.** Turning on buildx
  provenance publishes an OCI *index*, and `outputs.digest` would then be the index digest — so
  cosign would sign the index rather than the image that runs. ADR-0004's invariant, that the
  digest you sign is the digest you deploy, is worth more than the attestation format.
- **`:latest` no longer moves on build.** A mutable tag updated by the build is an automatic
  promotion with no confirmation and no verification. `:stable` moves only through the promote
  job, which is exactly the decision the typed confirmation exists to mark.
- **The heavy logic lives in `scripts/`, not in YAML.** A parser embedded in a `run:` block cannot
  be run, tested, or fixed anywhere else — hence `release_evidence.py --list`, which the workflow
  calls instead of inlining Python.

## Consequences

- What shipped in a release is answerable from the release itself, by anyone, later.
- A release can be held by the owner with a labelled issue, and the hold is read fail-closed.
- Promoting is a deliberate, verified act rather than a side effect of tagging.
- The deploy host keeps pinning by digest; promotion just tells you which digest, and the
  host-side signature check in the deploy module is unchanged.
- Cost: two release jobs instead of one, and a manual step before production moves. Both are
  intentional — the manual step is the control.
- **Residual, and stated plainly:** cosign signing and verification, GHCR pushes and SBOM
  generation cannot be exercised without a live tag and a real registry. The structure around them
  is negative-tested; the calls themselves are proven only by a real release.
