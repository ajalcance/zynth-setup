Run the Definition of Done for the change we just made (per `CLAUDE.md` §2):

1. Run `make check` (and `make dod-check`) — fix anything red.
2. Update `docs/PLAN.md` — move the item's status; add any follow-ups discovered.
3. Append a dated entry to `docs/LESSONS.md` — what changed, what we learned, any gotcha.
4. Update `docs/architecture/current-state.md` if a module, route, stored shape, dependency, or
   the deploy shape changed.
5. If the change introduced a **new design decision**, add an ADR in `docs/decisions/` (next
   number, using `template.md`) and reconcile `docs/ARCHITECTURE.md`.
6. Add a `CHANGELOG.md` entry under `## [Unreleased]`.
7. Stage the change and propose a Conventional Commit message.

Report what you changed for each step; if a step doesn't apply, say why.
