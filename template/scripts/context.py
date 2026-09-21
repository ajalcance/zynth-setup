#!/usr/bin/env python3
"""Derive a session-start snapshot of this repository's memory.

**Prints; never writes.** That is the whole point: the repository already holds the durable
memory, so persisting a summary would create a second copy that drifts out of agreement with
the first. This reads the real records and shows them, so a session can start from reality
instead of from recollection.

Run: ``python3 scripts/context.py`` (or ``make context``). Always exits 0 — a diagnostic,
not a gate.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULE = "─" * 78


def _git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=15, check=False
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _read(rel: str) -> str:
    path = ROOT / rel
    return path.read_text() if path.is_file() else ""


def _section(title: str) -> None:
    print(f"\n{title}\n{RULE}")


def _bullets(lines: list[str], empty: str) -> None:
    if not lines:
        print(f"  ({empty})")
        return
    for line in lines:
        print(f"  {line}")


def show_git() -> None:
    _section("Working tree")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "(unknown)"
    head = _git("log", "-1", "--pretty=%h %s") or "(no commits yet)"
    dirty = _git("status", "--porcelain")
    print(f"  branch : {branch}")
    print(f"  HEAD   : {head}")
    print(f"  state  : {'DIRTY — uncommitted changes' if dirty else 'clean'}")


def show_as_built() -> None:
    _section("As-built (docs/architecture/current-state.md)")
    text = _read("docs/architecture/current-state.md")
    if not text:
        print("  (missing — dod-check will fail)")
        return
    synced = re.search(r"^_Synced:\s*(.+?)_?$", text, re.M)
    status = re.search(r"^\*\*Status:\*\*\s*(.+)$", text, re.M)
    print(f"  synced : {synced.group(1).strip() if synced else '(not stated)'}")
    if status:
        print(f"  status : {status.group(1).strip()[:100]}")


def show_adrs() -> None:
    _section("Recent decisions (docs/decisions/)")
    decisions = ROOT / "docs" / "decisions"
    if not decisions.is_dir():
        print("  (none)")
        return
    adrs = sorted(f for f in decisions.glob("[0-9][0-9][0-9][0-9]-*.md"))
    titles = []
    for path in adrs[-4:]:
        first = path.read_text().splitlines()[0] if path.read_text().splitlines() else path.stem
        titles.append(first.lstrip("# ").strip())
    _bullets(titles, "no ADRs yet")
    if adrs:
        print(f"  next ADR number: {int(adrs[-1].name[:4]) + 1:04d}")


def show_plan() -> None:
    _section("Up next (docs/PLAN.md)")
    text = _read("docs/PLAN.md")
    block = re.search(r"###\s*🟨\s*Up next\s*\n(.*?)(\n###|\n##|\Z)", text, re.S)
    items = []
    if block:
        items = [
            ln.strip()
            for ln in block.group(1).splitlines()
            if ln.strip().startswith("- ")  # "- item", not a "---" rule
        ]
    _bullets(items[:6], "nothing listed")


def show_lessons() -> None:
    _section("Latest lessons (docs/LESSONS.md)")
    text = _read("docs/LESSONS.md")
    entries = re.findall(r"^##\s+(\d{4}-\d{2}-\d{2}.*)$", text, re.M)
    _bullets(entries[:4], "no dated entries yet")


def show_release() -> None:
    _section("Release state")
    changelog = _read("CHANGELOG.md")
    released = re.search(r"^##\s*\[(\d+\.\d+\.\d+)\]", changelog, re.M)
    print(f"  latest released : {released.group(1) if released else '(none yet)'}")
    unreleased = re.search(r"##\s*\[Unreleased\]\s*\n(.*?)(\n##|\Z)", changelog, re.S)
    pending = [
        ln.strip()
        for ln in (unreleased.group(1).splitlines() if unreleased else [])
        if ln.strip().startswith("-")
    ]
    print(f"  unreleased notes: {len(pending)}")
    tag = _git("describe", "--tags", "--abbrev=0")
    print(f"  latest tag      : {tag or '(none)'}")


def show_blockers() -> None:
    _section("Production blockers (scripts/prod_readiness.py)")
    text = _read("scripts/prod_readiness.py")
    block = re.search(r"BLOCKERS:[^=]*=\s*\((.*?)\n\)", text, re.S)
    body = block.group(1) if block else ""
    ids = re.findall(r'\(\s*"([^"]+)"', body)
    _bullets(ids, "none registered")


def main() -> int:
    print(RULE)
    print("  SESSION CONTEXT — derived from the repository, not stored anywhere.")
    print("  Source of truth, highest first: running code & live settings > as-built >")
    print("  ADRs > PLAN > LESSONS > CHANGELOG > session notes (reverify before use).")
    print(RULE)
    show_git()
    show_as_built()
    show_adrs()
    show_plan()
    show_lessons()
    show_release()
    show_blockers()
    print(f"\n{RULE}")
    print("  This is a snapshot, not authority. Verify anything load-bearing against the code.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
