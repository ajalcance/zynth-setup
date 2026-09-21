# 0011. A readiness verdict belongs to the artifact, not to a checkout

Status: accepted

## Context

`scripts/prod_readiness.py` keeps a register of deliberate stand-ins — a stubbed auth path, an
in-memory queue — that must not reach production. Its `--strict` mode refuses when any is still
open, and it ran in exactly one place: the release tag.

The tag does not reach production. Promotion does, and deployment does, and neither ran it. The
hazard was named correctly and the control was installed one step early.

The obvious repair is unsound. Promotion runs on `workflow_dispatch` and checks out the default
branch, not the tag being promoted — so a fresh scan there describes `main`, not the artifact. If
`main` has since closed a blocker that the image still contains, that scan passes. **A readiness
check against the wrong tree is worse than none, because it looks like a control.** The same
error waits on the deploy host, whose checkout is whatever the operator last pulled.

## Decision

The verdict moves into the artifact.

`prod_readiness.py --json` writes `{clean, open_blockers}` from a scan of the tree the release is
actually built from. `release_evidence.py --emit` binds that verdict into
`release-evidence.json`, which is then signed with `cosign sign-blob`. Promotion and deployment
both read it from there with `--require-clean`, and neither scans anything.

The fact is bound to the bytes it describes, and a signed candidate carries its own refusal.

A field that two refusals depend on must fail closed in three directions, each stated
explicitly and each with its own test:

1. **A missing verdict is not clean.** Evidence predating the field is refused rather than waved
   through: "we did not record it" and "there was nothing to record" are different facts, and
   only one of them is safe to deploy.
2. **An unreadable register refuses to emit** rather than writing an empty blocker list, because
   an empty list means clean. Emitting one would certify a release nobody checked.
3. **`clean` and `open_blockers` must agree**, so neither can be edited by hand alone.

The first two are the denominator rule (EXP-0001) applied to a verdict instead of a file count.

Two related orderings follow from the same reasoning, and are asserted by
`tests/guards/test_workflow_invariants.py`:

- **The SBOM scan runs before anything is recorded, signed or published.** Scanning afterwards
  means a failing scan rejects a release that already looks legitimate — the tag exists, the
  images are signed, and somebody downstream has to be told not to use them.
- **The deploy verifier takes a tag, not a list of images** (deploy module only), and reads the digests out of the
  signed evidence. An operator who types a digest by hand can type one the evidence does not
  mention, and then every check just performed covered a different artifact from the one about
  to run.

## Consequences

- A release cut while a production blocker is open is still a valid, signed candidate. It is
  simply not promotable, and it says so itself. That is the right split: a project mid-build
  phase must be able to cut releases without the register becoming something people delete.
- The deploy host now needs the evidence document and its signature bundle, not just an image
  reference. `gh release download <tag> --pattern 'release-evidence.*'` fetches both, and the
  verifier refuses without them. This is a deliberate break from the previous invocation.
- The pattern generalises well beyond readiness: **bind a verdict to the artifact it describes,
  never to a checkout.** Any fact a later step needs about a build belongs in the signed record
  of that build.

## Alternatives considered

**Run `--strict` at promotion.** Rejected: it scans the default branch, which is not the thing
being promoted. It would pass in exactly the case that matters.

**Run `--strict` on the deploy host.** Rejected for the same reason, more strongly — the host's
checkout has no defined relationship to the release at all.

**Move `--strict` off the tag entirely.** This was tempting while the tag check was the thing
blocking a release, and that is precisely the shape of changing a guard because it blocks you.
Check whether the gate is right before deciding it is inconvenient. It was right; it was just
in one place too few.
