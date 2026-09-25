#!/usr/bin/env python3
"""Who guards the guards: every guard needs a fault test and something that runs it.

This project ships its guards as loose scripts. Nothing otherwise stops one being written,
reviewed, merged — and never wired into any gate. It sits in `scripts/` looking like a
control, it is cited in an ADR as a control, and it has never once run. The same goes for a
guard with no negative test: nothing has ever demonstrated it *can* fail, so "green" from it
means nothing.

Two requirements per guard, and both are about evidence rather than intent:

1. **A fault test.** Some file under tests/guards/ must name the guard, so there is a test
   that proves it can fail. Ten passing assertions about a guard that cannot fail prove only
   that the test file parses.
2. **An enforcement surface.** Some Makefile target, CI workflow, pre-commit hook or hook
   registration must invoke it. A guard nothing runs is documentation.

A script that is genuinely not a gate — a diagnostic, a setup helper — is declared in
NON_GATES below *with its reason*. That list is short on purpose and lives in a file the
meta-guard gates, so growing it is a reviewed act rather than the cheap way past this check.

Usage:  python3 scripts/check_guard_coverage.py
Exit code is non-zero if a guard lacks either, or if no guard was discovered at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / ".claude" / "hooks"
FAULT_TESTS = ROOT / "tests" / "guards"

# Places a guard can legitimately be invoked from. A guard named in none of them runs nowhere.
ENFORCEMENT_SURFACES = (
    ROOT / "Makefile",
    ROOT / ".pre-commit-config.yaml",
    ROOT / ".claude" / "settings.json",
    *sorted((ROOT / ".github" / "workflows").glob("*.yml")),
    *sorted((ROOT / ".github" / "workflows").glob("*.yaml")),
)

# Not gates. Each needs a reason, and the reason is the review: if you cannot write one, the
# script is a gate you have not wired in yet.
NON_GATES: dict[str, str] = {
    "context.py": "a session-start snapshot printed for a reader; it asserts nothing",
    "preflight.py": "a diagnostic that tells you what to install; it gates no change",
    "bootstrap-repo.sh": "one-time repository setup, run by a human against GitHub",
    "check_guard_coverage.py": "this file — it is the coverage check, not a guard over code",
    "_shell.py": (
        "the parser the Bash hooks import — it decides nothing itself, and every behaviour it "
        "has is fault-tested through the two hooks that use it"
    ),
    "format_python.py": (
        "its own docstring says 'Ergonomics, NOT a guard' — it formats what was just written "
        "and always exits 0, so there is no failure for a fault test to provoke"
    ),
}


def discover() -> list[Path]:
    """Every script that looks like a check, in the two directories that hold them."""
    found: list[Path] = []
    for directory, patterns in ((SCRIPTS, ("*.py", "*.sh")), (HOOKS, ("*.py",))):
        if not directory.is_dir():
            continue
        for pattern in patterns:
            found.extend(sorted(directory.glob(pattern)))
    return [path for path in found if path.name != "__init__.py"]


def named_in(haystack: Path, needle: str) -> bool:
    try:
        return needle in haystack.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def fault_tested(name: str) -> list[str]:
    if not FAULT_TESTS.is_dir():
        return []
    return [t.name for t in sorted(FAULT_TESTS.glob("test_*.py")) if named_in(t, name)]


def enforced_by(name: str) -> list[str]:
    return [
        str(surface.relative_to(ROOT))
        for surface in ENFORCEMENT_SURFACES
        if surface.is_file() and named_in(surface, name)
    ]


def main() -> int:
    guards = discover()
    gates = [g for g in guards if g.name not in NON_GATES]
    declared = [g for g in guards if g.name in NON_GATES]

    surfaces = [s for s in ENFORCEMENT_SURFACES if s.is_file()]
    fault_test_files = sorted(FAULT_TESTS.glob("test_*.py")) if FAULT_TESTS.is_dir() else []

    print(
        f"guard-coverage: inspected {len(gates)} guard(s) across "
        f"{len({g.parent for g in guards})} director(ies) — "
        f"{len(surfaces)} enforcement surface(s), {len(fault_test_files)} fault-test file(s), "
        f"{len(declared)} documented non-gate(s)"
    )

    if not gates:
        print(
            "\nguard-coverage: FAILED — no guard was discovered, so nothing was checked.\n"
            "Either scripts/ has been renamed, or every script is declared a non-gate. A\n"
            "coverage check over an empty set reports green forever (EXP-0001)."
        )
        return 1
    if not fault_test_files:
        print(
            "\nguard-coverage: FAILED — tests/guards/ holds no fault tests, so the check\n"
            "below could only ever pass. Restore them."
        )
        return 1

    errors: list[str] = []
    for guard in gates:
        if not fault_tested(guard.name):
            errors.append(
                f"{guard.relative_to(ROOT)}: no fault test names it. A guard with no negative "
                f"test has never been shown to FAIL, so its green means nothing — add one under "
                f"tests/guards/ that makes it exit non-zero."
            )
        if not enforced_by(guard.name):
            errors.append(
                f"{guard.relative_to(ROOT)}: nothing invokes it. It is named in no Makefile "
                f"target, no workflow, no pre-commit hook and no hook registration, so it has "
                f"never run — wire it into a gate, or declare it in NON_GATES with a reason."
            )

    if errors:
        print("\nguard-coverage: FAILED — guards that are not actually controls:\n")
        for error in errors:
            print(f"  ✗ {error}")
        return 1

    for guard in declared:
        print(f"  · not a gate — {guard.name}: {NON_GATES[guard.name]}")
    print("guard-coverage: OK — every guard has a fault test and an enforcement surface.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
