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
Answer each line with exactly `updated` OR `N/A: <concrete reason>`.

The placeholders below deliberately FAIL until you replace them — a pre-ticked box proves
nothing. A claim of `updated` must be true (the file must appear in the diff), and a record the
diff *does* touch cannot be declared N/A.
-->

- PLAN: <updated | N/A: reason>
- LESSONS: <updated | N/A: reason>
- current-state: <updated | N/A: reason>
- ADR: <updated | N/A: reason>
- CHANGELOG: <updated | N/A: reason>

## Security

- [ ] No secrets/keys added to git
- [ ] Security-relevant change noted in `docs/SECURITY.md` (if applicable)
