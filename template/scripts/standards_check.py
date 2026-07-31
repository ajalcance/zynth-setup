#!/usr/bin/env python3
"""Standards-suite integrity: a rule may not claim enforcement it does not have.

``docs/standards/`` states the engineering rules as tables of stable, citable IDs. Each rule
declares **how it is actually enforced** using the marker vocabulary from
``docs/ENGINEERING_PROCESS.md``. That declaration is the valuable part and it is also the part
that rots first: a mechanism gets renamed, a rule gets written aspirationally, and the suite
starts describing a control system that is not there. Everyone downstream then believes a green
CI proves something it never checked.

So the claims are machine-checked, the same way ``risk_context.py --validate`` checks the
experience registry:

1. **Rule IDs are well-formed and unique** — ``<PREFIX>-<NNN>``, prefix from the declared set.
   A malformed ID is an error rather than a silently-skipped row: a rule that quietly drops out
   of the suite is worse than one that is wrong, because nothing shows it went missing.
2. **The marker is from the vocabulary** — ``[CI]``, ``[Review]``, ``[Production blocker]``, or
   ``[Phase gate - vX.Y]`` (a phase gate must name the release it is promised for).
3. **``[CI]`` names a mechanism that exists** — at least one repo-relative path in the Mechanism
   cell, and every path there present on disk.
4. **``[Production blocker]`` is actually registered** — its ``PROD-BLOCKER(<id>)`` must appear
   in the register in ``scripts/prod_readiness.py``. That marker means "a release is denied
   until this closes"; if nothing holds it, the rule is prose wearing a gate's uniform.
5. **Citations resolve** — a rule ID referenced anywhere in the docs must be defined in the
   suite, so renaming or deleting a rule cannot leave dangling references behind.

Run from the repo root: ``python3 scripts/standards_check.py`` (or via ``make dod-check``).
Exit code is non-zero if any claim is unsupported.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STANDARDS = ROOT / "docs" / "standards"

# Rule-ID prefixes. Each one must be documented in docs/standards/README.md (drift is a test).
PREFIXES = ("BE", "API", "FE", "TA", "SEC", "OBS", "REL")

# Loose enough to notice a row that MEANT to be a rule, strict enough not to match prose.
CANDIDATE_ID_RE = re.compile(r"^[A-Z]{2,6}-[0-9]{1,4}$")
RULE_ID_RE = re.compile(rf"^(?:{'|'.join(PREFIXES)})-[0-9]{{3}}$")

# The marker vocabulary of docs/ENGINEERING_PROCESS.md. An em dash is normalised to "-" first,
# so the doc can read "[Phase gate — v2.0]" without the guard depending on the dash character.
MARKER_RES = {
    "CI": re.compile(r"^\[CI\]$"),
    "Review": re.compile(r"^\[Review\]$"),
    "Production blocker": re.compile(r"^\[Production blocker\]$"),
    "Phase gate": re.compile(r"^\[Phase gate - v[0-9]+\.[0-9]+\]$"),
}

# A backticked token is treated as a repo path when it looks like one: no spaces, and it
# contains a "/" or carries a file extension. This keeps `mypy --strict`, `ruff`, `C90` and
# route templates such as /api/v1/... from being mistaken for files that must exist.
CODE_RE = re.compile(r"`([^`]+)`")
PATHISH_RE = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_./-]*$")
FILE_EXT_RE = re.compile(r"\.(py|ts|tsx|mjs|cjs|js|json|ya?ml|sh|toml|txt|ini|cfg|md|lock)$")
BLOCKER_REF_RE = re.compile(r"PROD-BLOCKER\(([a-z0-9][a-z0-9-]*)\)")

# Where a rule ID may be cited. Mirrors dod-check.py's DOC_GLOBS so the two guards agree on
# what counts as documentation.
DOC_GLOBS = ("docs/**/*.md", "*.md", ".github/**/*.md", ".claude/**/*.md")
CITATION_RE = re.compile(rf"\b(?:{'|'.join(PREFIXES)})-[0-9]{{3}}\b")


def _cells(line: str) -> list[str]:
    """Split a markdown table row into stripped cells, or [] if it is not a row."""
    stripped = line.strip()
    if not stripped.startswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def parse_rules() -> tuple[list[dict], list[str]]:
    """Every rule row in docs/standards/, plus errors for rows that only look like rules."""
    rules: list[dict] = []
    errors: list[str] = []
    if not STANDARDS.is_dir():
        return rules, errors

    for doc in sorted(STANDARDS.glob("*.md")):
        rel = doc.relative_to(ROOT)
        for number, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), start=1):
            cells = _cells(line)
            if len(cells) < 4 or not CANDIDATE_ID_RE.match(cells[0]):
                continue
            rule_id, text, marker, mechanism = cells[0], cells[1], cells[2], cells[3]
            where = f"{rel}:{number}"
            if not RULE_ID_RE.match(rule_id):
                errors.append(
                    f"{where}: '{rule_id}' is not a valid rule id — use <PREFIX>-<NNN> with a "
                    f"prefix from {', '.join(PREFIXES)} (an unparsed row silently leaves the suite)"
                )
                continue
            rules.append(
                {
                    "id": rule_id,
                    "text": text,
                    "marker": marker,
                    "mechanism": mechanism,
                    "where": where,
                }
            )
    return rules, errors


def _marker_kind(marker: str) -> str | None:
    normalised = " ".join(marker.replace("`", "").replace("—", "-").split())
    for kind, pattern in MARKER_RES.items():
        if pattern.match(normalised):
            return kind
    return None


def _paths(mechanism: str) -> list[str]:
    return [
        token
        for token in CODE_RE.findall(mechanism)
        if PATHISH_RE.match(token) and ("/" in token or FILE_EXT_RE.search(token))
    ]


def registered_blockers() -> set[str]:
    """The ids in the prod-readiness register, or an empty set if it cannot be read.

    Empty on failure is deliberate: a `[Production blocker]` claim then fails rather than
    passing on an unverified assumption.
    """
    path = ROOT / "scripts" / "prod_readiness.py"
    if not path.is_file():
        return set()
    try:
        spec = importlib.util.spec_from_file_location("_prod_readiness_register", path)
        if spec is None or spec.loader is None:
            return set()
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return {str(entry[0]) for entry in getattr(module, "BLOCKERS", ())}
    except (OSError, SyntaxError, ValueError, ImportError, AttributeError, IndexError, TypeError):
        # An unreadable register must not be read as "all clear" — return nothing, so a
        # [Production blocker] claim fails instead of passing on an unverified assumption.
        return set()


def check_rules(rules: list[dict], errors: list[str]) -> None:
    seen: dict[str, str] = {}
    blockers = registered_blockers()

    for rule in rules:
        rule_id, where = rule["id"], rule["where"]
        if rule_id in seen:
            errors.append(
                f"{where}: rule id '{rule_id}' is already defined at {seen[rule_id]} — a reused "
                f"id makes every citation of it ambiguous"
            )
        seen.setdefault(rule_id, where)

        if not rule["text"]:
            errors.append(f"{where}: {rule_id} has no rule text")

        kind = _marker_kind(rule["marker"])
        if kind is None:
            errors.append(
                f"{where}: {rule_id} has enforcement '{rule['marker']}' — use one of "
                f"[CI], [Review], [Production blocker], [Phase gate - vX.Y] "
                f"(a phase gate must name the release it is promised for)"
            )
            continue

        paths = _paths(rule["mechanism"])
        for path in paths:
            if not (ROOT / path).exists():
                errors.append(
                    f"{where}: {rule_id} names mechanism '{path}', which does not exist — "
                    f"the rule would be claiming enforcement that is not there"
                )

        if kind == "CI" and not paths:
            errors.append(
                f"{where}: {rule_id} is marked [CI] but names no mechanism — name the file or "
                f"directory that enforces it, or mark it [Review] and be honest about it"
            )

        if kind == "Production blocker":
            referenced = set(BLOCKER_REF_RE.findall(rule["mechanism"]))
            if not referenced:
                errors.append(
                    f"{where}: {rule_id} is marked [Production blocker] but names no "
                    f"PROD-BLOCKER(<id>) — that marker means a release is denied until an entry "
                    f"in scripts/prod_readiness.py closes"
                )
            for blocker in sorted(referenced - blockers):
                errors.append(
                    f"{where}: {rule_id} cites PROD-BLOCKER({blocker}), which is not in the "
                    f"BLOCKERS register in scripts/prod_readiness.py — nothing is actually "
                    f"holding the release"
                )


def check_citations(rules: list[dict], errors: list[str]) -> None:
    defined = {rule["id"] for rule in rules}
    for glob in DOC_GLOBS:
        for doc in sorted(ROOT.glob(glob)):
            if not doc.is_file():
                continue
            rel = doc.relative_to(ROOT)
            for cited in sorted(set(CITATION_RE.findall(doc.read_text(encoding="utf-8")))):
                if cited not in defined:
                    errors.append(
                        f"{rel}: cites rule '{cited}', which is not defined in docs/standards/ — "
                        f"a renamed or deleted rule leaves every reference to it dangling"
                    )


def main() -> int:
    rules, errors = parse_rules()
    check_rules(rules, errors)
    check_citations(rules, errors)

    if errors:
        print("standards-check: FAILED — the standards suite claims enforcement it cannot back\n")
        for error in errors:
            print(f"  ✗ {error}")
        print(
            "\nA rule that claims automation it does not have is worse than no rule: everyone\n"
            "downstream believes the gate exists. Name a real mechanism, or lower the marker."
        )
        return 1

    counts: dict[str, int] = {}
    for rule in rules:
        kind = _marker_kind(rule["marker"]) or "?"
        counts[kind] = counts.get(kind, 0) + 1
    summary = " · ".join(f"{kind}:{count}" for kind, count in sorted(counts.items()))
    print(f"standards-check: OK — {len(rules)} rule(s) validated ({summary or 'none'}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
