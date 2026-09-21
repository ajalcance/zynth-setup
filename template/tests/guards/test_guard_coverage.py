"""check_guard_coverage is the keystone: it is what stops a guard being decorative.

A guard can be written, reviewed, merged and never wired into any gate. It then sits in
scripts/ looking like a control and cited as one, having never run. A guard with no negative
test is the same problem one layer down: nothing has demonstrated it can fail, so its green
carries no information.

These tests build throwaway repositories rather than asserting against this one, so each
branch is exercised rather than inferred from a tree that happens to be healthy.
"""

from __future__ import annotations

from conftest import REPO_ROOT, SCRIPTS, install_guard, run_guard, write

GUARD = SCRIPTS / "check_guard_coverage.py"


def _repo(tmp_path, *, fault_test: bool = True, enforced: bool = True, extra: str = ""):
    """A minimal repository with one guard, and switches for each thing it might be missing."""
    coverage = install_guard(tmp_path, "check_guard_coverage.py")
    write(tmp_path / "scripts" / "check_thing.py", "print('thing')\n")
    if fault_test:
        write(
            tmp_path / "tests" / "guards" / "test_thing.py",
            "def test_check_thing_can_fail():\n    assert 'check_thing.py'\n",
        )
    else:
        # A fault-test DIRECTORY must still exist, or the guard fails for the other reason
        # and this fixture would prove nothing about the branch it names.
        write(
            tmp_path / "tests" / "guards" / "test_other.py",
            "def test_unrelated():\n    assert True\n",
        )
    makefile = "policy:\n\tpython3 scripts/check_thing.py\n" if enforced else "help:\n\t@echo hi\n"
    write(tmp_path / "Makefile", makefile + extra)
    return coverage


def test_the_guards_this_project_ships_are_all_real_controls():
    """The positive control — and the assertion that made two untested hooks visible."""
    result = run_guard(GUARD, cwd=REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "inspected" in result.stdout


def test_a_fully_wired_guard_passes(tmp_path):
    coverage = _repo(tmp_path)
    result = run_guard(coverage)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_guard_with_no_fault_test_fails(tmp_path):
    """Ten passing assertions about a guard that cannot fail prove the test file parses."""
    coverage = _repo(tmp_path, fault_test=False)
    result = run_guard(coverage)
    assert result.returncode != 0, "a guard with no negative test must fail coverage"
    assert "no fault test" in result.stdout, result.stdout
    assert "check_thing.py" in result.stdout


def test_a_guard_nothing_invokes_fails(tmp_path):
    """The shape this gate exists for: written, reviewed, merged, and never once run."""
    coverage = _repo(tmp_path, enforced=False)
    result = run_guard(coverage)
    assert result.returncode != 0, "a guard no surface invokes must fail coverage"
    assert "nothing invokes it" in result.stdout, result.stdout


def test_a_workflow_counts_as_an_enforcement_surface(tmp_path):
    """Not every guard runs from the Makefile; a CI step is an equally real surface."""
    coverage = _repo(tmp_path, enforced=False)
    write(
        tmp_path / ".github" / "workflows" / "ci.yml",
        "jobs:\n  static:\n    steps:\n      - run: python3 scripts/check_thing.py\n",
    )
    result = run_guard(coverage)
    assert result.returncode == 0, result.stdout + result.stderr


def test_discovering_no_guard_at_all_fails(tmp_path):
    """The denominator rule applied to the coverage check itself."""
    coverage = install_guard(tmp_path, "check_guard_coverage.py")  # only this file
    write(tmp_path / "tests" / "guards" / "test_x.py", "def test_x():\n    assert True\n")
    result = run_guard(coverage)
    assert result.returncode != 0, "discovering zero guards must fail, not pass vacuously"
    assert "no guard was discovered" in result.stdout, result.stdout


def test_an_empty_fault_test_directory_fails(tmp_path):
    """With no fault tests at all, the per-guard check below could only ever pass."""
    coverage = install_guard(tmp_path, "check_guard_coverage.py")
    write(tmp_path / "scripts" / "check_thing.py", "print('thing')\n")
    write(tmp_path / "Makefile", "policy:\n\tpython3 scripts/check_thing.py\n")
    result = run_guard(coverage)
    assert result.returncode != 0
    assert "no fault tests" in result.stdout, result.stdout


def test_a_declared_non_gate_is_exempt_and_says_why(tmp_path):
    """The escape hatch exists, and it costs a written reason — which is the review."""
    coverage = _repo(tmp_path)
    write(tmp_path / "scripts" / "diagnostic.py", "print('just prints')\n")
    blocked = run_guard(coverage)
    assert blocked.returncode != 0, "an unwired, untested script must fail before it is declared"

    source = coverage.read_text()
    coverage.write_text(
        source.replace(
            "NON_GATES: dict[str, str] = {",
            "NON_GATES: dict[str, str] = {\n"
            '    "diagnostic.py": "prints a snapshot; asserts nothing",',
        )
    )
    allowed = run_guard(coverage)
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr
    assert "prints a snapshot" in allowed.stdout, "the reason must be shown, not just honoured"


def test_the_exemption_list_is_short_enough_to_read():
    """A NON_GATES that grows without bound is how this check stops meaning anything.

    Not a hard cap on principle — a reminder that each entry is a guard somebody decided not
    to wire in, and a long list deserves a look rather than another append.
    """
    source = (SCRIPTS / "check_guard_coverage.py").read_text()
    declared = source.count('": (') + source.count('": "')
    assert declared <= 8, (
        f"{declared} scripts are declared non-gates. Each is a script nothing runs and "
        f"nothing tests; check they all still deserve it."
    )
