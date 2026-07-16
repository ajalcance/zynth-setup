#!/usr/bin/env python3
"""PreToolUse hook — block obvious Bash footguns before they run.

Ergonomics that mirror the **branch ruleset** (server-side is the real gate):
this catches the accidental self-inflicted commands an agent should never issue,
with a message pointing at the safe path. Narrow by design — it only blocks
clearly-destructive / gate-bypassing patterns to avoid false positives.

Contract: reads the PreToolUse JSON envelope on stdin. Exit 2 blocks the tool
call and feeds stderr back to the model; exit 0 allows. Fails **open** on an
internal error (a broken hook must not halt every Bash call).
"""

from __future__ import annotations

import json
import re
import sys

# (compiled pattern, human reason). Kept deliberately narrow.
RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\bgit\s+push\b(?=.*\b(?:--force|--force-with-lease|-f)\b)(?=.*\b(?:main|master)\b)"),
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
        re.compile(r"\brm\s+(?:-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r|-r\s+-f|-f\s+-r)\b"
                   r".*(?:\s/(?:\s|$)|\s~(?:/|\s|$)|\$HOME|\s\*(?:\s|$)|\s\.(?:\s|$))"),
        "recursive force-delete targeting a dangerous root (/, ~, $HOME, ., *).",
    ),
    (
        re.compile(r"\bgit\s+config\b.*\bcore\.hooksPath\b"),
        "changing core.hooksPath disables the repo's pre-commit hooks.",
    ),
]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    command = (payload.get("tool_input") or {}).get("command")
    if not isinstance(command, str) or not command:
        return 0

    for pattern, reason in RULES:
        if pattern.search(command):
            sys.stderr.write(
                "BLOCKED by .claude/hooks/block_dangerous_bash.py — " + reason + "\n"
                "This is a local guardrail; the branch ruleset enforces it server-side too.\n"
                "If this is genuinely intended, run it yourself outside the agent session.\n"
            )
            return 2

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — fail open: never halt every Bash call on a hook bug
        sys.exit(0)
