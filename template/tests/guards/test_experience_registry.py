"""The experience registry must not claim enforcement it does not have.

A registry entry marked `guard` asserts that something mechanical enforces it. If that claim can
be false, the registry becomes a wish list that reads like a control system — the same failure the
control map's enforcement markers exist to prevent.
"""

from __future__ import annotations

import shutil

import pytest
from conftest import REPO_ROOT, SCRIPTS, install_guard, run_guard, write

GUARD = SCRIPTS / "risk_context.py"
REGISTRY = REPO_ROOT / "experience" / "registry.toml"
LADDER = ("reference", "context", "checklist", "guard", "production_blocker")

ENTRY = """schema_version = 1

[[pattern]]
id = "EXP-9001"
title = "A test pattern"
enforcement = "{rung}"
{enforced_by}paths = ["backend/**"]
guidance = "Guidance text."
"""


def _sandbox(tmp_path, rung: str, enforced_by: str | None, mechanism_exists: bool = True):
    guard = install_guard(tmp_path, "risk_context.py")
    line = f'enforced_by = ["{enforced_by}"]\n' if enforced_by else ""
    write(tmp_path / "experience" / "registry.toml", ENTRY.format(rung=rung, enforced_by=line))
    if enforced_by and mechanism_exists:
        write(tmp_path / enforced_by, "# a real mechanism\n")
    return guard


def test_the_shipped_registry_validates():
    """The registry this project actually ships must be internally honest."""
    result = run_guard(GUARD, "--validate", cwd=REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


def test_guard_rung_naming_a_real_mechanism_passes(tmp_path):
    guard = _sandbox(tmp_path, "guard", "scripts/some_guard.py")
    result = run_guard(guard, "--validate")
    assert result.returncode == 0, result.stdout + result.stderr


def test_guard_rung_without_a_mechanism_fails(tmp_path):
    """Claiming automation with nothing named is the exact lie this check exists to catch."""
    guard = _sandbox(tmp_path, "guard", None)
    result = run_guard(guard, "--validate")
    assert result.returncode != 0, "a 'guard' rung with no enforced_by must fail"
    assert "enforced_by" in result.stdout


def test_guard_rung_naming_a_missing_mechanism_fails(tmp_path):
    """The subtler lie: a mechanism that was renamed or deleted."""
    guard = _sandbox(tmp_path, "guard", "scripts/deleted_guard.py", mechanism_exists=False)
    result = run_guard(guard, "--validate")
    assert result.returncode != 0, "enforced_by pointing at a missing file must fail"
    assert "does not exist" in result.stdout


def test_checklist_rung_needs_no_mechanism(tmp_path):
    """Judgement-based lessons are honest at 'checklist' — they must not be forced to lie."""
    guard = _sandbox(tmp_path, "checklist", None)
    result = run_guard(guard, "--validate")
    assert result.returncode == 0, result.stdout + result.stderr


def test_unknown_rung_fails(tmp_path):
    guard = _sandbox(tmp_path, "mandatory", None)
    result = run_guard(guard, "--validate")
    assert result.returncode != 0, "a rung outside the ladder must fail"


def test_duplicate_ids_fail(tmp_path):
    guard = install_guard(tmp_path, "risk_context.py")
    body = ENTRY.format(rung="checklist", enforced_by="")
    write(tmp_path / "experience" / "registry.toml", body + body.split("schema_version = 1\n")[1])
    result = run_guard(guard, "--validate")
    assert result.returncode != 0, "reused ids break citation — they must fail"


# --- Fail-closed: the three ways to erase the registry ----------------------------------
#
# One test per branch, each asserting its OWN marker string. Two failure modes that produce
# the same exit code need two different messages, or a test is satisfied by the wrong branch:
# the missing-file assertion below passed against the empty-registry branch until it asserted
# a marker only the missing-file branch prints. See EXP-0001.


def test_a_missing_registry_fails_validation(tmp_path):
    """Deleting the file must not be the cheapest way to pass every claim that cites it."""
    guard = install_guard(tmp_path, "risk_context.py")  # no experience/ at all
    result = run_guard(guard, "--validate")
    assert result.returncode != 0, "a missing registry must fail --validate, not pass it"
    assert "experience/registry.toml does not exist" in result.stdout, result.stdout


def test_an_empty_registry_fails_validation_with_its_own_message(tmp_path):
    """Emptying the file erases exactly as much as deleting it, and must say so distinctly."""
    guard = install_guard(tmp_path, "risk_context.py")
    write(tmp_path / "experience" / "registry.toml", "schema_version = 1\n")
    result = run_guard(guard, "--validate")
    assert result.returncode != 0, "a registry with no patterns must fail --validate"
    assert "declares no pattern" in result.stdout, result.stdout
    assert "does not exist" not in result.stdout, (
        "the empty-registry branch must not print the missing-file marker, or a test of one "
        "is satisfied by the other"
    )


def test_an_unparseable_registry_is_not_read_as_an_empty_one(tmp_path):
    guard = install_guard(tmp_path, "risk_context.py")
    write(tmp_path / "experience" / "registry.toml", "[[pattern]\nid = broken\n")
    result = run_guard(guard, "--validate")
    assert result.returncode != 0, "unparseable TOML must fail, not validate as zero patterns"
    assert "cannot be read as TOML" in result.stdout, result.stdout


def test_a_pattern_key_of_the_wrong_shape_fails(tmp_path):
    """`pattern = []` parses fine as TOML and yields no entries — that is the trap."""
    guard = install_guard(tmp_path, "risk_context.py")
    write(tmp_path / "experience" / "registry.toml", 'schema_version = 1\npattern = "none"\n')
    result = run_guard(guard, "--validate")
    assert result.returncode != 0, "a non-table 'pattern' key must fail"
    assert "array of tables" in result.stdout, result.stdout


def test_retrieval_is_advisory_and_never_fails(tmp_path):
    """Retrieval must not gate.

    It is context, and context that blocks becomes noise to route around.
    """
    guard = _sandbox(tmp_path, "guard", "scripts/some_guard.py")
    shutil.rmtree(tmp_path / "experience")  # even with no registry at all
    result = run_guard(guard)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("rung", LADDER)
def test_every_documented_rung_is_accepted(rung):
    """The ladder in experience/README.md and the validator must not drift apart."""
    readme = (REPO_ROOT / "experience" / "README.md").read_text()
    assert f"`{rung}`" in readme, f"rung '{rung}' is accepted by the validator but undocumented"
