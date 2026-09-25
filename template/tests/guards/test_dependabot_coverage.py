"""Every manifest in the tree has a Dependabot entry — derived from the tree, not a list.

docs-site shipped for months with no Dependabot coverage: a whole Next.js app whose
dependencies, security fixes included, were never proposed. It was wired into the Makefile
and CI, but nothing checked that the cross-cutting systems knew about it. Adding a module
means N systems must learn about it; this asserts one of them, and it lives in the project
so the check runs on every change, not only in the template's own self-test.
"""

from __future__ import annotations

import re

import yaml
from conftest import REPO_ROOT

SKIP = {"node_modules", ".venv", ".next", ".git", "__pycache__", ".pytest_cache"}
MANIFESTS = {"package.json": "npm", "Dockerfile": "docker", ".pre-commit-config.yaml": "pre-commit"}


def _required() -> set[tuple[str, str]]:
    required = set()
    for path in REPO_ROOT.rglob("*"):
        if any(part in SKIP for part in path.parts) or not path.is_file():
            continue
        ecosystem = MANIFESTS.get(path.name)
        if path.name.startswith("requirements") and path.suffix == ".txt":
            ecosystem = "pip"
        if ecosystem is None:
            continue
        relative = path.parent.relative_to(REPO_ROOT).as_posix()
        required.add((ecosystem, "/" if relative == "." else "/" + relative))
    if (REPO_ROOT / ".github" / "workflows").is_dir():
        required.add(("github-actions", "/"))
    return required


def test_every_manifest_location_has_a_dependabot_entry():
    config = yaml.safe_load((REPO_ROOT / ".github" / "dependabot.yml").read_text())
    covered = {
        (u["package-ecosystem"], u["directory"].rstrip("/") or "/") for u in config["updates"]
    }
    required = _required()
    assert required, "no manifest found anywhere — this assertion would be vacuous"
    missing = sorted(required - covered)
    print(f"dependabot-coverage: {len(required)} manifest location(s), {len(missing)} uncovered")
    assert not missing, f"manifest location(s) with no Dependabot entry: {missing}"


def test_every_entry_has_the_cooldown_the_waiver_assumes():
    """Mirrors the CI waiver's premise for the SAME file, so the two checks cannot disagree."""
    config = yaml.safe_load((REPO_ROOT / ".github" / "dependabot.yml").read_text())
    short = [
        f"{u['package-ecosystem']} {u['directory']}"
        for u in config["updates"]
        if int(u.get("cooldown", {}).get("default-days", 0)) < 7
    ]
    assert (
        not short
    ), f"entries without the 7-day cooldown the sensitive-path waiver assumes: {short}"


def _applied_labels() -> set[str]:
    config = yaml.safe_load((REPO_ROOT / ".github" / "dependabot.yml").read_text())
    return {label for update in config["updates"] for label in update.get("labels", [])}


def test_no_bot_applies_a_label_a_workflow_reads_as_consent():
    """This file labelled the scanner bumps `guardrail-change` — and the meta-guard passed.

    The label is the owner's consent; whoever applies it approves the change. A bot that
    applies it approves its own change to what judges every pull request.
    """
    consent = set()
    for workflow in (REPO_ROOT / ".github" / "workflows").glob("*.y*ml"):
        consent |= set(re.findall(r"labels\.\*\.name,\s*'([^']+)'", workflow.read_text()))
    assert consent, "no workflow reads a label — this would pass over nothing"
    applied = _applied_labels()
    assert not applied & consent, f"Dependabot applies consent label(s): {applied & consent}"


def test_a_bump_to_a_guard_is_flagged_for_the_owner():
    """Workflows, the scanner manifest and the hooks are guards: their bumps ask for the owner."""
    config = yaml.safe_load((REPO_ROOT / ".github" / "dependabot.yml").read_text())
    guard_updates = [
        u
        for u in config["updates"]
        if (u["package-ecosystem"], u["directory"])
        in {
            ("github-actions", "/"),
            ("pip", "/"),
            ("pre-commit", "/"),
        }
    ]
    assert len(guard_updates) == 3, f"expected 3 guard ecosystems, found {len(guard_updates)}"
    unflagged = [u["package-ecosystem"] for u in guard_updates if "needs-owner" not in u["labels"]]
    assert not unflagged, f"guard bumps that do not ask for the owner: {unflagged}"


def test_every_label_dependabot_applies_is_provisioned():
    """GitHub drops a label that does not exist; the flag would silently never appear."""
    bootstrap = (REPO_ROOT / "scripts" / "bootstrap-repo.sh").read_text()
    provisioned = set(re.findall(r'^\s*"([a-z-]+)\|', bootstrap, re.MULTILINE))
    missing = _applied_labels() - provisioned
    assert not missing, f"never created by scripts/bootstrap-repo.sh: {missing}"
