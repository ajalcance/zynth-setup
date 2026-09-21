#!/usr/bin/env python3
"""PreToolUse hook — a change may not reach outside this project.

Permission rules cannot express this. Precedence is deny → ask → allow and the patterns are
globs, so "everything except this folder" is not writable as a rule: any deny broad enough to
protect the rest of the machine also blocks the project itself. The dangerous-command hook
beside this one names `/`, `~` and `$HOME`, which leaves every sibling project directory fair
game — and an agent that changes directory first issues no single token that looks dangerous.

So this resolves first and decides second. It expands `~`, `..`, and any `cd` earlier in the
same command line before asking whether a target is inside the project.

Three design decisions worth keeping:

* **Only CHANGES are confined, never reads.** Reading another project is how an assistant
  learns from one. Deleting it is what must be impossible.
* **A redirect overwrites whatever the verb is.** `echo x > ~/.zshrc` contains no destructive
  verb at all, so redirects are checked ahead of the verb gate. Devices (`/dev/null`,
  `/dev/stderr`) are exempt, or this hook blocks its own mutation check.
* **Prefer a false positive on a convoluted one-liner to a false negative.** This refuses to
  guess what a variable expands to. The remedy is a simpler command, never a weaker hook.

Contract: reads the PreToolUse JSON envelope on stdin. Exit 2 blocks and feeds stderr back to
the model; exit 0 allows. Fails **closed** on a command it cannot parse — unlike its siblings,
because the thing it prevents is unrecoverable.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

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
REDIRECT_RE = re.compile(r"(?:\d?>>?|&>)\s*([^\s;|&]+)")
ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# A heredoc body is DATA. Prose that mentions a command is not a command — writing a lessons
# entry that quotes a path must not be read as touching that path.
HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
SEPARATORS = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")


def project_root() -> Path:
    """The directory this hook is protecting, from the environment Claude Code provides."""
    given = os.environ.get("CLAUDE_PROJECT_DIR")
    if given:
        return Path(given).resolve()
    return Path(__file__).resolve().parents[2]


def strip_heredocs(command: str) -> str:
    """Remove heredoc bodies, keeping the line that opens them."""
    lines = command.splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        out.append(line)
        match = HEREDOC_RE.search(line)
        index += 1
        if not match:
            continue
        terminator = match.group(2)
        while index < len(lines) and lines[index].strip() != terminator:
            index += 1
        index += 1  # skip the terminator itself
    return "\n".join(out)


def split_tokens(segment: str) -> list[str] | None:
    try:
        return shlex.split(segment)
    except ValueError:
        return None  # unbalanced quoting — see the fail-closed note in main()


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


def write_targets(segment: str) -> tuple[list[str], list[str]]:
    """(paths this segment writes, reasons it cannot be judged)."""
    targets: list[str] = []
    unresolvable: list[str] = []

    # Redirects first: they overwrite regardless of the verb in front of them.
    for redirect in REDIRECT_RE.findall(segment):
        cleaned = redirect.strip("\"'")
        if cleaned in DEVICES or cleaned.startswith("/dev/fd/") or cleaned.startswith("&"):
            continue
        targets.append(cleaned)

    tokens = split_tokens(REDIRECT_RE.sub(" ", segment))
    if tokens is None:
        return targets, ["the command could not be parsed (unbalanced quotes)"]

    # A leading `NAME=value` is a variable for the command, not a path it writes.
    # `PATH=/opt/bin make` says where to FIND programs; nearly every command carries one.
    while tokens and ENV_ASSIGNMENT_RE.match(tokens[0]):
        tokens.pop(0)
    if not tokens:
        return targets, unresolvable

    verb = Path(tokens[0]).name
    arguments = tokens[1:]
    if verb == "sed":
        # Only `sed -i` writes. `sed -n '1,5p' file` reads.
        if not any(a == "-i" or a.startswith("-i") for a in arguments):
            return targets, unresolvable
    elif verb not in DESTRUCTIVE:
        return targets, unresolvable

    targets.extend(a for a in arguments if not a.startswith("-"))
    return targets, unresolvable


def effective_cwd(segments: list[str], root: Path) -> tuple[Path, list[str]]:
    """Follow `cd` so a change made after one is judged where it actually lands."""
    cwd = root
    problems: list[str] = []
    for segment in segments:
        tokens = split_tokens(segment)
        # Parsed with shlex, not a whitespace regex: this machine's project path contains a
        # space, and a pattern that stops at whitespace hands back the first word — an
        # ancestor of the project, and therefore "outside" it. An older version of this hook
        # used shlex for exactly this reason and a rewrite lost it.
        if not tokens or Path(tokens[0]).name != "cd":
            continue
        destination = [a for a in tokens[1:] if not a.startswith("-")]
        if not destination:
            cwd = Path(os.path.expanduser("~"))
            continue
        if "$" in destination[0] or "`" in destination[0]:
            problems.append(f"`cd {destination[0]}` — this hook will not guess where that lands")
            continue
        cwd = resolve(destination[0], cwd)
    return cwd, problems


def decide(command: str, root: Path) -> str | None:
    """The reason this command is refused, or None to allow it."""
    segments = [s for s in SEPARATORS.split(strip_heredocs(command)) if s.strip()]
    cwd, problems = effective_cwd(segments, root)

    escaping: list[str] = []
    for segment in segments:
        targets, unresolvable = write_targets(segment)
        problems.extend(unresolvable)
        for target in targets:
            if "$" in target or "`" in target:
                problems.append(f"`{target}` — this hook will not guess what that expands to")
                continue
            resolved = resolve(target, cwd)
            if not inside(resolved, root):
                escaping.append(f"{target} → {resolved}")

    if escaping:
        return (
            "this command changes something outside the project:\n  "
            + "\n  ".join(escaping)
            + f"\nThe project is {root}. Reading outside it is fine; changing anything is not."
        )
    if problems:
        return (
            "this command cannot be judged safe:\n  "
            + "\n  ".join(dict.fromkeys(problems))
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
