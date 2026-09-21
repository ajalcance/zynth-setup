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
RELEASE_WF = REPO_ROOT / ".github" / "workflows" / "release.yml"
SCORECARD = REPO_ROOT / ".github" / "workflows" / "scorecard.yml"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"
SCANNERS = REPO_ROOT / "requirements-ci.txt"
# The waiver in ci.yml assumes a proposed version has been public long enough for a malicious
# publish to be noticed. Encode the premise, or the argument is decoration.
MIN_COOLDOWN_DAYS = 7
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
    """Strip how a binary is LOCATED, keep the tool and every flag.

    Where a tool lives is environment (a virtualenv locally, the runner's PATH in CI); which
    tool runs and with what flags is policy. Treating the two the same is how the bandit
    exclusion drifted: `-r . -ll -x tests` in CI against `-r <pkg> -ll -q` locally, with the
    CI form excluding nothing at all.
    """
    out = []
    for command in commands:
        command = " ".join(command.split()).replace("npx ", "").replace(".venv/bin/", "")
        if not command or command.startswith(("cd ", "npm ci", "pip install")):
            continue
        out.append(command)
    return out


@pytest.mark.parametrize(
    ("target", "job"), [("backend", "backend"), ("frontend", "frontend"), ("docs-site", "docs")]
)
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


# --- A hung job holds a runner, and the default is six hours ----------------------------


def _existing_workflows():
    return [w for w in (CI, RELEASE_WF, SCORECARD) if w.is_file()]


@pytest.mark.parametrize("workflow", [CI, RELEASE_WF, SCORECARD], ids=lambda w: w.name)
def test_every_job_declares_a_timeout(workflow):
    if not workflow.is_file():
        pytest.skip(f"{workflow.name} is not enabled in this project")
    jobs = _workflow(workflow)["jobs"]
    assert jobs, f"{workflow.name} declares no jobs — this assertion would be vacuous"
    missing = sorted(name for name, job in jobs.items() if "timeout-minutes" not in job)
    assert not missing, (
        f"{workflow.name} job(s) with no timeout — GitHub's default is six hours, and a hung "
        f"job holds a runner and its concurrency slot for all of it: {missing}"
    )


# --- Cancellation, and which runs may never be cut short --------------------------------


def test_a_run_on_the_default_branch_is_never_cancelled():
    """A cancelled run reports a non-success result, and main is the tree a tag is cut from."""
    setting = str(_workflow(CI)["concurrency"]["cancel-in-progress"])
    assert setting != "True", (
        "CI cancels superseded runs on every trigger, including push to the default branch. "
        "A main commit can then carry a cancelled gate."
    )
    assert (
        "pull_request" in setting
    ), f"cancellation must be conditional on the pull_request event, not {setting!r}"


def test_a_release_queues_behind_a_running_one():
    """Cancelling a release can leave a signed image in the registry with no evidence beside it."""
    if not RELEASE_WF.is_file():
        pytest.skip("the deploy module is not enabled in this project")
    concurrency = _workflow(RELEASE_WF).get("concurrency")
    assert concurrency, "the release workflow declares no concurrency group"
    assert (
        concurrency.get("cancel-in-progress") is False
    ), "a release must queue behind a running one, never cancel it"


# --- The payload a re-run replays is the ORIGINAL payload -------------------------------


def test_a_label_or_a_body_edit_retriggers_the_run():
    """The meta-guard reads labels from the event payload; the declaration guard reads the body.

    Without these trigger types a label applied after the run, and a body written after the
    run, never took effect — while the check that appeared green had evaluated the absent
    labels and the empty body.
    """
    triggers = _workflow(CI)[True]["pull_request"]
    types = set(triggers.get("types", []))
    assert types, "pull_request declares no types:, so it uses the default set without 'labeled'"
    for needed in ("labeled", "unlabeled", "edited", "opened", "synchronize", "reopened"):
        assert needed in types, f"'{needed}' is missing, so that event does not re-run CI"


# --- Dependabot's waiver rests on a premise that must be encoded ------------------------


def test_every_ecosystem_waits_out_a_cooldown():
    updates = yaml.safe_load(DEPENDABOT.read_text())["updates"]
    assert updates, "dependabot.yml declares no ecosystems — this assertion would be vacuous"
    bad = {
        f"{u['package-ecosystem']}:{u['directory']}": u.get("cooldown")
        for u in updates
        if (u.get("cooldown") or {}).get("default-days", 0) < MIN_COOLDOWN_DAYS
    }
    assert not bad, (
        f"ecosystem(s) with no cooldown, or one below the {MIN_COOLDOWN_DAYS} days the "
        f"sensitive-path waiver assumes: {bad}. A version published an hour ago would be "
        f"proposed immediately, down the shortest automated path to merge in the repository."
    )


# --- No unpinned program may judge a pull request ---------------------------------------


def test_every_program_that_judges_a_pull_request_is_pinned():
    """`pip install semgrep` takes whatever the index serves that morning.

    The scanners decide whether a change is safe, so an unpinned one is the highest-leverage
    supply-chain move against this repository — and the only dependency change nothing else
    would have asked a human about.
    """
    floating = []
    for workflow in _existing_workflows():
        for line in workflow.read_text().splitlines():
            stripped = line.strip().lstrip("-").strip()
            if not stripped.startswith(("pip install", "run: pip install")):
                continue
            body = stripped.split("pip install", 1)[1]
            if " -r " not in body and " -c " not in body and "==" not in body:
                floating.append(f"{workflow.name}: {stripped}")
    assert not floating, f"unpinned tool install(s) in CI: {floating}"


def test_the_scanner_manifest_needs_the_owners_label():
    """An escape hatch must never be wider than the gate it escapes."""
    assert SCANNERS.is_file(), "requirements-ci.txt is missing — the scanners are unpinned"
    guard = (REPO_ROOT / "scripts" / "meta_guard.py").read_text()
    match = re.search(r"GUARD_FILE_RE = re\.compile\((.*?)\n\)", guard, re.S)
    assert match, "GUARD_FILE_RE not found in scripts/meta_guard.py"
    assert "requirements-ci" in match.group(1), (
        "requirements-ci.txt names the programs that decide whether a PR is safe, but the "
        "meta-guard does not gate it — swapping a scanner would need no human at all"
    )


def test_the_pinned_scanners_are_the_ones_ci_installs():
    """A manifest nothing installs pins nothing."""
    installed = sum(
        1
        for workflow in _existing_workflows()
        for line in workflow.read_text().splitlines()
        if "requirements-ci.txt" in line and "pip install" in line
    )
    assert installed >= 2, (
        f"only {installed} CI step(s) install the pinned scanner manifest — the rest are "
        f"still taking whatever the index serves"
    )


# --- Dropping the credential and diffing a base are one decision, not two ---------------


def _checkout_steps(workflow):
    return {
        name: step
        for name, job in _workflow(workflow)["jobs"].items()
        for step in job.get("steps", [])
        if isinstance(step, dict) and "actions/checkout" in str(step.get("uses", ""))
    }


def test_the_path_filter_has_the_history_a_push_makes_it_read():
    """paths-filter reads the diff through the API on a PR, and through GIT on a push.

    On a push it diffs `github.event.before..github.sha`. A depth-1 clone does not have the
    before-SHA, so it falls back to `git fetch` — which exits 128 once the credential is gone,
    killing the job every other gate fans out from. Structurally invisible until the first
    merge: push runs only on the default branch, and the root commit has no `before`.
    """
    triggers = _workflow(CI)[True]
    assert "push" in triggers, "this assertion is only load-bearing while CI runs on push"
    filtering = {
        name: job
        for name, job in _workflow(CI)["jobs"].items()
        if any("paths-filter" in str(s.get("uses", "")) for s in job.get("steps", []))
    }
    assert filtering, "no job uses paths-filter — this assertion would be vacuous"
    bad = {}
    for name in filtering:
        step = _checkout_steps(CI).get(name)
        depth = (step or {}).get("with", {}).get("fetch-depth")
        if depth != 0:
            bad[name] = depth
    assert not bad, f"paths-filter job(s) checked out without full history: {bad}"


@pytest.mark.parametrize("workflow", [CI, RELEASE_WF, SCORECARD], ids=lambda w: w.name)
def test_a_job_either_keeps_its_credential_or_does_not_fetch(workflow):
    """Dropping the credential from a fetching job is the worst of both.

    It fails closed on a private repository and passes on a public one, so the defect is
    invisible until somebody generates the other kind of project.
    """
    if not workflow.is_file():
        pytest.skip(f"{workflow.name} is not enabled in this project")
    checkouts = _checkout_steps(workflow)
    assert checkouts, f"{workflow.name} has no checkout — this assertion would be vacuous"
    broken = []
    for name, job in _workflow(workflow)["jobs"].items():
        step = checkouts.get(name)
        if not step or (step.get("with") or {}).get("persist-credentials") is not False:
            continue
        for run in (s.get("run", "") for s in job.get("steps", []) if isinstance(s, dict)):
            if re.search(r"\bgit\s+(fetch|push|ls-remote)\b", run):
                broken.append(f"{workflow.name}:{name}")
                break
    assert not broken, (
        f"job(s) that drop the credential and then run git against the remote: {broken}. "
        f"Keep the credential, or stop fetching."
    )
