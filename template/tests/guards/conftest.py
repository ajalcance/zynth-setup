"""Shared helpers for the guard fault tests.

These tests execute the **real scripts that ship in `scripts/`** — never a reimplementation of
their logic. A test of a copy proves nothing about the guard that actually gates CI.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"


def run(
    cmd: list[str], cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    # `env` is merged over the real environment, never replacing it: a guard that shells out to
    # git or python must keep finding them. Used to put a stub tool earlier on PATH.
    merged = {**os.environ, **env} if env else None
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, check=False, timeout=120, env=merged
    )


def run_guard(
    script: Path, *args: str, cwd: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a guard script and return the completed process (never raises on failure)."""
    return run([sys.executable, str(script), *args], cwd or script.resolve().parents[1], env)


def install_guard(sandbox: Path, name: str) -> Path:
    """Copy a real guard into a sandbox repo so its ROOT resolves to that sandbox.

    Guards compute ``ROOT = Path(__file__).resolve().parents[1]``, so placing the script at
    ``<sandbox>/scripts/<name>`` makes it scan the sandbox instead of this repository.
    """
    scripts = sandbox / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    dest = scripts / name
    shutil.copy2(SCRIPTS / name, dest)
    return dest


def app_package() -> str:
    """The backend package name baked into dod-check.py when the project was generated."""
    match = re.search(r'^APP_PKG = "([^"]+)"', (SCRIPTS / "dod-check.py").read_text(), re.M)
    assert match, "APP_PKG constant not found in scripts/dod-check.py"
    return match.group(1)


def git_init(path: Path) -> None:
    """Initialise a hermetic git repo — no user config, no signing, no hooks."""
    run(["git", "init", "-q", "-b", "main"], path)
    run(["git", "config", "user.email", "guard-tests@example.com"], path)
    run(["git", "config", "user.name", "Guard Tests"], path)
    run(["git", "config", "commit.gpgsign", "false"], path)


def git_commit(path: Path, message: str) -> None:
    run(["git", "add", "-A"], path)
    run(["git", "commit", "-q", "--no-verify", "-m", message], path)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
