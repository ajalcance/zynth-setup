#!/usr/bin/env python3
"""Verify the PR's Memory impact declaration against the actual diff.

The Definition of Done says which records must be updated after a change. A checkbox proves
nothing — it is checked by the same person (or agent) who might have skipped the work. This
guard makes the claim *machine-checkable* by comparing it to the diff, in **both** directions:

* a record declared ``updated`` must actually appear in the diff — otherwise the claim is false;
* a record the diff **does** touch may not be declared ``N/A`` — otherwise the declaration is
  stale and the next reader trusts a summary that no longer matches the change.

``N/A`` is always allowed, but it must carry a concrete reason. That keeps the escape open for
the many changes that genuinely do not move the roadmap, while making "I skipped the docs"
something a human has to write down rather than something that happens silently.

Usage:
    python3 scripts/pr_declaration.py --body-file <path> [--base origin/main]

Exit code is non-zero if the declaration is missing, malformed, or contradicts the diff.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

# Declaration key -> the repo paths that satisfy it. A trailing "/" means "any file under here".
DECLARATIONS: dict[str, tuple[str, ...]] = {
    "PLAN": ("docs/PLAN.md",),
    "LESSONS": ("docs/LESSONS.md",),
    "current-state": ("docs/architecture/current-state.md",),
    "ADR": ("docs/decisions/",),
    "CHANGELOG": ("CHANGELOG.md",),
}

LINE_RE = re.compile(
    r"^\s*[-*]\s*(?P<key>" + "|".join(map(re.escape, DECLARATIONS)) + r")\s*:\s*(?P<value>.+?)\s*$",
    re.MULTILINE,
)
UPDATED_RE = re.compile(r"^updated\b", re.IGNORECASE)
NA_RE = re.compile(r"^n/?a\s*[:\-]\s*(?P<reason>.+)$", re.IGNORECASE)
MIN_REASON_CHARS = 8


def changed_files(base: str) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...HEAD"],
            capture_output=True, text=True, check=True, timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line for line in out.splitlines() if line]


def touches(paths: tuple[str, ...], changed: list[str]) -> list[str]:
    hits = []
    for path in paths:
        for candidate in changed:
            if candidate.startswith(path) if path.endswith("/") else candidate == path:
                hits.append(candidate)
    return sorted(set(hits))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--body-file", required=True, help="file containing the PR description")
    parser.add_argument("--base", default="origin/main", help="base ref to diff against")
    args = parser.parse_args()

    try:
        with open(args.body_file, encoding="utf-8") as handle:
            body = handle.read()
    except OSError:
        body = ""

    # Instructions live in HTML comments; stripping them stops the example text in the template
    # from being read as a real declaration.
    body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)

    declared = {m.group("key"): m.group("value").strip() for m in LINE_RE.finditer(body)}
    errors: list[str] = []
    changed = changed_files(args.base)

    missing = sorted(set(DECLARATIONS) - set(declared))
    if missing:
        errors.append(
            "PR description is missing the Memory impact line(s) for: "
            + ", ".join(missing)
            + ". Copy the block from .github/PULL_REQUEST_TEMPLATE.md and answer each one."
        )

    for key, value in sorted(declared.items()):
        paths = DECLARATIONS[key]
        hits = touches(paths, changed)

        if UPDATED_RE.match(value):
            if not hits:
                errors.append(
                    f"'{key}: updated' is declared, but the diff does not touch "
                    f"{' or '.join(paths)}. Either make the update or declare 'N/A: <reason>'."
                )
            continue

        na = NA_RE.match(value)
        if not na:
            errors.append(
                f"'{key}: {value}' is not a valid answer. Use exactly 'updated' or "
                f"'N/A: <concrete reason>'."
            )
            continue

        reason = na.group("reason").strip()
        if "<" in reason or ">" in reason or len(reason) < MIN_REASON_CHARS:
            errors.append(
                f"'{key}' is declared N/A without a concrete reason ({reason!r}). Say why this "
                f"change genuinely does not affect that record."
            )
        elif hits:
            errors.append(
                f"'{key}' is declared N/A, but the diff DOES change {', '.join(hits)}. "
                f"Declare it 'updated' so the record and the claim agree."
            )

    if errors:
        print("pr-declaration: FAILED — the Memory impact declaration does not match the diff\n")
        for error in errors:
            print(f"  ✗ {error}")
        print(
            "\nThis is the Definition of Done made checkable: a claim that a record was updated\n"
            "must be true, and skipping one must be a deliberate, stated choice."
        )
        return 1

    print(f"pr-declaration: OK — {len(declared)} record(s) declared and consistent with the diff.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
