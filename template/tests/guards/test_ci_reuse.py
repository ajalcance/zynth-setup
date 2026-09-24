"""Post-merge reuse: a tree the pull-request run already proved is not proved again.

GitHub bills per job, rounded up to a minute, and the push run after a squash merge tests the
SAME tree the PR run just passed. The `reuse` job looks that run up — same tree hash, a
successful `ci-complete` posted by GitHub Actions itself — and the deterministic jobs stand
down. The audits do not: an advisory database moves without us, so pip-audit and npm audit
run on every push. A weekly schedule runs everything, reuse or not.
Failing to VERIFY must fall back to a full run, never to a skipped one.

No tag trigger: a release tag names a default-branch commit whose push run has already
run the audits and proved the tree, and a tag-triggered workflow that restores caches is
one zizmor reads as a release build open to cache poisoning (release.yml builds on its own).
"""

from __future__ import annotations

import re

import yaml
from conftest import REPO_ROOT

CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
REUSE_CONDITION = "needs.reuse.outputs.verified != 'true'"
STANDS_DOWN = ("hygiene", "sast", "static")
AUDITED = ("backend", "frontend", "docs")
AUDIT_MARKERS = ("pip-audit", "npm audit", "npm ci", "pip install")


def _workflow():
    return yaml.safe_load(CI.read_text())


def _jobs():
    return _workflow()["jobs"]


# --- the lookup itself ---------------------------------------------------------------------


def test_reuse_runs_only_on_a_branch_push():
    condition = _jobs()["reuse"]["if"]
    assert "github.event_name == 'push'" in condition
    assert "refs/heads/" in condition, "a lookup keyed on a branch push must say so"


def test_reuse_compares_the_tree_and_demands_a_real_ci_complete():
    """Same tree, and a success posted by Actions — not by name alone (SEC-048)."""
    step = next(s for s in _jobs()["reuse"]["steps"] if "run" in s)
    run = step["run"]
    assert "^{tree}" in run, "reuse does not compare TREE hashes"
    assert "check_name=ci-complete" in run
    assert 'app.slug == "github-actions"' in run, "a check run by any app of that name would do"
    assert 'conclusion == "success"' in run
    assert (
        step.get("continue-on-error") is True
    ), "a lookup that errors must mean 'run everything', not a red gate on the default branch"
    assert "verified=" in run and "GITHUB_OUTPUT" in run


def test_reuse_reads_with_the_least_it_needs():
    permissions = _jobs()["reuse"]["permissions"]
    assert permissions == {"contents": "read", "pull-requests": "read", "checks": "read"}


# --- who stands down, and who never does ---------------------------------------------------


def test_the_deterministic_jobs_stand_down_only_when_verified():
    for name in STANDS_DOWN:
        job = _jobs()[name]
        assert "reuse" in job["needs"], f"{name} does not wait for reuse"
        assert REUSE_CONDITION in job["if"], f"{name} never stands down"
        assert (
            "!cancelled()" in job["if"]
        ), f"{name}: on a pull request `reuse` is skipped; without !cancelled() the job is too"


def test_the_audits_run_on_every_push_and_the_rest_stand_down():
    for name in AUDITED:
        job = _jobs()[name]
        assert "reuse" in job["needs"], f"{name} does not wait for reuse"
        assert REUSE_CONDITION not in job.get("if", ""), f"{name} must run for its audits"
        for step in job["steps"]:
            if "run" not in step:
                continue
            needed_for_audit = any(marker in step["run"] for marker in AUDIT_MARKERS)
            condition = str(step.get("if", ""))
            if needed_for_audit:
                assert REUSE_CONDITION not in condition, f"{name}: {step['name']} is an audit"
            else:
                assert REUSE_CONDITION in condition, f"{name}: {step['name']} re-proves the tree"


def test_ci_complete_waits_for_reuse():
    assert "reuse" in _jobs()["ci-complete"]["needs"]


# --- the full runs -------------------------------------------------------------------------


def test_a_weekly_schedule_runs_everything_and_no_tag_does():
    triggers = _workflow()[True]  # `on:` parses as YAML 1.1 boolean
    assert "schedule" in triggers and triggers["schedule"][0].get("cron"), "no weekly full run"
    assert "tags" not in triggers["push"], (
        "a tag-triggered workflow that restores caches is a release build open to cache "
        "poisoning; release.yml builds on its own checkout"
    )


def test_the_change_filter_reports_everything_changed_on_a_full_run():
    """paths-filter needs a base; a schedule has none. Every path counts as changed instead."""
    changes = _jobs()["changes"]
    for name, expression in changes["outputs"].items():
        assert "schedule" in expression, f"changes.{name} is not forced on a schedule: {expression}"
    filter_step = next(s for s in changes["steps"] if "paths-filter" in str(s.get("uses", "")))
    assert "schedule" in str(filter_step.get("if", "")), "the filter runs with no base to diff"


def test_the_secret_scan_knows_a_scheduled_run_has_no_range():
    """origin/main..HEAD is empty on main itself; a refused scan would redden every Monday."""
    scanner = (REPO_ROOT / "scripts" / "secret_scan.py").read_text()
    assert re.search(r"event == \"schedule\"", scanner), "secret_scan.py has no schedule branch"
