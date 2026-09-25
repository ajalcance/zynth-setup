# 0003. Releases and versioning

Date: 2026-09-25

## Status

Accepted. Records the practice from v1.0.0 to v3.2.0 and the two things that nearly went wrong.

## Context

Copier serves adopters the **highest** version tag by default. A tag is the release: there is
no package registry in between. Two near-misses shaped this record: a release proposed as
`v0.3.1`, then `v0.3.2.0`, after `v3.1.0` — both sort below it, so no adopter would ever have
received them; and a self-test gate keyed to "the previous release" that broke the moment
v3.1.0 was tagged, unseen until a later pull request.

## Decision

- **Semantic versioning, three components**, always above the latest tag. Major when an
  adopter's update needs action beyond `copier update`; minor when behaviour an adopter will
  notice changes; patch otherwise.
- **Tag from `main` only**, on a commit whose push self-test is green; the annotated tag names
  that run. After tagging, confirm a generation from the GitHub URL with no `--vcs-ref`
  records the new tag, and re-check the self-test on `main`, whose update gate now starts from
  the new release.
- **A published tag is never re-pointed or deleted.** A bad release is superseded by the next
  one (v3.0.0 → v3.0.1 is the precedent). The tag ruleset makes this mechanical.
- **Every release is recorded three times, for three readers:** the annotated tag (for `git`),
  `CHANGELOG.md` (for someone reading the repository), and a GitHub Release (for someone
  deciding whether to update).

## Consequences

- Tags are not yet signed. Signing needs the owner's key; once configured, releases use
  `git tag -s` and the ruleset can require it.
