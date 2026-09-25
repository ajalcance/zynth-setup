"""A tool this repository shares with the template runs at the template's version.

requirements-selftest.txt promises "one version of each tool" across the repository. Dependabot
reads only this repository's root config, so it proposes root bumps alone — a ruff bump here and
the root harness lints with a different ruff than every adopter's harness. This makes the drift
a red check: a shared bump moves the template's pin in the same pull request.
"""

from __future__ import annotations

import re

import pytest
import yaml
from conftest import ROOT

PIN = re.compile(r"^([A-Za-z0-9._-]+)==([^\s;#]+)", re.MULTILINE)
# Where the template pins each tool, in the order to consult. The CI manifest first: those are
# the versions the template's gates run.
TEMPLATE_MANIFESTS = (
    ROOT / "template" / "requirements-ci.txt",
    ROOT / "template" / "backend" / "requirements-dev.txt.jinja",
)


def pins(path) -> dict[str, str]:
    return {name.lower(): version for name, version in PIN.findall(path.read_text())}


def template_version(tool: str) -> str | None:
    for manifest in TEMPLATE_MANIFESTS:
        version = pins(manifest).get(tool)
        if version:
            return version
    return None


ROOT_PINS = pins(ROOT / "requirements-selftest.txt")
SHARED = sorted(tool for tool in ROOT_PINS if template_version(tool))


def test_the_comparison_is_not_vacuous():
    assert len(SHARED) >= 5, f"only {SHARED} are shared — the manifests may have moved"


@pytest.mark.parametrize("tool", SHARED)
def test_a_shared_tool_is_pinned_to_the_templates_version(tool):
    assert ROOT_PINS[tool] == template_version(tool), (
        f"{tool}: root pins {ROOT_PINS[tool]}, the template pins {template_version(tool)}. "
        "Move both in the same pull request."
    )


def hook_revs(path) -> dict[str, str]:
    config = yaml.safe_load(path.read_text())
    return {repo["repo"]: repo["rev"] for repo in config["repos"]}


ROOT_HOOKS = hook_revs(ROOT / ".pre-commit-config.yaml")
TEMPLATE_HOOKS = hook_revs(ROOT / "template" / ".pre-commit-config.yaml")


@pytest.mark.parametrize("repo", sorted(ROOT_HOOKS))
def test_every_hook_runs_at_the_templates_commit(repo):
    assert repo in TEMPLATE_HOOKS, f"{repo} is a root hook the template does not ship"
    assert ROOT_HOOKS[repo] == TEMPLATE_HOOKS[repo], (
        f"{repo}: root runs {ROOT_HOOKS[repo]}, the template {TEMPLATE_HOOKS[repo]}. "
        "Move both in the same pull request."
    )
