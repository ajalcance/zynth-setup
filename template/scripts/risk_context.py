#!/usr/bin/env python3
"""Experience retrieval and registry validation.

Two modes over ``experience/registry.toml``:

**Retrieval** (default) — matches the paths in your current diff against the registry and prints
only the patterns that apply. This is a *diagnostic*: it always exits 0, and it never overrides
code, tests, ADRs or live settings. Reading every past lesson before every change does not scale;
being shown the three that touch the files you are editing does.

**Validation** (``--validate``) — blocking, and the reason the registry can be trusted. A pattern
claiming ``enforcement = "guard"`` must NAME a file that exists, so the registry cannot assert
automation it does not have. This is the same honesty rule the control map's enforcement markers
follow: a claim of mechanical enforcement has to be backed by a mechanism.

Usage:
    python3 scripts/risk_context.py [--base <ref>]   # retrieval (make risk-context)
    python3 scripts/risk_context.py --validate       # registry integrity (CI)
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "experience" / "registry.toml"
REGISTRY_REL = "experience/registry.toml"

# The enforcement ladder, weakest first. See experience/README.md.
LADDER = ("reference", "context", "checklist", "guard", "production_blocker")
NEEDS_MECHANISM = {"guard", "production_blocker"}
RULE = "─" * 78


class RegistryError(Exception):
    """The registry file exists but cannot be read as a registry.

    Distinct from "absent" and from "empty" on purpose. A malformed registry read as an empty
    one is the cheapest possible way to silence every claim that cites it (EXP-0001) — so the
    three states carry three different messages, and ``--validate`` refuses two of them.
    """


def load() -> list[dict]:
    """Registry patterns, or [] when the file is absent. Raises RegistryError if unreadable.

    Absent and empty are *both* returned as [] here — they are distinguished by the caller,
    because retrieval tolerates both and validation refuses both for different reasons.
    """
    if not REGISTRY.is_file():
        return []
    try:
        with REGISTRY.open("rb") as handle:
            document = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RegistryError(f"{REGISTRY_REL} cannot be read as TOML — {exc}") from exc
    patterns = document.get("pattern", [])
    if not isinstance(patterns, list) or any(not isinstance(entry, dict) for entry in patterns):
        raise RegistryError(
            f"{REGISTRY_REL}: 'pattern' must be an array of tables ([[pattern]]) — "
            f"a malformed registry must not be read as an empty one"
        )
    return patterns


def _has_commits() -> bool:
    return (
        subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        ).returncode
        == 0
    )


def changed_files(base: str | None) -> list[str]:
    """Files in the working tree diff, or against a base ref when one is given.

    A freshly generated project has no commits yet, so `git diff HEAD` errors. That is the exact
    moment an adopter first runs this, so it must not silently report a partial picture.
    """
    if base is None and not _has_commits():
        return sorted(
            line
            for line in subprocess.run(
                ["git", "ls-files"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            ).stdout.splitlines()
            if line
        )
    commands = (
        [["git", "diff", "--name-only", f"{base}...HEAD"]]
        if base
        else [
            ["git", "diff", "--name-only", "HEAD"],
            ["git", "ls-files", "--others", "--exclude-standard"],
        ]
    )
    files: list[str] = []
    for command in commands:
        try:
            out = subprocess.run(
                command, cwd=ROOT, capture_output=True, text=True, check=False, timeout=60
            ).stdout
            files.extend(line for line in out.splitlines() if line)
        except (OSError, subprocess.SubprocessError):
            continue
    return sorted(set(files))


def matches(pattern: dict, files: list[str]) -> list[str]:
    hits: list[str] = []
    for glob in pattern.get("paths", []):
        for path in files:
            # fnmatch's "*" crosses "/", so "**" and "*" both behave as a broad match here.
            if fnmatch.fnmatch(path, glob) or (
                glob.endswith("/**") and path.startswith(glob[:-3] + "/")
            ):
                hits.append(path)
    return sorted(set(hits))


def validate() -> int:
    """Blocking registry integrity check. Fails closed — see EXP-0001.

    An absent registry, an empty one and an unreadable one each fail with their OWN message.
    They are three different ways to erase every enforcement claim that cites the registry,
    and a single shared message lets a test pass against the wrong branch.
    """
    if not REGISTRY.is_file():
        print(
            f"risk-context: FAILED — {REGISTRY_REL} does not exist.\n\n"
            "  Every enforcement claim citing a pattern id is unverifiable without it, so\n"
            "  deleting the file would otherwise be the cheapest way to pass this gate.\n"
            "  Restore it from git history, or from the template if this is a fresh project."
        )
        return 1
    try:
        patterns = load()
    except RegistryError as exc:
        print(f"risk-context: FAILED — {exc}")
        return 1
    if not patterns:
        print(
            f"risk-context: FAILED — {REGISTRY_REL} declares no pattern.\n\n"
            "  An empty registry erases the recorded failure patterns exactly as deleting the\n"
            "  file would. If a pattern no longer applies, say so in its entry — do not remove\n"
            "  the last one."
        )
        return 1

    errors: list[str] = []
    seen: set[str] = set()
    for entry in patterns:
        pid = entry.get("id", "<missing id>")
        if pid in seen:
            errors.append(f"{pid}: duplicate id — ids must be unique so they can be cited")
        seen.add(pid)

        for field in ("id", "title", "enforcement", "guidance"):
            if not entry.get(field):
                errors.append(f"{pid}: missing required field '{field}'")

        rung = entry.get("enforcement")
        if rung and rung not in LADDER:
            errors.append(f"{pid}: unknown enforcement '{rung}' — use one of {', '.join(LADDER)}")
            continue

        if rung in NEEDS_MECHANISM:
            mechanisms = entry.get("enforced_by") or []
            if not mechanisms:
                errors.append(
                    f"{pid}: enforcement '{rung}' claims automation but names no 'enforced_by' — "
                    f"either name the guard that enforces it, or drop it to 'checklist'"
                )
            for mechanism in mechanisms:
                if not (ROOT / mechanism).exists():
                    errors.append(
                        f"{pid}: enforced_by '{mechanism}' does not exist — the registry would be "
                        f"claiming enforcement that is not there"
                    )

    if errors:
        print("risk-context: FAILED — the experience registry is not trustworthy\n")
        for error in errors:
            print(f"  ✗ {error}")
        print(
            "\nA registry that can claim enforcement it does not have is a wish list. Fix the entry,\n"
            "or lower its rung to one that is honest about how it is actually enforced."
        )
        return 1

    ladder_counts = {
        rung: sum(1 for e in patterns if e.get("enforcement") == rung) for rung in LADDER
    }
    summary = " · ".join(f"{rung}:{count}" for rung, count in ladder_counts.items() if count)
    print(f"risk-context: OK — {len(patterns)} pattern(s) validated ({summary}).")
    return 0


def retrieve(base: str | None) -> int:
    # Retrieval is advisory and always exits 0, so a broken registry degrades to "no patterns"
    # here rather than blocking work. --validate is the blocking read of the same file.
    try:
        patterns = load()
    except RegistryError as exc:
        print(f"  (registry unreadable — {exc}; run `--validate` for the blocking check)")
        patterns = []
    files = changed_files(base)

    print(RULE)
    print(
        f"  RISK CONTEXT — {len(files)} changed file(s) matched against {len(patterns)} pattern(s)"
    )
    print("  Advisory only. Never overrides code, tests, ADRs or live settings.")
    print(RULE)

    if not files:
        print("\n  No changes detected — nothing to match.")
        return 0

    if not _has_commits():
        print("\n  (No commits yet — matching against the whole tree.)")

    applicable = [(entry, hit) for entry in patterns if (hit := matches(entry, files))]
    if not applicable:
        print("\n  No registered pattern touches these paths.")
        return 0

    # Strongest rung first: the ones that can actually block you are worth reading first.
    applicable.sort(
        key=lambda pair: LADDER.index(pair[0].get("enforcement", "reference")), reverse=True
    )

    for entry, hits in applicable:
        rung = entry.get("enforcement", "reference")
        print(f"\n  {entry['id']}  [{rung}]  {entry['title']}")
        for line in entry.get("guidance", "").strip().splitlines():
            print(f"      {line}")
        shown = ", ".join(hits[:4]) + (f" (+{len(hits) - 4} more)" if len(hits) > 4 else "")
        print(f"      matched: {shown}")
        if rung in NEEDS_MECHANISM:
            print(f"      enforced by: {', '.join(entry.get('enforced_by', []))}")

    print(f"\n{RULE}")
    print("  An agent may RECOMMEND promoting a pattern up the ladder; it may not do so itself.")
    print("  See experience/README.md.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--validate", action="store_true", help="check registry integrity (blocking)"
    )
    parser.add_argument(
        "--base", default=None, help="diff against this ref instead of the worktree"
    )
    args = parser.parse_args()
    return validate() if args.validate else retrieve(args.base)


if __name__ == "__main__":
    sys.exit(main())
