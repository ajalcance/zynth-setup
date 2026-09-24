#!/usr/bin/env python3
"""The twelve-point CI-integrity audit — run quarterly, and at each growth trigger.

Every defect the audit behind this list found shared one shape: a check that reported
success without doing its job, and nothing that could tell the difference. Seven of the
twelve points are mechanical here — each runs the control that holds it and fails closed —
and five need a person, so they print the exact command to run and what to look for. The
scheduled workflow (.github/workflows/audit.yml) runs this and opens an issue with the result.

    make audit              run everything, fail on any mechanical point
    make audit ONLY=4       one point
    scripts/audit.py --list the checklist as Markdown (the issue body)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
PYTEST = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-header"]


@dataclass(frozen=True)
class Point:
    number: int
    question: str
    how: str  # what a person does, or what the mechanical run is
    command: list[str] | None = None  # None: manual


POINTS: tuple[Point, ...] = (
    Point(
        1,
        "Does the secret scanner actually scan?",
        "A committed fake token in a sandbox repository must fail the CI-shaped scan.",
        [*PYTEST, "tests/guards/test_secret_scan.py", "-k", "committed_secret or ci_shape"],
    ),
    Point(
        2,
        "Does every negative-result check have a canary?",
        "The scanner plants tokens in every source tree and must find all of them.",
        [PY, "scripts/secret_scan.py", "--canary-only"],
    ),
    Point(
        3,
        "Are all tools pinned by version and hash / commit SHA?",
        "Actions, pre-commit hooks, scanners, the fetched linters and every requirement.",
        [
            *PYTEST,
            "tests/guards/test_workflow_invariants.py::test_every_program_that_judges_a_pull_request_is_pinned",
            "tests/guards/test_control_liveness.py::test_every_pre_commit_revision_is_a_commit_sha",
            "tests/guards/test_infra_lint.py::test_every_platform_has_a_checksum_for_both_tools",
            "tests/guards/test_infra_lint.py::test_zizmor_is_pinned_with_the_other_scanners",
        ],
    ),
    Point(
        4,
        "Does CI test the runtime you ship?",
        "Every Python and Node declaration is compared with the image and .nvmrc.",
        [*PYTEST, "tests/guards/test_runtime_versions.py"],
    ),
    Point(
        5,
        "Do any checks run nowhere?",
        "Every guard is named by a Makefile target, a workflow or a hook, and has a fault test.",
        [PY, "scripts/check_guard_coverage.py"],
    ),
    Point(
        6,
        "Does every security-doc claim have a blocking config line?",
        "`python3 scripts/standards_check.py` proves each `[CI]` marker names a mechanism that "
        "exists. Then read docs/SECURITY.md one sentence at a time and, for each claim, open the "
        "config line that enforces it. A claim with no line is a `[Review]` marker at best.",
    ),
    Point(
        7,
        "Do path filters cover every file each suite reads?",
        "For each suite: `grep -rn '\\.\\./\\|deploy/\\|docs/' backend/tests frontend/tests` and "
        "compare with that job's filter in .github/workflows/ci.yml (`changes` job). A read "
        "outside the filtered tree is a change that can break the suite without running it.",
    ),
    Point(
        8,
        "Are you re-testing identical trees?",
        "The post-merge reuse job compares tree hashes and stands the proved jobs down.",
        [*PYTEST, "tests/guards/test_ci_reuse.py"],
    ),
    Point(
        9,
        "Are 'flaky' tests really flaky?",
        "`gh run list --status failure --limit 50 --json databaseId,createdAt,name` then read the "
        "failing test's timestamps and look for a boundary (midnight, month end, DST, a pool "
        "limit) before retrying. A flake is a hypothesis about production.",
    ),
    Point(
        10,
        "Are enforcement configs (allowlists, waivers, bot config) protected?",
        "Editing any of them in a pull request must demand the owner's label.",
        [*PYTEST, "tests/guards/test_meta_guard.py"],
    ),
    Point(
        11,
        "Is the automation identity separate from the approver?",
        "`gh api repos/{owner}/{repo}/collaborators --jq '.[] | select(.permissions.admin) | "
        ".login'` — if the account the agent acts through is in that list, the forge cannot tell "
        "agent from owner, and only local settings hold the line. See ONBOARDING.md §0 and the "
        "growth triggers in docs/PLAN.md.",
    ),
    Point(
        12,
        "Images: scanned, SBOM, provenance, signature verified at deploy?",
        "`grep -n 'cosign\\|sbom\\|trivy\\|grype\\|provenance' .github/workflows/release.yml "
        "deploy/verify.sh` — signing and verified deploy ship with the deploy module; image "
        "scanning, SBOM and provenance attestations do not yet: the next supply-chain step.",
    ),
)

MECHANICAL = tuple(p for p in POINTS if p.command)
MANUAL = tuple(p for p in POINTS if not p.command)
assert len(POINTS) == 12 and len(MECHANICAL) == 7 and len(MANUAL) == 5


def run_point(point: Point) -> tuple[bool, str]:
    assert point.command
    result = subprocess.run(
        point.command, cwd=ROOT, capture_output=True, text=True, check=False, timeout=900
    )
    lines = [line for line in (result.stdout + result.stderr).splitlines() if line.strip()]
    evidence = lines[-1] if lines else "(no output)"
    return result.returncode == 0, evidence


def checklist_markdown() -> str:
    out = ["| # | Check | How |", "|---|---|---|"]
    for p in POINTS:
        kind = "mechanical — `make audit`" if p.command else "manual"
        out.append(f"| {p.number} | {p.question} | {p.how} ({kind}) |")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true", help="print the checklist as Markdown")
    ap.add_argument("--only", type=int, metavar="N", help="run one point (1-12)")
    args = ap.parse_args()

    if args.list:
        print(checklist_markdown())
        return 0

    selected = [p for p in POINTS if args.only is None or p.number == args.only]
    if not selected:
        print(f"audit: no point numbered {args.only} — the checklist has 1-12")
        return 2

    failed = 0
    ran = 0
    for point in selected:
        if point.command is None:
            print(f"  · {point.number:>2}  {point.question}\n        manual — {point.how}")
            continue
        ran += 1
        ok, evidence = run_point(point)
        mark = "✓" if ok else "✗"
        failed += 0 if ok else 1
        print(f"  {mark} {point.number:>2}  {point.question}\n        {evidence}")

    manual = sum(1 for p in selected if p.command is None)
    print(
        f"audit: {len(selected)} point(s) — {ran} mechanical ({ran - failed} passed, "
        f"{failed} failed) · {manual} manual (commands above)"
    )
    if ran == 0 and manual == 0:
        print("audit: FAILED — nothing was checked")
        return 1
    if failed:
        print(
            "audit: FAILED — a control that held last quarter no longer does. "
            "Fix it; do not skip it."
        )
        return 1
    print("audit: OK — every mechanical point holds. Run the manual ones and record the answers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
