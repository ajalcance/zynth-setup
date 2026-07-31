# Experience-to-control loop

A place for lessons that is **not** a flat list nobody re-reads.

`docs/LESSONS.md` is the dated narrative — what happened, in order. This registry is the
*normalized* form: each recurring pattern stated once, tagged with how strongly it is enforced,
and matched to the files you are actually touching by `make risk-context`.

The point is proportionality. A lesson does not have to become a blocking gate to be useful, and
it must not *claim* to be one when it isn't.

## The enforcement ladder

| Rung | Meaning | Cost of being wrong |
|---|---|---|
| `reference` | retained context; not surfaced automatically | none |
| `context` | surfaced by `make risk-context` when related paths change | a moment's reading |
| `checklist` | a required answer in the PR or a runbook step | a little ceremony |
| `guard` | mechanically decided, and **negative-tested** | a false positive blocks real work |
| `production_blocker` | production is denied until objective closure evidence exists | shipping stops |

Higher is not better. A rung above what a lesson can support produces either false positives
(which train people to reach for the override label) or a claim of automation that does not exist
(which is worse, because everyone downstream believes it).

## Promotion rules

**An agent may recommend a promotion. It may not perform one.** `experience/registry.toml` is a
guard-defining file: changing it requires the owner-applied `guardrail-change` label, exactly like
editing a guard script. That is deliberate — the alternative is an agent turning its own advice
into policy.

A promotion to `guard` requires all of:

1. a **decidable invariant** — you can state precisely what makes a change violating;
2. an analysis of **under- and over-gating** — what it will miss, and what it will wrongly flag;
3. a **negative test** in `tests/guards/` proving the new guard can fail;
4. the owner's explicit approval.

A promotion to `production_blocker` additionally requires a registered entry in
`scripts/prod_readiness.py` and objective evidence that would close it.

## Honesty is enforced, not assumed

`python3 scripts/risk_context.py --validate` runs in CI and **fails** when an entry claims
`guard` or `production_blocker` enforcement without naming a file that exists. Without that check
the registry could quietly assert automation it does not have — the same failure the control map's
enforcement markers exist to prevent.

## Using it

```bash
make risk-context     # what applies to my current diff?
```

Retrieval is advisory and always exits 0. It never overrides code, tests, ADRs, or live settings —
if the registry and reality disagree, reality wins.
