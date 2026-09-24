"""The quarterly audit: twelve points, seven that fail closed, one issue that always opens.

A checklist nobody runs is a document; a check that reports success on an empty repository
is the failure mode this whole audit is about. So the runner must fail when a control is
missing rather than skip it, and the workflow must open its issue even when the run is red.
"""

from __future__ import annotations

import re

import yaml
from conftest import REPO_ROOT, SCRIPTS, install_guard, run_guard

AUDIT = SCRIPTS / "audit.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "audit.yml"
MAKEFILE = REPO_ROOT / "Makefile"


def test_the_checklist_has_twelve_points_seven_mechanical():
    result = run_guard(AUDIT, "--list")
    assert result.returncode == 0, result.stdout + result.stderr
    rows = [line for line in result.stdout.splitlines() if re.match(r"\| \d+ \|", line)]
    assert len(rows) == 12, f"the checklist has {len(rows)} points, not 12"
    mechanical = [r for r in rows if "mechanical" in r]
    assert len(mechanical) == 7, f"{len(mechanical)} mechanical points, expected 7"
    assert all("`" in r for r in rows if "manual" in r), "a manual point without a command to run"


def test_a_missing_control_is_a_failure_not_a_skip(tmp_path):
    """In a sandbox with no guards, every mechanical point must fail and say so by number."""
    guard = install_guard(tmp_path, "audit.py")
    result = run_guard(guard, cwd=tmp_path)
    assert result.returncode != 0, result.stdout
    assert "7 failed" in result.stdout, result.stdout
    assert "FAILED" in result.stdout and "do not skip it" in result.stdout


def test_one_point_can_be_run_alone_and_holds_here():
    """The positive control, on the real project: the runtime-version point passes."""
    result = run_guard(AUDIT, "--only", "4")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "✓  4" in result.stdout and "1 mechanical (1 passed" in result.stdout


def test_an_unknown_point_is_refused():
    result = run_guard(AUDIT, "--only", "13")
    assert result.returncode == 2 and "1-12" in result.stdout


def test_the_makefile_runs_it():
    body = re.search(r"^audit:\n((?:\t.*\n)+)", MAKEFILE.read_text(), re.M)
    assert body, "the Makefile has no `audit:` target"
    assert "scripts/audit.py" in body.group(1)


def test_the_workflow_runs_quarterly_and_by_hand():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    triggers = workflow[True]
    cron = triggers["schedule"][0]["cron"]
    month = cron.split()[3]
    assert month in ("1,4,7,10", "*/3"), f"not quarterly: {cron}"
    assert "workflow_dispatch" in triggers, "the growth triggers need a by-hand run"


def test_the_workflow_opens_its_issue_even_when_the_audit_is_red():
    job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["audit"]
    assert job["permissions"] == {"contents": "read", "issues": "write"}
    steps = {s.get("name", ""): s for s in job["steps"]}
    audit = next(s for n, s in steps.items() if "make audit" in s.get("run", ""))
    assert audit.get("continue-on-error") is True, "a red audit would never open its issue"
    opener = next(s for n, s in steps.items() if "gh issue create" in s.get("run", ""))
    assert "steps.audit.outcome" in str(opener.get("env", {})), "the issue must carry the outcome"
    assert "scripts/audit.py --list" in opener["run"], "the issue must carry the checklist"
    checkout = next(s for s in job["steps"] if "actions/checkout" in str(s.get("uses", "")))
    assert checkout["with"].get("persist-credentials") is False
