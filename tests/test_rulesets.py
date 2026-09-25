"""The rulesets require checks that exist, bypass nobody, and protect every release tag."""

from __future__ import annotations

import json

import pytest
import yaml
from conftest import ROOT, WORKFLOWS

RULESETS = ROOT / ".github" / "rulesets"
GITHUB_ACTIONS_APP_ID = 15368
# Documented parameters of the pull_request rule (GitHub REST: repository rules). A parameter
# the API does not document is either rejected — the bootstrap fails — or silently ignored,
# which is a control claiming more than it does. Backlog T10: the template ships one.
PULL_REQUEST_PARAMETERS = {
    "allowed_merge_methods",
    "dismiss_stale_reviews_on_push",
    "dismissal_restriction",
    "require_code_owner_review",
    "require_last_push_approval",
    "required_approving_review_count",
    "required_review_thread_resolution",
    "required_reviewers",
}


def load(name: str) -> dict:
    return json.loads((RULESETS / name).read_text())


def rules(ruleset: dict) -> dict:
    return {rule["type"]: rule.get("parameters", {}) for rule in ruleset["rules"]}


def pull_request_jobs() -> set[str]:
    """Check contexts a pull request can post: job ids (or names) in PR-triggered workflows."""
    contexts = set()
    for path in WORKFLOWS.glob("*.yml"):
        workflow = yaml.safe_load(path.read_text())
        triggers = workflow.get(True) or workflow.get("on") or {}
        if "pull_request" not in triggers:
            continue
        for job_id, job in workflow["jobs"].items():
            contexts.add(job.get("name", job_id))
    return contexts


@pytest.mark.parametrize("name", ["main.json", "tags.json"])
def test_nobody_bypasses(name):
    ruleset = load(name)
    assert ruleset["enforcement"] == "active"
    assert ruleset["bypass_actors"] == [], f"{name}: a bypass actor is a hole with a name"


def test_every_required_check_is_one_a_pull_request_posts():
    """A required check nothing posts blocks every PR — or gets quietly dropped."""
    required = rules(load("main.json"))["required_status_checks"]["required_status_checks"]
    assert required, "no required checks — the ruleset gates nothing"
    posted = pull_request_jobs()
    for check in required:
        assert check["context"] in posted, f"required but never posted on a PR: {check['context']}"
        assert (
            check.get("integration_id") == GITHUB_ACTIONS_APP_ID
        ), f"{check['context']}: bound to no app, so any app — or a user token — can post it"


def test_both_owner_gates_are_required():
    contexts = {
        c["context"]
        for c in rules(load("main.json"))["required_status_checks"]["required_status_checks"]
    }
    assert {"ci-complete", "guard-label"} <= contexts


def test_main_takes_pull_requests_only_and_never_rewrites_history():
    main = rules(load("main.json"))
    for rule in ("deletion", "non_fast_forward", "pull_request", "required_linear_history"):
        assert rule in main, f"main-protection lacks {rule}"


def test_the_pull_request_rule_uses_only_documented_parameters():
    parameters = set(rules(load("main.json"))["pull_request"])
    assert (
        parameters <= PULL_REQUEST_PARAMETERS
    ), f"undocumented: {parameters - PULL_REQUEST_PARAMETERS}"


def test_a_release_tag_can_never_be_moved_or_deleted():
    tags = load("tags.json")
    assert tags["target"] == "tag"
    assert "refs/tags/v*" in tags["conditions"]["ref_name"]["include"]
    assert {"deletion", "update", "non_fast_forward"} <= set(rules(tags))


def test_the_bootstrap_allows_only_the_merge_method_the_ruleset_allows():
    """A merge button the ruleset then refuses is a trap; one it allows but the repo disables,
    a dead end."""
    allowed = rules(load("main.json"))["pull_request"]["allowed_merge_methods"]
    script = (ROOT / "scripts" / "bootstrap-repo.sh").read_text()
    # Ruleset method name → the repository setting that enables its merge button.
    flags = {
        "rebase": "allow_rebase_merge",
        "squash": "allow_squash_merge",
        "merge": "allow_merge_commit",
    }
    for method, flag in flags.items():
        expected = "true" if method in allowed else "false"
        assert (
            f"-F {flag}={expected}" in script
        ), f"bootstrap sets {flag} inconsistently with the ruleset"
