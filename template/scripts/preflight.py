#!/usr/bin/env python3
"""Environment preflight: verify the toolchain `make check` needs is actually installed.

Post-generation setup is best-effort — it must not hard-fail an offline generation — so an
install can be skipped and the project still be created. Without this check the next thing the
adopter sees is `sh: eslint: command not found` from deep inside a Makefile target, which says
nothing about the cause or the fix.

This turns that into a named problem with the exact command to run. It is a *diagnostic*, not
a guardrail: it reports what is missing, it does not install anything.

Run: ``python3 scripts/preflight.py`` (or ``make preflight``; ``make check`` runs it first).
Exit code is non-zero if anything required is missing.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_TOOLS = ("ruff", "black", "mypy", "pytest")


def _node_major() -> str | None:
    try:
        out = subprocess.run(
            ["node", "--version"], capture_output=True, text=True, timeout=10, check=False
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return out.lstrip("v").split(".")[0] or None


def _check_backend(problems: list[tuple[str, str]]) -> None:
    venv = ROOT / "backend" / ".venv"
    if not venv.is_dir():
        problems.append(
            (
                "backend/.venv is missing (the Python toolchain is not installed)",
                "cd backend && python3 -m venv .venv && "
                ".venv/bin/pip install -r requirements.txt -r requirements-dev.txt",
            )
        )
        return
    missing = [t for t in BACKEND_TOOLS if not (venv / "bin" / t).exists()]
    if missing:
        problems.append(
            (
                f"backend/.venv exists but is incomplete (missing: {', '.join(missing)})",
                "cd backend && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt",
            )
        )


def _check_node(problems: list[tuple[str, str]]) -> None:
    modules = [m for m in ("frontend", "docs-site") if (ROOT / m).is_dir()]
    if not modules:
        return  # no JS module enabled — nothing to check

    for module in modules:
        if not (ROOT / module / "node_modules").is_dir():
            problems.append(
                (
                    f"{module}/node_modules is missing (its gate cannot run)",
                    f"cd {module} && npm ci",
                )
            )

    if shutil.which("node") is None:
        problems.append(("node is not on PATH", "install Node — see .nvmrc for the version"))
        return

    nvmrc = ROOT / ".nvmrc"
    want = nvmrc.read_text().strip().lstrip("v") if nvmrc.is_file() else ""
    have = _node_major()
    if want and have and have != want:
        problems.append(
            (
                f"node v{have} is installed but this project targets v{want} (.nvmrc) — "
                "other majors are known to fail lint/build here",
                f"nvm use {want}   # or the fnm/asdf equivalent",
            )
        )


def main() -> int:
    problems: list[tuple[str, str]] = []
    _check_backend(problems)
    _check_node(problems)

    if problems:
        print("preflight: FAILED — the environment is incomplete\n")
        for what, how in problems:
            print(f"  x {what}")
            print(f"      fix: {how}\n")
        print(
            f"{len(problems)} problem(s). Post-generation setup is best-effort (so an offline\n"
            "generation still produces a project), which means a skipped install surfaces here\n"
            "rather than as a confusing error from inside `make check`."
        )
        return 1

    print("preflight: OK — the toolchain `make check` needs is installed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
