"""The template repository holds itself to the rules it ships.

Each test here is a rule the template enforces on every generated project, applied to this
repository's own workflows and configuration. They were all broken here until 2026-09-25 —
the template demanded them of adopters while its own CI met none of them.
"""

from __future__ import annotations

import re
import subprocess

import pytest
import yaml
from conftest import ROOT, WORKFLOWS

# Variables the runner sets and a step cannot override: GitHub silently ignores the attempt.
# The log header shows the override, the process never sees it. This hid a broken policy step
# in the self-test until the first pull request. Blanking one means `env -u` in the run line.
DEFAULT_VARIABLE = re.compile(r"^(GITHUB|RUNNER)_[A-Z_]+$")
# Not defaults — names the workflows set on purpose. GITHUB_EVENT_BEFORE is read by
# secret_scan.py --auto and is NOT a variable the runner provides.
NOT_DEFAULTS = {"GITHUB_EVENT_BEFORE"}
PINNED_ACTION = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
INSTALL = re.compile(r"\b(?:pipx|pip|pip3)\s+install\b[^\n]*")


def workflows() -> list[tuple[str, dict]]:
    found = [(p.name, yaml.safe_load(p.read_text())) for p in sorted(WORKFLOWS.glob("*.yml"))]
    assert found, "no workflows found — every test below would be vacuous"
    return found


def jobs():
    for name, workflow in workflows():
        for job_id, job in workflow["jobs"].items():
            yield name, job_id, job


def steps():
    for name, job_id, job in jobs():
        for step in job.get("steps", []):
            yield f"{name}:{job_id}:{step.get('name') or step.get('uses')}", step


def test_every_job_has_a_timeout():
    missing = [f"{name}:{job_id}" for name, job_id, job in jobs() if "timeout-minutes" not in job]
    assert not missing, f"a job with no timeout runs for six hours when it wedges: {missing}"


def test_every_action_is_pinned_to_a_commit():
    loose = [
        f"{where} → {step['uses']}"
        for where, step in steps()
        if "uses" in step and not PINNED_ACTION.match(step["uses"])
    ]
    assert not loose, f"an action pinned to a tag runs whatever the tag points at today: {loose}"


def test_no_checkout_leaves_a_credential_behind():
    left = [
        where
        for where, step in steps()
        if str(step.get("uses", "")).startswith("actions/checkout@")
        and (step.get("with") or {}).get("persist-credentials") is not False
    ]
    assert not left, f"these checkouts leave the token in .git/config (zizmor: artipacked): {left}"


def test_no_step_overrides_a_variable_the_runner_owns():
    overridden = [
        f"{where} sets {key}"
        for scope, env in (
            *((f"{n}:{j}", job.get("env") or {}) for n, j, job in jobs()),
            *((where, step.get("env") or {}) for where, step in steps()),
        )
        for key in env
        if DEFAULT_VARIABLE.match(key) and key not in NOT_DEFAULTS
        for where in [scope]
    ]
    assert not overridden, (
        "GitHub ignores an env override of its own GITHUB_*/RUNNER_* variables; the process "
        f"still sees the real value. Unset it in the shell with `env -u NAME`: {overridden}"
    )


def test_every_install_names_its_pins():
    """The rule template/requirements-ci.txt enforces on adopters, held here."""
    loose = [
        f"{where}: {match.group(0).strip()}"
        for where, step in steps()
        for match in INSTALL.finditer(step.get("run", ""))
        if not re.search(r"\s-(?:c|r)\s+\S+", match.group(0))
    ]
    assert not loose, f"an install with no constraints file floats with the index: {loose}"


def test_ci_complete_needs_every_other_job():
    """A job the aggregator does not need can fail while the required check stays green."""
    for name, workflow in workflows():
        job_ids = set(workflow["jobs"])
        if "ci-complete" not in job_ids:
            continue
        needs = set(workflow["jobs"]["ci-complete"].get("needs", []))
        assert needs == job_ids - {
            "ci-complete"
        }, f"{name}: ci-complete ignores {job_ids - needs - {'ci-complete'}}"
        assert workflow["jobs"]["ci-complete"].get("if") == "always()"


def test_the_repo_gate_is_the_makefile():
    """One definition: CI runs `make check`, and `make check` is every gate the root has."""
    makefile = (ROOT / "Makefile").read_text()
    assert re.search(r"^check:\s*hooks lint policy test\s*$", makefile, re.MULTILINE)
    runs = " ".join(step.get("run", "") for _, step in steps())
    assert "make check" in runs, "no workflow runs the repository's own gate"


# --- .gitleaksignore ---------------------------------------------------------------------

FINGERPRINT = re.compile(
    r"^(?P<commit>[0-9a-f]{40}):(?P<file>[^:]+):(?P<rule>[\w-]+):(?P<line>\d+)$"
)


def entries() -> list[str]:
    path = ROOT / ".gitleaksignore"
    if not path.is_file():
        return []
    return [
        line for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")
    ]


@pytest.mark.parametrize("entry", entries() or ["<none>"])
def test_every_ignored_finding_is_one_exact_fingerprint_in_real_history(entry):
    """Commit, file, rule and line — never a path or a rule on its own, which would widen."""
    if entry == "<none>":
        return
    match = FINGERPRINT.match(entry)
    assert match, f"not a full fingerprint (commit:file:rule:line): {entry!r}"
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{match['commit']}^{{commit}}"], cwd=ROOT, capture_output=True
    )
    assert exists.returncode == 0, f"{entry}: names a commit this repository does not have"


def test_every_ignored_finding_carries_its_reason():
    text = (ROOT / ".gitleaksignore").read_text() if (ROOT / ".gitleaksignore").is_file() else ""
    for entry in entries():
        short = entry[:7]
        assert f"# {short}:" in text, f"{entry}: no '# {short}: <why this is not a secret>' line"


# --- Dependabot ----------------------------------------------------------------------------


def test_every_kind_of_pin_this_repository_holds_is_updated():
    """A pin nothing updates rots. Actions, the self-test tools and the hooks are all pinned."""
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())
    covered = {(u["package-ecosystem"], u["directory"]) for u in config["updates"]}
    for needed in (("github-actions", "/"), ("pip", "/"), ("pre-commit", "/")):
        assert needed in covered, f"{needed[0]} pins at {needed[1]} are never updated"
    short = [
        u["package-ecosystem"]
        for u in config["updates"]
        if (u.get("cooldown") or {}).get("default-days", 0) < 7
    ]
    assert not short, f"a version public for under a week has not been looked at yet: {short}"
