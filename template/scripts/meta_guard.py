#!/usr/bin/env python3
"""Meta-guard: stop an agent from quietly weakening the guards to make CI green.

Two diff-based checks against the PR's base branch (no stored baseline to tamper with):

1. **Suppression ratchet** — the PR must not add net-new bypass markers
   (``# noqa``, ``# type: ignore``, ``# nosemgrep``, ``# pragma: no cover``,
   ``eslint-disable``, ``@ts-ignore``, ``@ts-nocheck``). Removing them is always fine.
2. **Test presence** — if package source changed, a test must have changed too
   (catches "delete/hollow the tests so coverage/pytest pass").

Each check has an explicit escape hatch (a PR label → a CLI flag) so a human can
consciously override, but an agent cannot do it silently.

Usage:  python scripts/meta_guard.py --base origin/main [--allow-suppressions] [--allow-missing-tests]
Exit code is non-zero if any active check fails.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

BYPASS_MARKERS = (
    r"#\s*noqa",
    r"#\s*type:\s*ignore",
    r"#\s*nosemgrep",
    r"#\s*pragma:\s*no cover",
    r"eslint-disable",
    r"@ts-ignore",
    r"@ts-nocheck",
)
_MARKER_RE = re.compile("|".join(BYPASS_MARKERS))

# A changed .py here counts as "source"; tests/migrations don't.
SRC_RE = re.compile(r"^backend/(?!tests/|migrations/).*\.py$")
TEST_RE = re.compile(r"^backend/tests/.*\.py$")


def _run(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def _diff(base: str) -> str:
    return _run("diff", "--unified=0", f"{base}...HEAD")


def check_suppressions(base: str, errors: list[str]) -> None:
    added = removed = 0
    for line in _diff(base).splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") and _MARKER_RE.search(line):
            added += 1
        elif line.startswith("-") and _MARKER_RE.search(line):
            removed += 1
    net = added - removed
    if net > 0:
        errors.append(
            f"PR adds {net} net new suppression marker(s) "
            f"(noqa / type: ignore / nosemgrep / pragma: no cover / eslint-disable). "
            f"Fix the finding instead, or label the PR 'allow-suppressions' if justified."
        )


def check_tests(base: str, errors: list[str]) -> None:
    changed = [f for f in _run("diff", "--name-only", f"{base}...HEAD").splitlines() if f]
    src = [f for f in changed if SRC_RE.match(f)]
    tests = [f for f in changed if TEST_RE.match(f)]
    if src and not tests:
        errors.append(
            "Package source changed but no test under backend/tests/ changed. Add/adjust a test, "
            "or label the PR 'no-tests-needed' if this is a pure refactor/rename."
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main", help="base ref to diff against")
    ap.add_argument("--allow-suppressions", action="store_true")
    ap.add_argument("--allow-missing-tests", action="store_true")
    args = ap.parse_args()

    errors: list[str] = []
    if not args.allow_suppressions:
        check_suppressions(args.base, errors)
    if not args.allow_missing_tests:
        check_tests(args.base, errors)

    if errors:
        print("meta-guard: FAILED\n")
        for e in errors:
            print(f"  ✗ {e}")
        return 1
    print("meta-guard: OK — no silent guard-weakening detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
