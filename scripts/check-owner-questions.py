#!/usr/bin/env python3
"""The owner tier of copier.yml has no defaults, refuses empty answers, and is announced.

An AI agent generates with `--defaults`; a question with a default is a question nobody
answers. This reads copier.yml — not a copy of its contents — and fails if an owner-tier
question grew a default back, lost its validator, or dropped out of the message that tells
the agent what to ask. Run by the template self-test before any project is generated.
"""

from __future__ import annotations

import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
OWNER_TIER = ("github_owner", "author_name", "author_email", "license", "solo_maintainer")
CONDITIONAL = {"server_host": "include_deploy"}  # asked only with the module; then required


def main() -> int:
    config = yaml.safe_load((ROOT / "copier.yml").read_text())
    before = config.get("_message_before_copy", "")
    errors: list[str] = []
    checked = 0

    for name in OWNER_TIER:
        question = config.get(name)
        checked += 1
        if question is None:
            errors.append(f"{name}: not a question in copier.yml")
            continue
        if "default" in question:
            errors.append(f"{name}: has a default ({question['default']!r}) — --defaults would answer it for the owner")
        # A bool has no empty form, and `choices` refuse anything outside the list.
        if question.get("type") != "bool" and "choices" not in question and "validator" not in question:
            errors.append(f"{name}: no validator — an explicit empty answer would pass")
        if name not in before:
            errors.append(f"{name}: not named in _message_before_copy — the agent is not told to ask")

    for name, gate in CONDITIONAL.items():
        question = config.get(name, {})
        checked += 1
        validator = question.get("validator", "")
        if gate not in validator or name not in validator:
            errors.append(f"{name}: validator must refuse an empty answer when {gate} is on")
        if name not in before:
            errors.append(f"{name}: not named in _message_before_copy")

    print(f"owner-questions: inspected {checked} owner-tier question(s) in copier.yml")
    if errors:
        print("owner-questions: FAILED")
        for e in errors:
            print(f"  x {e}")
        return 1
    print("owner-questions: OK — no defaults, validators present, every one announced to the agent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
