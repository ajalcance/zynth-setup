"""The standards suite must not claim enforcement it does not have.

A rule tagged `[CI]` asserts that a gate catches a violation today. If that claim can be false,
`docs/standards/` becomes a description of a control system nobody built — and everyone
downstream reads a green pipeline as proof of rules it never checked. Same failure mode as the
experience registry (`test_experience_registry.py`), same remedy: machine-check the claim.
"""

from __future__ import annotations

import re
import shutil

import pytest

from conftest import REPO_ROOT, SCRIPTS, install_guard, run_guard, write

GUARD = SCRIPTS / "standards_check.py"
STANDARDS = REPO_ROOT / "docs" / "standards"
PREFIXES = ("BE", "API", "FE", "TA", "SEC", "OBS", "REL")
MARKERS = ("[CI]", "[Review]", "[Production blocker]", "[Phase gate")

# Assembled at runtime on purpose. scripts/prod_readiness.py scans .py files for this marker and
# would read the fixtures below as a real, unregistered production blocker — the same
# "wrote about it" vs "did it" trap that guard documents. Never write the literal token here.
BLOCKER = "PROD-" + "BLOCKER"

DOC = """# Test standards

| ID | Rule | Enforcement | Mechanism |
|---|---|---|---|
| {rule_id} | A rule that means something. | `{marker}` | {mechanism} |
"""


def _sandbox(
    tmp_path,
    *,
    rule_id: str = "BE-001",
    marker: str = "[Review]",
    mechanism: str = "—",
    mechanism_exists: bool = True,
    blockers: str | None = None,
):
    guard = install_guard(tmp_path, "standards_check.py")
    write(
        tmp_path / "docs" / "standards" / "test.md",
        DOC.format(rule_id=rule_id, marker=marker, mechanism=mechanism),
    )
    if mechanism_exists:
        for token in mechanism.split("`"):
            if "/" in token and not token.startswith(BLOCKER):
                write(tmp_path / token, "# a real mechanism\n")
    if blockers is not None:
        write(tmp_path / "scripts" / "prod_readiness.py", f"BLOCKERS = {blockers}\n")
    return guard


# --- The suite this project actually ships -------------------------------------------------


def test_the_shipped_standards_validate():
    """Every marker in the suite this project ships must be backed by what it names."""
    result = run_guard(GUARD, cwd=REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_shipped_suite_is_not_empty():
    """A guard that validated zero rules would pass for the wrong reason — see TA-013.

    The count is parsed, not substring-matched: "120 rule(s) validated" contains
    "0 rule(s) validated", so the naive check passes on an empty suite for some totals and
    fails on a healthy one for others. Print a denominator, then actually read it.
    """
    result = run_guard(GUARD, cwd=REPO_ROOT)
    match = re.search(r"(\d+) rule\(s\) validated", result.stdout)
    assert match, f"the guard must report how many rules it inspected:\n{result.stdout}"
    assert int(match.group(1)) > 0, "the suite validated zero rules — it is checking nothing"


# --- Marker honesty ------------------------------------------------------------------------


def test_ci_marker_naming_a_real_mechanism_passes(tmp_path):
    guard = _sandbox(tmp_path, marker="[CI]", mechanism="`scripts/some_guard.py`")
    result = run_guard(guard)
    assert result.returncode == 0, result.stdout + result.stderr


def test_ci_marker_without_a_mechanism_fails(tmp_path):
    """Claiming a gate while naming nothing is the exact lie this guard exists to catch."""
    guard = _sandbox(tmp_path, marker="[CI]", mechanism="—")
    result = run_guard(guard)
    assert result.returncode != 0, "a [CI] rule naming no mechanism must fail"
    assert "names no mechanism" in result.stdout


def test_ci_marker_naming_a_missing_mechanism_fails(tmp_path):
    """The subtler lie: the gate was real once, then renamed or deleted."""
    guard = _sandbox(
        tmp_path, marker="[CI]", mechanism="`scripts/deleted.py`", mechanism_exists=False
    )
    result = run_guard(guard)
    assert result.returncode != 0, "a [CI] rule naming a missing file must fail"
    assert "does not exist" in result.stdout


def test_review_marker_needs_no_mechanism(tmp_path):
    """Judgement rules are honest at [Review]; they must not be pushed into lying."""
    guard = _sandbox(tmp_path, marker="[Review]", mechanism="—")
    result = run_guard(guard)
    assert result.returncode == 0, result.stdout + result.stderr


def test_review_marker_naming_a_missing_file_still_fails(tmp_path):
    """A [Review] rule may point at a file, but a dangling pointer is still drift."""
    guard = _sandbox(
        tmp_path, marker="[Review]", mechanism="`docs/gone.md`", mechanism_exists=False
    )
    result = run_guard(guard)
    assert result.returncode != 0, "a mechanism path that does not exist must fail on any marker"


def test_unknown_marker_fails(tmp_path):
    guard = _sandbox(tmp_path, marker="[Enforced]")
    result = run_guard(guard)
    assert result.returncode != 0, "a marker outside the vocabulary must fail"


def test_phase_gate_without_a_release_fails(tmp_path):
    """'Planned' with no named release is indistinguishable from 'never'."""
    guard = _sandbox(tmp_path, marker="[Phase gate]")
    result = run_guard(guard)
    assert result.returncode != 0, "a phase gate must name the release it is promised for"


def test_phase_gate_with_a_release_passes(tmp_path):
    guard = _sandbox(tmp_path, marker="[Phase gate — v9.9]")
    result = run_guard(guard)
    assert result.returncode == 0, result.stdout + result.stderr


# --- Production blockers -------------------------------------------------------------------


def test_production_blocker_marker_without_a_registered_id_fails(tmp_path):
    """That marker means a release is denied. If nothing holds it, it is a costume."""
    guard = _sandbox(
        tmp_path,
        marker="[Production blocker]",
        mechanism=f"`{BLOCKER}(auth-stub)`",
        blockers="()",
    )
    result = run_guard(guard)
    assert result.returncode != 0, "an unregistered production blocker must fail"
    assert "not in the BLOCKERS register" in result.stdout


def test_production_blocker_marker_with_a_registered_id_passes(tmp_path):
    guard = _sandbox(
        tmp_path,
        marker="[Production blocker]",
        mechanism=f"`{BLOCKER}(auth-stub)`",
        blockers='(("auth-stub", "dev-only bearer check"),)',
    )
    result = run_guard(guard)
    assert result.returncode == 0, result.stdout + result.stderr


def test_production_blocker_marker_naming_no_blocker_fails(tmp_path):
    guard = _sandbox(tmp_path, marker="[Production blocker]", mechanism="—", blockers="()")
    result = run_guard(guard)
    assert result.returncode != 0, "a production-blocker rule must name the hold it relies on"


# --- Rule identity -------------------------------------------------------------------------


def test_duplicate_rule_ids_fail(tmp_path):
    guard = install_guard(tmp_path, "standards_check.py")
    body = DOC.format(rule_id="BE-001", marker="[Review]", mechanism="—")
    write(tmp_path / "docs" / "standards" / "a.md", body)
    write(tmp_path / "docs" / "standards" / "b.md", body)
    result = run_guard(guard)
    assert result.returncode != 0, "a reused id makes every citation of it ambiguous"


def test_malformed_rule_id_fails(tmp_path):
    """A row that MEANT to be a rule must not vanish silently from the suite."""
    guard = _sandbox(tmp_path, rule_id="BE-1")
    result = run_guard(guard)
    assert result.returncode != 0, "a malformed id must fail, not be skipped"
    assert "not a valid rule id" in result.stdout


def test_undeclared_prefix_fails(tmp_path):
    guard = _sandbox(tmp_path, rule_id="ZZZ-001")
    result = run_guard(guard)
    assert result.returncode != 0, "a prefix outside the declared set must fail"


# --- Citations -----------------------------------------------------------------------------


def test_citing_an_undefined_rule_fails(tmp_path):
    """Renaming or deleting a rule must not leave dangling references behind."""
    guard = _sandbox(tmp_path)
    write(tmp_path / "docs" / "GUIDE.md", "Handlers stay thin (see BE-999).\n")
    result = run_guard(guard)
    assert result.returncode != 0, "a citation with no matching rule must fail"
    assert "BE-999" in result.stdout


def test_citing_a_defined_rule_passes(tmp_path):
    guard = _sandbox(tmp_path, rule_id="BE-001")
    write(tmp_path / "docs" / "GUIDE.md", "Handlers stay thin (see BE-001).\n")
    result = run_guard(guard)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_deleted_suite_does_not_pass_silently(tmp_path):
    """Removing docs/standards/ while other docs still cite it must be caught."""
    guard = _sandbox(tmp_path)
    write(tmp_path / "docs" / "GUIDE.md", "Handlers stay thin (see BE-001).\n")
    shutil.rmtree(tmp_path / "docs" / "standards")
    result = run_guard(guard)
    assert result.returncode != 0, "deleting the suite must not silently satisfy its citations"


# --- Drift between the guard and the documents ----------------------------------------------


@pytest.mark.parametrize("prefix", PREFIXES)
def test_every_prefix_is_documented(prefix):
    """The guard accepts these prefixes; the suite's index must explain them."""
    index = (STANDARDS / "README.md").read_text()
    assert f"`{prefix}`" in index, f"prefix '{prefix}' is accepted but undocumented"


@pytest.mark.parametrize("marker", MARKERS)
def test_marker_vocabulary_matches_the_control_map(marker):
    """One vocabulary, defined once. A marker the process doc does not define is drift."""
    process = (REPO_ROOT / "docs" / "ENGINEERING_PROCESS.md").read_text()
    assert marker in process, f"marker '{marker}' is used by the standards suite but undefined"
