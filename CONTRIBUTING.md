# Contributing to zynth-setup

Improvements to the template are welcome — better defaults, new optional modules, doc fixes.

## The one rule: a generated project must stay green

Any change to `template/` must keep a freshly generated project passing `make check` +
`make dod-check` **out of the box**. See [`MAINTAINING.md`](MAINTAINING.md) for how to generate
and test locally.

## Workflow

1. Branch off `main` (`feat/*`, `fix/*`, `docs/*`).
2. Edit under `template/` (add a `.jinja` suffix for files needing variables/conditionals).
3. Generate a sample project and run its gates — include a variant (different package name /
   license / toggles) if your change touches parameterization.
4. Open a PR with a Conventional Commit title.

## Security

Report template security issues privately — see [`.github/SECURITY.md`](.github/SECURITY.md).
Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).
