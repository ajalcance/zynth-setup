"""The agent permission policy must be well-formed and actually deny what it claims.

A malformed permission rule does not error — it simply never matches, so the policy silently
grants everything it was written to restrict. These tests make that a build failure. They only
run when the Claude Code policy module is enabled.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import REPO_ROOT

SETTINGS = REPO_ROOT / ".claude" / "settings.json"
HOOK = REPO_ROOT / ".claude" / "hooks" / "block_dangerous_bash.py"
RULE_RE = re.compile(r"^(Bash|Read|Edit|Write|MultiEdit|NotebookEdit|WebFetch|Glob|Grep)\(.+\)$")
# Every tool that can put bytes on disk. A rule written for Edit alone leaves Write open,
# and a protected path an agent can Write is not protected.
WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")

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


def test_the_agents_own_authority_stays_statically_gated():
    """`.claude/` keeps STATIC rules and no hook may waive them.

    Everything else that needs a human moved to .claude/hooks/approved_scope.py — a static
    `ask` there would outrank the hook's `allow` and the scope would waive nothing (see
    tests/guards/test_approved_scope.py). This one path is the deliberate exception:
    widening the agent's own authority must not depend on the agent's code being correct.
    """
    ask = " ".join(_permissions()["ask"])
    assert (
        "Edit(./.claude/**)" in ask
    ), "the permission policy and the hooks must prompt through a static rule, not a hook"


def test_the_paths_that_need_a_human_are_gated_somewhere():
    """Statically or by the scope hook — but never by neither.

    The reconciliation between the two lives in
    tests/guards/test_protected_path_reconciliation.py, which checks both against a
    population written out by hand rather than against each other.
    """
    ask = " ".join(_permissions()["ask"])
    hook = REPO_ROOT / ".claude" / "hooks" / "approved_scope.py"
    core = hook.read_text() if hook.is_file() else ""
    for path, pattern in (
        ("./.github/**", ".github/**"),
        ("./scripts/**", "scripts/**"),
        ("./CLAUDE.md", "CLAUDE.md"),
        ("./docs/decisions/**", "docs/decisions/**"),
    ):
        assert (
            f"Edit({path})" in ask or f'"{pattern}"' in core
        ), f"{path} is gated by neither a static rule nor the scope hook"


def test_every_protected_path_is_protected_against_every_write_tool():
    """A rule written for Edit only does not stop a Write, and Write overwrites the file whole.

    Trivially exploitable, trivially fixed, and exactly the kind of thing a template should
    get right once for everyone. Only the statically-gated paths are checked here; the scope
    hook matches on the tool NAME, so it cannot have this gap by construction — and
    test_approved_scope.py asserts it is registered for all four.
    """
    ask = _permissions()["ask"]
    paths = {rule[len("Edit(") : -1] for rule in ask if rule.startswith("Edit(")}
    assert paths, "no protected paths found — this assertion would otherwise be vacuous"
    missing = [
        f"{tool}({path})"
        for path in sorted(paths)
        for tool in WRITE_TOOLS
        if f"{tool}({path})" not in ask
    ]
    assert not missing, (
        "protected paths with a gap — an agent can reach them with another write tool: "
        + ", ".join(missing)
    )


def test_an_adr_cannot_be_written_without_a_prompt():
    """ADRs outrank docs/PLAN.md in the source-of-truth order (CLAUDE.md §0).

    A broad `docs/**` allowance waived the prompt, leaving the one record that outranks the
    roadmap the only one an agent could write with nobody in the loop. The prompt now comes
    from the scope hook, which sees every write tool at once — so this asserts the path is
    claimed there rather than listing four static rules.
    """
    hook = REPO_ROOT / ".claude" / "hooks" / "approved_scope.py"
    if not hook.is_file():
        ask = _permissions()["ask"]
        for tool in WRITE_TOOLS:
            assert f"{tool}(./docs/decisions/**)" in ask
        return
    assert (
        '"docs/decisions/**"' in hook.read_text()
    ), "an ADR an agent writes unreviewed silently overrules the roadmap"


def test_settings_gate_edits_to_themselves():
    """ADR-0004: an agent must not be able to quietly widen its own authority."""
    assert "Edit(./.claude/**)" in _permissions()["ask"]


def test_the_agents_own_settings_are_denied_to_every_write_tool():
    """SEC-065: an `ask` here is a prompt somebody approves by reflex, and it widens authority.

    The rest of `.claude/` still asks — a scope or a hook is legitimately drafted by the agent
    and approved by the owner. The two files that decide what the agent may do are not.
    """
    deny = _permissions()["deny"]
    missing = [
        f"{tool}(./.claude/{name})"
        for name in ("settings.json", "settings.local.json")
        for tool in WRITE_TOOLS
        if f"{tool}(./.claude/{name})" not in deny
    ]
    assert not missing, f"the agent can rewrite its own permissions: {missing}"


def test_no_allow_rule_hands_over_an_interpreter():
    """`backend/.venv/bin/* *` allowed `python -c` and `pip install` — anything, unprompted.

    Every hook here reads a command line. A command line that is itself a program sails past
    all of them, so the venv's tools are allowed by name and the interpreter is not. This closes
    the one-liner, not the class: `pytest` runs test code the agent wrote. ADR-0007 says so, and
    names the fix that does close it — a separate GitHub identity for the agent.
    """
    allow = _permissions()["allow"]
    wildcards = [rule for rule in allow if re.search(r"bin/\*", rule)]
    assert not wildcards, f"a wildcard over a bin directory allows an interpreter: {wildcards}"
    for rule in allow:
        program = rule[len("Bash(") : -1].split(" ", 1)[0]
        assert Path(program).name not in {
            "python",
            "python3",
            "pip",
            "pip3",
            "node",
            "bash",
            "sh",
        } or rule.startswith("Bash(python3 scripts/"), f"{rule} allows arbitrary code"


def test_bypass_permissions_mode_is_disabled():
    assert _permissions().get("disableBypassPermissionsMode") == "disable"


def test_release_and_destructive_actions_are_never_silent():
    """Each must prompt or be refused outright — deny is the stronger of the two, not a gap."""
    permissions = _permissions()
    gated = " ".join(permissions["ask"] + permissions["deny"])
    for rule in ("git tag", "git push --force", "rm -rf", "gh release", "sudo", "docker"):
        assert (
            rule in gated
        ), f"'{rule}' changes state beyond the working tree — it must not be silent"


def test_the_never_acceptable_is_denied_rather_than_asked():
    """A prompt that is always declined is not a control; it is a click that trains reflex.

    Most prompts came from the unlisted, not the dangerous, and clicking through each one
    destroys the signal on the prompts that matter. Where there is no acceptable answer,
    there is no reason to spend a click.
    """
    deny = " ".join(_permissions()["deny"])
    for rule in ("git push --force", "sudo", "npm publish", "gh secret", "--no-verify"):
        assert rule in deny, (
            f"'{rule}' has no acceptable answer, so it must be denied outright rather than "
            f"left to a prompt somebody will eventually approve by reflex"
        )


def test_routine_work_does_not_prompt():
    """Confirmation fatigue is the failure mode: if everything prompts, nothing is read."""
    allow = " ".join(_permissions()["allow"])
    for rule in ("make ", "git status", "git commit", "git diff"):
        assert rule in allow, f"'{rule}' is routine and should not consume an approval"


def _fake_key(kind: str) -> str:
    """A private-key block assembled at RUNTIME, so this file contains no literal.

    A fixture that trips the secret scanner teaches the next person to add an allowlist
    entry, and the allowlist is always easier than the fix — which is exactly why the
    ratchet exists. `detect-private-key` and gitleaks both scan this file on the adopter's
    very first commit, so a literal here means their first commit is rejected.
    """
    marker = "-" * 5
    head = " ".join(x for x in ("BEGIN", kind, "PRIVATE", "KEY") if x)
    tail = " ".join(x for x in ("END", kind, "PRIVATE", "KEY") if x)
    return f"{marker}{head}{marker}\nAAAA\n{marker}{tail}{marker}\n"


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


# --- The secret-write hook ---------------------------------------------------------------
#
# Added because scripts/check_guard_coverage.py found it: this hook shipped as a control,
# was cited as a control, and nothing had ever demonstrated it could block anything.

SECRET_HOOK = REPO_ROOT / ".claude" / "hooks" / "block_secret_write.py"

secret_hook = pytest.mark.skipif(not SECRET_HOOK.is_file(), reason="hooks not enabled")


def _write_verdict(file_path: str, content: str = "") -> int:
    """Run the real PreToolUse hook against a Write payload; 2 means blocked."""
    payload = json.dumps({"tool_input": {"file_path": file_path, "content": content}})
    return subprocess.run(
        [sys.executable, str(SECRET_HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
    ).returncode


@secret_hook
@pytest.mark.parametrize(
    "path",
    [
        "/repo/.env",
        "/repo/.env.production",
        "/repo/certs/server.pem",
        "/repo/certs/server.key",
        "/repo/.ssh/id_ed25519",
        "/repo/.npmrc",
    ],
)
def test_secret_material_is_blocked_on_write(path):
    assert _write_verdict(path) == 2, f"a Write to {path} must be blocked, not allowed"


@secret_hook
def test_a_private_key_in_the_content_is_blocked_whatever_the_filename():
    """The filename is the easy half; a key pasted into notes.txt is the interesting one."""
    body = _fake_key("OPENSSH")
    assert _write_verdict("/repo/docs/notes.txt", body) == 2


@secret_hook
@pytest.mark.parametrize("path", ["/repo/.env.example", "/repo/backend/app/main.py"])
def test_ordinary_writes_are_not_blocked(path):
    """The positive control. .env.example is the file the README tells adopters to copy."""
    assert _write_verdict(path) == 0, f"{path} must not be blocked"


@secret_hook
def test_a_private_key_inserted_by_an_edit_is_blocked():
    """Registered for Write only, this hook never saw an Edit — and an Edit inserts bytes too.

    Extending the matcher without reading Edit's own field would be worse than leaving it:
    the hook would run, inspect nothing, and report clean.
    """
    body = _fake_key("RSA")
    payload = json.dumps(
        {"tool_name": "Edit", "tool_input": {"file_path": "/repo/notes.txt", "new_string": body}}
    )
    result = subprocess.run(
        [sys.executable, str(SECRET_HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2, "an Edit carrying a private key must be blocked"


@secret_hook
def test_a_private_key_inserted_by_a_multiedit_is_blocked():
    body = _fake_key("EC")
    payload = json.dumps(
        {
            "tool_name": "MultiEdit",
            "tool_input": {
                "file_path": "/repo/notes.txt",
                "edits": [{"old_string": "x", "new_string": body}],
            },
        }
    )
    result = subprocess.run(
        [sys.executable, str(SECRET_HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2, "a MultiEdit carrying a private key must be blocked"


@secret_hook
def test_the_secret_hook_sees_every_write_tool():
    """A tool the matcher misses is an unguarded way in."""
    settings = json.loads(SETTINGS.read_text())
    matchers = [
        entry.get("matcher", "")
        for entry in settings["hooks"]["PreToolUse"]
        if any("block_secret_write.py" in h.get("command", "") for h in entry.get("hooks", []))
    ]
    assert matchers, "the secret-write hook is registered for nothing"
    joined = "|".join(matchers)
    for tool in WRITE_TOOLS:
        assert tool in joined, f"the secret-write hook does not see {tool}"


@secret_hook
def test_a_malformed_payload_does_not_halt_every_write():
    """This hook fails OPEN by design: a bug in it must not brick the session.

    Its backstops are gitleaks in pre-commit and the CI hygiene job, which do not fail open.
    Recorded here so the direction is a decision somebody made, not an accident.
    """
    result = subprocess.run(
        [sys.executable, str(SECRET_HOOK)],
        input="not json",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0


# --- Self-approval and flags a glob cannot see (SEC-064, SEC-065) ------------------------
#
# `Bash(gh pr create*)` and `Bash(gh api repos/*)` are allowed, and CI reads a label as the
# owner's consent. So `gh pr create --label guardrail-change` approved the agent's own guard
# change without a single prompt. Every case below ran silently before this hook read tokens.


def _decision(command: str, cwd: Path | None = None) -> str:
    """The real hook's verdict: 'block', 'ask' or 'allow'."""
    payload = {"tool_input": {"command": command}}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode == 2:
        return "block"
    if result.stdout.strip():
        return json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]
    return "allow" if result.returncode == 0 else f"exit {result.returncode}"


@pytest.fixture(scope="module")
def tagged_repo(tmp_path_factory) -> Path:
    """A repository holding tag v1.0.0, so a bare tag name can be told from a branch."""
    repo = tmp_path_factory.mktemp("tagged")
    git = ["git", "-c", "user.email=a@example.com", "-c", "user.name=a", "-C", str(repo)]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    subprocess.run([*git, "tag", "v1.0.0"], check=True)
    return repo


hooked = pytest.mark.skipif(not HOOK.is_file(), reason="hooks not enabled")


@hooked
@pytest.mark.parametrize(
    "command",
    [
        "gh pr create --fill --label guardrail-change",
        "gh pr create --fill -l guardrail-change",
        "gh pr create --fill -lguardrail-change",
        "gh pr create --fill --label=allow-suppressions",
        "gh pr create --fill --label enhancement,no-tests-needed",
        'gh pr create --fill --label "$LABEL"',
        "gh issue create --title t --label allow-exemptions",
        "gh pr edit 5 --add-label guardrail-change",
        "gh issue edit 5 --add-label Sensitive-Change-Approved",
        "gh pr edit 5 --add-label no-changelog",
        "gh issue edit 7 --remove-label release-blocker",
        "gh label edit old-name --name guardrail-change",
        "gh api repos/acme/x/issues/5/labels -f labels[]=guardrail-change",
        "gh api repos/acme/x/issues/5/labels --input body.json",
        "gh api repos/acme/x/issues/7/labels/release-blocker -X DELETE",
        "gh api repos/acme/x/issues/5 -X PATCH -f labels[]=enhancement",
        "gh api repos/acme/x/issues/5 -X PATCH --field=labels[]=enhancement",
        "gh api repos/acme/x/issues -flabels[]=guardrail-change -f title=t",
        "gh api graphql -f query='mutation{addLabelsToLabelable(input:{}){clientMutationId}}'",
        "git status && gh pr create --fill --label guardrail-change",
        "GH_TOKEN=x gh pr create --fill --label guardrail-change",
        'echo "$(gh pr edit 5 --add-label no-tests-needed)"',
        "echo `gh pr edit 5 --add-label guardrail-change`",
        'bash -c "gh pr edit 5 --add-label guardrail-change"',
        "eval gh pr edit 5 --add-label guardrail-change",
    ],
)
def test_the_agent_cannot_approve_its_own_change(command):
    assert _decision(command) == "block", f"self-approval must be refused: {command!r}"


@hooked
@pytest.mark.parametrize(
    "command",
    [
        "git push origin feat/x --force",
        "git push -f origin feat/x",
        "git push -uf origin feat/x",
        "git push origin +v1.0.0",
        "git push origin v1.0.0 --force-with-lease",
        "git push --mirror origin",
        "git -c core.x=y push --force origin feat/x",
        'x=$(echo "$(git push origin feat/x --force)")',
    ],
)
def test_a_force_push_is_refused_wherever_the_flag_sits(command):
    assert _decision(command) == "block", f"a force push must be refused: {command!r}"


@hooked
@pytest.mark.parametrize(
    "command",
    [
        "git push origin --delete v1.0.0",
        "git push -d origin feat/x",
        "git push origin :refs/tags/v1.0.0",
        "git push origin :feat/x",
        "git push origin --tags",
        "git push --follow-tags origin feat/x",
        "git push origin refs/tags/v1.0.0",
        "git push origin v1.0.0",
        "git push --prune origin",
        "gh api repos/acme/x/git/refs/tags/v1.0.0 -X DELETE",
        "gh api -XDELETE repos/acme/x/git/refs/tags/v1.0.0",
        "gh api repos/acme/x/git/refs/heads/main --method PATCH -f sha=abc",
        "gh api repos/acme/x/rulesets -f name=x",
        "gh api repos/acme/x/rulesets -fname=x",
        "gh api repos/acme/x/issues/5 -X PATCH -f state=closed",
        "gh api repos/acme/x/actions/secrets/X --input s.json",
        "gh api graphql -f query='{viewer{login}}'",
        "gh label create allow-exemptions",
        'gh pr create --fill --title "unbalanced',
    ],
)
def test_what_has_a_legitimate_form_asks(command, tagged_repo):
    assert _decision(command, tagged_repo) == "ask", f"the owner must be asked: {command!r}"


@hooked
@pytest.mark.parametrize(
    "command",
    [
        "gh pr create --fill",
        "gh pr create --fill --label enhancement",
        "gh pr list --label guardrail-change",
        "gh pr view 5 --json labels",
        "gh issue edit 5 --add-label release-blocker",
        "gh api repos/acme/x/pulls/5",
        "gh api repos/acme/x/issues/5/labels",
        "gh api repos/acme/x/pulls -X GET -f state=open",
        "git push -u origin feat/x",
        "git push origin feat/x 2>&1",
        "git push",
        'echo "$(git rev-parse HEAD)"',
        'git commit -m "docs: never git push --force or gh pr edit --add-label guardrail-change"',
        "cat <<'EOF' > notes.md\ngit push -f origin feat/x\n"
        "gh pr edit 1 --add-label no-tests-needed\nEOF",
    ],
)
def test_routine_github_work_stays_silent(command, tagged_repo):
    """The positive control: a hook that asks about everything trains the reflex it must beat."""
    assert _decision(command, tagged_repo) == "allow", f"must stay unprompted: {command!r}"


def _hook_constants() -> dict:
    spec = importlib.util.spec_from_file_location("block_dangerous_bash", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {"consent": set(module.CONSENT_LABELS), "hold": set(module.HOLD_LABELS)}


@hooked
def test_the_consent_labels_are_every_label_a_workflow_reads():
    """Reconciled against the population, not typed out twice.

    A label a workflow reads and this hook does not know is a self-approval nobody sees.
    """
    read = set()
    for workflow in (REPO_ROOT / ".github" / "workflows").glob("*.yml"):
        read |= set(re.findall(r"labels\.\*\.name,\s*'([^']+)'", workflow.read_text()))
    assert read, "no workflow reads a label — this reconciliation would be vacuous"
    assert _hook_constants()["consent"] == read, (
        "the hook's CONSENT_LABELS and the labels the workflows read have drifted: "
        f"{sorted(_hook_constants()['consent'] ^ read)}"
    )


@hooked
def test_the_hold_labels_are_the_release_preflights():
    preflight = (REPO_ROOT / "scripts" / "release_preflight.py").read_text()
    held = set(re.findall(r'^BLOCKER_LABEL = "([^"]+)"', preflight, re.MULTILINE))
    assert held, "release_preflight.py no longer names its hold label"
    assert _hook_constants()["hold"] == held


@hooked
def test_every_owner_label_is_provisioned():
    """GitHub only applies a label that exists: an unprovisioned one is consent nobody can give."""
    bootstrap = (REPO_ROOT / "scripts" / "bootstrap-repo.sh").read_text()
    provisioned = set(re.findall(r'^\s*"([a-z-]+)\|', bootstrap, re.MULTILINE))
    constants = _hook_constants()
    missing = (constants["consent"] | constants["hold"]) - provisioned
    assert not missing, f"read by a workflow but never created by bootstrap-repo.sh: {missing}"


# --- One command at a time (backlog T11) ---------------------------------------------------
#
# The first rules were regexes over the whole line, so words from different commands combined.


@hooked
@pytest.mark.parametrize(
    "command",
    [
        "git push -u origin feat/x && gh pr create --fill --title 'main takes PRs only'",
        "rm -rf .cache/x && cp README.md .",
        'git commit -m "docs: explain why we never use --no-verify"',
        "git commit -mnothing-to-see",
        'git commit -m "-n is the short form of --no-verify"',
        "git push -u origin feat/main-fix",
        "gh pr view 5 --json title --jq '.title | ascii_downcase'",
    ],
)
def test_words_from_different_commands_do_not_combine(command, tagged_repo):
    assert _decision(command, tagged_repo) == "allow", f"must stay unprompted: {command!r}"


@hooked
@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "git push origin HEAD:main",
        "git push origin HEAD:refs/heads/master",
        "git commit -n -m wip",
        "git commit -an -m wip",
        "git commit --no-verify -m wip",
        "git -c user.name=x commit --no-verify -m wip",
        "git push --no-verify -u origin feat/x",
        "git config core.hooksPath /dev/null",
        "git config --local core.hooksPath .nohooks",
        "rm -rf ~",
        "rm -rf /",
        "rm -fr .",
        "rm -r -f *",
        "rm --recursive --force ~/",
        "gh pr merge 5 --squash --admin",
        'echo "$(git push origin main)"',
    ],
)
def test_each_rule_still_holds_on_its_own_command(command, tagged_repo):
    assert _decision(command, tagged_repo) == "block", f"must be refused: {command!r}"


@hooked
def test_a_line_that_cannot_be_parsed_falls_back_to_the_raw_rules():
    """Over-refusing a line nobody could read is the safe direction."""
    assert _decision('rm -rf ~ "unbalanced') == "block"
    assert _decision('gh pr create --title "unbalanced') == "ask"
    assert _decision('echo "unbalanced') == "allow"


@hooked
def test_without_its_parser_it_asks_about_gh_and_git_rather_than_passing(tmp_path):
    lonely = tmp_path / "block_dangerous_bash.py"
    lonely.write_text(HOOK.read_text())

    def run(command: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(lonely)],
            input=json.dumps({"tool_input": {"command": command}}),
            capture_output=True,
            text=True,
            timeout=30,
        )

    assert run("rm -rf ~").returncode == 2
    labelled = run("gh pr create --fill --label guardrail-change")
    assert labelled.returncode == 0 and '"ask"' in labelled.stdout
