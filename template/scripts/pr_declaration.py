#!/usr/bin/env python3
"""Verify the PR's Memory impact declaration against the actual diff.

The Definition of Done says which records must be updated after a change. A checkbox proves
nothing — it is checked by the same person (or agent) who might have skipped the work. This
guard makes the claim *machine-checkable* by comparing it to the diff, in **both** directions:

* a record declared ``updated`` must actually appear in the diff — **and the change must be
  real**. A whitespace edit, or one token appended to the lessons log, is a file touched to
  satisfy a checkbox, not a record kept current;
* a record the diff **does** touch may not be declared ``N/A`` — otherwise the declaration is
  stale and the next reader trusts a summary that no longer matches the change.

**Fail-closed.** An unreadable diff is a hard failure, never an empty one. With no diff to
contradict them, *every* ``N/A`` passes — so "git could not run" would silently turn this guard
into a rubber stamp. That is EXP-0001 in a different costume: a guard that inspects nothing
still reports green. Do not "soften" this back to returning an empty list.

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

# Records whose update is a dated, append-only log entry rather than an edit in place. One
# token added to the bottom of LESSONS.md satisfies "the file appears in the diff" while
# recording nothing, so these two need either a dated heading or real prose.
DATED_LOG_RECORDS = ("PLAN", "LESSONS")
MIN_SUBSTANTIVE_LINES = 3
DATED_HEADING_RE = re.compile(r"^#{1,6}\s.*\d{4}-\d{2}-\d{2}|^\s*[-*]\s.*\d{4}-\d{2}-\d{2}")

# A separator may be a colon or any dash a human (or an editor's smart-punctuation) produces.
# The grammar the parser accepts and the shape .github/PULL_REQUEST_TEMPLATE.md shows must be
# the same thing — a rejection whose message does not name the accepted shape sends the author
# guessing. See ACCEPTED_SHAPE below, which is printed on every parse failure.
SEP = r"[:\-\u2013\u2014]"
LINE_RE = re.compile(
    r"^\s*[-*]\s*(?P<key>"
    + "|".join(map(re.escape, DECLARATIONS))
    + r")\s*"
    + SEP
    + r"\s*(?P<value>.+?)\s*$",
    re.MULTILINE,
)
UPDATED_RE = re.compile(r"^updated\b", re.IGNORECASE)
NA_RE = re.compile(r"^n/?a\s*" + SEP + r"\s*(?P<reason>.+)$", re.IGNORECASE)
MIN_REASON_CHARS = 8
ACCEPTED_SHAPE = (
    "Accepted shapes (one record per line):\n"
    "    - PLAN: updated\n"
    "    - PLAN: N/A: <concrete reason>\n"
    "  A colon, hyphen, en dash or em dash all work as the separator, and a reason may wrap\n"
    "  onto following indented lines."
)

# A new module tree under the backend package is a new subsystem. Matched without knowing the
# package name — interpolating a copier value into a linted line is its own hazard, and this
# guard must keep working after a package rename. `backend/tests/` and `backend/migrations/`
# are siblings of the package, not trees inside it.
NEW_TREE_RE = re.compile(r"^backend/(?!tests/|migrations/)(?P<pkg>[^/]+)/(?P<tree>[^/]+)/.+\.py$")


class DiffUnavailable(RuntimeError):
    """git could not produce a diff. Distinct from "the diff is empty" — see the module docstring."""


def _git(*args: str, base: str) -> str:
    try:
        done = subprocess.run(
            ["git", *args], capture_output=True, text=True, check=False, timeout=60
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DiffUnavailable(f"git {' '.join(args)} could not run — {exc}") from exc
    if done.returncode != 0:
        raise DiffUnavailable(
            f"git {' '.join(args)} exited {done.returncode} — {done.stderr.strip() or 'no stderr'}.\n"
            f"  The base ref {base!r} is probably missing from this checkout: a shallow clone has\n"
            f"  no merge base. Fetch it (actions/checkout with fetch-depth: 0) and re-run."
        )
    return done.stdout


def changed_files(base: str) -> list[str]:
    """Paths in the diff. Raises DiffUnavailable rather than reporting an empty diff."""
    return [
        line
        for line in _git("diff", "--name-only", f"{base}...HEAD", base=base).splitlines()
        if line
    ]


def _diff_lines(base: str, *paths: str) -> tuple[list[str], list[str]]:
    """(added, removed) content lines for the given paths, file headers excluded."""
    out = _git("diff", "-U0", f"{base}...HEAD", "--", *paths, base=base)
    added = [ln[1:] for ln in out.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    removed = [ln[1:] for ln in out.splitlines() if ln.startswith("-") and not ln.startswith("---")]
    return added, removed


def substance(key: str, paths: tuple[str, ...], base: str) -> str | None:
    """Why this record's change is too thin to be called an update, or None if it is real."""
    added, removed = _diff_lines(base, *paths)
    if key in DATED_LOG_RECORDS:
        if any(DATED_HEADING_RE.match(line.strip()) for line in added):
            return None
        substantive = [line for line in added if line.strip()]
        if len(substantive) < MIN_SUBSTANTIVE_LINES:
            return (
                f"'{key}: updated' is declared, but the diff adds only {len(substantive)} "
                f"non-blank line(s) to {' or '.join(paths)} and no dated heading. A log entry "
                f"nobody can date is a file touched to satisfy a checkbox."
            )
        return None
    if not any(line.strip() for line in added + removed):
        return (
            f"'{key}: updated' is declared, but the only change to {' or '.join(paths)} is "
            f"whitespace. Record what changed, or declare 'N/A: <reason>'."
        )
    return None


def new_package_trees(base: str) -> list[str]:
    """Module trees under the backend package that this diff creates from nothing."""
    added = [
        line
        for line in _git(
            "diff", "--name-only", "--diff-filter=A", f"{base}...HEAD", base=base
        ).splitlines()
        if line
    ]
    candidates = {
        f"backend/{m.group('pkg')}/{m.group('tree')}"
        for line in added
        if (m := NEW_TREE_RE.match(line))
    }
    # Only trees that did not exist at the base: adding a file to an existing package is not a
    # new subsystem.
    return sorted(
        tree
        for tree in candidates
        if not _git("ls-tree", "-d", base, "--", tree, base=base).strip()
    )


def touches(paths: tuple[str, ...], changed: list[str]) -> list[str]:
    hits = []
    for path in paths:
        for candidate in changed:
            if candidate.startswith(path) if path.endswith("/") else candidate == path:
                hits.append(candidate)
    return sorted(set(hits))


def unwrap(body: str) -> str:
    """Join a declaration's wrapped continuation lines back onto one line.

    A PR body written in an editor that soft-wraps arrives with the reason split across lines.
    The parser wants one record per line, so rejoin before matching rather than rejecting a
    declaration that is only badly wrapped — a guard whose message sends the author guessing
    at whitespace teaches them to route around it.
    """
    start = re.compile(
        r"^\s*[-*]\s*(?:" + "|".join(map(re.escape, DECLARATIONS)) + r")\s*" + SEP, re.IGNORECASE
    )
    out: list[str] = []
    joining = False
    for line in body.splitlines():
        if start.match(line):
            out.append(line.rstrip())
            joining = True
            continue
        if joining and line.strip() and not re.match(r"^\s*(?:[-*+]\s|#{1,6}\s|\||>|```)", line):
            out[-1] += " " + line.strip()
            continue
        joining = False
        out.append(line)
    return "\n".join(out)


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
    body = unwrap(body)

    declared = {m.group("key"): m.group("value").strip() for m in LINE_RE.finditer(body)}
    errors: list[str] = []

    # Fail closed. Without a diff every N/A is unopposed, so this guard would pass everything.
    try:
        changed = changed_files(args.base)
        new_trees = new_package_trees(args.base)
    except DiffUnavailable as exc:
        print("pr-declaration: FAILED — the diff could not be read, so nothing was checked\n")
        print(f"  ✗ {exc}")
        print(
            "\nThis is a hard failure on purpose. With no diff to contradict them, every 'N/A'\n"
            "would pass and the declaration would be checked against nothing."
        )
        return 1

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
            elif (thin := substance(key, paths, args.base)) is not None:
                errors.append(thin)
            continue

        na = NA_RE.match(value)
        if not na:
            errors.append(f"'{key}: {value}' is not a valid answer.\n  {ACCEPTED_SHAPE}")
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
        elif key == "ADR" and new_trees:
            # No reason is good enough here. A new subsystem IS a design decision, and the
            # honest N/A ("refactor only") is exactly what an agent writes while adding one.
            errors.append(
                f"'ADR' is declared N/A, but this diff creates {', '.join(new_trees)} — a new "
                f"module tree under the backend package is a new subsystem, and a new subsystem "
                f"is a design decision. Write the ADR in docs/decisions/."
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
