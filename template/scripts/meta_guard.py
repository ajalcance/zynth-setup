#!/usr/bin/env python3
"""Meta-guard: stop an agent from quietly weakening the guards to make CI green.

Five diff-based checks against the PR's base branch (no stored baseline to tamper with):

1. **Suppression ratchet** — the PR must not add net-new bypass markers
   (``# noqa``, ``# type: ignore``, ``# nosemgrep``, ``# pragma: no cover``,
   ``eslint-disable``, ``@ts-ignore``, ``@ts-nocheck``). Removing them is always fine.
   Scoped to source files (``.py``/``.ts``/``.tsx``/``.js``/``.jsx``, excluding ``docs/``)
   so that *documenting* a marker — an ADR explaining why blanket-disabling is banned —
   is not counted the same as *adding* one.
2. **Test presence** — if package source changed, a test must have changed too
   (catches "delete/hollow the tests so coverage/pytest pass").
3. **Guard-file change** — the PR must not touch a file that DEFINES a guard (this script,
   any CI workflow, a ruleset, Semgrep/gitleaks/pre-commit config, CODEOWNERS) without a
   human's explicit sign-off. This is the sharpest failure mode of the three: an agent hits
   a guard failure mid-task, decides "this is actually a bug in the guard," and edits the
   guard so its own PR goes green. The reasoning can be genuinely plausible and still be
   self-serving — which is exactly why it isn't the agent's call to make silently.

4. **Sensitive paths** — a change to migrations, auth, or the audit chain needs an explicit
   human sign-off. These are the changes whose blast radius outlives the PR: a migration
   rewrites stored data, an auth edit changes who can reach what, and the audit chain is the
   record you would reach for *after* an incident.
5. **Weakened thresholds and exemptions** — the suppression ratchet catches an inline
   ``# noqa``, but not a coverage floor being lowered, a bundle budget being raised, or an
   ignore list growing in a scanner's own config. Same intent, different file, so the same
   ratchet applies.

Each check has an explicit escape hatch (a PR label → a CLI flag) so a human can
consciously override, but an agent cannot do it silently.

Usage:  python scripts/meta_guard.py --base origin/main \\
            [--allow-suppressions] [--allow-missing-tests] [--allow-guardrail-change] \\
            [--allow-sensitive] [--allow-exemptions]
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

# Only real source files can carry a real suppression directive. Prose that merely NAMES a
# marker (docs, ADRs, markdown) must not count — see check_suppressions().
SUPPRESSIBLE_RE = re.compile(r"^(?!docs/).*\.(py|ts|tsx|js|jsx|mjs|cjs)$")

# A changed .py here counts as "source"; tests/migrations don't.
SRC_RE = re.compile(r"^backend/(?!tests/|migrations/).*\.py$")
TEST_RE = re.compile(r"^backend/tests/.*\.py$")

# Files that DEFINE a guard rather than being checked by one. Deliberately broad — any CI
# workflow, ruleset, or scanner config, not just this script — because the failure mode is
# "edit whichever guard is currently in the way," not just this file specifically.
GUARD_FILE_RE = re.compile(
    r"^scripts/.*\.py$"
    r"|^\.github/workflows/.*\.ya?ml$"
    r"|^\.github/rulesets/.*\.json$"
    r"|^\.github/CODEOWNERS$"
    r"|^\.semgrep/.*\.ya?ml$"
    r"|^\.gitleaks\.toml$"
    r"|^\.pre-commit-config\.yaml$"
)


# Paths whose blast radius outlives the PR. Deliberately NARROW: dependency manifests are
# excluded because Dependabot touches them constantly, and a label everyone applies weekly
# stops being a signal. Those are already covered by check_pins + CODEOWNERS review.
SENSITIVE_PATH_RE = re.compile(
    r"^backend/migrations/versions/.*\.py$"   # irreversible: rewrites stored data
    r"|^backend/[^/]+/auth/"                  # who can reach what
    r"|^backend/[^/]+/command/audit\.py$"     # the tamper-evident chain itself
)

# Config files that can exempt code from a scanner — the suppression ratchet's blind spot.
EXEMPTION_FILE_RE = re.compile(
    r"(^|/)\.gitleaks\.toml$|(^|/)pyproject\.toml$|^\.semgrep/.*\.ya?ml$|(^|/)\.semgrepignore$"
)
EXEMPTION_LINE_RE = re.compile(r"\b(ignore|exclude|omit|allowlist|skip)\b", re.IGNORECASE)

# Numeric floors/ceilings whose movement in one direction is a weakening.
THRESHOLDS = (
    ("coverage floor (fail_under)", re.compile(r"fail_under\s*=\s*(\d+)"), "lower"),
    ("bundle budget (BUNDLE_MAX_KB)", re.compile(r"BUNDLE_MAX_KB\s*\?\?\s*(\d+)"), "raise"),
    ("scorecard gate (--min)", re.compile(r"--min[\s\"\']+(\d+)"), "lower"),
)


def _run(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def _diff(base: str) -> str:
    return _run("diff", "--unified=0", f"{base}...HEAD")


def check_suppressions(base: str, errors: list[str]) -> None:
    # Scoped to source files, mirroring check_tests() below. Without this the scan counts a
    # suppression marker NAMED IN PROSE (an ADR explaining why blanket-disabling is banned, a
    # standards doc listing what not to add) exactly the same as a real directive — so writing
    # documentation about suppressions trips the guard that exists to catch adding them. That
    # pushes toward either routinely using the 'allow-suppressions' label (meant to be rare and
    # deliberate) or contorting the docs to avoid literal strings. Both are worse outcomes.
    added = removed = 0
    current_file = ""
    for line in _diff(base).splitlines():
        if line.startswith("+++"):
            current_file = line[6:] if line.startswith("+++ b/") else ""
            continue
        if line.startswith("---") or line.startswith("diff ") or line.startswith("@@"):
            continue
        if not SUPPRESSIBLE_RE.match(current_file):
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


def check_guard_files(base: str, errors: list[str]) -> None:
    changed = [f for f in _run("diff", "--name-only", f"{base}...HEAD").splitlines() if f]
    touched = sorted(f for f in changed if GUARD_FILE_RE.match(f))
    if touched:
        errors.append(
            "PR modifies guard-defining file(s): " + ", ".join(touched) + ". "
            "If a guard is blocking you, the guard is very likely right and your change is "
            "wrong — fix the code, don't edit the check. If the guard is genuinely broken, "
            "that is a decision for the repo owner, not something to resolve mid-PR: open it "
            "as its own PR, on its own merits, and label it 'guardrail-change' once approved. "
            "A plausible-sounding argument for why 'this guard has a bug' is exactly the shape "
            "this failure mode takes — if your own reasoning concludes you should edit the "
            "thing that is checking you, stop and ask instead."
        )


def check_sensitive_paths(base: str, errors: list[str]) -> None:
    changed = [f for f in _run("diff", "--name-only", f"{base}...HEAD").splitlines() if f]
    touched = sorted(f for f in changed if SENSITIVE_PATH_RE.match(f))
    if touched:
        errors.append(
            "PR changes sensitive path(s): " + ", ".join(touched) + ". A migration rewrites "
            "stored data, an auth change alters who can reach what, and the audit chain is the "
            "record you would rely on after an incident — each outlives this PR. Have the owner "
            "review it and apply the 'sensitive-change-approved' label."
        )


def check_exemptions(base: str, errors: list[str]) -> None:
    """Catch weakening that happens in config rather than in a source comment."""
    current_file = ""
    added = removed = 0
    before: dict[str, list[int]] = {}
    after: dict[str, list[int]] = {}

    for line in _diff(base).splitlines():
        if line.startswith("+++"):
            current_file = line[6:] if line.startswith("+++ b/") else ""
            continue
        if line.startswith(("---", "diff ", "@@")) or not line.startswith(("+", "-")):
            continue
        body = line[1:]
        for name, pattern, _direction in THRESHOLDS:
            match = pattern.search(body)
            if match:
                side = after if line.startswith("+") else before
                side.setdefault(name, []).append(int(match.group(1)))
        if EXEMPTION_FILE_RE.search(current_file) and EXEMPTION_LINE_RE.search(body):
            if line.startswith("+"):
                added += 1
            else:
                removed += 1

    for name, _pattern, direction in THRESHOLDS:
        olds, news = before.get(name), after.get(name)
        if not olds or not news:
            continue  # introduced or deleted, not moved — nothing to compare
        weakened = min(news) < min(olds) if direction == "lower" else max(news) > max(olds)
        if weakened:
            errors.append(
                f"PR weakens the {name}: {sorted(olds)} -> {sorted(news)}. A threshold is an "
                f"anti-regression ratchet — moving it to make the run pass removes the protection "
                f"instead of restoring it. Fix the underlying gap, or label 'allow-exemptions'."
            )

    net = added - removed
    if net > 0:
        errors.append(
            f"PR adds {net} net new exemption line(s) to scanner config "
            f"(ignore / exclude / omit / allowlist). Same intent as a '# noqa', different file — "
            f"which is exactly the suppression ratchet's blind spot. Narrow the exemption or fix "
            f"the finding, or label the PR 'allow-exemptions' if justified."
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main", help="base ref to diff against")
    ap.add_argument("--allow-suppressions", action="store_true")
    ap.add_argument("--allow-missing-tests", action="store_true")
    ap.add_argument("--allow-guardrail-change", action="store_true")
    ap.add_argument("--allow-sensitive", action="store_true")
    ap.add_argument("--allow-exemptions", action="store_true")
    args = ap.parse_args()

    errors: list[str] = []
    if not args.allow_suppressions:
        check_suppressions(args.base, errors)
    if not args.allow_missing_tests:
        check_tests(args.base, errors)
    if not args.allow_guardrail_change:
        check_guard_files(args.base, errors)
    if not args.allow_sensitive:
        check_sensitive_paths(args.base, errors)
    if not args.allow_exemptions:
        check_exemptions(args.base, errors)

    if errors:
        print("meta-guard: FAILED\n")
        for e in errors:
            print(f"  ✗ {e}")
        return 1
    print("meta-guard: OK — no silent guard-weakening detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
