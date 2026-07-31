"""The agent permission policy must be well-formed and actually deny what it claims.

A malformed permission rule does not error — it simply never matches, so the policy silently
grants everything it was written to restrict. These tests make that a build failure. They only
run when the Claude Code policy module is enabled.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

import pytest

from conftest import REPO_ROOT

SETTINGS = REPO_ROOT / ".claude" / "settings.json"
HOOK = REPO_ROOT / ".claude" / "hooks" / "block_dangerous_bash.py"
RULE_RE = re.compile(r"^(Bash|Read|Edit|Write|WebFetch|Glob|Grep)\(.+\)$")

pytestmark = pytest.mark.skipif(
    not SETTINGS.is_file(), reason="the Claude Code agent policy is not enabled in this project"
)


def _permissions() -> dict:
    return json.loads(SETTINGS.read_text())["permissions"]


def test_every_rule_is_well_formed():
    """A typo'd rule matches nothing and quietly grants what it meant to restrict."""
    malformed = [
        rule
        for bucket in ("deny", "ask", "allow")
        for rule in _permissions().get(bucket, [])
        if not RULE_RE.match(rule)
    ]
    assert not malformed, f"malformed permission rules (these match nothing): {malformed}"


def test_secret_material_is_denied_not_merely_asked():
    """Precedence is deny -> ask -> allow, so secrets must be in deny to be unconditional."""
    deny = " ".join(_permissions()["deny"])
    for expected in ("./.env", "*.pem", "*.key"):
        assert expected in deny, f"{expected} must be denied outright, not left to a prompt"


def test_env_example_stays_readable():
    """A `.env.*` glob would also block the documented placeholder file."""
    deny = _permissions()["deny"]
    assert "Read(./.env.*)" not in deny, (
        "denying ./.env.* also blocks .env.example, which the README tells adopters to copy; "
        "list the real secret filenames instead"
    )


def test_policy_and_guard_files_require_confirmation():
    ask = " ".join(_permissions()["ask"])
    for path in ("./.claude/**", "./.github/**", "./scripts/**", "./CLAUDE.md"):
        assert f"Edit({path})" in ask, f"edits to {path} must prompt — the agent gates itself"


def test_settings_gate_edits_to_themselves():
    """ADR-0004: an agent must not be able to quietly widen its own authority."""
    assert "Edit(./.claude/**)" in _permissions()["ask"]


def test_bypass_permissions_mode_is_disabled():
    assert _permissions().get("disableBypassPermissionsMode") == "disable"


def test_release_and_destructive_actions_ask():
    ask = " ".join(_permissions()["ask"])
    for rule in ("git tag", "git push --force", "rm -rf", "gh release", "sudo", "docker"):
        assert rule in ask, f"'{rule}' changes state beyond the working tree — it must prompt"


def test_routine_work_does_not_prompt():
    """Confirmation fatigue is the failure mode: if everything prompts, nothing is read."""
    allow = " ".join(_permissions()["allow"])
    for rule in ("make ", "git status", "git commit", "git diff"):
        assert rule in allow, f"'{rule}' is routine and should not consume an approval"


def _hook_verdict(command: str) -> int:
    """Run the real PreToolUse hook against a command; 2 means blocked."""
    payload = json.dumps({"tool_input": {"command": command}})
    return subprocess.run(
        [sys.executable, str(HOOK)], input=payload, capture_output=True, text=True, timeout=30
    ).returncode


@pytest.mark.skipif(not HOOK.is_file(), reason="hooks not enabled")
@pytest.mark.parametrize(
    "command",
    [
        "gh pr merge --admin 5",
        "gh pr merge 5 --admin",
        "gh pr merge --squash --admin --delete-branch 5",
    ],
)
def test_admin_flag_is_blocked_in_any_position(command):
    """Permission rules are globs; `--admin` can appear anywhere, so the hook enforces it."""
    assert _hook_verdict(command) == 2, f"--admin must be blocked, but this passed: {command!r}"


@pytest.mark.skipif(not HOOK.is_file(), reason="hooks not enabled")
def test_ordinary_merge_is_still_allowed():
    """The positive control: the hook must not block the normal path."""
    assert _hook_verdict("gh pr merge --squash 5") == 0
