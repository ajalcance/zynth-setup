"""The agent working on this repository runs under the policy the template ships.

Until 2026-09-25 the agent maintaining the guard template ran with no guards at all: a
machine-local settings file with 199 allow rules, no ask, no deny, and `git push *`.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys

import pytest
from conftest import ROOT, WORKFLOWS

SETTINGS = ROOT / ".claude" / "settings.json"
HOOKS = ROOT / ".claude" / "hooks"
TEMPLATE_HOOKS = ROOT / "template" / ".claude" / "{% if include_claude_hooks %}hooks{% endif %}"
WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
RULE = re.compile(r"^(Bash|Read|Edit|Write|MultiEdit|NotebookEdit)\(.+\)$")

# What judges the agent HERE. A change to any of these alters its own enforcement, so it asks.
ROOT_GUARD_PATHS = (
    "./.claude/**",
    "./.github/**",
    "./scripts/**",
    "./tests/**",
    "./Makefile",
    "./requirements-selftest.txt",
    "./.pre-commit-config.yaml",
    "./.gitleaks.toml",
    "./.gitleaksignore",
)


def permissions() -> dict:
    return json.loads(SETTINGS.read_text())["permissions"]


def test_every_rule_is_well_formed():
    """A malformed rule matches nothing and quietly grants what it meant to restrict."""
    bad = [r for b in ("deny", "ask", "allow") for r in permissions()[b] if not RULE.match(r)]
    assert not bad, f"these rules match nothing: {bad}"


@pytest.mark.parametrize(
    "hook", ["block_dangerous_bash.py", "confine_to_project.py", "block_secret_write.py"]
)
def test_each_hook_is_the_one_the_template_ships(hook):
    """A copy, byte for byte — never a pointer into template/.

    Pointing the session at template/ would let an edit to the template change the agent's own
    live guard mid-session. A copy changes only when someone deliberately copies it.
    """
    assert (HOOKS / hook).read_bytes() == (
        TEMPLATE_HOOKS / hook
    ).read_bytes(), (
        f".claude/hooks/{hook} has drifted from the template's. Fix the template's, then copy it."
    )


def test_every_hook_is_registered():
    settings = json.loads(SETTINGS.read_text())
    commands = " ".join(
        hook["command"] for entry in settings["hooks"]["PreToolUse"] for hook in entry["hooks"]
    )
    for hook in HOOKS.glob("*.py"):
        assert hook.name in commands, f"{hook.name} ships but never runs"


def test_the_agents_own_settings_are_denied_to_every_write_tool():
    deny = permissions()["deny"]
    missing = [
        f"{tool}(./.claude/{name})"
        for name in ("settings.json", "settings.local.json")
        for tool in WRITE_TOOLS
        if f"{tool}(./.claude/{name})" not in deny
    ]
    assert not missing, f"the agent can rewrite its own permissions: {missing}"


@pytest.mark.parametrize("path", ROOT_GUARD_PATHS)
def test_what_judges_the_agent_here_asks_before_every_write_tool(path):
    ask = permissions()["ask"]
    missing = [f"{tool}({path})" for tool in WRITE_TOOLS if f"{tool}({path})" not in ask]
    assert not missing, f"an agent can change what judges it without a prompt: {missing}"


def test_bypass_mode_is_disabled():
    assert permissions().get("disableBypassPermissionsMode") == "disable"


def test_no_allow_rule_hands_over_an_interpreter():
    for rule in permissions()["allow"]:
        program = rule[len("Bash(") : -1].split(" ", 1)[0]
        assert program.rsplit("/", 1)[-1] not in {
            "python",
            "pip",
            "pip3",
            "bash",
            "sh",
            "node",
        }, f"{rule} allows arbitrary code"
        assert "bin/*" not in rule, f"{rule} is a wildcard over a bin directory"


def test_the_hook_refuses_every_label_a_workflow_here_reads():
    """The label CI reads as consent is one the agent's session cannot apply."""
    spec = importlib.util.spec_from_file_location("hook", HOOKS / "block_dangerous_bash.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    read = set()
    for workflow in WORKFLOWS.glob("*.yml"):
        read |= set(re.findall(r"labels\.\*\.name,\s*'([^']+)'", workflow.read_text()))
    assert read, "no workflow reads a label — this would pass over nothing"
    assert read <= set(
        module.CONSENT_LABELS
    ), f"not refused by the hook: {read - module.CONSENT_LABELS}"


@pytest.mark.parametrize(
    "command",
    [
        "gh pr edit 9 --add-label guardrail-change",
        "gh pr create --fill --label guardrail-change",
        "git push origin v3.2.0 --force",
    ],
)
def test_the_live_hook_refuses_self_approval_and_rewriting_a_release(command):
    """Run through the real hook, as the session runs it."""
    result = subprocess.run(
        [sys.executable, str(HOOKS / "block_dangerous_bash.py")],
        input=json.dumps({"tool_input": {"command": command}, "cwd": str(ROOT)}),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2, f"must be refused: {command}"
