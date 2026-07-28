"""meta_guard must catch silent guard-weakening — and its escape hatches must work.

Each test isolates ONE check by passing the flags that disable the others; otherwise a test
could pass because a *different* check fired, which would prove nothing about the one named.
"""

from __future__ import annotations

from conftest import git_commit, git_init, install_guard, run, run_guard, write

BASE = "base-ref"


def _repo(tmp_path):
    """A sandbox whose base commit already contains the guard, so it is not itself in the diff."""
    guard = install_guard(tmp_path, "meta_guard.py")
    git_init(tmp_path)
    write(tmp_path / "backend" / "app" / "main.py", "x = 1\n")
    write(tmp_path / "backend" / "tests" / "test_main.py", "def test_x():\n    assert True\n")
    git_commit(tmp_path, "base")
    run(["git", "branch", BASE], tmp_path)
    return guard


def test_ordinary_change_with_a_test_passes(tmp_path):
    guard = _repo(tmp_path)
    write(tmp_path / "backend" / "app" / "main.py", "x = 2\n")
    write(tmp_path / "backend" / "tests" / "test_main.py", "def test_x():\n    assert 1\n")
    git_commit(tmp_path, "feat: change with test")
    result = run_guard(guard, "--base", BASE)
    assert result.returncode == 0, result.stdout + result.stderr


def test_new_suppression_marker_fails(tmp_path):
    guard = _repo(tmp_path)
    write(tmp_path / "backend" / "app" / "main.py", "x = 1  # type: ignore\n")
    git_commit(tmp_path, "chore: silence the type error")
    blocked = run_guard(guard, "--base", BASE, "--allow-missing-tests", "--allow-guardrail-change")
    assert blocked.returncode != 0, "a net-new suppression marker must fail"
    allowed = run_guard(
        guard, "--base", BASE, "--allow-missing-tests", "--allow-guardrail-change",
        "--allow-suppressions",
    )
    assert allowed.returncode == 0, "the allow-suppressions escape hatch must work"


def test_suppression_named_only_in_prose_does_not_fail(tmp_path):
    """Documenting a marker is not adding one — a guard must tell 'wrote about it' from 'did it'."""
    guard = _repo(tmp_path)
    write(tmp_path / "docs" / "STANDARDS.md", "Never add `# type: ignore` to silence an error.\n")
    git_commit(tmp_path, "docs: explain the prohibition")
    result = run_guard(guard, "--base", BASE, "--allow-missing-tests", "--allow-guardrail-change")
    assert result.returncode == 0, result.stdout + result.stderr


def test_source_change_without_a_test_fails(tmp_path):
    guard = _repo(tmp_path)
    write(tmp_path / "backend" / "app" / "main.py", "x = 3\n")
    git_commit(tmp_path, "feat: untested change")
    blocked = run_guard(guard, "--base", BASE, "--allow-guardrail-change")
    assert blocked.returncode != 0, "changing source without touching a test must fail"
    allowed = run_guard(guard, "--base", BASE, "--allow-guardrail-change", "--allow-missing-tests")
    assert allowed.returncode == 0, "the no-tests-needed escape hatch must work"


def test_editing_a_guard_file_fails(tmp_path):
    """The sharpest case: an agent editing the thing that is checking it."""
    guard = _repo(tmp_path)
    write(tmp_path / "scripts" / "some_guard.py", "# weakened\n")
    git_commit(tmp_path, "fix: correct a false positive")
    blocked = run_guard(guard, "--base", BASE, "--allow-missing-tests")
    assert blocked.returncode != 0, "editing a guard-defining file must fail"
    allowed = run_guard(guard, "--base", BASE, "--allow-missing-tests", "--allow-guardrail-change")
    assert allowed.returncode == 0, "the guardrail-change escape hatch must work"


def test_editing_a_workflow_also_counts_as_a_guard_file(tmp_path):
    guard = _repo(tmp_path)
    write(tmp_path / ".github" / "workflows" / "ci.yml", "name: CI\n")
    git_commit(tmp_path, "ci: tweak")
    result = run_guard(guard, "--base", BASE, "--allow-missing-tests")
    assert result.returncode != 0, "a workflow edit must be treated as a guard-file change"


def test_migration_change_needs_sensitive_approval(tmp_path):
    """A migration rewrites stored data — its blast radius outlives the PR."""
    guard = _repo(tmp_path)
    write(tmp_path / "backend" / "migrations" / "versions" / "0001_add_table.py", "revision = '1'\n")
    git_commit(tmp_path, "feat: add a migration")
    blocked = run_guard(guard, "--base", BASE, "--allow-missing-tests")
    assert blocked.returncode != 0, "a migration must require sensitive-change approval"
    allowed = run_guard(guard, "--base", BASE, "--allow-missing-tests", "--allow-sensitive")
    assert allowed.returncode == 0, "the sensitive-change-approved escape hatch must work"


def test_dependency_manifest_is_not_treated_as_sensitive(tmp_path):
    """Dependabot touches manifests weekly; a label applied that often stops being a signal."""
    guard = _repo(tmp_path)
    write(tmp_path / "backend" / "requirements.txt", "fastapi==0.1.1\n")
    git_commit(tmp_path, "chore: bump fastapi")
    result = run_guard(guard, "--base", BASE, "--allow-missing-tests")
    assert result.returncode == 0, result.stdout + result.stderr


def test_lowering_the_coverage_floor_fails(tmp_path):
    """The classic silent weakening: move the ratchet instead of restoring the coverage."""
    guard = _repo(tmp_path)
    write(tmp_path / "backend" / "pyproject.toml", "[tool.coverage.report]\nfail_under = 70\n")
    git_commit(tmp_path, "chore: baseline")
    run(["git", "branch", "-f", BASE], tmp_path)
    write(tmp_path / "backend" / "pyproject.toml", "[tool.coverage.report]\nfail_under = 40\n")
    git_commit(tmp_path, "chore: lower the floor")
    blocked = run_guard(guard, "--base", BASE, "--allow-missing-tests")
    assert blocked.returncode != 0, "lowering the coverage floor must fail"
    assert "coverage floor" in blocked.stdout
    allowed = run_guard(guard, "--base", BASE, "--allow-missing-tests", "--allow-exemptions")
    assert allowed.returncode == 0, "the allow-exemptions escape hatch must work"


def test_raising_the_coverage_floor_is_fine(tmp_path):
    """The ratchet is directional — tightening it must never be blocked."""
    guard = _repo(tmp_path)
    write(tmp_path / "backend" / "pyproject.toml", "[tool.coverage.report]\nfail_under = 70\n")
    git_commit(tmp_path, "chore: baseline")
    run(["git", "branch", "-f", BASE], tmp_path)
    write(tmp_path / "backend" / "pyproject.toml", "[tool.coverage.report]\nfail_under = 85\n")
    git_commit(tmp_path, "chore: raise the floor")
    result = run_guard(guard, "--base", BASE, "--allow-missing-tests")
    assert result.returncode == 0, result.stdout + result.stderr


def test_growing_a_scanner_exemption_list_fails(tmp_path):
    """Config-level exemptions are the inline suppression scan's blind spot."""
    guard = _repo(tmp_path)
    write(tmp_path / ".gitleaks.toml", "[allowlist]\npaths = []\n")
    git_commit(tmp_path, "chore: baseline")
    run(["git", "branch", "-f", BASE], tmp_path)
    write(tmp_path / ".gitleaks.toml", '[allowlist]\npaths = []\nignore = ["secrets/*"]\n')
    git_commit(tmp_path, "chore: widen the allowlist")
    blocked = run_guard(guard, "--base", BASE, "--allow-missing-tests", "--allow-guardrail-change")
    assert blocked.returncode != 0, "a new scanner exemption must fail"
    allowed = run_guard(
        guard, "--base", BASE, "--allow-missing-tests", "--allow-guardrail-change",
        "--allow-exemptions",
    )
    assert allowed.returncode == 0, "the allow-exemptions escape hatch must work"
