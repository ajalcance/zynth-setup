"""Structural invariants that keep the merge gate honest.

These are not fault-injection tests; they assert wiring that, if it silently regressed, would
make CI *look* green while checking less. Every one of these was verified by hand at least once
during development — this is that check, automated.
"""

from __future__ import annotations

import re

import pytest
import yaml

from conftest import REPO_ROOT

CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _workflow(path):
    # `on:` is parsed by PyYAML as the boolean True (YAML 1.1), so triggers live under `True`.
    return yaml.safe_load(path.read_text())


def test_ci_complete_fans_in_every_job():
    """The aggregator is the single required check; a job missing from `needs` is unguarded."""
    jobs = _workflow(CI)["jobs"]
    aggregated = set(jobs["ci-complete"]["needs"])
    others = set(jobs) - {"ci-complete"}
    missing = sorted(others - aggregated)
    assert not missing, f"jobs absent from ci-complete.needs — they cannot block a merge: {missing}"


def test_ci_complete_always_runs():
    """Without `if: always()` the aggregator is skipped when an upstream job fails."""
    assert _workflow(CI)["jobs"]["ci-complete"].get("if") == "always()"


def test_ci_complete_rejects_a_failed_result():
    """The pass condition must accept only success/skipped — not 'anything that is not failure'."""
    step = _workflow(CI)["jobs"]["ci-complete"]["steps"][0]["run"]
    assert "success" in step and "skipped" in step
    assert "exit 1" in step, "the aggregator must actually fail the job on a bad result"


def _make_target(name: str) -> list[str] | None:
    body = re.search(rf"^{name}:\n((?:\t.*\n)+)", (REPO_ROOT / "Makefile").read_text(), re.M)
    if body is None:
        return None
    chain = body.group(1).replace("\\\n", "").replace("\t", " ")
    return _normalise(chain.split("&&"))


def _ci_job(name: str) -> list[str]:
    steps = _workflow(CI)["jobs"][name]["steps"]
    return _normalise([s["run"] for s in steps if "run" in s])


def _normalise(commands) -> list[str]:
    out = []
    for command in commands:
        command = " ".join(command.split()).replace("npx ", "")
        if not command or command.startswith(("cd ", "npm ci")):
            continue
        out.append(command)
    return out


@pytest.mark.parametrize(("target", "job"), [("frontend", "frontend"), ("docs-site", "docs")])
def test_make_target_and_ci_job_run_the_same_checks(target, job):
    """A check that runs locally but not in CI is absent from the merge gate (and vice versa)."""
    local = _make_target(target)
    if local is None:
        pytest.skip(f"the {target} module is not enabled in this project")
    assert local == _ci_job(job), (
        f"`make {target}` and the CI `{job}` job have drifted:\n"
        f"  make: {local}\n  ci  : {_ci_job(job)}"
    )


def test_release_signing_is_gated_on_the_provenance_guard():
    """Pushing a tag is an ordinary git operation; nothing may be signed before the guard runs."""
    release = REPO_ROOT / ".github" / "workflows" / "release.yml"
    if not release.is_file():
        pytest.skip("the deploy module is not enabled in this project")
    jobs = _workflow(release)["jobs"]
    assert "guard" in jobs, "release.yml must have a provenance guard job"
    assert "guard" in (jobs["images"].get("needs") or []), "image signing must depend on the guard"
