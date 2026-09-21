<!-- Keep PRs small and focused: one logical change. -->

## What & why

<!-- What does this change do, and why? Link the issue/ADR if any. -->

## Definition of Done (CLAUDE.md §2)

- [ ] Code compiles / tests pass (`make check`)
- [ ] Docs updated — `docs/PLAN.md` (status), `docs/LESSONS.md` (dated entry), `docs/architecture/current-state.md` (if a component/route/dependency changed)
- [ ] New design decision → an **ADR** in `docs/decisions/`
- [ ] `CHANGELOG.md` updated under `## [Unreleased]`
- [ ] Conventional Commit message

## Memory impact

<!--
REQUIRED and machine-checked by scripts/pr_declaration.py against the actual diff.

The two accepted shapes, exactly as the parser reads them — one record per line:

    - PLAN: updated
    - PLAN: N/A: no roadmap movement, this is a one-file bug fix

A colon, hyphen, en dash or em dash all work as the separator, and a reason that soft-wraps
onto the following indented lines is rejoined before parsing.

The placeholders below deliberately FAIL until you replace them — a pre-ticked box proves
nothing. Four further rules the guard enforces:

  * `updated` must be true: the file has to appear in the diff;
  * the change has to be REAL — PLAN and LESSONS need a dated heading or a few lines of prose,
    everything else needs more than a whitespace edit;
  * a record the diff *does* touch cannot be declared N/A;
  * `ADR: N/A` is refused outright when the diff adds a new module tree under the backend
    package. A new subsystem is a design decision.
-->

- PLAN: <updated | N/A: reason>
- LESSONS: <updated | N/A: reason>
- current-state: <updated | N/A: reason>
- ADR: <updated | N/A: reason>
- CHANGELOG: <updated | N/A: reason>

## Security

- [ ] No secrets/keys added to git
- [ ] Security-relevant change noted in `docs/SECURITY.md` (if applicable)
