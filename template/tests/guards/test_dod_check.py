"""dod-check must catch an undocumented module and a stale doc reference."""

from __future__ import annotations

from conftest import app_package, install_guard, run_guard, write

ARCH = "docs/architecture/current-state.md"


def _sandbox(tmp_path, arch_body: str):
    guard = install_guard(tmp_path, "dod-check.py")
    write(tmp_path / ARCH, arch_body)
    return guard


def _base_arch() -> str:
    # `scripts/` exists in every sandbox (the guard lives there), so it must be documented.
    return "# Current State\n\nscripts/   the guards\n"


def test_documented_tree_passes(tmp_path):
    guard = _sandbox(tmp_path, _base_arch())
    result = run_guard(guard)
    assert result.returncode == 0, result.stdout + result.stderr


def test_top_level_dir_absent_from_as_built_fails(tmp_path):
    guard = _sandbox(tmp_path, "# Current State\n\nnothing documented here\n")
    result = run_guard(guard)
    assert result.returncode != 0, "an undocumented top-level dir must fail"
    assert "scripts" in result.stdout


def test_undocumented_backend_module_fails(tmp_path):
    guard = _sandbox(tmp_path, _base_arch())
    write(tmp_path / "backend" / app_package() / "billing" / "__init__.py", "")
    result = run_guard(guard)
    assert result.returncode != 0, "a new backend module must be named in current-state.md"
    assert "billing" in result.stdout


def test_documenting_the_module_makes_it_pass(tmp_path):
    """The positive control: the guard must be satisfiable, not merely angry."""
    guard = _sandbox(tmp_path, _base_arch() + "\nbackend/*/billing/   invoicing\n")
    write(tmp_path / "backend" / app_package() / "billing" / "__init__.py", "")
    result = run_guard(guard)
    assert result.returncode == 0, result.stdout + result.stderr


def test_stale_backticked_reference_fails(tmp_path):
    guard = _sandbox(tmp_path, _base_arch() + "\nSee `scripts/does_not_exist.py` for details.\n")
    result = run_guard(guard)
    assert result.returncode != 0, "a backticked path that does not exist must fail"
    assert "does_not_exist" in result.stdout
