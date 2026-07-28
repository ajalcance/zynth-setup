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
    """Vacuity guard: check_file() silently skips a missing path.

    That is deliberate (a variant may not ship a file), but it means a rename would make the
    gate pass while checking nothing. The manifests this project really ships must be present.
    """
    manifests = [
        REPO_ROOT / "backend" / "requirements.txt",
        REPO_ROOT / "backend" / "requirements-dev.txt",
    ]
    missing = [str(m.relative_to(REPO_ROOT)) for m in manifests if not m.is_file()]
    assert not missing, f"check_pins is gating files that do not exist: {missing}"
