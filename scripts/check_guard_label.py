#!/usr/bin/env python3
"""A pull request that changes a guard needs the owner's `guardrail-change` label.

The template ships this rule to every adopter (template/scripts/meta_guard.py). Here the
product IS the guards, so the rule covers two populations:

* **What judges this repository** — the root gate, workflows, hooks, agent policy and pins,
  listed in ROOT_GUARDS below.
* **What judges every adopter** — any file under template/ that, once rendered, the template's
  own meta-guard would call a guard file. Its GUARD_FILE_RE is imported, not copied, so the two
  definitions cannot drift. (Until 2026-09-26 this file added three paths the template's
  definition missed — `.claude/`, `tests/guards/`, `Makefile`. Backlog T8 put them in the
  template's own GUARD_FILE_RE, where adopters get them too, and the copy here was removed.)

The label is applied by the owner. The agent's session hook refuses applying it
(.claude/hooks/block_dangerous_bash.py), and CI checks the label is present — not who applied
it, which is why the hook matters.

Usage:  GUARDRAIL_LABEL=true|false python3 scripts/check_guard_label.py --base origin/main
Exit 0: no guard touched, or labelled. 1: a guard touched without the label. 2: refused —
the base cannot be resolved or the diff is empty, and "could not check" is never "clean".
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ROOT_GUARDS = re.compile(
    r"^\.claude/"
    r"|^\.github/"
    r"|^scripts/"
    r"|^tests/"
    r"|^Makefile$"
    r"|^requirements-selftest\.txt$"
    r"|^\.pre-commit-config\.yaml$"
    r"|^\.gitleaks\.toml$"
    r"|^\.gitleaksignore$"
    # The owner tier and its validators live here: a question that regains a default lets an
    # agent answer for the owner.
    r"|^copier\.yml$"
)

CONDITIONAL = re.compile(r"\{%\s*if[^%]*%\}(.*?)\{%\s*endif\s*%\}")


def template_guard_re() -> re.Pattern[str]:
    path = ROOT / "template" / "scripts" / "meta_guard.py"
    spec = importlib.util.spec_from_file_location("template_meta_guard", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.GUARD_FILE_RE


def rendered(template_path: str) -> str:
    """template/<path> as copier writes it: conditionals resolved on, `.jinja` dropped."""
    path = CONDITIONAL.sub(r"\1", template_path)
    return path[: -len(".jinja")] if path.endswith(".jinja") else path


def guard_files(changed: list[str]) -> list[str]:
    template_re = template_guard_re()
    guards = []
    for name in changed:
        if name.startswith("template/"):
            inner = rendered(name[len("template/") :])
            if template_re.match(inner):
                guards.append(name)
        elif ROOT_GUARDS.match(name):
            guards.append(name)
    return guards


def changed_files(base: str) -> list[str]:
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        raise LookupError(f"base {base!r} does not resolve to a commit — fetch it")
    diff = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in diff.stdout.splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", required=True)
    args = parser.parse_args()
    labelled = os.environ.get("GUARDRAIL_LABEL", "").lower() == "true"

    try:
        changed = changed_files(args.base)
    except LookupError as exc:
        print(f"guard-label: REFUSED — {exc}")
        return 2
    if not changed:
        print(f"guard-label: REFUSED — {args.base}...HEAD changes no files; nothing was checked")
        return 2

    try:
        guards = guard_files(changed)
    except Exception as exc:  # noqa: BLE001 — any failure to read the definition is a refusal
        print(
            f"guard-label: REFUSED — the template meta-guard's GUARD_FILE_RE could not be read "
            f"({type(exc).__name__}: {exc}). Nothing was classified."
        )
        return 2
    print(f"guard-label: {len(guards)} of {len(changed)} changed file(s) are guards")
    if not guards:
        print("guard-label: OK — no guard changed")
        return 0
    if labelled:
        print("guard-label: OK — guards changed, and the owner's guardrail-change label is on")
        return 0
    print("guard-label: FAILED — these guard files changed without the owner's label:")
    for name in guards:
        print(f"  x {name}")
    print(
        "A guard change is its own PR, on its own merits. Once the owner has reviewed it, "
        "they apply `guardrail-change` — never the agent."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
