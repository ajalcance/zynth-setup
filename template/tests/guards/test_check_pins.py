"""check_pins must reject a floating dependency spec — and accept an exact one."""

from __future__ import annotations

from conftest import REPO_ROOT, SCRIPTS, run_guard, write

GUARD = SCRIPTS / "check_pins.py"


def test_exact_pins_pass(tmp_path):
    req = tmp_path / "requirements.txt"
    write(req, "fastapi==0.1.0\nuvicorn==0.2.0\n# a comment\n-r other.txt\n")
    result = run_guard(GUARD, str(req))
    assert result.returncode == 0, result.stdout + result.stderr


def test_floating_pin_fails(tmp_path):
    req = tmp_path / "requirements.txt"
    write(req, "fastapi==0.1.0\nrequests>=2.0\n")
    result = run_guard(GUARD, str(req))
    assert result.returncode != 0, "a '>=' spec must fail the pin guard"
    assert "requests" in result.stdout


def test_bare_package_fails(tmp_path):
    req = tmp_path / "requirements.txt"
    write(req, "redis\n")
    result = run_guard(GUARD, str(req))
    assert result.returncode != 0, "an unversioned requirement must fail the pin guard"


def test_the_files_ci_checks_actually_exist():
    """The manifests this project really ships must be present.

    A missing path is tolerated (a variant may not ship one) but never silently: an absent
    file is named in the denominator line, and reading nothing at all is a hard failure.
    """
    manifests = [
        REPO_ROOT / "backend" / "requirements.txt",
        REPO_ROOT / "backend" / "requirements-dev.txt",
    ]
    missing = [str(m.relative_to(REPO_ROOT)) for m in manifests if not m.is_file()]
    assert not missing, f"check_pins is gating files that do not exist: {missing}"


# --- The denominator: a gate that inspects nothing must not report green ----------------


def test_reading_no_requirement_at_all_fails(tmp_path):
    """A rename must not be able to turn this gate into a no-op that still prints OK."""
    result = run_guard(GUARD, str(tmp_path / "renamed.txt"))
    assert result.returncode != 0, "inspecting zero requirements must fail (EXP-0001)"
    assert "inspected 0 requirement" in result.stdout, result.stdout


def test_an_empty_manifest_fails(tmp_path):
    req = tmp_path / "requirements.txt"
    write(req, "# only comments\n\n")
    result = run_guard(GUARD, str(req))
    assert result.returncode != 0, "a manifest with no requirements is an empty denominator"


def test_the_denominator_is_printed_on_success(tmp_path):
    req = tmp_path / "requirements.txt"
    write(req, "fastapi==0.1.0\nuvicorn==0.2.0\n")
    result = run_guard(GUARD, str(req))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "inspected 2 requirement(s)" in result.stdout, result.stdout


# --- A comment must not vouch for the spec beside it ------------------------------------


def test_a_comment_cannot_make_a_floating_spec_look_hashed(tmp_path):
    """Reading the RAW line let `requests>=2  # --hash=sha256:...` pass as a pinned lock line."""
    req = tmp_path / "requirements.txt"
    write(req, "requests>=2  # --hash=sha256:" + "a" * 64 + "\n")
    result = run_guard(GUARD, str(req))
    assert result.returncode != 0, "a --hash inside a comment does not pin anything"
    assert "requests" in result.stdout


def test_a_real_hash_on_the_spec_line_is_accepted(tmp_path):
    req = tmp_path / "requirements.txt"
    write(req, "requests==2.32.3 --hash=sha256:" + "a" * 64 + "\n")
    result = run_guard(GUARD, str(req))
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_url_fragment_is_a_pin_not_a_comment(tmp_path):
    """The '#' that pins a direct reference must survive comment stripping."""
    req = tmp_path / "requirements.txt"
    write(req, "pkg @ https://example.invalid/pkg-1.0.whl#sha256=" + "b" * 64 + "\n")
    result = run_guard(GUARD, str(req))
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_direct_reference_without_a_concrete_artifact_fails(tmp_path):
    """An '@' alone is not a pin — `pkg @ .../latest.whl` moves under you."""
    req = tmp_path / "requirements.txt"
    write(req, "pkg @ https://example.invalid/latest.whl\n")
    result = run_guard(GUARD, str(req))
    assert result.returncode != 0, "a direct reference naming no artifact must fail"


# --- Both directions between an input and the lock it produced --------------------------

INPUT = "black==25.1.0\nsemgrep==1.140.0\n"
LOCK_HEADER = "# compiled by pip-compile from requirements-ci.in\n"


def _pair(tmp_path, input_text: str, lock_text: str):
    write(tmp_path / "requirements-ci.in", input_text)
    lock = tmp_path / "requirements-ci.txt"
    write(lock, lock_text)
    return lock


def test_a_reconciled_pair_passes(tmp_path):
    lock = _pair(
        tmp_path,
        INPUT,
        LOCK_HEADER
        + "black==25.1.0\n    # via -r requirements-ci.in\n"
        + "semgrep==1.140.0\n    # via -r requirements-ci.in\n"
        + "click==8.1.8\n    # via black\n",
    )
    result = run_guard(GUARD, str(lock))
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_line_added_only_to_the_lock_is_caught(tmp_path):
    """The reverse direction. It installs on every machine and appears in no reviewed input."""
    lock = _pair(
        tmp_path,
        INPUT,
        LOCK_HEADER
        + "black==25.1.0\n    # via -r requirements-ci.in\n"
        + "semgrep==1.140.0\n    # via -r requirements-ci.in\n"
        + "evil==6.6.6\n    # via -r requirements-ci.in\n",
    )
    result = run_guard(GUARD, str(lock))
    assert result.returncode != 0, "a direct lock entry absent from the input must fail"
    assert "evil" in result.stdout, result.stdout


def test_a_transitive_dependency_is_not_treated_as_a_direct_entry(tmp_path):
    """Otherwise every pip-compile lock fails and the rule is deleted within a week."""
    lock = _pair(
        tmp_path,
        INPUT,
        LOCK_HEADER
        + "black==25.1.0\n    # via -r requirements-ci.in\n"
        + "semgrep==1.140.0\n    # via -r requirements-ci.in\n"
        + "packaging==24.2\n    # via\n    #   black\n    #   semgrep\n",
    )
    result = run_guard(GUARD, str(lock))
    assert result.returncode == 0, result.stdout + result.stderr


def test_an_input_missing_from_the_lock_is_caught(tmp_path):
    lock = _pair(tmp_path, INPUT, LOCK_HEADER + "black==25.1.0\n    # via -r requirements-ci.in\n")
    result = run_guard(GUARD, str(lock))
    assert result.returncode != 0, "the lock must satisfy its own input"
    assert "semgrep" in result.stdout, result.stdout


def test_versions_are_compared_whole_not_by_prefix(tmp_path):
    """0.1.0 matched 0.1.0rc1 under a prefix match: a pre-release where a release was reviewed."""
    lock = _pair(
        tmp_path,
        "tool==0.1.0\n",
        LOCK_HEADER + "tool==0.1.0rc1\n    # via -r requirements-ci.in\n",
    )
    result = run_guard(GUARD, str(lock))
    assert result.returncode != 0, "0.1.0rc1 must not satisfy a pin of 0.1.0"
    assert "0.1.0rc1" in result.stdout, result.stdout


def test_package_names_reconcile_case_and_separator_insensitively(tmp_path):
    """PEP 503: Foo_Bar and foo-bar are one package, and a false mismatch trains people to ignore."""
    lock = _pair(
        tmp_path,
        "Foo_Bar==1.0\n",
        LOCK_HEADER + "foo-bar==1.0\n    # via -r requirements-ci.in\n",
    )
    result = run_guard(GUARD, str(lock))
    assert result.returncode == 0, result.stdout + result.stderr
