"""meta_guard must catch silent guard-weakening — and its escape hatches must work.

Each test isolates ONE check by passing the flags that disable the others; otherwise a test
could pass because a *different* check fired, which would prove nothing about the one named.
"""

from __future__ import annotations

import pytest
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
        guard,
        "--base",
        BASE,
        "--allow-missing-tests",
        "--allow-guardrail-change",
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
    write(
        tmp_path / "backend" / "migrations" / "versions" / "0001_add_table.py", "revision = '1'\n"
    )
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


def test_growing_the_dockerfile_linter_ignore_list_fails(tmp_path):
    """hadolint's config is scanner config too — the same blind spot, a different file."""
    guard = _repo(tmp_path)
    write(tmp_path / ".hadolint.yaml", "ignored:\n  - DL3008\n")
    git_commit(tmp_path, "chore: baseline")
    run(["git", "branch", "-f", BASE], tmp_path)
    write(tmp_path / ".hadolint.yaml", "ignored:\n  - DL3008\n  - DL3025\n")
    git_commit(tmp_path, "chore: ignore one more rule")
    blocked = run_guard(guard, "--base", BASE, "--allow-missing-tests", "--allow-guardrail-change")
    assert blocked.returncode != 0, "a new hadolint exemption must fail"
    allowed = run_guard(
        guard,
        "--base",
        BASE,
        "--allow-missing-tests",
        "--allow-guardrail-change",
        "--allow-exemptions",
    )
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr


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
        guard,
        "--base",
        BASE,
        "--allow-missing-tests",
        "--allow-guardrail-change",
        "--allow-exemptions",
    )
    assert allowed.returncode == 0, "the allow-exemptions escape hatch must work"


# --- An ADR outranks the roadmap, and was gated by nothing ------------------------------


def test_writing_an_adr_needs_the_owners_label(tmp_path):
    """ADRs sit above docs/PLAN.md in the source-of-truth order (CLAUDE.md §0).

    An agent that can write one unreviewed can overrule the roadmap with a human nowhere in
    the loop — while `docs/**` waived the keystroke prompt on the way in.
    """
    guard = _repo(tmp_path)
    write(
        tmp_path / "docs" / "decisions" / "0099-a-decision.md",
        "# 0099 — A decision\n\nStatus: accepted\n",
    )
    git_commit(tmp_path, "docs: record a decision")
    blocked = run_guard(guard, "--base", BASE, "--allow-missing-tests")
    assert blocked.returncode != 0, "an ADR must not merge without the owner's sign-off"
    assert "docs/decisions/0099-a-decision.md" in blocked.stdout, blocked.stdout
    allowed = run_guard(guard, "--base", BASE, "--allow-missing-tests", "--allow-guardrail-change")
    assert allowed.returncode == 0, "the escape hatch must still work once approved"


def test_ordinary_docs_are_not_gated(tmp_path):
    """The prompt has to stay rare to stay meaningful — only decisions, not all of docs/."""
    guard = _repo(tmp_path)
    write(tmp_path / "docs" / "LESSONS.md", "# Lessons\n\n## 2026-09-21 — a lesson\n")
    git_commit(tmp_path, "docs: a lesson")
    result = run_guard(guard, "--base", BASE, "--allow-missing-tests")
    assert result.returncode == 0, result.stdout + result.stderr


# --- The ratchet must not count its own source ------------------------------------------
#
# A marker-detecting guard has to contain every marker it matches on, and its fault tests
# have to contain example suppressions to prove detection works. Counting those buries the
# real suppressions in noise and asks the owner to apply `allow-suppressions` for the guard
# testing itself — and a label applied routinely stops being a signal.


def test_markers_in_the_guards_own_source_are_not_counted(tmp_path):
    guard = _repo(tmp_path)
    existing = (tmp_path / "scripts" / "meta_guard.py").read_text()
    write(tmp_path / "scripts" / "meta_guard.py", existing + "\n# a new marker: # type: ignore\n")
    git_commit(tmp_path, "chore: extend the marker list")
    result = run_guard(guard, "--base", BASE, "--allow-missing-tests", "--allow-guardrail-change")
    assert result.returncode == 0, (
        "the ratchet counted markers in its own source, which is 100% noise:\n" + result.stdout
    )


def test_markers_in_the_guards_own_fault_tests_are_not_counted(tmp_path):
    guard = _repo(tmp_path)
    write(
        tmp_path / "tests" / "guards" / "test_meta_guard.py",
        "# fixture suppression: # noqa\ndef test_detection():\n    assert True\n",
    )
    git_commit(tmp_path, "test: add a detection fixture")
    result = run_guard(guard, "--base", BASE, "--allow-missing-tests", "--allow-guardrail-change")
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    "path",
    ["scripts/check_pins.py", "scripts/dod-check.py", "tests/guards/test_check_pins.py"],
)
def test_the_exemption_is_two_files_not_two_directories(tmp_path, path):
    """Exempting scripts/ or tests/guards/ wholesale reopens the hole the ratchet closes.

    A real suppression smuggled into any *other* guard must still be counted.
    """
    guard = _repo(tmp_path)
    write(tmp_path / path, "value = 1  # type: ignore\n")
    git_commit(tmp_path, f"chore: suppress in {path}")
    result = run_guard(guard, "--base", BASE, "--allow-missing-tests", "--allow-guardrail-change")
    assert (
        result.returncode != 0
    ), f"a suppression added to {path} went uncounted — the exemption is too broad"


def test_the_self_referential_exemption_removes_no_human_checkpoint(tmp_path):
    """Both exempted files are still guard files, so every change to them needs the label."""
    guard = _repo(tmp_path)
    existing = (tmp_path / "scripts" / "meta_guard.py").read_text()
    write(tmp_path / "scripts" / "meta_guard.py", existing + "\n# an edit\n")
    git_commit(tmp_path, "chore: edit the guard")
    result = run_guard(guard, "--base", BASE, "--allow-missing-tests")
    assert result.returncode != 0, "editing the meta-guard must still require the owner's label"
    assert "scripts/meta_guard.py" in result.stdout
