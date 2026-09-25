"""A command line as the shell reads it — shared by the Bash hooks, so they parse it one way.

Not a hook: nothing registers it, and it decides nothing. Both Bash hooks used to read the raw
line with regexes and a naive split, and both were wrong in the same two directions:

* **False positives on ordinary reads.** The confinement hook split on `|` and `;` before it
  parsed quotes, so `grep -n "a\\|b" f`, `"$(x | y)"` and `--format='%h|%s'` were refused as
  "unbalanced quotes". The dangerous-command hook ran each rule over the whole line, so
  `rm -rf build && copier copy . dest` was a recursive delete of `.`, and a PR title containing
  the word "main" was a push to main.
* **Missed changes.** `echo "$(rm -rf ~/x)"` was judged as `echo`; `nice rm -rf ~/x` as `nice`;
  and a `cd` anywhere in the line moved EVERY command to the final directory — so
  `rm -rf build && cd /tmp` was judged as deleting /tmp/build.

So: tokens come from shlex with shell punctuation, which respects quotes; a redirect is a
redirect only when it is unquoted; commands are kept in order, so a `cd` affects only what
follows it; wrappers and leading assignments are peeled off; and command lines hidden inside a
token — `$(...)`, backticks, `sh -c "..."`, `eval ...` — are returned for the caller to judge
like any other.

A line shlex cannot read raises ValueError. Each hook decides what that means: the confinement
hook refuses, the dangerous-command hook falls back to its raw-line rules and asks.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field

SEPARATORS = {";", "&", "&&", "|", "||", "(", ")", "|&", ";;"}
REDIRECTS = {">", ">>", "<", ">&", "&>", "<&", "<>", ">|", "&>>"}
# The redirects that write the file named after them. `<` reads; `>&2` names a descriptor.
WRITING = {">", ">>", "&>", ">|", "&>>", ">&"}
WRAPPERS = {"command", "builtin", "exec", "nohup", "time", "nice"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
BACKTICKS = re.compile(r"`([^`]*)`")
DESCRIPTOR = re.compile(r"^(?:\d+|-)$")


@dataclass
class Command:
    """One simple command: its words, and the files its redirects write."""

    tokens: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)

    @property
    def words(self) -> list[str]:
        """The command itself: leading `NAME=value`, wrappers and `env` peeled off."""
        words = list(self.tokens)
        while words and (ENV_ASSIGNMENT.match(words[0]) or words[0] in WRAPPERS):
            words = words[1:]
        if words and words[0] == "env":
            words = words[1:]
            while words and (words[0].startswith("-") or ENV_ASSIGNMENT.match(words[0])):
                words = words[1:]
        return words

    @property
    def program(self) -> str:
        words = self.words
        return os.path.basename(words[0]) if words else ""


def strip_heredocs(command: str) -> str:
    """A heredoc body is data. Prose that mentions a command is not a command."""
    lines = command.splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        out.append(line)
        index += 1
        match = HEREDOC.search(line)
        if not match:
            continue
        while index < len(lines) and lines[index].strip() != match.group(2):
            index += 1
        index += 1
    return "\n".join(out)


def commands(line: str) -> list[Command]:
    """Every simple command in the line, in order. Raises ValueError if shlex cannot read it."""
    text = strip_heredocs(line).replace("\\\n", " ").replace("\n", " ; ")
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    tokens = list(lexer)
    result: list[Command] = [Command()]
    index = 0
    while index < len(tokens):
        token = tokens[index]
        current = result[-1]
        if token in SEPARATORS:
            result.append(Command())
        elif token in REDIRECTS:
            # A descriptor number written against the operator (`2>`) arrives as its own token.
            if current.tokens and len(current.tokens[-1]) == 1 and current.tokens[-1].isdigit():
                current.tokens.pop()
            target = tokens[index + 1] if index + 1 < len(tokens) else ""
            if target and target != "(":
                index += 1
                if token in WRITING and not DESCRIPTOR.match(target):
                    current.writes.append(target)
        elif token != "$":  # the `$` of `$(`: the parenthesis that follows is a separator
            current.tokens.append(token)
        index += 1
    return [command for command in result if command.tokens or command.writes]


def nested(line: str, parsed: list[Command]) -> list[str]:
    """Command lines hiding inside the line: `$(...)` in a token, backticks, `sh -c`, `eval`.

    shlex keeps `"$(rm -rf ~/x)"` as ONE token of `echo` — without this, what runs inside a
    quoted substitution is never seen. Backticks are read from the raw line, because unquoted
    their body is split across tokens.
    """
    inner: list[str] = list(BACKTICKS.findall(strip_heredocs(line)))
    for command in parsed:
        for token in command.tokens:
            start = token.find("$(")
            while start != -1:
                depth, index = 0, start + 1
                while index < len(token):
                    depth += {"(": 1, ")": -1}.get(token[index], 0)
                    if depth == 0:
                        break
                    index += 1
                inner.append(token[start + 2 : index])
                start = token.find("$(", start + 2)
        words = command.words
        if words and os.path.basename(words[0]) in SHELLS and "-c" in words[1:-1]:
            inner.append(words[words.index("-c", 1) + 1])
        if words and words[0] == "eval":
            inner.append(" ".join(words[1:]))
    return inner
