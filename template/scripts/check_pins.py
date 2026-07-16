#!/usr/bin/env python3
"""Dependency pin guard: every requirement must be exactly pinned.

A floating spec (``requests>=2``, ``redis``, ``foo~=1.2``) lets a resolver — or an agent — pull a
different version silently on the next install. Combined with CODEOWNERS review on the manifests
(docs/decisions/0004) and Socket's behavioural analysis, exact pins make "the version changed"
always an explicit, reviewable diff. Hashes (``--hash=...``) are accepted and encouraged.

Usage:  python scripts/check_pins.py backend/requirements.txt backend/requirements-dev.txt
Exit code is non-zero if any requirement is not exactly pinned.
"""

from __future__ import annotations

import sys


def _strip(line: str) -> str:
    line = line.split("#", 1)[0]  # inline comment
    line = line.split(";", 1)[0]  # environment marker
    return line.strip()


def check_file(path: str, errors: list[str]) -> None:
    try:
        lines = open(path).read().splitlines()
    except FileNotFoundError:
        return  # a variant may not ship this file
    for n, raw in enumerate(lines, 1):
        spec = _strip(raw)
        if not spec:
            continue
        if spec.startswith(("-r", "-c", "--")):  # includes / pip options
            continue
        if "--hash=" in raw:  # a hashed lock line
            continue
        if "==" in spec:  # exact version pin
            continue
        if "@" in spec:  # direct URL / VCS ref (pins to a concrete ref)
            continue
        errors.append(f"{path}:{n}: not exactly pinned (use '==') → {spec!r}")


def main() -> int:
    files = sys.argv[1:] or ["backend/requirements.txt", "backend/requirements-dev.txt"]
    errors: list[str] = []
    for f in files:
        check_file(f, errors)
    if errors:
        print("check-pins: FAILED — floating/unpinned dependencies:\n")
        for e in errors:
            print(f"  ✗ {e}")
        print("\nPin every dependency with '==' (or a --hash). Then Dependabot proposes bumps as PRs.")
        return 1
    print("check-pins: OK — all dependencies exactly pinned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
