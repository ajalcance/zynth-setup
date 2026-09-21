#!/usr/bin/env python3
"""PreToolUse hook — approval at the unit of work, not the keystroke.

**Precedence in Claude Code is deny → ask → allow, and a hook's `allow` is one more allow. It
loses to any static `ask` rule matching the same path.** This cost a full day: a scope hook
that returned `allow` correctly, verified by hand, with a hundred passing assertions, waived
nothing at all for an entire day while three documents described it as live. Its tests ran the
hook directly and asserted its verdict; nothing exercised the path from a real tool call,
through the permission system, to a silent edit. A control tested at the point it is easiest
to test rather than the point it has to hold.

So the design is inverted: **this hook does the asking.** For the core paths a scope may
cover there is no static `ask` rule at all — this returns `ask` unless an active scope covers
the path. Two consequences follow, and both are deliberate:

1. **Its failure direction is inverted from every other hook here.** It is now the only thing
   asking about those paths, so every error must become `ask`. The blanket `except` at the
   bottom is required, not sloppy.
2. **`.claude/settings.json`, `.claude/hooks/` and the scope file itself keep their static
   rules, and this hook says nothing about them.** Widening the agent's own authority is
   guarded by a mechanism that does not depend on the agent's code being correct.

Why a scope at all: per-file prompts are the right shape for an unplanned edit to a guard and
the wrong shape for an approved programme of work. Approving a thousand prompts is not
approving anything. A scope moves the approval to the same unit as the plan — it names the
work, cites the decision it serves, gives a reason, lists its paths and expires — and the
owner approves that one file, once.

It is STRICTER than what it replaces, which is the argument worth keeping:

* the approval is written down and citable, so an auditor can read what was agreed;
* it is narrower than a blanket rule covering every core path for every change;
* it expires, so an approval nobody renews lapses on its own;
* no scope can ever waive the agent's own permission policy;
* a broad pattern never reaches a system-altering area. Migrations, auth, the audit ledger,
  deploy, the workflows, the rulesets and the scanner config are covered only by a pattern
  that NAMES them — so `backend/**` pre-approves module work and stops at the migrations
  folder. Pre-approving something dangerous is allowed and has to be said out loud.
* a scope that is malformed, uncited, unbounded or expired waives nothing, and the prompts
  return.

Nothing downstream moves: the meta-guard still demands the owner's label on the pull request,
and the gates and CI are untouched. A scope buys silence at the keystroke, never at the gate.

Choose the failure direction before writing the control. Every way of being sloppy with a
scope produces MORE asking, and a permission mechanism whose bugs produce more asking is one
you can afford to be wrong about.

Contract: reads the PreToolUse JSON envelope on stdin, writes a permission decision as JSON on
stdout, and always exits 0.
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import json
import os
import sys
from pathlib import Path, PurePosixPath

SCOPE_FILE = PurePosixPath(".claude/approved-scope.json")

# Paths this hook asks about. There must be NO static `ask` rule for these in settings.json —
# if there were, it would outrank every allow this hook returns and the scope would waive
# nothing, silently.
CORE = (
    ".github/**",
    "scripts/**",
    "tests/guards/**",
    ".semgrep/**",
    ".gitleaks.toml",
    ".pre-commit-config.yaml",
    "Makefile",
    "ruff-harness.toml",
    "requirements-ci.txt",
    "CLAUDE.md",
    "AGENTS.md",
    "deploy/**",
    "docs/decisions/**",
    "experience/registry.toml",
    "backend/migrations/**",
    "backend/*/auth/**",
    "backend/*/command/audit.py",
)

# Reachable only by a pattern that NAMES them. A broad `backend/**` pre-approves module work
# and stops here. These are the same paths the meta-guard demands a label for on the pull
# request — the two lists are reconciled by a test, because they had never been diffed and
# eighteen paths needed a label while raising no prompt at all.
SYSTEM_ALTERING = (
    "backend/migrations/**",
    "backend/*/auth/**",
    "backend/*/command/audit.py",
    "deploy/**",
    ".github/workflows/**",
    ".github/rulesets/**",
    ".semgrep/**",
    ".gitleaks.toml",
    "requirements-ci.txt",
    "experience/registry.toml",
)

# No scope may ever reach these, by any pattern. This hook says nothing about them at all, so
# their static rules in settings.json are what applies.
NEVER_WAIVABLE = (".claude/**",)

WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
MAX_HORIZON_DAYS = 45
MIN_REASON_CHARS = 20


def _emit(decision: str, reason: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )
    sys.stdout.write("\n")


def _project() -> Path:
    given = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(given).resolve() if given else Path(__file__).resolve().parents[2]


def relative(file_path: str, root: Path) -> PurePosixPath | None:
    try:
        resolved = Path(file_path).expanduser().resolve(strict=False)
        return PurePosixPath(resolved.relative_to(root).as_posix())
    except (ValueError, OSError):
        return None  # outside the project; the confinement hook owns that question


def matches(path: PurePosixPath, pattern: str) -> bool:
    """Glob match where `**` means "here and everything under here".

    fnmatch's `*` already crosses `/`, so `<base>/*` covers any depth. A literal prefix
    comparison would be wrong the moment the pattern itself contains a wildcard —
    `backend/*/auth/**` is exactly that shape, and it is one of the system-altering paths.
    """
    text = path.as_posix()
    if pattern == "**":
        return True
    if pattern.endswith("/**"):
        base = pattern[:-3]
        return fnmatch.fnmatch(text, base) or fnmatch.fnmatch(text, f"{base}/*")
    return fnmatch.fnmatch(text, pattern)


def names_explicitly(pattern: str, path: PurePosixPath) -> bool:
    """A pattern reaches a system-altering path only by naming it, never by breadth.

    `backend/migrations/**` names the migrations folder. `backend/**` does not, even though
    fnmatch says it matches — that is the whole distinction.
    """
    if not matches(path, pattern):
        return False
    return any(
        pattern == guarded or pattern.startswith(guarded.rstrip("*").rstrip("/") + "/")
        for guarded in SYSTEM_ALTERING
        if matches(path, guarded)
    )


def load_scopes(root: Path, today: dt.date) -> tuple[list[dict], list[str]]:
    """(usable scopes, why each unusable one waives nothing)."""
    path = root / SCOPE_FILE
    if not path.is_file():
        return [], []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        declared = document["scopes"]
        assert isinstance(declared, list)
    except Exception as exc:  # noqa: BLE001 — malformed waives nothing; see the module docstring
        return [], [f"{SCOPE_FILE} could not be read ({type(exc).__name__}: {exc})"]

    usable: list[dict] = []
    rejected: list[str] = []
    for index, scope in enumerate(declared):
        name = (
            (scope or {}).get("name", f"scope #{index + 1}")
            if isinstance(scope, dict)
            else f"scope #{index + 1}"
        )
        problem = _why_unusable(scope, today)
        if problem:
            rejected.append(f"{name}: {problem}")
        else:
            usable.append(scope)
    return usable, rejected


def _why_unusable(scope: object, today: dt.date) -> str | None:
    if not isinstance(scope, dict):
        return "is not an object"
    for field in ("name", "cites", "reason", "paths", "expires"):
        if not scope.get(field):
            return f"declares no '{field}' — an approval nobody can read back is not one"
    if not isinstance(scope["paths"], list) or any(not isinstance(p, str) for p in scope["paths"]):
        return "'paths' must be a list of patterns"
    if len(str(scope["reason"])) < MIN_REASON_CHARS:
        return "gives no real reason — say what this work is, so an auditor can disagree"
    try:
        expires = dt.date.fromisoformat(str(scope["expires"]))
    except ValueError:
        return f"'expires' is not a date ({scope['expires']!r})"
    if expires < today:
        return f"expired on {expires.isoformat()} — renew it deliberately or let it lapse"
    if (expires - today).days > MAX_HORIZON_DAYS:
        return (
            f"expires in {(expires - today).days} days, beyond the {MAX_HORIZON_DAYS}-day "
            f"horizon — an approval that never lapses is a permanent widening"
        )
    return None


def covering(path: PurePosixPath, scopes: list[dict]) -> dict | None:
    guarded = any(matches(path, pattern) for pattern in SYSTEM_ALTERING)
    for scope in scopes:
        for pattern in scope["paths"]:
            if guarded:
                if names_explicitly(pattern, path):
                    return scope
            elif matches(path, pattern):
                return scope
    return None


def decide(payload: dict, root: Path, today: dt.date) -> tuple[str, str] | None:
    """(decision, reason), or None to say nothing and let the static rules apply."""
    if payload.get("tool_name") not in WRITE_TOOLS:
        return None
    file_path = (payload.get("tool_input") or {}).get("file_path")
    if not isinstance(file_path, str) or not file_path:
        return None
    path = relative(file_path, root)
    if path is None:
        return None

    # This hook is silent about the agent's own authority. Those paths keep static rules, so
    # widening them does not depend on this code being correct.
    if any(matches(path, pattern) for pattern in NEVER_WAIVABLE) or path == SCOPE_FILE:
        return None

    if not any(matches(path, pattern) for pattern in CORE):
        return None  # ordinary module work: no prompt, as before

    scopes, rejected = load_scopes(root, today)
    scope = covering(path, scopes)
    if scope:
        return (
            "allow",
            f"covered by the approved scope {scope['name']!r} (cites {scope['cites']}, "
            f"expires {scope['expires']}).",
        )

    detail = ""
    if rejected:
        detail = " Scope(s) that waive nothing right now: " + "; ".join(rejected) + "."
    if any(matches(path, pattern) for pattern in SYSTEM_ALTERING):
        return (
            "ask",
            f"{path} is a system-altering path. A scope reaches it only by naming it — a broad "
            f"pattern never does. Pre-approving one is allowed and has to be said out loud."
            + detail,
        )
    return (
        "ask",
        f"{path} is a core path and no active scope covers it. Approve this edit, or add a "
        f"scope to {SCOPE_FILE} naming the work, citing the decision it serves, and expiring."
        + detail,
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        verdict = decide(payload, _project(), dt.date.today())
    except Exception as exc:  # noqa: BLE001
        # REQUIRED, not sloppy. This hook is the only thing asking about the core paths, so a
        # bug in it must produce a prompt rather than a silent edit. Every way of being wrong
        # here asks more, which is what makes the mechanism affordable.
        _emit(
            "ask",
            f"{SCOPE_FILE} could not be evaluated ({type(exc).__name__}), so this edit is "
            f"treated as unapproved core.",
        )
        return 0
    if verdict is not None:
        _emit(*verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
