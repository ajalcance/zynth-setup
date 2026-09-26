"""Three lists answer one question — "which paths need a human?" — in two files.

`SYSTEM_ALTERING` in the scope hook, and `SENSITIVE_PATH_RE` / `GUARD_FILE_RE` in the
meta-guard. Diffing two lists a project already maintains found a real gap five separate times
in three days, and nobody was doing it. Eighteen paths once needed the owner's label on a pull
request while raising no keystroke prompt at all.

**The caveat that makes this test worth writing carefully.** A first attempt drew its sample
from the same regexes it was reconciling, so the sample could only contain paths at least one
list already matched — a path in NEITHER was unreachable by construction, which is how the
scanner manifests survived it. Reconciling lists against each other is not the same as
reconciling them against the population they are meant to cover. So the population below is
written out by hand, from what the repository actually contains.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import REPO_ROOT

META_GUARD = REPO_ROOT / "scripts" / "meta_guard.py"
SCOPE_HOOK = REPO_ROOT / ".claude" / "hooks" / "approved_scope.py"

# The POPULATION: paths whose change outlives the pull request, enumerated independently of
# any list under test. Add to this when the repository grows a new consequential surface —
# that is the whole point, and it is cheaper than any audit.
CONSEQUENTIAL = (
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    ".github/rulesets/main.json",
    ".github/dependabot.yml",
    ".github/CODEOWNERS",
    ".pre-commit-config.yaml",
    ".gitleaks.toml",
    ".semgrep/dangerous-ops.yml",
    "requirements-ci.txt",
    "scripts/meta_guard.py",
    "scripts/check_pins.py",
    "scripts/check_guard_coverage.py",
    "tests/guards/test_meta_guard.py",
    "docs/decisions/0004-agent-resistant-guardrails.md",
    "experience/registry.toml",
    "Makefile",
    "ruff-harness.toml",
    # The agent's own permission policy. Absent from this population until 2026-09-26, and so
    # absent from the meta-guard too: an agent could widen its own authority with no label.
    ".claude/settings.json",
    ".claude/hooks/block_dangerous_bash.py",
    ".claude/approved-scope.json",
    "backend/migrations/versions/0001_initial.py",
    "deploy/docker-compose.yml",
    "deploy/verify.sh",
)


def _regex(name: str) -> re.Pattern[str]:
    source = META_GUARD.read_text()
    match = re.search(rf"{name} = re\.compile\(\n(.*?)\n\)", source, re.S)
    assert match, f"{name} not found in scripts/meta_guard.py"
    parts = re.findall(r'r"([^"]*)"', match.group(1))
    assert parts, f"{name} has no pattern parts — this assertion would be vacuous"
    return re.compile("".join(parts))


def _scope_tuple(name: str) -> tuple[str, ...]:
    namespace: dict = {}
    source = SCOPE_HOOK.read_text()
    start = source.index(f"{name} = (")
    end = source.index("\n)", start) + 2
    exec(source[start:end], namespace)  # noqa: S102 — our own file, read from disk
    return namespace[name]


def _covered_by_scope_list(path: str, patterns: tuple[str, ...]) -> bool:
    import fnmatch

    for pattern in patterns:
        if pattern == "**":
            return True
        if pattern.endswith("/**"):
            base = pattern[:-3]
            if fnmatch.fnmatch(path, base) or fnmatch.fnmatch(path, f"{base}/*"):
                return True
        elif fnmatch.fnmatch(path, pattern):
            return True
    return False


pytestmark = pytest.mark.skipif(
    not SCOPE_HOOK.is_file(), reason="the Claude Code hooks are not enabled"
)


SETTINGS = Path(REPO_ROOT) / ".claude" / "settings.json"


def _statically_asked(path: str) -> bool:
    """Prompted by a static rule in .claude/settings.json rather than by the scope hook.

    `.claude/` is deliberately outside CORE: no scope may ever waive it, so its prompt comes from
    static `ask`/`deny` rules that do not depend on the agent's own code being correct.
    """
    import fnmatch
    import json

    permissions = json.loads(SETTINGS.read_text())["permissions"]
    for rule in permissions.get("ask", []) + permissions.get("deny", []):
        if not rule.startswith("Edit(./"):
            continue
        pattern = rule[len("Edit(./") : -1]
        base = pattern[:-3] if pattern.endswith("/**") else None
        if fnmatch.fnmatch(path, pattern) or (base and path.startswith(base + "/")):
            return True
    return False


@pytest.mark.parametrize("path", CONSEQUENTIAL)
def test_every_consequential_path_is_known_to_at_least_one_list(path):
    """A path in NEITHER list changes with nobody in the loop at either point."""
    gated = _regex("GUARD_FILE_RE").match(path) or _regex("SENSITIVE_PATH_RE").match(path)
    prompted = _covered_by_scope_list(path, _scope_tuple("CORE"))
    assert gated or prompted, (
        f"{path} outlives the pull request but appears in no protected-path list: the "
        f"meta-guard does not demand a label for it and the scope hook does not prompt on it"
    )


@pytest.mark.parametrize("path", CONSEQUENTIAL)
def test_a_path_the_meta_guard_gates_also_raises_a_prompt(path):
    """The eighteen-path gap: a label demanded at the gate, nothing asked at the keystroke.

    Noticing at merge time that a change should never have been made is strictly worse than
    being asked before making it.
    """
    gated = _regex("GUARD_FILE_RE").match(path) or _regex("SENSITIVE_PATH_RE").match(path)
    if not gated:
        pytest.skip(f"{path} is not gated by the meta-guard")
    core = _scope_tuple("CORE")
    assert _covered_by_scope_list(path, core) or _statically_asked(path), (
        f"{path} needs the owner's label on a pull request but raises no keystroke prompt. "
        f"Add it to CORE in .claude/hooks/approved_scope.py (or, for .claude/ itself, a static "
        f"ask rule in .claude/settings.json)."
    )


@pytest.mark.parametrize("path", CONSEQUENTIAL)
def test_a_system_altering_path_is_one_the_meta_guard_also_gates(path):
    """And the reverse direction, so neither list quietly outgrows the other."""
    altering = _covered_by_scope_list(path, _scope_tuple("SYSTEM_ALTERING"))
    if not altering:
        pytest.skip(f"{path} is not declared system-altering")
    gated = _regex("GUARD_FILE_RE").match(path) or _regex("SENSITIVE_PATH_RE").match(path)
    assert gated, (
        f"{path} may only be pre-approved by name at the keystroke, but the meta-guard lets "
        f"it merge without a label. The escape hatch is wider than the gate."
    )


def test_the_population_is_not_drawn_from_the_lists_it_checks():
    """The trap that let the scanner manifests survive an earlier reconciliation.

    A sample derived from the regexes can only contain paths at least one list already
    matches, so a path in neither is unreachable by construction. This asserts the sample is
    a hand-written list of files that really exist, not a projection of the lists.
    """
    missing = [p for p in CONSEQUENTIAL if not (Path(REPO_ROOT) / p).exists()]
    allowed_absent = {
        "backend/migrations/versions/0001_initial.py",  # named by shape; the file varies
        ".github/workflows/release.yml",  # deploy module
        "deploy/docker-compose.yml",
        "deploy/verify.sh",
    }
    unexpected = sorted(set(missing) - allowed_absent)
    assert not unexpected, (
        f"the population names files that do not exist, so those rows test nothing: "
        f"{unexpected}"
    )
    assert len(CONSEQUENTIAL) >= 15, "the population is too small to be a population"
