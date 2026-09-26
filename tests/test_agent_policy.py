"""The agent working on this repository runs under the no-prompt model (ADR 0005).

Until 2026-09-25 the agent maintaining the guard template ran with no guards at all: a
machine-local settings file with 199 allow rules, no ask, no deny, and `git push *`. From then
it asked before touching what judges it. From 2026-09-26 nothing asks: every action runs or is
refused at once, inside the OS sandbox (ADR 0004), and the approvals that matter are the
owner's label, merge and release. These tests hold that shape so it cannot drift back.
"""

from __future__ import annotations

import fnmatch
import importlib.util
import json
import re
import subprocess
import sys

import pytest
from conftest import ROOT, SCRIPTS, WORKFLOWS

SETTINGS = ROOT / ".claude" / "settings.json"
HOOKS = ROOT / ".claude" / "hooks"
TEMPLATE_HOOKS = ROOT / "template" / ".claude" / "{% if include_claude_hooks %}hooks{% endif %}"
WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
TOOLS = {"Read", "Glob", "Grep", "Edit", "Write", "MultiEdit", "NotebookEdit", "Bash"}
RULE = re.compile(r"^(Bash|Read|Edit|Write|MultiEdit|NotebookEdit)\(.+\)$")
NEVER_ASK = "CLAUDE_HOOKS_NEVER_ASK"

# What judges the agent HERE, and used to ask. It no longer does, so each path must be one a
# pull request cannot change without the owner's label. .claude/ is stricter still: denied.
STOPPED_ASKING = (
    ".github/workflows/template-test.yml",
    "scripts/check_sandbox.py",
    "tests/test_agent_policy.py",
    "Makefile",
    "requirements-selftest.txt",
    ".pre-commit-config.yaml",
    ".gitleaks.toml",
    ".gitleaksignore",
)

# The owner's acts, and the irreversible ones. Each must be refused outright.
OWNER_ONLY = (
    "git tag",
    "git tag -a v9.9.9 -F notes",
    "git tag --list",
    "git push origin --tags",
    "git push --tags",
    "git push origin --follow-tags",
    "git push origin refs/tags/v9.9.9",
    "git push origin HEAD:refs/tags/v9.9.9",
    "git push origin main --tags --no-thin",
    "gh release create v9.9.9",
    "gh pr merge 5 --rebase",
    "gh label create x",
    "gh pr edit 5 --add-label guardrail-change",
    "gh pr edit 5 --remove-label release-blocker",
    "gh pr create --fill --label guardrail-change",
    "gh api -X POST repos/o/r/issues/5/labels",
    "gh api repos/o/r/rulesets --method PUT",
    "gh api repos/o/r/issues/5/labels",
    "gh repo edit --visibility private",
    "gh secret set TOKEN",
    "gh ruleset list",
    "gh workflow run template-test.yml",
    "git push origin feat/x --force",
    "git push -f origin feat/x",
    "git push origin feat/x -f",
    "git push origin --delete feat/x",
    "git reset --hard HEAD~1",
    "git clean -fdx",
    "git commit --no-verify -m x",
    "git config core.hooksPath /dev/null",
    "ssh deploy@example.com",
    "sudo rm -rf /",
    "docker run --rm -v /:/host alpine",
    "npm publish",
    "gh release list",
    "gh repo view",
    "sudo -s",
)

# Everyday work. None of it may be refused, or the model breaks the work it is meant to allow.
ROUTINE = (
    "git status",
    "git diff --cached",
    "git commit -F .copier-test/msg.txt",
    "git push origin feat/x",
    "git switch --no-track -c feat/x origin/main",
    "gh pr create --base main --head feat/x --title t --body-file f.md",
    "gh pr view 5",
    "gh pr checks 5",
    "gh api repos/o/r/pulls",
    "gh api user/repos --paginate -q .[].full_name",
    "make check",
    "make verify",
    ".venv/bin/python -m pytest -q tests",
)


def permissions() -> dict:
    return json.loads(SETTINGS.read_text())["permissions"]


def bash_denies() -> list[str]:
    return [r[len("Bash(") : -1] for r in permissions()["deny"] if r.startswith("Bash(")]


def refused(command: str) -> bool:
    """A Bash rule is a glob over the whole command: `*` matches anything, spaces included."""
    return any(fnmatch.fnmatchcase(command, pattern) for pattern in bash_denies())


def test_every_deny_rule_is_well_formed():
    """A malformed rule matches nothing and quietly grants what it meant to restrict."""
    bad = [r for r in permissions()["deny"] if not RULE.match(r)]
    assert not bad, f"these rules match nothing: {bad}"


def test_nothing_asks():
    """An ask rule is a control only while someone watches; here nobody is asked anything."""
    assert not permissions().get("ask"), "an ask rule is back: refuse it or allow it"


def test_the_allow_list_is_the_tools_themselves():
    allow = set(permissions()["allow"])
    assert allow <= TOOLS, f"not a whole tool: {allow - TOOLS}"
    assert (
        "Bash" in allow and "Edit" in allow
    ), "the model allows the tools; the deny list bounds them"


def test_a_command_rule_also_matches_the_bare_command():
    """`Bash(npm publish *)` needs a space after it, so a bare `npm publish` ran silently."""
    spaced = [p for p in bash_denies() if p.endswith(" *") and "*" not in p[:-2]]
    assert not spaced, f"write these without the space before the star: {spaced}"


def test_a_flag_rule_matches_wherever_the_flag_sits():
    """`Bash(--admin)` is compared from the start of the command, so it matches nothing."""
    starts_with_a_flag = [p for p in bash_denies() if p.startswith("-")]
    assert not starts_with_a_flag, f"write these as *--flag*: {starts_with_a_flag}"


@pytest.mark.parametrize("command", OWNER_ONLY)
def test_the_owners_acts_are_refused_outright(command):
    assert refused(command), f"not denied — it would run silently: {command}"


@pytest.mark.parametrize("command", ROUTINE)
def test_routine_work_is_not_refused(command):
    assert not refused(command), f"denied, but it is everyday work: {command}"


def _root_guards() -> re.Pattern[str]:
    spec = importlib.util.spec_from_file_location(
        "check_guard_label", SCRIPTS / "check_guard_label.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ROOT_GUARDS


@pytest.mark.parametrize("path", STOPPED_ASKING)
def test_what_stopped_asking_needs_the_owners_label_at_the_pull_request(path):
    assert _root_guards().search(path), f"{path} no longer asks and no label gates it"


def test_the_agents_own_policy_is_denied_to_every_write_tool():
    deny = permissions()["deny"]
    wanted = [
        f"{tool}(./.claude/{name})"
        for name in ("**", "settings.json", "settings.local.json")
        for tool in WRITE_TOOLS
    ]
    missing = [rule for rule in wanted if rule not in deny]
    assert not missing, f"the agent can rewrite its own policy or hooks: {missing}"


def test_secret_files_are_denied_at_any_depth():
    """A bare file name matches at any depth; `./.env` would match only the root one."""
    deny = permissions()["deny"]
    for name in (".env", ".env.local", ".env.production"):
        assert f"Read({name})" in deny, name


def test_no_prompt_mode_holds_only_with_what_makes_it_safe():
    """Bypass mode is allowed here only because nothing it removes was doing the work."""
    settings = json.loads(SETTINGS.read_text())
    assert settings.get("env", {}).get(NEVER_ASK) == "1", "the hooks would still ask"
    assert "disableBypassPermissionsMode" not in settings["permissions"]
    commands = " ".join(
        hook["command"] for entry in settings["hooks"]["PreToolUse"] for hook in entry["hooks"]
    )
    for hook in ("block_dangerous_bash.py", "confine_to_project.py", "block_secret_write.py"):
        assert hook in commands, f"{hook} is not registered, and nothing asks in its place"
    assert "approved_scope.py" not in commands, "the scope hook asks; it has no place here"


@pytest.mark.parametrize(
    "hook",
    ["block_dangerous_bash.py", "confine_to_project.py", "block_secret_write.py", "_shell.py"],
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
        # `_shell.py` is the parser the Bash hooks import, not a hook: nothing runs it directly.
        if hook.name.startswith("_"):
            continue
        assert hook.name in commands, f"{hook.name} ships but never runs"


def test_every_module_a_hook_imports_ships_beside_it():
    """A hook whose parser is missing refuses everything — the copy must travel with it."""
    for module in (TEMPLATE_HOOKS).glob("_*.py"):
        assert (HOOKS / module.name).is_file(), f".claude/hooks/{module.name} was never copied"


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
