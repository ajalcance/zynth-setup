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
# No default, and deliberately not the owner's: each self-test run names its own project.
PER_RUN = ("project_name",)
# The owner's answers for every self-test generation. See the file for why it is one file.
SELF_TEST_ANSWERS = ROOT / ".github" / "self-test-owner.yml"


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

    # The population, not the list: a question with no default that is neither owner tier nor
    # per-run is one nothing answers — every `copier copy --defaults` in the self-test dies on
    # it, and the step that dies may be one that only runs once the next release is tagged.
    for name, question in config.items():
        if name.startswith("_") or not isinstance(question, dict) or "default" in question:
            continue
        if name not in OWNER_TIER and name not in PER_RUN:
            errors.append(f"{name}: no default, but not in OWNER_TIER — nothing answers it")

    answers = yaml.safe_load(SELF_TEST_ANSWERS.read_text()) if SELF_TEST_ANSWERS.is_file() else None
    if not isinstance(answers, dict):
        errors.append(f"{SELF_TEST_ANSWERS.relative_to(ROOT)}: missing or not a mapping")
    elif set(answers) != set(OWNER_TIER):
        errors.append(
            f"{SELF_TEST_ANSWERS.relative_to(ROOT)} must answer exactly the owner tier: "
            f"missing {sorted(set(OWNER_TIER) - set(answers))}, "
            f"extra {sorted(set(answers) - set(OWNER_TIER))}"
        )

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
