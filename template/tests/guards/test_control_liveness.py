"""Four controls that did less than everyone believed, each now held by a test.

All four come from an audit of a repository at half a million lines: a tool pinned by a
movable tag, an advisory scan whose output went nowhere, a path filter that skipped the job
that reads the changed files, and enforcement config nobody had to ask before editing.
"""

from __future__ import annotations

import re

import yaml
from conftest import REPO_ROOT, git_commit, git_init, install_guard, run, run_guard, write

CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PRE_COMMIT = REPO_ROOT / ".pre-commit-config.yaml"
SHA40 = re.compile(r"^[0-9a-f]{40}$")


def _workflow():
    return yaml.safe_load(CI.read_text())


# --- 10: a tag can be moved; the commit it pointed at cannot -----------------------------


def test_every_pre_commit_revision_is_a_commit_sha():
    revs = re.findall(r"^\s*rev:\s*(\S+)", PRE_COMMIT.read_text(), re.M)
    assert revs, "no `rev:` found — this assertion would be vacuous"
    tags = [r for r in revs if not SHA40.match(r)]
    assert not tags, f"pre-commit revisions pinned by movable tag, not commit: {tags}"


def test_the_commit_time_hook_and_the_ci_scan_use_one_gitleaks_version():
    """Two versions of the same scanner disagree about what a secret looks like."""
    hook = re.search(r"gitleaks/gitleaks\n\s*rev:\s*\S+\s*#\s*v(\S+)", PRE_COMMIT.read_text())
    assert hook, "the gitleaks hook does not record its version beside the sha"
    scanner = (REPO_ROOT / "scripts" / "secret_scan.py").read_text()
    pinned = re.search(r'^VERSION = "([^"]+)"', scanner, re.M)
    assert pinned, "secret_scan.py does not pin a version"
    hook_version, ci_version = hook.group(1), pinned.group(1)
    assert hook_version == ci_version, f"the hook runs gitleaks {hook_version}, CI {ci_version}"


# --- 6: an advisory scan whose output is discarded costs a minute and catches nothing --------


def _sast_runs() -> list[str]:
    return [s.get("run", "") for s in _workflow()["jobs"]["sast"]["steps"] if "run" in s]


def test_no_scan_in_the_gate_swallows_its_own_exit_code():
    """`|| true` turns a scanner into a 44-second delay."""
    offenders = [r for r in [*_sast_runs(), _sast_recipe()] if "|| true" in r]
    assert not offenders, f"scan step(s) that can never fail the job: {offenders}"


def _sast_recipe() -> str:
    """The `sast:` recipe of the Makefile — the ONE place the scans are defined."""
    makefile = (REPO_ROOT / "Makefile").read_text()
    match = re.search(r"^sast:\n((?:\t.*\n)+)", makefile, re.M)
    assert match, "the Makefile has no `sast:` target"
    return match.group(1)


def _semgrep_invocations() -> list[str]:
    parts = re.split(r"&&\s*\\\n", _sast_recipe())
    runs = [p for p in parts if " scan " in p]
    assert runs, "no semgrep invocation in `make sast` — the assertions below would be vacuous"
    return runs


def test_ci_runs_the_scans_through_make_and_never_relists_them():
    """Two definitions of a gate is how a flag gets added to one and forgotten in the other."""
    runs = _sast_runs()
    assert any("make sast" in r for r in runs), "the sast job must invoke `make sast`"
    relisted = [r for r in runs if "semgrep scan" in r]
    assert not relisted, f"the sast job runs semgrep directly AND through `make sast`: {relisted}"


def _community_scan() -> str:
    """The one step that runs the community rules, not the whole job: a flag on the
    dangerous-ops step must not satisfy an assertion about this one."""
    matches = [r for r in _semgrep_invocations() if "p/security-audit" in r]
    assert len(matches) == 1, f"expected one community-rules step, found {len(matches)}"
    return matches[0]


def test_every_semgrep_invocation_fails_the_job_on_a_finding():
    silent = [r for r in _semgrep_invocations() if "--error" not in r]
    assert not silent, f"semgrep step(s) that report findings without failing: {silent}"


def test_the_community_scan_blocks_on_new_findings_only():
    community = _community_scan()
    assert "--error" in community, "the community scan does not fail the job on a finding"
    assert "--baseline-commit" in community, (
        "the community scan is not diff-aware: it would fail a fresh project on day one for "
        "pre-existing noise, and a gate that is red on day one gets lowered"
    )


def test_the_community_scan_keeps_its_report():
    steps = _workflow()["jobs"]["sast"]["steps"]
    uploads = [s for s in steps if "upload-sarif" in str(s.get("uses", ""))]
    assert uploads, "the Semgrep report is produced and then discarded"
    upload = uploads[0]
    assert upload.get("if") == "always()", "the report must be kept when the scan FAILS too"
    assert upload.get("continue-on-error") is True, (
        "the upload is the record, not the gate: a repo without code scanning enabled must "
        "still fail on a finding without failing on the upload"
    )
    assert "--sarif-output" in _community_scan(), "the community scan writes no report"


def test_the_community_scan_takes_its_baseline_from_the_event():
    """A baseline the job does not pass is a full scan on every run — slow, and noisy."""
    step = next(r for r in _sast_runs() if "make sast" in r)
    assert "SEMGREP_BASELINE=" in step, "CI runs `make sast` without handing it the base sha"
    assert "0000000000000000000000000000000000000000" in step, (
        "the first push to a ref carries the null sha as its base; passing it as a baseline "
        "makes semgrep fail on a commit that does not exist"
    )


def test_the_sast_job_drops_its_credential_and_fetches_nothing():
    """Full history without a fetch: the baseline is a sha the clone already holds."""
    job = _workflow()["jobs"]["sast"]
    checkout = next(s for s in job["steps"] if "actions/checkout" in str(s.get("uses", "")))
    assert checkout["with"].get("fetch-depth") == 0
    assert checkout["with"].get("persist-credentials") is False
    assert not any(re.search(r"\bgit\s+fetch\b", r) for r in _sast_runs())


# --- 12: a path filter must cover every file the job's work reads -------------------------


def test_the_docs_job_runs_on_everything_the_docs_site_renders():
    """The site renders all of docs/; only two subfolders were listed, so an ADR could break it."""
    changes = _workflow()["jobs"]["changes"]
    filter_step = next(s for s in changes["steps"] if "paths-filter" in str(s.get("uses", "")))
    docs_paths = yaml.safe_load(filter_step["with"]["filters"])["docs"]
    assert "docs/**" in docs_paths, f"the docs job triggers on {docs_paths}, not on all of docs/"


# --- 11: enforcement config is edited with the same review as the checks -------------------

BASE = "base-ref"


def test_the_dependency_bot_config_needs_the_owners_label(tmp_path):
    """Its cooldown is the premise CI's manifest waiver rests on. Removing it was a free edit."""
    guard = install_guard(tmp_path, "meta_guard.py")
    git_init(tmp_path)
    write(tmp_path / "backend" / "app" / "main.py", "x = 1\n")
    write(tmp_path / ".github" / "dependabot.yml", "version: 2\nupdates: []\n")
    git_commit(tmp_path, "base")
    run(["git", "branch", BASE], tmp_path)
    write(tmp_path / ".github" / "dependabot.yml", "version: 2\nupdates: [] # cooldown gone\n")
    git_commit(tmp_path, "chore: loosen the bot")
    blocked = run_guard(guard, "--base", BASE, "--allow-missing-tests")
    assert blocked.returncode != 0, "editing dependabot.yml must need the guardrail-change label"
    assert ".github/dependabot.yml" in blocked.stdout
    allowed = run_guard(guard, "--base", BASE, "--allow-missing-tests", "--allow-guardrail-change")
    assert allowed.returncode == 0, "the escape hatch must still work once the owner approves"
