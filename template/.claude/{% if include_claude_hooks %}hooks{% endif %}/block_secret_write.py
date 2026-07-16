#!/usr/bin/env python3
"""PreToolUse hook — block writing secret material to disk.

Mirrors the pre-commit ``detect-private-key`` / gitleaks gate and the repo
``.gitignore`` (``.env``, ``*.pem``, ``*.key``): stop a real ``.env`` or a
private key from ever being written, so it cannot be staged by accident. Only
``.env.example`` (placeholders) is allowed.

Contract: reads the PreToolUse JSON envelope on stdin (Write tool). Exit 2 blocks
and feeds stderr back to the model; exit 0 allows. Fails **open** on internal error.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import PurePath

SECRET_EXTS = {".pem", ".key", ".p12", ".pfx", ".keystore", ".jks"}
SECRET_NAMES = {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".npmrc", ".pypirc"}
PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")


def _reason(file_path: str, content: str) -> str | None:
    name = PurePath(file_path).name
    suffix = PurePath(file_path).suffix.lower()

    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return f"'{name}' is a real env file — only .env.example (placeholders) may be committed."
    if suffix in SECRET_EXTS:
        return f"'{name}' has a secret-material extension ({suffix}) — keys never enter git."
    if name in SECRET_NAMES:
        return f"'{name}' is a credential file — keys/tokens never enter git."
    if isinstance(content, str) and PRIVATE_KEY_RE.search(content):
        return f"the content of '{name}' contains a PRIVATE KEY block."
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tin = payload.get("tool_input") or {}
    file_path = tin.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        return 0

    reason = _reason(file_path, tin.get("content") or "")
    if reason:
        sys.stderr.write(
            "BLOCKED by .claude/hooks/block_secret_write.py — " + reason + "\n"
            "Non-negotiable #1: secrets & keys never enter the repo. Reference an env var, "
            "or add a placeholder to .env.example instead.\n"
        )
        return 2

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — fail open: never halt every Write on a hook bug
        sys.exit(0)
