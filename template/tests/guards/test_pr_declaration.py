"""The PR memory declaration must be checked against the diff in BOTH directions."""

from __future__ import annotations

from conftest import SCRIPTS, git_commit, git_init, run, run_guard, write

GUARD = SCRIPTS / "pr_declaration.py"
BASE = "base-ref"

FULL = """## Memory impact

- PLAN: {plan}
- LESSONS: {lessons}
- current-state: {state}
- ADR: {adr}
- CHANGELOG: {changelog}
"""

NA = "N/A: no roadmap movement in this change"


def _body(tmp_path, **overrides):
    values = {"plan": NA, "lessons": NA, "state": NA, "adr": NA, "changelog": NA}
    values.update(overrides)
    path = tmp_path / "body.md"
    write(path, FULL.format(**values))
    return str(path)


def _repo(tmp_path):
    """A repo whose base commit exists, so a diff can be taken against it."""
    git_init(tmp_path)
    write(tmp_path / "README.md", "# base\n")
    git_commit(tmp_path, "base")
    run(["git", "branch", BASE], tmp_path)


def test_all_na_with_reasons_passes_when_the_diff_touches_nothing(tmp_path):
    _repo(tmp_path)
    write(tmp_path / "src.txt", "change\n")
    git_commit(tmp_path, "chore: unrelated change")
    result = run_guard(GUARD, "--body-file", _body(tmp_path), "--base", BASE, cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_missing_declaration_fails(tmp_path):
    _repo(tmp_path)
    empty = tmp_path / "empty.md"
    write(empty, "## What & why\n\nJust a description.\n")
    result = run_guard(GUARD, "--body-file", str(empty), "--base", BASE, cwd=tmp_path)
    assert result.returncode != 0, "a PR with no Memory impact block must fail"
    assert "missing" in result.stdout.lower()


def test_claiming_updated_without_touching_the_file_fails(tmp_path):
    """The core lie this guard exists to catch."""
    _repo(tmp_path)
    write(tmp_path / "src.txt", "change\n")
    git_commit(tmp_path, "feat: change without docs")
    result = run_guard(
        GUARD, "--body-file", _body(tmp_path, lessons="updated"), "--base", BASE, cwd=tmp_path
    )
    assert result.returncode != 0, "'updated' must be false when the diff omits the file"
    assert "LESSONS" in result.stdout


def test_claiming_updated_when_the_file_changed_passes(tmp_path):
    _repo(tmp_path)
    write(tmp_path / "docs" / "LESSONS.md", "# Lessons\n\n## 2026-01-01 — x\n")
    git_commit(tmp_path, "docs: add a lesson")
    result = run_guard(
        GUARD, "--body-file", _body(tmp_path, lessons="updated"), "--base", BASE, cwd=tmp_path
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_declaring_na_while_changing_the_file_fails(tmp_path):
    """The other direction: a stale declaration misleads the next reader."""
    _repo(tmp_path)
    write(tmp_path / "CHANGELOG.md", "# Changelog\n\n## [Unreleased]\n- thing\n")
    git_commit(tmp_path, "docs: changelog entry")
    result = run_guard(GUARD, "--body-file", _body(tmp_path), "--base", BASE, cwd=tmp_path)
    assert result.returncode != 0, "N/A must fail when the diff DOES touch the record"
    assert "CHANGELOG" in result.stdout


def test_unreplaced_template_placeholder_fails(tmp_path):
    """The shipped template is pre-filled with a placeholder that must not pass."""
    _repo(tmp_path)
    write(tmp_path / "src.txt", "x\n")
    git_commit(tmp_path, "chore: x")
    body = _body(tmp_path, plan="<updated | N/A: reason>")
    result = run_guard(GUARD, "--body-file", body, "--base", BASE, cwd=tmp_path)
    assert result.returncode != 0, "an unreplaced placeholder must fail"


def test_na_without_a_real_reason_fails(tmp_path):
    _repo(tmp_path)
    write(tmp_path / "src.txt", "x\n")
    git_commit(tmp_path, "chore: x")
    result = run_guard(
        GUARD, "--body-file", _body(tmp_path, plan="N/A: n/a"), "--base", BASE, cwd=tmp_path
    )
    assert result.returncode != 0, "a token reason must not satisfy the declaration"


def test_instructions_in_html_comments_are_not_read_as_answers(tmp_path):
    """The template's own guidance mentions 'updated'; that must not count as a declaration."""
    _repo(tmp_path)
    write(tmp_path / "src.txt", "x\n")
    git_commit(tmp_path, "chore: x")
    path = tmp_path / "body.md"
    write(path, "<!--\n- PLAN: updated\n-->\n" + FULL.format(
        plan=NA, lessons=NA, state=NA, adr=NA, changelog=NA))
    result = run_guard(GUARD, "--body-file", str(path), "--base", BASE, cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
