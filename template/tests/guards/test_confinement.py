"""The confinement hook must stop a change reaching outside the project — and only that.

Every fixture here runs the REAL hook through its stdin contract, because a hook tested by
calling its functions is tested at the point that is easiest rather than the point it has to
hold. The scope hook next door was verified that way for a whole day while waiving nothing.

**The sandbox is a path that does not exist, under the home directory — never pytest's
`tmp_path`.** The system temp tree is somewhere a project could legitimately live, so a
`..`-escape test that lands there passes for the wrong reason: the empty-set trap, wearing a
test suite as a costume.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import REPO_ROOT

HOOK = REPO_ROOT / ".claude" / "hooks" / "confine_to_project.py"

pytestmark = pytest.mark.skipif(not HOOK.is_file(), reason="the Claude Code hooks are not enabled")

# A project path CONTAINING A SPACE, permanently. A pattern that stops at whitespace hands
# back the first word — an ancestor of the project, and therefore "outside" it. This machine's
# real path has a space in it, and that is how the bug was found: the hook blocked its own
# author within a minute, while 106 fault tests passed.
PROJECT = Path.home() / "no such directory" / "Software Applications" / "demo project"
OUTSIDE = Path.home() / "no such directory" / "Software Applications" / "other project"


def verdict(command: str, project: Path = PROJECT) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"tool_input": {"command": command}}),
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "CLAUDE_PROJECT_DIR": str(project)},
    )
    return result.returncode, result.stderr


def allowed(command: str) -> bool:
    return verdict(command)[0] == 0


def blocked(command: str) -> bool:
    return verdict(command)[0] == 2


# --- What must be impossible ------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf ~/Documents",
        "rm -rf /etc/hosts",
        f"rm -rf '{OUTSIDE}'",
        f"mv backend/app.py '{OUTSIDE}/app.py'",
        "truncate -s 0 ~/.zshrc",
    ],
)
def test_a_change_outside_the_project_is_blocked(command):
    assert blocked(command), f"must not be allowed: {command!r}"


def test_changing_directory_first_does_not_launder_the_command():
    """No single token here looks dangerous; the hook has to resolve before it decides."""
    assert blocked(f"cd '{OUTSIDE}' && rm -rf .")


def test_a_relative_escape_is_resolved():
    assert blocked("rm -rf ../../../etc/hosts")


def test_a_redirect_overwrites_whatever_the_verb_is():
    """`echo x > ~/.zshrc` contains no destructive verb at all."""
    assert blocked("echo 'evil' > ~/.zshrc")
    assert blocked(f"cat backend/app.py >> '{OUTSIDE}/stolen.py'")


def test_sed_in_place_outside_the_project_is_blocked():
    assert blocked(f"sed -i 's/a/b/' '{OUTSIDE}/config.toml'")


# --- sed's script is not a file (backlog T18) --------------------------------------------
#
# Every word after `sed -i` was a target, so a script holding a `$` was an "unguessable path"
# and the command was refused. Found preparing the v3.3.0 release.


@pytest.mark.parametrize(
    "command",
    [
        "sed -i '' 's/a$/b/' docs/PLAN.md",
        "sed -i 's/a$/b/' docs/PLAN.md",
        "sed -i.bak 's/$HOME/x/' docs/PLAN.md",
        "sed -i -e 's/a$/b/' -e 's/^c/d/' docs/PLAN.md docs/NOTES.md",
        "sed -i -E --expression='s/(a)$/b/' docs/PLAN.md",
        "sed -i '.orig' 's/a$/b/' docs/PLAN.md",
    ],
)
def test_the_sed_script_is_not_read_as_a_path(command):
    code, message = verdict(command)
    assert code == 0, f"{command!r} was refused:\n{message}"


@pytest.mark.parametrize(
    "command",
    [
        "sed -i '' 's/a$/b/' ~/elsewhere/config.toml",
        "sed -i -e 's/a/b/' ~/elsewhere/config.toml",
        "sed -i 's/a/b/' docs/PLAN.md ~/elsewhere/config.toml",
        "sed -i -f fix.sed ~/elsewhere/config.toml",
        "sed -i --file=fix.sed ~/elsewhere/config.toml",
        "sed -i '' 's/ask/allow/' .claude/settings.json",
    ],
)
def test_every_file_sed_edits_is_still_judged(command):
    assert blocked(command), f"must not be allowed: {command!r}"


# --- What must stay possible ------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf backend/.venv",
        "mkdir -p docs/decisions",
        "mv docs/a.md docs/b.md",
        "cp backend/requirements.txt backend/requirements.bak",
        "sed -i '' 's/a/b/' docs/PLAN.md",
        "touch docs/NOTES.md",
    ],
)
def test_ordinary_work_inside_the_project_is_allowed(command):
    code, message = verdict(command)
    assert code == 0, f"{command!r} was blocked:\n{message}"


@pytest.mark.parametrize(
    "command",
    [
        "cat ~/.gitconfig",
        "ls ~/Documents",
        "grep -r pattern /usr/share/doc",
        "diff backend/app.py ~/other-project/app.py",
    ],
)
def test_reading_outside_the_project_is_allowed(command):
    """Reading another project is how an assistant learns from one. Only changes are confined."""
    code, message = verdict(command)
    assert code == 0, f"reading must not be blocked: {command!r}\n{message}"


def test_a_device_is_not_a_file():
    """Without this the hook blocks its own mutation check, and every quiet command."""
    assert allowed("make check > /dev/null 2>&1")
    assert allowed("python3 scripts/dod-check.py 2>/dev/null")


def test_an_environment_prefix_is_not_a_write_target():
    """A search path says where to FIND programs. Nearly every command carries one."""
    assert allowed("PATH=/opt/homebrew/bin:$PATH make check")
    assert allowed("CLAUDE_PROJECT_DIR=/tmp npm test")


def test_an_environment_prefix_does_not_hide_the_verb_behind_it():
    """The discriminating case, and the dangerous direction.

    Skipping the assignment is not cosmetic: without it the real verb is never found, and
    `PATH=... rm -rf ~/Documents` is waved through. The two assertions above pass either way,
    so they prove nothing on their own — a surviving mutant is a missing test.
    """
    assert blocked("PATH=/opt/homebrew/bin rm -rf ~/Documents")
    assert blocked(f"TMPDIR=/tmp LC_ALL=C rm -rf '{OUTSIDE}'")


def test_an_environment_prefix_still_allows_the_same_work_inside():
    code, message = verdict("PATH=/opt/homebrew/bin rm -rf backend/.venv")
    assert code == 0, message


def test_a_heredoc_body_is_data_not_a_command():
    """Prose that mentions a command is not a command — writing a lessons entry must work.

    The body has to contain something that WOULD parse as a destructive command, or the test
    passes whether or not the body is stripped. A shell operator inside prose is the case:
    `&& rm -rf ~/Documents` in a sentence becomes its own segment the moment the body is read
    as a command line. This is how writing the lessons file got blocked, twice.
    """
    command = (
        "cat > docs/LESSONS.md <<'EOF'\n"
        "## 2026-09-21 — the hook and the lessons file\n"
        "Never write `cd /etc && rm -rf hosts` in a session; the hook refuses it,\n"
        "and quoting it here must not be refused too.\n"
        "EOF"
    )
    code, message = verdict(command)
    assert code == 0, f"a heredoc body must not be scanned as commands:\n{message}"


def test_the_same_text_outside_a_heredoc_is_still_a_command():
    """The positive control: stripping bodies must not stop the hook reading real commands."""
    assert blocked("cd /etc && rm -rf hosts")


def test_the_project_path_may_contain_a_space():
    """The regression that matters most here: a truncated path is an ancestor of itself."""
    code, message = verdict("rm -rf backend/.venv")
    assert code == 0, f"a project path with a space must work:\n{message}"
    assert "Software" not in message


# --- Refusing to guess ------------------------------------------------------------------


def test_an_unresolvable_variable_is_refused_rather_than_guessed():
    """A false positive on a convoluted one-liner beats a false negative."""
    code, message = verdict('rm -rf "$TARGET_DIR"')
    assert code == 2, "the hook must not guess what a variable expands to"
    assert "will not guess" in message, message


def test_an_unresolvable_cd_is_refused():
    assert blocked('cd "$SOMEWHERE" && rm -rf .')


def test_the_remedy_is_a_simpler_command_not_a_weaker_hook():
    """The same work, written out, is allowed. That is what makes the refusal reasonable."""
    assert allowed("rm -rf backend/.venv")


# --- The failure direction is a decision ------------------------------------------------


def test_the_hook_fails_closed_on_a_command_it_cannot_parse():
    """Unlike its siblings. What this prevents is unrecoverable, so a bug costs a prompt."""
    code, _ = verdict('rm -rf "unbalanced')
    assert code == 2, "an unparseable command must be refused, not waved through"


def test_a_payload_that_is_not_a_bash_call_is_ignored():
    result = subprocess.run(
        [sys.executable, str(HOOK)], input="not json", capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0


def test_the_hook_is_registered_for_bash():
    """A hook nothing invokes is a file. See scripts/check_guard_coverage.py."""
    settings = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text())
    commands = [
        hook.get("command", "")
        for entry in settings["hooks"]["PreToolUse"]
        if entry.get("matcher") == "Bash"
        for hook in entry.get("hooks", [])
    ]
    assert any(
        "confine_to_project.py" in c for c in commands
    ), "the confinement hook is not registered for Bash, so it never runs"


# --- The agent's own policy (SEC-065) ---------------------------------------------------
#
# `.claude/` is gated for the file tools, and `echo '{...}' > .claude/settings.local.json`
# walked past both gates: `echo` is allowed and a redirect is not an Edit.


@pytest.mark.parametrize(
    "command",
    [
        "echo '{}' > .claude/settings.local.json",
        "cp docs/x.json .claude/settings.json",
        "sed -i 's/ask/allow/' .claude/settings.json",
        "mv notes.py .claude/hooks/block_dangerous_bash.py",
        "tee .claude/approved-scope.json < scope.json",
        "cd docs && rm ../.claude/hooks/confine_to_project.py",
        "git checkout v1.0.0 -- .claude/settings.json",
        "git restore --source=HEAD~3 .claude/settings.json",
        "git -c advice.x=false checkout main .claude/hooks",
    ],
)
def test_no_shell_command_changes_the_agents_own_policy(command):
    code, message = verdict(command)
    assert code == 2, f"must not be allowed: {command!r}"
    assert "agent's own policy" in message, f"blocked for the wrong reason:\n{message}"


@pytest.mark.parametrize(
    "command",
    [
        "cat .claude/settings.json",
        "grep -r deny .claude",
        "git checkout feat/next",
        "git checkout -b feat/claude-docs",
        "git restore backend/app.py",
        "echo checkout .claude/settings.json",
    ],
)
def test_reading_the_policy_and_ordinary_checkouts_stay_allowed(command):
    """The positive control: reading `.claude/` and switching branches must not be caught."""
    code, message = verdict(command)
    assert code == 0, f"{command!r} was blocked:\n{message}"


# --- Read as the shell reads it (backlog T7) ---------------------------------------------
#
# The hook split on `|` and `;` before it parsed quotes, judged every command against the LAST
# `cd` in the line, and never looked inside a quoted substitution. Found by running the hook in
# the template repository's own agent session, where it refused a dozen ordinary reads.


@pytest.mark.parametrize(
    "command",
    [
        'grep -n "a\\|b" docs/PLAN.md',
        "git log --format='%h|%s' -3",
        'echo "$(git rev-parse HEAD | cut -c1-7)"',
        'echo "cost > /etc/x is text, not a redirect"',
        "rm -rf build && cd ~/elsewhere",
        "cat <<'EOF' > notes.md\nrm -rf ~\nEOF",
        "make check > /dev/null 2>&1",
    ],
)
def test_an_ordinary_line_is_not_refused(command):
    code, message = verdict(command)
    assert code == 0, f"{command!r} was refused:\n{message}"


@pytest.mark.parametrize(
    "command",
    [
        'echo "$(rm -rf ~/elsewhere)"',
        "echo `rm -rf ~/elsewhere`",
        'bash -c "rm -rf ~/elsewhere"',
        "nice rm -rf ~/elsewhere",
        "cd ~/elsewhere && rm -rf build",
        "echo x > ~/.zshrc",
    ],
)
def test_a_change_hidden_in_the_line_is_still_seen(command):
    assert blocked(command), f"must not be allowed: {command!r}"


def test_a_descriptor_is_not_a_file():
    """`2>&1` names stream 1, and the `2` of `2>` is a stream, not an argument.

    After a `cd` out of the project either one read as a path would be a write outside it.
    """
    assert allowed("cd ~/elsewhere && ls 2>&1")
    assert allowed(f"cd ~/elsewhere && touch '{PROJECT}/notes.md' 2>/dev/null")


def test_a_cd_moves_only_the_commands_after_it():
    """Judged against the FINAL directory, one of these was refused and the other allowed."""
    assert allowed("rm -rf build && cd ~/elsewhere")
    assert blocked("cd ~/elsewhere && rm -rf build")


def test_without_its_parser_it_refuses_rather_than_passes(tmp_path):
    """The hook fails closed: a missing _shell.py must not turn every command into a pass."""
    lonely = tmp_path / "confine_to_project.py"
    lonely.write_text(HOOK.read_text())
    result = subprocess.run(
        [sys.executable, str(lonely)],
        input=json.dumps({"tool_input": {"command": "ls"}}),
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "CLAUDE_PROJECT_DIR": str(PROJECT)},
    )
    assert result.returncode == 2 and "could not be imported" in result.stderr
