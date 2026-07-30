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


def test_duplicate_adr_number_fails(tmp_path):
    guard = _sandbox(tmp_path, _base_arch())
    decisions = tmp_path / "docs" / "decisions"
    write(decisions / "0001-first.md", "# 1. First\n")
    write(decisions / "0001-also-first.md", "# 1. Also first\n")
    write(decisions / "README.md", "- 0001-first.md\n- 0001-also-first.md\n")
    result = run_guard(guard)
    assert result.returncode != 0, "a reused ADR number must fail"
    assert "0001" in result.stdout


def test_adr_number_gap_fails(tmp_path):
    guard = _sandbox(tmp_path, _base_arch())
    decisions = tmp_path / "docs" / "decisions"
    write(decisions / "0001-first.md", "# 1\n")
    write(decisions / "0003-third.md", "# 3\n")
    write(decisions / "README.md", "- 0001-first.md\n- 0003-third.md\n")
    result = run_guard(guard)
    assert result.returncode != 0, "a gap in ADR numbering must fail"


def test_unindexed_adr_fails(tmp_path):
    guard = _sandbox(tmp_path, _base_arch())
    decisions = tmp_path / "docs" / "decisions"
    write(decisions / "0001-first.md", "# 1\n")
    write(decisions / "README.md", "no entries here\n")
    result = run_guard(guard)
    assert result.returncode != 0, "an ADR absent from the index must fail"
    assert "0001-first.md" in result.stdout


def test_contiguous_indexed_adrs_pass(tmp_path):
    guard = _sandbox(tmp_path, _base_arch())
    decisions = tmp_path / "docs" / "decisions"
    write(decisions / "0001-first.md", "# 1\n")
    write(decisions / "0002-second.md", "# 2\n")
    write(decisions / "README.md", "- 0001-first.md\n- 0002-second.md\n")
    result = run_guard(guard)
    assert result.returncode == 0, result.stdout + result.stderr


def test_out_of_order_lessons_fail(tmp_path):
    guard = _sandbox(tmp_path, _base_arch())
    write(
        tmp_path / "docs" / "LESSONS.md",
        "# Lessons\n\n## 2026-01-01 — older on top\n\n## 2026-06-01 — newer below\n",
    )
    result = run_guard(guard)
    assert result.returncode != 0, "LESSONS declares newest-first; ascending order must fail"


def test_newest_first_lessons_pass(tmp_path):
    guard = _sandbox(tmp_path, _base_arch())
    write(
        tmp_path / "docs" / "LESSONS.md",
        "# Lessons\n\n## 2026-06-01 — newest\n\n## 2026-01-01 — older\n",
    )
    result = run_guard(guard)
    assert result.returncode == 0, result.stdout + result.stderr
