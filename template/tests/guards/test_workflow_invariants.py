"""Structural invariants that keep the merge gate honest.

These are not fault-injection tests; they assert wiring that, if it silently regressed, would
make CI *look* green while checking less. Every one of these was verified by hand at least once
during development — this is that check, automated.
"""

from __future__ import annotations

import json
import re

import pytest
import yaml

from conftest import REPO_ROOT

CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
RULESET = REPO_ROOT / ".github" / "rulesets" / "main.json"
# GitHub Actions' own GitHub App. A required check bound to this id can only be posted by
# Actions — which is what stops a pull request declaring a job of the same name and
# satisfying the gate itself.
GITHUB_ACTIONS_APP_ID = 15368


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


RELEASE = REPO_ROOT / ".github" / "workflows" / "release.yml"
# Word-bounded on purpose: `docker buildx imagetools create` copies an existing manifest and is
# exactly what promotion is allowed to do, but a naive "docker build" substring matches it.
BUILD_MARKERS = (
    r"build-push-action",
    r"docker\s+build\b",
    r"buildx\s+build\b",
    r"docker\s+compose\s+build\b",
)


def _release_jobs():
    if not RELEASE.is_file():
        pytest.skip("the deploy module is not enabled in this project")
    return _workflow(RELEASE)["jobs"]


def test_release_signing_is_gated_on_the_provenance_guard():
    """Pushing a tag is an ordinary git operation; nothing may be signed before the guard runs."""
    jobs = _release_jobs()
    assert "guard" in jobs, "release.yml must have a provenance guard job"
    assert "candidate" in jobs, "release.yml must build the candidate in a 'candidate' job"
    assert "guard" in (jobs["candidate"].get("needs") or []), "building must depend on the guard"


def test_the_guard_runs_the_release_preflight():
    """The preflight is where the release-blocker hold and open production blockers are read."""
    jobs = _release_jobs()
    steps = " ".join(step.get("run", "") for step in jobs["guard"]["steps"])
    assert "release_preflight.py" in steps, "the guard job must run the release preflight"
    assert "--mode at-tag" in steps, "in CI the tag exists, so the at-tag direction applies"


def test_promotion_never_rebuilds():
    """Promotion that rebuilds is not promotion — it ships bytes nobody reviewed.

    This is the whole point of a build-once candidate, and it is one careless copied step away
    from being false, so it is asserted rather than trusted to the comment that says it.
    """
    jobs = _release_jobs()
    assert "promote" in jobs, "release.yml must have a promote job"
    body = yaml.safe_dump(jobs["promote"])
    found = [marker for marker in BUILD_MARKERS if re.search(marker, body)]
    assert not found, f"the promote job contains build step(s): {found}"


def test_the_rebuild_check_would_catch_a_real_build_step():
    """The check above passes trivially if its patterns match nothing. Prove they match."""
    sample = "steps:\n- uses: docker/build-push-action@abc\n- run: docker build . && buildx build ."
    found = [marker for marker in BUILD_MARKERS if re.search(marker, sample)]
    assert len(found) >= 3, f"the build markers do not detect an obvious build: {found}"
    allowed = "run: docker buildx imagetools create --tag x:stable y@sha256:0"
    assert not [m for m in BUILD_MARKERS if re.search(m, allowed)], "retagging is not a build"


def test_promotion_requires_a_typed_confirmation():
    """Moving what production pulls must not be satisfiable by reflex.

    The step must actually COMPARE the two inputs. Asserting only that an `exit 1` appears
    somewhere passes against `if false; then ... exit 1; fi` — a confirmation that can never
    fail, which is the exact shape this check exists to rule out.
    """
    if not RELEASE.is_file():
        pytest.skip("the deploy module is not enabled in this project")
    workflow = _workflow(RELEASE)
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    assert {"promote_tag", "confirm"} <= set(inputs), "promotion needs a tag and a confirmation"

    comparing = [
        step
        for step in workflow["jobs"]["promote"]["steps"]
        if "promote_tag" in str(step.get("env", "")) and "confirm" in str(step.get("env", ""))
    ]
    assert comparing, "no promote step reads both promote_tag and confirm"
    body = " ".join(step.get("run", "") for step in comparing)
    assert "!=" in body, "the confirmation must compare the two inputs, not just exist"
    assert "exit 1" in body, "a mismatched confirmation must fail the job"


def test_promotion_verifies_the_evidence_belongs_to_this_release():
    """A valid evidence document from another release would promote the wrong bytes."""
    jobs = _release_jobs()
    steps = " ".join(step.get("run", "") for step in jobs["promote"]["steps"])
    assert "cosign verify-blob" in steps, "the evidence signature must be verified"
    assert "--expect-tag" in steps, "the evidence must be checked against the tag being promoted"
    assert "cosign verify " in steps, "every image digest must be verified before promotion"


# --- The merge gate must not be forgeable by the thing it gates -------------------------


def _ruleset() -> dict:
    return json.loads(RULESET.read_text())


def _required_checks() -> list[dict]:
    rules = [r for r in _ruleset()["rules"] if r["type"] == "required_status_checks"]
    assert rules, "the ruleset declares no required status checks at all"
    return rules[0]["parameters"]["required_status_checks"]


def test_every_required_check_names_the_app_that_may_post_it():
    """Matched by name only, the one required check was forgeable by any pull request.

    A PR could add a workflow declaring a job called `ci-complete`; that job posts a check of
    that name, and the merge gate is satisfied without CI ever running. `integration_id` binds
    the context to GitHub Actions, so a status from anything else does not count.
    """
    checks = _required_checks()
    assert checks, "no required status check — this assertion would otherwise be vacuous"
    unbound = [c["context"] for c in checks if c.get("integration_id") != GITHUB_ACTIONS_APP_ID]
    assert not unbound, (
        f"required check(s) matched by name alone, so any PR can forge them: {unbound}. "
        f'Add "integration_id": {GITHUB_ACTIONS_APP_ID}.'
    )


def test_the_required_check_is_a_job_this_repository_actually_runs():
    """A required context nothing posts blocks every PR forever; the wrong one blocks nothing."""
    contexts = {c["context"] for c in _required_checks()}
    jobs = set(_workflow(CI)["jobs"])
    assert contexts <= jobs, f"required check(s) with no matching CI job: {sorted(contexts - jobs)}"


def test_nobody_may_bypass_the_ruleset():
    """Stated explicitly rather than left absent — an empty list is a decision, a gap is not."""
    actors = _ruleset().get("bypass_actors")
    assert actors == [], f"the ruleset grants bypass to {actors!r}"


def test_a_merge_cannot_reintroduce_unreviewed_history():
    rules = {r["type"] for r in _ruleset()["rules"]}
    for required in ("deletion", "non_fast_forward", "required_linear_history", "pull_request"):
        assert required in rules, f"the ruleset is missing the '{required}' rule"
    pull_request = [r for r in _ruleset()["rules"] if r["type"] == "pull_request"][0]["parameters"]
    assert pull_request.get("allowed_merge_methods") == [
        "squash"
    ], "linear history plus an unrestricted merge method lets a merge commit through"
