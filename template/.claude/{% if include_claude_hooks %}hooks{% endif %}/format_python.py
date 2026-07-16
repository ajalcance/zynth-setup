#!/usr/bin/env python3
"""PostToolUse hook — auto-format backend Python after an Edit/Write.

Ergonomics, NOT a guard: this shifts the `make fmt` / lint gate left so the file
the agent just wrote is already ruff-fixed and black-formatted. CI remains the
source of truth. Fails **open** — a missing venv or a formatter error never
blocks the session (a broken formatter must not brick work).

Contract: reads the PostToolUse JSON envelope on stdin, formats the touched file
in place if it is a ``backend/`` Python file, and always exits 0.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env) if env else Path.cwd()


def _tool(root: Path, name: str) -> str | None:
    """Prefer the backend venv's pinned tool; fall back to PATH; else None."""
    venv = root / "backend" / ".venv" / "bin" / name
    if venv.is_file():
        return str(venv)
    from shutil import which

    return which(name)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # nothing parseable — no-op

    fp = (payload.get("tool_input") or {}).get("file_path")
    if not fp or not fp.endswith(".py"):
        return 0

    root = _repo_root()
    path = Path(fp)
    if not path.is_absolute():
        path = root / path
    try:
        path = path.resolve()
        # Only format files inside backend/ — that is where the venv + pyproject config live.
        path.relative_to((root / "backend").resolve())
    except (ValueError, OSError):
        return 0
    if not path.is_file():
        return 0

    ruff = _tool(root, "ruff")
    black = _tool(root, "black")
    try:
        if ruff:
            subprocess.run([ruff, "check", "--fix", "-q", str(path)], timeout=30, check=False)
        if black:
            subprocess.run([black, "-q", str(path)], timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        pass  # fail open

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — a hook must never crash the session
        sys.exit(0)
