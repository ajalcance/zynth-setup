#!/usr/bin/env python3
"""Production-readiness register: track temporary stand-ins so none reach production.

Every project accumulates deliberate stubs during scaffolding — a placeholder auth layer to
unblock frontend work, ``CHANGE_ME`` secrets, a mutable image tag before the first real
release, a placeholder ACME email. Each is fine *while building* and unacceptable in
production, and the usual fate of a TODO comment is to be forgotten.

The convention: mark the code, and register it here. Both directions are checked, so the
register cannot silently drift from the tree.

    # PROD-BLOCKER(auth-stub): dev-only bearer check; replace with real OIDC before launch

Two-way consistency:

1. **Every marker in the tree has a register entry.** Add a stub, declare it — otherwise a
   temporary hack can hide in the codebase with nothing tracking it.
2. **Every register entry still has a marker in the tree.** Resolve a stub, close the entry —
   otherwise the register rots into a list of things that were fixed months ago, and a rotten
   register is one nobody reads.

Run from the repo root: ``python3 scripts/prod_readiness.py`` (or via ``make dod-check``).
Exit code is non-zero if the two sides disagree.

**This is a checklist, not a gate.** It deliberately does not fail merely because open
blockers exist — that would make it red for the entire build phase and train everyone to
ignore it. It fails only on *inconsistency*. Use ``--strict`` in a release workflow to
additionally require the register be empty before shipping.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------------------
# The register. One entry per deliberate stand-in that must not reach production.
#   (id, why it exists / what must replace it)
# The id must match a `# PROD-BLOCKER(<id>): ...` marker somewhere in the tree.
# Ships empty: a fresh project has no stubs until you add one.
# ---------------------------------------------------------------------------------------
BLOCKERS: tuple[tuple[str, str], ...] = ()

MARKER_RE = re.compile(r"PROD-BLOCKER\(([a-z0-9][a-z0-9-]*)\)")

SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    ".next",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "coverage",
    "htmlcov",
    "out",
    "build",
    "dist",
}
# Source and config only — deliberately NOT markdown. Documentation that *explains* the
# convention (ONBOARDING.md, an ADR) names the marker in prose, and counting that as a real
# marker would make a fresh project fail on its own example. Same lesson as the suppression
# scan in scripts/meta_guard.py: a guard must tell "wrote about it" from "did it".
SCAN_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".yml",
    ".yaml",
    ".toml",
    ".json",
    ".sh",
    ".env",
    ".example",
    ".tf",
}


SCANNED = 0  # the denominator: how many files the last _scan() actually read


def _scan() -> dict[str, list[str]]:
    """Map each marker id found in the tree to the files declaring it."""
    global SCANNED
    SCANNED = 0
    found: dict[str, list[str]] = {}
    for path in ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts) or not path.is_file():
            continue
        if path.suffix not in SCAN_SUFFIXES and path.name != "Dockerfile":
            continue
        # This file defines the convention; its own examples are not real markers.
        if path.resolve() == Path(__file__).resolve():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        SCANNED += 1
        for match in MARKER_RE.finditer(text):
            found.setdefault(match.group(1), []).append(str(path.relative_to(ROOT)))
    return found


def _write_verdict(path: str) -> None:
    """Record the verdict so it can travel INSIDE the signed release evidence.

    ``--strict`` used to run in exactly one place: the tag. The tag does not reach production;
    promotion and deploy do, and neither ran it. The obvious fix is unsound — promotion runs on
    workflow_dispatch and checks out the default branch, so a fresh scan there would describe
    `main`, not the artifact. If main has since closed a blocker the image still contains, that
    scan passes. A readiness check against the wrong tree is worse than none, because it looks
    like a control. The same applies on the deploy host, whose checkout is whatever the
    operator last pulled.

    So the verdict is bound to the bytes it describes. Two refusals depend on this field, so it
    fails closed in three directions, each stated:

    1. a MISSING verdict is not clean — release_evidence refuses evidence without one;
    2. an unreadable register refuses to EMIT rather than writing an empty blocker list,
       because an empty list means clean (that is this function);
    3. ``clean`` and ``open_blockers`` must agree, so neither can be edited alone.
    """
    try:
        open_blockers = sorted(bid for bid, _ in BLOCKERS)
    except Exception as exc:  # noqa: BLE001 — see (2): refuse to emit, never emit "clean"
        raise SystemExit(
            f"prod-readiness: FAILED — the register could not be read ({exc}), so no verdict\n"
            f"was written. An empty blocker list means CLEAN, and emitting one here would\n"
            f"certify a release nobody checked."
        ) from exc
    verdict = {"clean": not open_blockers, "open_blockers": open_blockers}
    Path(path).write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n")
    print(
        f"prod-readiness: wrote {path} — clean={verdict['clean']}, "
        f"{len(open_blockers)} open blocker(s)"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--strict",
        action="store_true",
        help="also fail if ANY blocker is still open (use in a release workflow)",
    )
    ap.add_argument(
        "--json",
        metavar="FILE",
        help="write the verdict for release_evidence.py to bind into the signed document",
    )
    args = ap.parse_args()

    found = _scan()
    registered = {bid for bid, _ in BLOCKERS}
    errors: list[str] = []

    print(
        f"prod-readiness: inspected {SCANNED} file(s) — {len(found)} marker id(s) in the tree, "
        f"{len(registered)} in the register"
    )
    # The denominator rule (EXP-0001). "No open blockers" and "this never read a file" print
    # the same reassuring line otherwise, and a narrowed SCAN_SUFFIXES or a renamed root would
    # turn the register into decoration without anything going red.
    if not SCANNED:
        print(
            "\nprod-readiness: FAILED — no file was scanned for markers, so the register was\n"
            "compared against nothing. Check SCAN_SUFFIXES and SKIP_DIRS in this script."
        )
        return 1

    for bid in sorted(set(found) - registered):
        errors.append(
            f"PROD-BLOCKER({bid}) is marked in {', '.join(sorted(found[bid]))} but is not in "
            f"the BLOCKERS register in scripts/prod_readiness.py — add it, with why it exists "
            f"and what must replace it."
        )
    for bid in sorted(registered - set(found)):
        errors.append(
            f"PROD-BLOCKER({bid}) is in the BLOCKERS register but no marker remains in the "
            f"tree — if it is resolved, delete the register entry."
        )

    if errors:
        print("prod-readiness: FAILED — register and code disagree\n")
        for e in errors:
            print(f"  ✗ {e}")
        return 1

    if args.json:
        _write_verdict(args.json)

    if not BLOCKERS:
        print("prod-readiness: OK — no open production blockers.")
        return 0

    print(f"prod-readiness: {len(BLOCKERS)} open blocker(s) — must be resolved before launch:")
    for bid, why in BLOCKERS:
        print(f"  • {bid}: {why}")
    if args.strict:
        print("\nprod-readiness: FAILED (--strict) — resolve these before releasing.")
        return 1
    print(
        "\n(Consistent with the code. Run with --strict in a release workflow to block on these.)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
