"""The scope mechanism must waive prompts only where an owner really approved the work.

The most expensive lesson behind this file: **permission precedence is deny → ask → allow,
and a hook's `allow` is one more allow.** It loses to any static `ask` rule matching the same
path. A previous version of this mechanism returned `allow` correctly, was verified by hand,
had a hundred passing assertions — and waived nothing for a whole day, while an ADR and two
other documents described it as live. The tests ran the hook directly and asserted its
verdict; nothing checked that no static rule outranked it.

So this file tests BOTH halves: the hook's verdicts, and the settings invariant that makes
those verdicts reachable at all.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import REPO_ROOT, write

HOOK = REPO_ROOT / ".claude" / "hooks" / "approved_scope.py"
SETTINGS = REPO_ROOT / ".claude" / "settings.json"
SCOPE_FILE = REPO_ROOT / ".claude" / "approved-scope.json"

pytestmark = pytest.mark.skipif(not HOOK.is_file(), reason="the Claude Code hooks are not enabled")

WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def _scope(**overrides) -> dict:
    scope = {
        "name": "billing module, slices 1-3",
        "cites": "docs/decisions/0013-billing-boundary.md",
        "reason": "Approved on 2026-09-21: build the billing module and its guards.",
        "paths": ["backend/**", "tests/guards/**"],
        "expires": (dt.date.today() + dt.timedelta(days=14)).isoformat(),
    }
    scope.update(overrides)
    return scope


def _project(tmp_path: Path, scopes: list[dict] | str | None) -> Path:
    if scopes is not None:
        body = scopes if isinstance(scopes, str) else json.dumps({"scopes": scopes})
        write(tmp_path / ".claude" / "approved-scope.json", body)
    return tmp_path


def verdict(tmp_path: Path, file_path: str, scopes=None, tool: str = "Edit") -> tuple[str, str]:
    root = _project(tmp_path, scopes)
    payload = {"tool_name": tool, "tool_input": {"file_path": str(root / file_path)}}
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": str(root)},
    )
    assert result.returncode == 0, result.stderr
    if not result.stdout.strip():
        return "silent", ""
    out = json.loads(result.stdout)["hookSpecificOutput"]
    return out["permissionDecision"], out["permissionDecisionReason"]


# --- The precedence fact, asserted where it actually holds -------------------------------


def test_no_static_ask_rule_outranks_this_hook():
    """Precedence is deny -> ask -> allow. A static `ask` here makes every allow a no-op.

    This is the assertion that would have caught a day of the mechanism waiving nothing while
    three documents said it was live. It reads the REAL settings file and the REAL hook.
    """
    ask = set(json.loads(SETTINGS.read_text())["permissions"]["ask"])
    core = _hook_constant("CORE")
    overridden = [
        f"{tool}(./{pattern})"
        for pattern in core
        for tool in WRITE_TOOLS
        if f"{tool}(./{pattern})" in ask
    ]
    assert not overridden, (
        "these paths have a static `ask` rule AND are claimed by the scope hook. `ask` "
        "outranks the hook's `allow`, so the scope would waive nothing — silently: "
        + ", ".join(overridden)
    )


def test_the_hook_is_registered_for_every_write_tool():
    """A hook nothing invokes is a file, and a tool it misses is an unguarded way in."""
    settings = json.loads(SETTINGS.read_text())
    matchers = [
        entry.get("matcher", "")
        for entry in settings["hooks"]["PreToolUse"]
        if any("approved_scope.py" in h.get("command", "") for h in entry.get("hooks", []))
    ]
    assert matchers, "the scope hook is registered for nothing, so it never runs"
    joined = "|".join(matchers)
    for tool in WRITE_TOOLS:
        assert tool in joined, f"the scope hook does not see {tool}"


def _hook_constant(name: str) -> tuple[str, ...]:
    """Read a tuple constant out of the real hook rather than restating it here."""
    namespace: dict = {}
    source = HOOK.read_text()
    start = source.index(f"{name} = (")
    end = source.index("\n)", start) + 2
    exec(source[start:end], namespace)  # noqa: S102 — our own file, read from disk
    return namespace[name]


# --- What a scope waives, and what it never does -----------------------------------------


def test_a_core_path_prompts_when_no_scope_covers_it(tmp_path):
    decision, reason = verdict(tmp_path, "scripts/check_pins.py", scopes=[])
    assert decision == "ask", reason
    assert "no active scope" in reason


def test_an_active_scope_waives_the_prompt(tmp_path):
    decision, reason = verdict(tmp_path, "tests/guards/test_x.py", scopes=[_scope()])
    assert decision == "allow", reason
    assert "billing module" in reason, "the reason must name the approval, for the record"


def test_ordinary_module_work_is_not_asked_about_at_all(tmp_path):
    """Confirmation fatigue is the failure mode: if everything prompts, nothing is read."""
    decision, _ = verdict(tmp_path, "backend/svc/main.py", scopes=[])
    assert decision == "silent"


# --- Every way of being sloppy produces MORE asking ---------------------------------------


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"cites": ""}, "uncited"),
        ({"reason": "wip"}, "no real reason"),
        ({"expires": ""}, "unbounded"),
        ({"expires": (dt.date.today() - dt.timedelta(days=1)).isoformat()}, "expired"),
        ({"expires": (dt.date.today() + dt.timedelta(days=400)).isoformat()}, "never lapses"),
        ({"name": ""}, "unnamed"),
    ],
)
def test_a_scope_that_is_not_in_good_order_waives_nothing(tmp_path, overrides, why):
    decision, reason = verdict(tmp_path, "tests/guards/test_x.py", scopes=[_scope(**overrides)])
    assert decision == "ask", f"a scope that is {why} must waive nothing: {reason}"


def test_a_malformed_scope_file_waives_nothing(tmp_path):
    decision, reason = verdict(tmp_path, "scripts/check_pins.py", scopes="{not json")
    assert decision == "ask", reason
    assert "could not be read" in reason


def test_a_missing_scope_file_waives_nothing(tmp_path):
    decision, _ = verdict(tmp_path, "scripts/check_pins.py", scopes=None)
    assert decision == "ask"


def test_the_shipped_scope_file_is_empty():
    """It must ship approving nothing: a template that pre-approves is a template that lies."""
    assert json.loads(SCOPE_FILE.read_text())["scopes"] == []


# --- A broad pattern never reaches a system-altering area ---------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "backend/migrations/versions/001_init.py",
        "backend/svc/auth/principal.py",
        "deploy/docker-compose.yml",
        ".github/workflows/ci.yml",
    ],
)
def test_a_broad_pattern_stops_at_a_system_altering_path(tmp_path, path):
    broad = _scope(paths=["backend/**", "**", ".github/**"])
    decision, reason = verdict(tmp_path, path, scopes=[broad])
    assert decision == "ask", f"a broad pattern must not reach {path}: {reason}"
    assert "naming it" in reason


def test_a_pattern_that_names_it_does_reach_it(tmp_path):
    """Pre-approving something dangerous is allowed — it just has to be said out loud."""
    named = _scope(paths=["backend/migrations/**"])
    decision, reason = verdict(tmp_path, "backend/migrations/versions/001_init.py", scopes=[named])
    assert decision == "allow", reason


def test_no_scope_can_widen_the_agents_own_authority(tmp_path):
    """The hook says NOTHING here, so the static rules apply whatever this code does."""
    everything = _scope(paths=["**", ".claude/**"])
    for path in (".claude/settings.json", ".claude/hooks/approved_scope.py"):
        decision, _ = verdict(tmp_path, path, scopes=[everything])
        assert decision == "silent", f"the hook must not speak about {path}"


def test_no_scope_can_waive_the_scope_file_itself(tmp_path):
    everything = _scope(paths=["**"])
    decision, _ = verdict(tmp_path, ".claude/approved-scope.json", scopes=[everything])
    assert decision == "silent"
