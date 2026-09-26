"""No-prompt mode: with CLAUDE_HOOKS_NEVER_ASK set, a hook never asks — it refuses instead.

A prompt is a control only while someone is watching. A project that runs its agent unattended
inside an OS sandbox takes its approvals at the pull request, and a hook that asks there either
interrupts nobody or is answered without being read. The switch is off by default and only
ever tightens: what would ask is refused, what was refused stays refused, and what was allowed
stays allowed. These tests run the real hooks, as Claude Code does.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import pytest
from conftest import REPO_ROOT

HOOKS = REPO_ROOT / ".claude" / "hooks"
BASH_HOOK = HOOKS / "block_dangerous_bash.py"
SCOPE_HOOK = HOOKS / "approved_scope.py"
SWITCH = "CLAUDE_HOOKS_NEVER_ASK"

pytestmark = pytest.mark.skipif(not BASH_HOOK.is_file(), reason="the hooks are not enabled")

# Every kind of command the Bash hook asks about by default. A tag is named by its full ref:
# a bare `v1.0.0` counts as a tag only where one exists, and a fresh project has none.
ASKED = [
    "gh label create x",
    "gh api -X POST repos/o/r/issues",
    'gh api -X "$M" repos/o/r',
    "git push origin --delete feat",
    "git push origin refs/tags/v1.0.0",
    "git push origin --tags",
]
ON = ["1", "true", "yes", "on", "anything"]
OFF = ["", "0", "false", "no", "off", " OFF "]


def _env(value: str | None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != SWITCH}
    if value is not None:
        env[SWITCH] = value
    return env


def bash_verdict(command: str, switch: str | None = None) -> str:
    result = subprocess.run(
        [sys.executable, str(BASH_HOOK)],
        input=json.dumps({"tool_input": {"command": command}}),
        capture_output=True,
        text=True,
        timeout=30,
        env=_env(switch),
    )
    if result.returncode == 2:
        return "block"
    assert result.returncode == 0, result.stderr
    if not result.stdout.strip():
        return "allow"
    return json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]


@pytest.mark.parametrize("command", ASKED)
def test_by_default_the_hook_asks(command):
    assert bash_verdict(command) == "ask"


@pytest.mark.parametrize("command", ASKED)
def test_in_no_prompt_mode_what_would_ask_is_refused(command):
    assert bash_verdict(command, "1") == "block"


@pytest.mark.parametrize("value", ON)
def test_every_spelling_of_on_turns_it_on(value):
    assert bash_verdict("gh label create x", value) == "block"


@pytest.mark.parametrize("value", OFF)
def test_only_a_spelling_of_off_leaves_the_prompt(value):
    assert bash_verdict("gh label create x", value) == "ask"


@pytest.mark.parametrize("switch", [None, "1"])
def test_a_refusal_stays_a_refusal_and_routine_work_stays_allowed(switch):
    assert bash_verdict("git push --force", switch) == "block"
    for routine in ("git status", "gh pr view 5", "gh api repos/o/r"):
        assert bash_verdict(routine, switch) == "allow", routine


def test_the_refusal_says_why():
    result = subprocess.run(
        [sys.executable, str(BASH_HOOK)],
        input=json.dumps({"tool_input": {"command": "gh label create x"}}),
        capture_output=True,
        text=True,
        timeout=30,
        env=_env("1"),
    )
    assert result.returncode == 2 and SWITCH in result.stderr


def test_every_hook_that_can_ask_honours_the_switch():
    # Closes the class: a hook added later that emits "ask" without reading the switch would
    # put a prompt back into a project that has none.
    asking = [p for p in sorted(HOOKS.glob("*.py")) if re.search(r"[\"']ask[\"']", p.read_text())]
    assert BASH_HOOK in asking, "the Bash hook no longer asks — this test would be vacuous"
    for hook in asking:
        text = hook.read_text()
        assert f'NEVER_ASK = "{SWITCH}"' in text and "never_ask()" in text, hook.name


@pytest.mark.skipif(not SCOPE_HOOK.is_file(), reason="the scope hook is not shipped")
@pytest.mark.parametrize("switch,expected", [(None, "ask"), ("1", "deny")])
def test_the_scope_hook_denies_instead_of_asking(tmp_path, switch, expected):
    env = _env(switch) | {"CLAUDE_PROJECT_DIR": str(tmp_path)}
    payload = {"tool_name": "Edit", "tool_input": {"file_path": str(tmp_path / "Makefile")}}
    result = subprocess.run(
        [sys.executable, str(SCOPE_HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    decision = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]
    assert decision == expected
