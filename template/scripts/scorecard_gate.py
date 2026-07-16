#!/usr/bin/env python3
"""Gate an OSSF Scorecard JSON result on a curated subset of checks.

Scorecard scores many things; only a few are load-bearing for "the guards haven't eroded".
We fail the run when any of these drops below threshold, and *skip* (don't fail) a check that
Scorecard could not evaluate — e.g. Branch-Protection returns score -1 without an admin PAT,
which is a "can't tell", not a "bad". A vacuous failure would train people to ignore this.

Usage:  python scripts/scorecard_gate.py results.json [--min 7]
"""

from __future__ import annotations

import argparse
import json
import sys

GATED_CHECKS = {
    "Branch-Protection",
    "Token-Permissions",
    "Pinned-Dependencies",
    "Dangerous-Workflow",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("results", help="path to Scorecard JSON output")
    ap.add_argument("--min", type=int, default=7, help="minimum passing score (0-10)")
    args = ap.parse_args()

    with open(args.results) as fh:
        data = json.load(fh)

    checks = {c.get("name"): c for c in data.get("checks", [])}
    failures: list[str] = []
    skipped: list[str] = []

    for name in sorted(GATED_CHECKS):
        check = checks.get(name)
        if check is None:
            skipped.append(f"{name} (not in results)")
            continue
        score = check.get("score", -1)
        if score is None or score < 0:
            skipped.append(f"{name} (inconclusive — needs an admin PAT?)")
        elif score < args.min:
            failures.append(f"{name}: {score}/10 (min {args.min})")

    for s in skipped:
        print(f"scorecard-gate: skipped {s}")
    if failures:
        print("\nscorecard-gate: FAILED — security posture regressed:")
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print(f"scorecard-gate: OK — gated checks ≥ {args.min}/10.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
