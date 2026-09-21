"""prod_readiness must detect drift between PROD-BLOCKER markers and the register, both ways."""

from __future__ import annotations

from conftest import install_guard, run_guard, write

# Assembled at runtime so this file contains no literal marker of its own. prod_readiness.py
# scans .py sources, and a test *demonstrating* the convention must not be counted as *declaring*
# a real production blocker — the same "wrote about it vs did it" distinction the suppression scan
# makes. Do NOT inline these back into string literals: it will fail `make dod-check`.
MARKER = "PROD-" + "BLOCKER"

REGISTER_EMPTY = "BLOCKERS: tuple[tuple[str, str], ...] = ()"
REGISTER_ONE = 'BLOCKERS: tuple[tuple[str, str], ...] = (("auth-stub", "replace before launch"),)'


def _sandbox(tmp_path, *, register: str, marker: bool):
    guard = install_guard(tmp_path, "prod_readiness.py")
    guard.write_text(guard.read_text().replace(REGISTER_EMPTY, register))
    # A scannable source file, always. "A clean project" means one with source and no
    # markers, not an empty directory — and an empty directory is precisely the vacuous
    # denominator this guard now refuses, so a fixture without one tests the wrong branch.
    write(tmp_path / "main.py", "def run():\n    return 1\n")
    if marker:
        write(tmp_path / "app.py", f"# {MARKER}(auth-stub): dev-only check\n")
    return guard


def test_clean_project_passes(tmp_path):
    guard = _sandbox(tmp_path, register=REGISTER_EMPTY, marker=False)
    result = run_guard(guard)
    assert result.returncode == 0, result.stdout + result.stderr


def test_marker_without_register_entry_fails(tmp_path):
    guard = _sandbox(tmp_path, register=REGISTER_EMPTY, marker=True)
    result = run_guard(guard)
    assert result.returncode != 0, "an unregistered PROD-BLOCKER marker must fail"
    assert "auth-stub" in result.stdout


def test_register_entry_without_marker_fails(tmp_path):
    """Anti-rot: a register that outlives its marker becomes a list of already-fixed items."""
    guard = _sandbox(tmp_path, register=REGISTER_ONE, marker=False)
    result = run_guard(guard)
    assert result.returncode != 0, "a stale register entry must fail"


def test_consistent_pair_passes_but_strict_blocks_release(tmp_path):
    guard = _sandbox(tmp_path, register=REGISTER_ONE, marker=True)
    assert run_guard(guard).returncode == 0, "a consistent open blocker is not an error"
    assert run_guard(guard, "--strict").returncode != 0, "--strict must deny release"


def test_documentation_prose_is_not_counted_as_a_marker(tmp_path):
    """Docs explaining the convention name the marker; that must not count as declaring one."""
    guard = _sandbox(tmp_path, register=REGISTER_EMPTY, marker=False)
    write(tmp_path / "ONBOARDING.md", f"Use `# {MARKER}(example): why` to register a hold.\n")
    assert run_guard(guard).returncode == 0


def test_scanning_no_file_at_all_fails(tmp_path):
    """The denominator rule: "no open blockers" and "this read nothing" printed the same line."""
    guard = install_guard(tmp_path, "prod_readiness.py")  # nothing else in the tree
    result = run_guard(guard)
    assert result.returncode != 0, "scanning zero files must fail, not report no blockers"
    assert "no file was scanned" in result.stdout, result.stdout


def test_the_denominator_is_printed_on_success(tmp_path):
    guard = _sandbox(tmp_path, register=REGISTER_EMPTY, marker=False)
    result = run_guard(guard)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "inspected" in result.stdout and "file(s)" in result.stdout, result.stdout
