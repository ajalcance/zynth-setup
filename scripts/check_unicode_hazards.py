#!/usr/bin/env python3
"""Reject source that reads differently from how it runs.

A bidirectional override character reorders how a line is *displayed* without changing a byte
of what the parser sees. ``if (isAdmin) // RLO ...`` can render as a comment and execute as a
branch, and a reviewer approving it is reading a different program from the one that ships.
Zero-width and invisible formatting characters do the neighbouring trick: two identifiers that
render identically and compare unequal.

Nearly free to run and it closes a real class of attack, so it runs over every text file this
repository ships rather than a curated subset.

What is allowed, deliberately:

* every ordinary non-ASCII character — em dashes, box drawing, accented names and emoji are
  normal writing, and a guard that rejects them would be turned off within a week;
* a byte-order mark at offset 0, which some editors write and no parser mis-reads.

Usage:  python3 scripts/check_unicode_hazards.py [path ...]
Exit code is non-zero if a hazard is found, or if no file was inspected at all.
"""

from __future__ import annotations

import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Each entry is (codepoint, short name, why it is a hazard).
# Built with chr() at runtime so this file contains NONE of the characters it forbids. A
# fixture that trips the scanner teaches the next person to add an exemption, and the
# exemption is always easier than the fix — which is exactly why the ratchet exists.
# {codepoint: (short name, why it is a hazard)}
_HAZARDS_BY_CODEPOINT: dict[int, tuple[str, str]] = {
    # Bidirectional overrides and isolates — the "Trojan Source" class.
    0x202A: ("LRE", "reorders the rendered line without changing what the parser reads"),
    0x202B: ("RLE", "reorders the rendered line without changing what the parser reads"),
    0x202C: ("PDF", "ends a reordering started by LRE/RLE"),
    0x202D: ("LRO", "forces display order to differ from logical order"),
    0x202E: ("RLO", "forces display order to differ from logical order"),
    0x2066: ("LRI", "isolates a run so it renders out of order"),
    0x2067: ("RLI", "isolates a run so it renders out of order"),
    0x2068: ("FSI", "isolates a run so it renders out of order"),
    0x2069: ("PDI", "ends a bidirectional isolate"),
    0x200E: ("LRM", "invisible mark that changes rendered order"),
    0x200F: ("RLM", "invisible mark that changes rendered order"),
    # Zero-width and invisible formatting — identifiers that render alike and compare unequal.
    0x200B: ("ZWSP", "invisible; two identifiers can render identically and differ"),
    0x200C: ("ZWNJ", "invisible; two identifiers can render identically and differ"),
    0x200D: ("ZWJ", "invisible; two identifiers can render identically and differ"),
    0x2060: ("WJ", "invisible word joiner"),
    0x2061: ("FUNCTION APPLICATION", "invisible mathematical operator"),
    0x2062: ("INVISIBLE TIMES", "invisible mathematical operator"),
    0x2063: ("INVISIBLE SEPARATOR", "invisible mathematical operator"),
    0x2064: ("INVISIBLE PLUS", "invisible mathematical operator"),
    0x00AD: ("SOFT HYPHEN", "invisible except at a line break"),
    0x2028: ("LINE SEPARATOR", "a line break the eye and the parser disagree about"),
    0x2029: ("PARAGRAPH SEPARATOR", "a line break the eye and the parser disagree about"),
    0xFEFF: ("BOM", "zero-width no-break space anywhere but the very first byte"),
}
HAZARDS: dict[str, tuple[str, str]] = {
    chr(code): names for code, names in _HAZARDS_BY_CODEPOINT.items()
}
BOM = chr(0xFEFF)

SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".next",
    ".ruff_cache",
    "dist",
    "build",
}
# Binary formats a text scan would only produce noise over.
SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",
    ".svg",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
    ".mp4",
    ".pyc",
    ".so",
    ".dylib",
    ".whl",
}


def tracked_files() -> list[Path]:
    """Every file git tracks. Falls back to a walk when there is no repository yet."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if out.returncode == 0 and out.stdout:
            return [ROOT / name for name in out.stdout.split("\0") if name]
    except (OSError, subprocess.SubprocessError):
        pass
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file() and not SKIP_DIRS & set(path.relative_to(ROOT).parts)
    ]


def inspectable(path: Path) -> bool:
    if path.suffix.lower() in SKIP_SUFFIXES:
        return False
    return path.is_file() and not SKIP_DIRS & set(path.parts)


def display(path: Path) -> str:
    """A path the reader can act on, whether or not it lives under this repository.

    `relative_to` RAISES on a path outside ROOT, and an explicit path argument frequently is
    one — a guard that crashes prints no finding at all, which is a silent pass.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def scan(path: Path) -> list[str]:
    """Hazards in one file, as human-readable findings."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []  # not text; the suffix list catches most, this catches the rest
    findings: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        for column, character in enumerate(line, 1):
            if character not in HAZARDS:
                continue
            # A BOM at the very start of the file is an encoding marker, not a hazard.
            if character == BOM and number == 1 and column == 1:
                continue
            short, why = HAZARDS[character]
            official = unicodedata.name(character, "unnamed")
            findings.append(
                f"{display(path)}:{number}:{column}: "
                f"U+{ord(character):04X} {short} ({official}) — {why}"
            )
    return findings


def main() -> int:
    argv = sys.argv[1:]
    roots = [Path(a) for a in argv] if argv else [ROOT]
    if argv:
        candidates = [p for root in roots for p in ([root] if root.is_file() else root.rglob("*"))]
    else:
        candidates = tracked_files()

    inspected = 0
    findings: list[str] = []
    for path in candidates:
        if not inspectable(path):
            continue
        inspected += 1
        findings.extend(scan(path))

    print(f"unicode-hazards: inspected {inspected} file(s)")

    if not inspected:
        print(
            "\nunicode-hazards: FAILED — no file was inspected, so nothing was checked.\n"
            "A gate that scans an empty set reports green forever (EXP-0001)."
        )
        return 1

    if findings:
        print("\nunicode-hazards: FAILED — source that reads differently from how it runs:\n")
        for finding in findings:
            print(f"  ✗ {finding}")
        print(
            "\nDelete the character. If you genuinely need one in DATA, put it in a fixture\n"
            "built at runtime (chr(0x202E)) rather than as a literal in a source file — the\n"
            "point of this gate is that no reviewer can see it."
        )
        return 1

    print("unicode-hazards: OK — no bidirectional, zero-width or invisible character found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
