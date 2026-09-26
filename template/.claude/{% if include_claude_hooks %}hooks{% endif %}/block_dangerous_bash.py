#!/usr/bin/env python3
"""PreToolUse hook — block obvious Bash footguns before they run.

Ergonomics that mirror the **branch ruleset** (server-side is the real gate):
this catches the accidental self-inflicted commands an agent should never issue,
with a message pointing at the safe path. Narrow by design — it only blocks
clearly-destructive / gate-bypassing patterns to avoid false positives.

**The flag that matters can sit anywhere, and a permission rule is a prefix glob.**
`Bash(git push*)` is allowed so an agent can push its branch — and `git push origin v1.0.0
--force` starts the same way. `Bash(gh pr create*)` is allowed so it can open a PR — and
`gh pr create --label guardrail-change` approves its own guard change, because CI reads that
label as the owner's consent. So the second half of this hook reads `git push`, `gh api`,
`gh pr|issue` and `gh label` commands token by token, wherever the flag is:

* **self-approval is refused** — applying a label CI reads as the owner's consent, removing
  the owner's release hold, or any mutation of a labels endpoint through `gh api`;
* **rewriting published history is refused** — a force push in any spelling, anywhere;
* **deleting a ref, publishing a tag and any mutating `gh api` call ask** — each has a
  legitimate form, so the owner decides instead of a glob.

The label names are not a list somebody keeps in sync by hand: tests/guards/test_agent_policy.py
reads them out of the workflows and the release preflight and fails if this file disagrees.

**Every rule reads ONE command, never the whole line.** The first rules here were regexes over
the raw line, so words from different commands combined: `rm -rf build && copier copy . dest`
was a recursive delete of `.`, a PR title containing "main" made `git push -u origin feat/x`
a push to main, and a commit message that MENTIONED `--no-verify` was refused as using it. The
line is now read as the shell reads it (`_shell.py`, shared with the confinement hook) and each
rule looks at one simple command's own words. The raw-line regexes survive only as the
fallback for a line the parser cannot read — there, over-refusing is the safe direction.

**No-prompt mode.** With `CLAUDE_HOOKS_NEVER_ASK` set in the settings' `env`, nothing here
asks: what would ask is refused, and the owner runs it from their own terminal. A prompt is a
control only while someone watches, and a project that runs its agent unattended inside an OS
sandbox gets its approvals at the pull request instead. Off by default. The switch only ever
tightens: every value but an empty one or 0/false/no/off turns it on, and unsetting it returns
the prompts, never a pass.

Contract: reads the PreToolUse JSON envelope on stdin. Exit 2 blocks the tool
call and feeds stderr back to the model; a JSON `ask` on stdout makes Claude Code prompt even
where a static rule allows; exit 0 alone allows. Fails **open** on an internal error (a broken
hook must not halt every Bash call) — except that a `gh` or `git` command the token pass could
not read ASKS, because the static rules allow those forms on the assumption that it did.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# The shared parser sits beside this file. If it cannot be imported, main() falls back to the
# raw-line rules and asks about every gh/git command — never a silent pass on those forms.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import _shell
except Exception:  # noqa: BLE001
    _shell = None

# Raw-line rules — the FALLBACK, used only when the line cannot be parsed into commands. Read
# over the whole line they over-refuse (words from different commands combine), which is the
# safe direction for a line nobody could read. A parsed line is judged per command, below.
FALLBACK_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"\bgit\s+push\b(?=.*\b(?:--force|--force-with-lease|-f)\b)(?=.*\b(?:main|master)\b)"
        ),
        "force-push to a protected branch (main/master) rewrites shared history.",
    ),
    (
        re.compile(r"\bgit\s+push\b(?=.*\borigin\b)(?=.*\b(?:main|master)\b)"),
        "direct push to main/master bypasses the PR ruleset. Open a PR from a feat/* branch.",
    ),
    (
        re.compile(r"--no-verify\b|(?<!\w)-n\b(?=.*\bgit\s+commit)"),
        "--no-verify skips the pre-commit / commit-msg hooks (gitleaks, hygiene).",
    ),
    (
        re.compile(
            r"\brm\s+(?:-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r|-r\s+-f|-f\s+-r)\b"
            r".*(?:\s/(?:\s|$)|\s~(?:/|\s|$)|\$HOME|\s\*(?:\s|$)|\s\.(?:\s|$))"
        ),
        "recursive force-delete targeting a dangerous root (/, ~, $HOME, ., *).",
    ),
    (
        re.compile(r"\bgit\s+config\b.*\bcore\.hooksPath\b"),
        "changing core.hooksPath disables the repo's pre-commit hooks.",
    ),
    (
        # Enforced HERE rather than as a permission deny rule: `--admin` can appear at any
        # position, and permission rules are globs, not regexes. A PreToolUse hook that exits 2
        # is also evaluated BEFORE permission rules, so this cannot be undone by an allow rule.
        re.compile(r"(^|\s)--admin(\s|$)"),
        "--admin overrides branch protection and merges past the required checks. "
        "That is the owner's decision, never the agent's — ask instead.",
    ),
]


# Labels a workflow reads as the OWNER'S consent to relax a check. An agent that can apply one
# approves its own change: the meta-guard cannot tell who clicked. Reconciled with every
# `labels.*.name` the workflows read by tests/guards/test_agent_policy.py.
CONSENT_LABELS = frozenset(
    {
        "guardrail-change",
        "allow-suppressions",
        "no-tests-needed",
        "sensitive-change-approved",
        "allow-exemptions",
        "no-changelog",
    }
)
# Labels that HOLD something while present. Adding one is always fine; removing one is the
# owner's call. Reconciled with BLOCKER_LABEL in scripts/release_preflight.py.
HOLD_LABELS = frozenset({"release-blocker"})

# GraphQL mutations that change a label or what carries one.
LABEL_MUTATIONS = re.compile(
    r"\b(?:add|remove)LabelsToLabelable\b|\b(?:create|update|delete)Label\b|\bclearLabelsFromLabelable\b"
)
LABELS_ENDPOINT = re.compile(r"(?:^|/)labels(?:/|$|\?)")

# Targets a recursive force-delete must never name. The confinement hook stops deletes outside
# the project; these are the ones that take the project itself, or the machine, with them.
DANGEROUS_ROOTS = {
    "/",
    "/*",
    "~",
    "~/",
    "~/*",
    "$HOME",
    "${HOME}",
    ".",
    "./",
    "./*",
    "*",
    "..",
    "../",
}
PROTECTED_BRANCHES = {"main", "master", "refs/heads/main", "refs/heads/master"}

# `git` options that come BEFORE the subcommand and take a separate value.
GIT_GLOBAL_WITH_VALUE = {"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
# `gh api` flags that take a value, so the value is not mistaken for the endpoint.
GH_API_WITH_VALUE = {
    "-X",
    "--method",
    "-f",
    "--raw-field",
    "-F",
    "--field",
    "-H",
    "--header",
    "--input",
    "-q",
    "--jq",
    "-t",
    "--template",
    "--hostname",
    "-p",
    "--preview",
    "--cache",
}
GH_API_FIELDS = {"-f", "--raw-field", "-F", "--field", "--input"}
# `git push` options that take a separate value.
GIT_PUSH_WITH_VALUE = {"-o", "--push-option", "--receive-pack", "--exec", "--repo"}

Verdict = tuple[str, str]  # ("block" | "ask", reason)


def unknowable(value: str) -> bool:
    """A value this hook cannot read without running the shell."""
    return "$" in value or "`" in value


def flag_values(arguments: list[str], long: str, short: str | None) -> list[str]:
    """Every value given to `--long v`, `--long=v`, `-s v` or `-sv`."""
    values: list[str] = []
    for index, token in enumerate(arguments):
        following = arguments[index + 1] if index + 1 < len(arguments) else ""
        if token == long or (short and token == short):
            values.append(following)
        elif token.startswith(long + "="):
            values.append(token[len(long) + 1 :])
        elif short and token.startswith(short) and not token.startswith("--") and len(token) > 2:
            values.append(token[len(short) :].lstrip("="))
    return [label.strip().lower() for value in values for label in value.split(",")]


def judge_labels(labels: list[str], protected: frozenset[str], verb: str) -> Verdict | None:
    """`verb` completes "this would <verb> ..." — apply, remove, rename a label to."""
    for label in labels:
        if unknowable(label):
            return (
                "block",
                f"this would {verb} a label named by a shell expansion ({label!r}), which could "
                "be one a workflow reads as the owner's decision. Write the name out.",
            )
        if label in protected:
            return (
                "block",
                f"this would {verb} '{label}', and a workflow reads that label as the owner's "
                "decision — the meta-guard cannot tell who clicked. Ask the owner to do it.",
            )
    return None


def judge_gh(tokens: list[str]) -> Verdict | None:
    # Enforced here rather than as a permission deny rule: `--admin` can appear at any
    # position, and permission rules are globs. A PreToolUse hook that exits 2 is evaluated
    # BEFORE permission rules, so no allow rule can undo it.
    if "--admin" in tokens:
        return (
            "block",
            "--admin overrides branch protection and merges past the required checks. "
            "That is the owner's decision, never the agent's — ask instead.",
        )
    if len(tokens) < 2:
        return None
    group, arguments = tokens[1], tokens[2:]
    action = arguments[0] if arguments else ""

    if group in {"pr", "issue"} and action == "create":
        return judge_labels(flag_values(arguments, "--label", "-l"), CONSENT_LABELS, "apply")
    if group in {"pr", "issue"} and action == "edit":
        return judge_labels(
            flag_values(arguments, "--add-label", None), CONSENT_LABELS, "apply"
        ) or judge_labels(flag_values(arguments, "--remove-label", None), HOLD_LABELS, "remove")
    if group == "label" and action == "edit":
        renamed = flag_values(arguments, "--name", "-n")
        return judge_labels(renamed, CONSENT_LABELS | HOLD_LABELS, "rename a label to")
    if group == "label" and action in {"create", "delete", "clone"}:
        return ("ask", f"`gh label {action}` changes the repository's labels.")
    if group == "api":
        return judge_gh_api(arguments)
    return None


def judge_gh_api(arguments: list[str]) -> Verdict | None:
    method: str | None = None
    has_fields = False
    field_keys: list[str] = []
    endpoint: str | None = None
    index = 0
    while index < len(arguments):
        token = arguments[index]
        following = arguments[index + 1] if index + 1 < len(arguments) else ""
        if token in {"-X", "--method"}:
            method = following
        elif token.startswith("--method="):
            method = token.split("=", 1)[1]
        elif token.startswith("-X") and len(token) > 2:
            method = token[2:]
        if (
            token in GH_API_FIELDS
            or any(token.startswith(flag + "=") for flag in GH_API_FIELDS if flag.startswith("--"))
            or (token[:2] in {"-f", "-F"} and len(token) > 2)
        ):
            has_fields = True
            # `-f k=v`, `--field=k=v` or `-fk=v`: the key says what the call sets.
            if token in GH_API_FIELDS:
                field = following
            elif token.startswith("--"):
                field = token.split("=", 1)[1]
            else:
                field = token[2:]
            field_keys.append(field.split("=", 1)[0])
        if token in GH_API_WITH_VALUE:
            index += 2
            continue
        if not token.startswith("-") and endpoint is None:
            endpoint = token
        index += 1

    text = " ".join(arguments)
    if LABEL_MUTATIONS.search(text):
        return ("block", "this GraphQL call changes labels, and a label is the owner's consent.")
    if method is not None and unknowable(method):
        return ("ask", f"the HTTP method is a shell expansion ({method!r}).")
    effective = (method or ("POST" if has_fields else "GET")).upper()
    if effective in {"GET", "HEAD"}:
        return None
    if endpoint is None or unknowable(endpoint):
        return ("ask", f"a {effective} through `gh api` to an endpoint this hook cannot read.")
    if LABELS_ENDPOINT.search(endpoint.split("?", 1)[0]) or any(
        key.lower().startswith("labels") for key in field_keys
    ):
        return (
            "block",
            f"a {effective} on a labels endpoint ({endpoint}). Labels are how the owner "
            "approves a guard change or holds a release; applying or removing one is theirs.",
        )
    return ("ask", f"a {effective} through `gh api` ({endpoint}) changes repository state.")


def is_tag(name: str, cwd: str) -> bool | None:
    """Whether `name` is a local tag. None when git cannot say."""
    try:
        result = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/tags/{name}"],
            cwd=cwd,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return {0: True, 1: False}.get(result.returncode)


# `git commit` options whose next word is a value, so the value is never read as a flag.
COMMIT_WITH_VALUE = {"-m", "-F", "-c", "-C", "--author", "--date", "--template", "-t", "--cleanup"}


def commit_skips_hooks(arguments: list[str]) -> bool:
    """`-n` (alone or in a cluster like `-an`) is --no-verify for `git commit`."""
    skip = False
    for token in arguments:
        if skip:
            skip = False
            continue
        if token in COMMIT_WITH_VALUE:
            skip = True
            continue
        if token.startswith("-") and not token.startswith("--") and "n" in token[1:]:
            # `-m` with its message attached (`-mfix`) is a message, not a cluster of flags.
            if not token.startswith(("-m", "-F", "-c", "-C", "-t")):
                return True
    return False


def judge_rm(tokens: list[str]) -> Verdict | None:
    """A recursive force-delete of the machine, the home directory or the project itself."""
    flags = "".join(t[1:] for t in tokens[1:] if t.startswith("-") and not t.startswith("--"))
    recursive = "r" in flags.lower() or "--recursive" in tokens
    force = "f" in flags or "--force" in tokens
    if not (recursive and force):
        return None
    for target in tokens[1:]:
        if target in DANGEROUS_ROOTS or target.rstrip("/") in {"", "~", "$HOME", "${HOME}"}:
            return ("block", f"recursive force-delete of `{target}`, a dangerous root.")
    return None


def judge_git(tokens: list[str], cwd: str) -> Verdict | None:
    index = 1
    while index < len(tokens) and tokens[index].startswith("-"):
        index += 2 if tokens[index] in GIT_GLOBAL_WITH_VALUE else 1
    if index >= len(tokens):
        return None
    subcommand, rest = tokens[index], tokens[index + 1 :]
    if subcommand == "config" and any(t.lower().startswith("core.hookspath") for t in rest):
        return ("block", "changing core.hooksPath disables the repo's pre-commit hooks.")
    if "--no-verify" in rest or (subcommand == "commit" and commit_skips_hooks(rest)):
        return ("block", "--no-verify skips the pre-commit / commit-msg hooks (gitleaks, hygiene).")
    if subcommand != "push":
        return None
    arguments = rest

    positionals: list[str] = []
    asks: list[str] = []
    skip = False
    for position, token in enumerate(arguments):
        if skip:
            skip = False
            continue
        if token in GIT_PUSH_WITH_VALUE:
            skip = True
            continue
        if token.startswith("--"):
            name = token.split("=", 1)[0]
            if name in {"--force", "--force-with-lease", "--force-if-includes", "--mirror"}:
                return ("block", f"`{name}` rewrites or replaces what others already fetched.")
            if name in {"--delete", "--prune"}:
                asks.append(f"`{name}` deletes refs on the remote")
            if name in {"--tags", "--follow-tags"}:
                asks.append(f"`{name}` publishes tags, and a tag is a release")
            continue
        if token.startswith("-") and len(token) > 1:
            if "f" in token[1:]:
                return ("block", f"`{token}` is a force push; it rewrites published history.")
            if "d" in token[1:]:
                asks.append(f"`{token}` deletes refs on the remote")
            if token[-1] == "o" and position + 1 < len(arguments):
                skip = True
            continue
        positionals.append(token)

    for refspec in positionals[1:]:
        destination = refspec.partition(":")[2] or refspec
        if destination in PROTECTED_BRANCHES:
            return (
                "block",
                f"`{refspec}` pushes straight to {destination}, past the pull-request ruleset. "
                "Open a PR from a feature branch.",
            )
        if refspec.startswith("+"):
            return ("block", f"`{refspec}` is a force push; it rewrites published history.")
        if unknowable(refspec):
            asks.append(f"the refspec {refspec!r} is a shell expansion")
            continue
        source, _, destination = refspec.partition(":")
        if not source and destination:
            asks.append(f"`{refspec}` deletes `{destination}` on the remote")
        for side in (source, destination):
            if not side:
                continue
            if side.startswith("refs/tags/"):
                asks.append(f"`{refspec}` publishes a tag, and a tag is a release")
            elif not side.startswith("refs/") and is_tag(side, cwd) is not False:
                asks.append(f"`{side}` is (or may be) a tag, and publishing a tag is a release")
    if asks:
        return ("ask", "; ".join(dict.fromkeys(asks)) + ".")
    return None


def token_verdicts(line: str, cwd: str, depth: int = 0) -> list[Verdict]:
    """Verdicts for every command in the line, and in the lines hidden inside it."""
    if depth > 5:
        return [("ask", "command substitutions nested deeper than this hook reads.")]
    verdicts: list[Verdict] = []
    parsed = _shell.commands(line)  # ValueError propagates: main() decides what that means
    for command in parsed:
        words = command.words
        if not words:
            continue
        program = os.path.basename(words[0])
        verdict = None
        if program == "gh":
            verdict = judge_gh(words)
        elif program == "git":
            verdict = judge_git(words, cwd)
        elif program == "rm":
            verdict = judge_rm(words)
        if verdict:
            verdicts.append(verdict)
    for inner in _shell.nested(line, parsed):
        verdicts.extend(token_verdicts(inner, cwd, depth + 1))
    return verdicts


def block(reason: str) -> int:
    sys.stderr.write(
        "BLOCKED by .claude/hooks/block_dangerous_bash.py — " + reason + "\n"
        "This is a local guardrail; the branch ruleset enforces it server-side too.\n"
        "If this is genuinely intended, run it yourself outside the agent session.\n"
    )
    return 2


NEVER_ASK = "CLAUDE_HOOKS_NEVER_ASK"


def never_ask() -> bool:
    """No-prompt mode: set, and not one of the spellings of "off"."""
    return os.environ.get(NEVER_ASK, "").strip().lower() not in ("", "0", "false", "no", "off")


def ask(reason: str) -> int:
    if never_ask():
        return block(
            reason + f" In no-prompt mode ({NEVER_ASK}) what this hook would ask about is refused."
        )
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": ".claude/hooks/block_dangerous_bash.py: " + reason,
            }
        },
        sys.stdout,
    )
    return 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    command = (payload.get("tool_input") or {}).get("command")
    if not isinstance(command, str) or not command:
        return 0

    cwd = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    try:
        if _shell is None:
            raise ImportError("_shell.py could not be imported")
        verdicts = token_verdicts(command, cwd)
    except Exception:  # noqa: BLE001 — the direction below is the decision, not an accident
        for pattern, reason in FALLBACK_RULES:
            if pattern.search(command):
                return block(reason)
        if re.search(r"\b(?:gh|git)\b", command):
            return ask(
                "this gh/git command could not be read token by token (unbalanced quotes?). "
                "The static rules allow these forms on the assumption that it could."
            )
        return 0
    for kind, reason in verdicts:
        if kind == "block":
            return block(reason)
    if verdicts:
        return ask(" ".join(reason for _, reason in verdicts))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — fail open: never halt every Bash call on a hook bug
        sys.exit(0)
