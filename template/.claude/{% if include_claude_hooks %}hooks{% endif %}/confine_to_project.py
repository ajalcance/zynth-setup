#!/usr/bin/env python3
"""PreToolUse hook — a change may not reach outside this project.

Permission rules cannot express this. Precedence is deny → ask → allow and the patterns are
globs, so "everything except this folder" is not writable as a rule: any deny broad enough to
protect the rest of the machine also blocks the project itself. The dangerous-command hook
beside this one names `/`, `~` and `$HOME`, which leaves every sibling project directory fair
game — and an agent that changes directory first issues no single token that looks dangerous.

So this resolves first and decides second. It expands `~` and `..`, and follows each `cd` in
order — a `cd` moves only the commands AFTER it — before asking whether a target is inside the
project. The line is read as the shell reads it (`_shell.py`, shared with the dangerous-command
hook): quotes respected, so `grep "a|b"` is one argument, not a pipe; a redirect counted only
when it is unquoted; and the command lines inside `$(...)`, backticks, `sh -c` and `eval`
judged like any other. An earlier version split on `|` before reading quotes, refused everyday
reads as "unbalanced", judged every command against the LAST `cd`, and never looked inside a
quoted substitution.

Three design decisions worth keeping:

* **Only CHANGES are confined, never reads.** Reading another project is how an assistant
  learns from one. Deleting it is what must be impossible.
* **A redirect overwrites whatever the verb is.** `echo x > ~/.zshrc` contains no destructive
  verb at all, so redirects are checked ahead of the verb gate. Devices (`/dev/null`,
  `/dev/stderr`) are exempt, or this hook blocks its own mutation check.
* **Prefer a false positive on a convoluted one-liner to a false negative.** This refuses to
  guess what a variable expands to. The remedy is a simpler command, never a weaker hook.
* **The agent's own policy is outside the project too, as far as the shell is concerned.**
  `.claude/` is gated for the file tools — the settings files are denied, the rest asks — and
  `echo '{...}' > .claude/settings.local.json` walked straight past both, because `echo` is
  allowed and a redirect is not an Edit. So no shell command may change anything under
  `.claude/`, including `git checkout <old-ref> -- .claude/settings.json`, which restores a
  weaker policy without writing a byte of it. A change there goes through the Edit tool,
  where the permission system can see it.

Contract: reads the PreToolUse JSON envelope on stdin. Exit 2 blocks and feeds stderr back to
the model; exit 0 allows. Fails **closed** on a command it cannot parse — unlike its siblings,
because the thing it prevents is unrecoverable.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# The shared parser sits beside this file. An import that fails must not become a pass: main()
# refuses every command while `_shell` is None, because this hook fails closed.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import _shell
except Exception:  # noqa: BLE001
    _shell = None

# Verbs that change or destroy something at a path. `sed` is here only for `-i`; see below.
DESTRUCTIVE = {
    "rm",
    "rmdir",
    "mv",
    "cp",
    "dd",
    "shred",
    "truncate",
    "tee",
    "install",
    "chmod",
    "chown",
    "chgrp",
    "ln",
    "mkdir",
    "touch",
    "unlink",
    "rsync",
}
# Writing to a device is not writing to a file. Without this the hook blocks any command that
# sends output to /dev/null — including the checks inside this repository.
DEVICES = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty", "/dev/zero", "/dev/fd"}
# `git` subcommands that overwrite working-tree files from another ref.
GIT_OVERWRITES = {"checkout", "restore"}
GIT_GLOBAL_WITH_VALUE = {"-c", "-C", "--git-dir", "--work-tree", "--namespace"}


def project_root() -> Path:
    """The directory this hook is protecting, from the environment Claude Code provides."""
    given = os.environ.get("CLAUDE_PROJECT_DIR")
    if given:
        return Path(given).resolve()
    return Path(__file__).resolve().parents[2]


def resolve(target: str, cwd: Path) -> Path:
    expanded = os.path.expanduser(target)
    path = Path(expanded)
    if not path.is_absolute():
        path = cwd / path
    # No resolve(strict=...) — the target need not exist yet, and a symlink is followed on
    # purpose: a link pointing out of the project is exactly the escape this closes.
    return Path(os.path.normpath(str(path.expanduser()))).resolve(strict=False)


def inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def git_overwrite_targets(words: list[str]) -> list[str]:
    """Paths a `git checkout`/`git restore` may overwrite. Judged against `.claude/` only.

    A branch name or an option's value read as a path is harmless here — it would have to
    resolve inside `.claude/` to matter, and git refuses a ref name with a component starting
    with a dot — so every non-option token is a candidate. Not used for the escape check:
    `git -C` moves git's directory without a `cd`, and judging these as escapes would be
    guessing.
    """
    if not words or Path(words[0]).name != "git":
        return []
    index = 1
    while index < len(words) and words[index].startswith("-"):
        index += 2 if words[index] in GIT_GLOBAL_WITH_VALUE else 1
    if index >= len(words) or words[index] not in GIT_OVERWRITES:
        return []
    return [word for word in words[index + 1 :] if not word.startswith("-")]


def write_targets(command) -> list[str]:
    """Paths this command writes: its redirects, then a destructive verb's arguments."""
    targets = [
        target
        for target in command.writes
        if target not in DEVICES and not target.startswith("/dev/fd/")
    ]
    words = command.words
    if not words:
        return targets
    verb = Path(words[0]).name
    arguments = words[1:]
    if verb == "sed":
        # Only `sed -i` writes. `sed -n '1,5p' file` reads.
        if not any(a == "-i" or a.startswith("-i") for a in arguments):
            return targets
    elif verb not in DESTRUCTIVE:
        return targets
    targets.extend(a for a in arguments if not a.startswith("-"))
    return targets


class Findings:
    def __init__(self) -> None:
        self.escaping: list[str] = []
        self.into_policy: list[str] = []
        self.problems: list[str] = []


def judge(line: str, root: Path, cwd: Path, findings: Findings, depth: int = 0) -> None:
    """Judge every command in the line, in order, following each `cd` as it comes."""
    if depth > 5:
        findings.problems.append("command substitutions nested deeper than this hook reads")
        return
    try:
        parsed = _shell.commands(line)
    except ValueError:
        findings.problems.append("the command could not be parsed (unbalanced quotes)")
        return
    policy = root / ".claude"
    for command in parsed:
        words = command.words
        if words and Path(words[0]).name == "cd":
            destination = [a for a in words[1:] if not a.startswith("-")]
            if not destination:
                cwd = Path(os.path.expanduser("~"))
            elif "$" in destination[0] or "`" in destination[0]:
                findings.problems.append(
                    f"`cd {destination[0]}` — this hook will not guess where that lands"
                )
            else:
                cwd = resolve(destination[0], cwd)
            continue
        for target in write_targets(command):
            if "$" in target or "`" in target:
                findings.problems.append(
                    f"`{target}` — this hook will not guess what that expands to"
                )
                continue
            resolved = resolve(target, cwd)
            if not inside(resolved, root):
                findings.escaping.append(f"{target} → {resolved}")
            elif inside(resolved, policy):
                findings.into_policy.append(target)
        for target in git_overwrite_targets(words):
            if inside(resolve(target, cwd), policy):
                findings.into_policy.append(target)
    # A substitution runs where the command around it runs: the directory reached so far.
    for inner in _shell.nested(line, parsed):
        judge(inner, root, cwd, findings, depth + 1)


def decide(command: str, root: Path) -> str | None:
    """The reason this command is refused, or None to allow it."""
    findings = Findings()
    judge(command, root, root, findings)

    if findings.into_policy:
        return (
            "this command changes the agent's own policy from the shell:\n  "
            + "\n  ".join(dict.fromkeys(findings.into_policy))
            + "\nNothing under .claude/ may be changed by a shell command. Its settings files are "
            "the owner's to edit by hand; for anything else there, use the Edit tool, where the "
            "permission system can see the change and ask."
        )
    if findings.escaping:
        return (
            "this command changes something outside the project:\n  "
            + "\n  ".join(findings.escaping)
            + f"\nThe project is {root}. Reading outside it is fine; changing anything is not."
        )
    if findings.problems:
        return (
            "this command cannot be judged safe:\n  "
            + "\n  ".join(dict.fromkeys(findings.problems))
            + "\nA convoluted one-liner is refused on purpose — the remedy is a simpler "
            "command, never a weaker hook. Split it up, or write the path out in full."
        )
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # not a payload this hook understands; another hook will see it too

    command = (payload.get("tool_input") or {}).get("command")
    if not isinstance(command, str) or not command.strip():
        return 0

    if _shell is None:
        sys.stderr.write(
            "BLOCKED by .claude/hooks/confine_to_project.py — its parser (_shell.py, beside it) "
            "could not be imported, so no command can be judged. It fails closed on purpose.\n"
        )
        return 2
    reason = decide(command, project_root())
    if reason:
        sys.stderr.write("BLOCKED by .claude/hooks/confine_to_project.py — " + reason + "\n")
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        # FAILS CLOSED, unlike the other hooks here, and the direction is the decision: what
        # this prevents is unrecoverable, so a bug in it must cost a blocked command rather
        # than an erased directory.
        sys.stderr.write(
            f"BLOCKED by .claude/hooks/confine_to_project.py — the hook itself failed "
            f"({type(exc).__name__}: {exc}). It fails closed on purpose; what it prevents "
            f"cannot be undone. Run the command yourself if it is genuinely safe.\n"
        )
        sys.exit(2)
