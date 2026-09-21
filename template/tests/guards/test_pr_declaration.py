"""The PR memory declaration must be checked against the diff in BOTH directions."""

from __future__ import annotations

from conftest import REPO_ROOT, SCRIPTS, git_commit, git_init, run, run_guard, write

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
    write(
        path,
        "<!--\n- PLAN: updated\n-->\n"
        + FULL.format(plan=NA, lessons=NA, state=NA, adr=NA, changelog=NA),
    )
    result = run_guard(GUARD, "--body-file", str(path), "--base", BASE, cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


# --- Fail-closed: an unreadable diff must not be read as an empty one -------------------


def test_an_unreadable_diff_is_a_hard_failure(tmp_path):
    """With no diff to contradict them, every N/A passes. That must fail, not rubber-stamp."""
    _repo(tmp_path)
    write(tmp_path / "src.txt", "x\n")
    git_commit(tmp_path, "chore: x")
    result = run_guard(GUARD, "--body-file", _body(tmp_path), "--base", "no-such-ref", cwd=tmp_path)
    assert result.returncode != 0, "a base ref git cannot resolve must fail the guard"
    assert "could not be read" in result.stdout, result.stdout


def test_the_unreadable_diff_branch_is_not_reached_by_an_ordinary_empty_diff(tmp_path):
    """The two must stay distinguishable, or the test above passes for the wrong reason."""
    _repo(tmp_path)
    result = run_guard(GUARD, "--body-file", _body(tmp_path), "--base", BASE, cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "could not be read" not in result.stdout


# --- 'updated' must be a real change ----------------------------------------------------


def test_a_whitespace_only_edit_does_not_count_as_updated(tmp_path):
    _repo(tmp_path)
    write(tmp_path / "CHANGELOG.md", "# Changelog\n")
    git_commit(tmp_path, "base changelog")
    run(["git", "branch", "-f", BASE], tmp_path)
    write(tmp_path / "CHANGELOG.md", "# Changelog\n   \n")
    git_commit(tmp_path, "chore: whitespace")
    result = run_guard(
        GUARD, "--body-file", _body(tmp_path, changelog="updated"), "--base", BASE, cwd=tmp_path
    )
    assert result.returncode != 0, "a whitespace edit is a file touched, not a record updated"
    assert "whitespace" in result.stdout, result.stdout


def test_one_token_appended_to_the_lessons_log_does_not_count(tmp_path):
    """The log records need a dated heading or real prose — appending 'ok' records nothing."""
    _repo(tmp_path)
    write(tmp_path / "docs" / "LESSONS.md", "# Lessons\n")
    git_commit(tmp_path, "base lessons")
    run(["git", "branch", "-f", BASE], tmp_path)
    write(tmp_path / "docs" / "LESSONS.md", "# Lessons\nok\n")
    git_commit(tmp_path, "docs: token")
    result = run_guard(
        GUARD, "--body-file", _body(tmp_path, lessons="updated"), "--base", BASE, cwd=tmp_path
    )
    assert result.returncode != 0, "one token is not a lesson"
    assert "dated heading" in result.stdout, result.stdout


def test_a_dated_heading_satisfies_a_log_record(tmp_path):
    _repo(tmp_path)
    write(tmp_path / "docs" / "PLAN.md", "# Plan\n\n## 2026-09-21 — slice 3 shipped\n")
    git_commit(tmp_path, "docs: plan")
    result = run_guard(
        GUARD, "--body-file", _body(tmp_path, plan="updated"), "--base", BASE, cwd=tmp_path
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_several_lines_of_prose_satisfy_a_log_record_without_a_date(tmp_path):
    _repo(tmp_path)
    write(tmp_path / "docs" / "PLAN.md", "# Plan\n\nPhase two is done.\nPhase three starts now.\n")
    git_commit(tmp_path, "docs: plan prose")
    result = run_guard(
        GUARD, "--body-file", _body(tmp_path, plan="updated"), "--base", BASE, cwd=tmp_path
    )
    assert result.returncode == 0, result.stdout + result.stderr


# --- A new subsystem is a design decision ----------------------------------------------


def test_na_on_the_adr_is_refused_when_the_diff_adds_a_module_tree(tmp_path):
    _repo(tmp_path)
    write(tmp_path / "backend" / "demo" / "billing" / "__init__.py", "")
    write(tmp_path / "backend" / "demo" / "billing" / "service.py", "def charge():\n    ...\n")
    git_commit(tmp_path, "feat: billing")
    result = run_guard(GUARD, "--body-file", _body(tmp_path), "--base", BASE, cwd=tmp_path)
    assert result.returncode != 0, "a new module tree with ADR: N/A must fail"
    assert "backend/demo/billing" in result.stdout, result.stdout


def test_adding_a_file_to_an_existing_tree_is_not_a_new_subsystem(tmp_path):
    """Otherwise every PR touching a package would demand an ADR, and the rule becomes noise."""
    _repo(tmp_path)
    write(tmp_path / "backend" / "demo" / "billing" / "service.py", "def charge():\n    ...\n")
    git_commit(tmp_path, "feat: billing")
    run(["git", "branch", "-f", BASE], tmp_path)
    write(tmp_path / "backend" / "demo" / "billing" / "refunds.py", "def refund():\n    ...\n")
    git_commit(tmp_path, "feat: refunds")
    result = run_guard(GUARD, "--body-file", _body(tmp_path), "--base", BASE, cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_backend_tests_and_migrations_are_not_module_trees(tmp_path):
    _repo(tmp_path)
    write(tmp_path / "backend" / "tests" / "unit" / "test_x.py", "def test_x():\n    assert True\n")
    write(tmp_path / "backend" / "migrations" / "versions" / "001_x.py", "revision = '001'\n")
    git_commit(tmp_path, "test: add tests")
    result = run_guard(GUARD, "--body-file", _body(tmp_path), "--base", BASE, cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


# --- The parser's grammar and the PR template must be the same thing --------------------


def test_an_em_dash_reason_is_accepted(tmp_path):
    """Smart punctuation is what an editor produces; rejecting it teaches nothing about rigour."""
    _repo(tmp_path)
    write(tmp_path / "src.txt", "x\n")
    git_commit(tmp_path, "chore: x")
    body = _body(tmp_path, plan="N/A — no roadmap movement in this change")
    result = run_guard(GUARD, "--body-file", body, "--base", BASE, cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_reason_wrapped_onto_a_second_line_is_accepted(tmp_path):
    _repo(tmp_path)
    write(tmp_path / "src.txt", "x\n")
    git_commit(tmp_path, "chore: x")
    path = tmp_path / "wrapped.md"
    write(
        path,
        FULL.format(plan=NA, lessons=NA, state=NA, adr=NA, changelog=NA).replace(
            f"- PLAN: {NA}",
            "- PLAN: N/A — this change only renames a private helper and\n"
            "  moves no roadmap item at all",
        ),
    )
    result = run_guard(GUARD, "--body-file", str(path), "--base", BASE, cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_malformed_answer_is_told_the_accepted_shape(tmp_path):
    _repo(tmp_path)
    write(tmp_path / "src.txt", "x\n")
    git_commit(tmp_path, "chore: x")
    result = run_guard(
        GUARD, "--body-file", _body(tmp_path, plan="maybe later"), "--base", BASE, cwd=tmp_path
    )
    assert result.returncode != 0
    assert "Accepted shapes" in result.stdout, result.stdout


def test_the_shipped_pr_template_shows_the_shape_the_parser_accepts(tmp_path):
    """The example and the grammar drifting apart is how a correct declaration gets rejected.

    The example is not merely searched for — it is fed to the real guard. A template that
    shows a shape the parser refuses sends every author guessing at whitespace.
    """
    template = (REPO_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text()
    example = "- PLAN: N/A: no roadmap movement, this is a one-file bug fix"
    assert example in template, "the template must show a literally-valid example"

    _repo(tmp_path)
    write(tmp_path / "src.txt", "x\n")
    git_commit(tmp_path, "chore: x")
    path = tmp_path / "from-template.md"
    write(
        path,
        "## Memory impact\n\n"
        + example
        + "\n"
        + "\n".join(f"- {k}: {NA}" for k in ("LESSONS", "current-state", "ADR", "CHANGELOG"))
        + "\n",
    )
    result = run_guard(GUARD, "--body-file", str(path), "--base", BASE, cwd=tmp_path)
    assert result.returncode == 0, (
        "the example shipped in PULL_REQUEST_TEMPLATE.md is rejected by the parser:\n"
        + result.stdout
    )
