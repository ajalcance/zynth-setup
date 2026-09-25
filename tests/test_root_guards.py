"""Every root guard can fail — each is run for real against a sandbox built to trip it.

These three scripts gate every generation in the self-test and had no fault test at all:
they were verified by hand when written, which proves only that they passed once.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import ROOT, SCRIPTS


def run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None):
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, **(env or {})},
    )


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


# --- check-owner-questions.py ------------------------------------------------------------


@pytest.fixture
def owner_sandbox(tmp_path) -> Path:
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".github").mkdir()
    shutil.copy(SCRIPTS / "check-owner-questions.py", tmp_path / "scripts")
    shutil.copy(ROOT / "copier.yml", tmp_path)
    shutil.copy(ROOT / ".github" / "self-test-owner.yml", tmp_path / ".github")
    return tmp_path


def owner_check(sandbox: Path):
    return run([sys.executable, str(sandbox / "scripts" / "check-owner-questions.py")], sandbox)


def test_owner_questions_pass_on_the_real_files(owner_sandbox):
    result = owner_check(owner_sandbox)
    assert result.returncode == 0, result.stdout


def test_an_owner_question_the_answers_file_does_not_answer_fails(owner_sandbox):
    answers = owner_sandbox / ".github" / "self-test-owner.yml"
    answers.write_text(
        "".join(
            line for line in answers.read_text().splitlines(True) if not line.startswith("license:")
        )
    )
    result = owner_check(owner_sandbox)
    assert result.returncode == 1 and "missing ['license']" in result.stdout


def test_an_answer_to_no_owner_question_fails(owner_sandbox):
    with (owner_sandbox / ".github" / "self-test-owner.yml").open("a") as handle:
        handle.write("not_a_question: 1\n")
    result = owner_check(owner_sandbox)
    assert result.returncode == 1 and "extra ['not_a_question']" in result.stdout


def test_a_new_question_with_no_default_is_named_before_anything_generates(owner_sandbox):
    """The population, not the list: this is what broke the copier-update gate."""
    with (owner_sandbox / "copier.yml").open("a") as handle:
        handle.write("\nsupport_email:\n  type: str\n  help: where users write\n")
    result = owner_check(owner_sandbox)
    assert result.returncode == 1 and "support_email: no default" in result.stdout


def test_a_missing_answers_file_fails(owner_sandbox):
    (owner_sandbox / ".github" / "self-test-owner.yml").unlink()
    result = owner_check(owner_sandbox)
    assert result.returncode == 1 and "missing or not a mapping" in result.stdout


def test_an_owner_question_that_grows_a_default_fails(owner_sandbox):
    config = owner_sandbox / "copier.yml"
    config.write_text(config.read_text().replace("license:\n", "license:\n  default: MIT\n", 1))
    result = owner_check(owner_sandbox)
    assert result.returncode == 1 and "license: has a default" in result.stdout


# --- check-tracked-ignores.sh ------------------------------------------------------------


@pytest.fixture
def ignore_sandbox(tmp_path) -> Path:
    git(tmp_path, "init", "-q")
    (tmp_path / "keep.txt").write_text("x\n")
    git(tmp_path, "add", "keep.txt")
    return tmp_path


def ignore_check(sandbox: Path):
    return run(["bash", str(SCRIPTS / "check-tracked-ignores.sh")], sandbox)


def test_a_clean_tree_passes(ignore_sandbox):
    result = ignore_check(ignore_sandbox)
    assert result.returncode == 0 and "1 tracked files" in result.stdout


def test_a_tracked_file_matched_by_an_ignore_rule_fails(ignore_sandbox):
    """How `.env.*` swallowed .env.example.jinja from every local generation for weeks."""
    (ignore_sandbox / ".env.example.jinja").write_text("A=1\n")
    git(ignore_sandbox, "add", ".env.example.jinja")
    (ignore_sandbox / ".gitignore").write_text(".env.*\n")
    result = ignore_check(ignore_sandbox)
    assert result.returncode == 1 and ".env.example.jinja" in result.stderr


def test_rules_git_cannot_evaluate_are_a_failure_not_a_pass(ignore_sandbox):
    """`git check-ignore` exits >1 when it cannot read the rules; that is not "none ignored"."""
    exclude = ignore_sandbox / ".git" / "info" / "exclude"
    exclude.unlink(missing_ok=True)
    exclude.mkdir(parents=True)
    result = ignore_check(ignore_sandbox)
    assert result.returncode > 1 and "could not be evaluated" in result.stderr


def test_outside_a_repository_it_refuses(tmp_path):
    result = run(["bash", str(SCRIPTS / "check-tracked-ignores.sh")], tmp_path)
    assert result.returncode != 0


# --- check-jinja-syntax.sh ---------------------------------------------------------------


@pytest.fixture
def jinja_sandbox(tmp_path) -> Path:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "template").mkdir()
    shutil.copy(SCRIPTS / "check-jinja-syntax.sh", tmp_path / "scripts")
    (tmp_path / "template" / "ok.md.jinja").write_text("Hello {{ name }}\n")
    return tmp_path


def jinja_check(sandbox: Path, env: dict[str, str] | None = None):
    return run(
        ["bash", str(sandbox / "scripts" / "check-jinja-syntax.sh")],
        sandbox,
        {"PYTHON": sys.executable, **(env or {})},
    )


def test_compiling_templates_pass(jinja_sandbox):
    result = jinja_check(jinja_sandbox)
    assert result.returncode == 0 and "parsed 1 template" in result.stdout


def test_the_shell_array_length_form_is_caught(jinja_sandbox):
    """`{` then `#` opens a Jinja comment — a valid shell script, an invalid template."""
    (jinja_sandbox / "template" / "run.sh.jinja").write_text('echo "${#items[@]}"\n')
    result = jinja_check(jinja_sandbox)
    assert result.returncode == 1 and "run.sh.jinja" in result.stdout


def test_a_bad_conditional_in_a_path_is_caught(jinja_sandbox):
    (jinja_sandbox / "template" / "{% if x %}broken").mkdir()
    result = jinja_check(jinja_sandbox)
    assert result.returncode == 1


def test_an_empty_template_tree_fails_rather_than_passing_over_nothing(jinja_sandbox):
    (jinja_sandbox / "template" / "ok.md.jinja").unlink()
    result = jinja_check(jinja_sandbox)
    assert result.returncode == 1 and "nothing was parsed" in result.stdout


def test_without_jinja2_it_refuses_instead_of_skipping(jinja_sandbox, tmp_path_factory):
    """It used to print SKIPPED and exit 0 — a green run that parsed nothing."""
    shadow = tmp_path_factory.mktemp("shadow") / "jinja2"
    shadow.mkdir()
    (shadow / "__init__.py").write_text("raise ImportError('shadowed for the test')\n")
    result = jinja_check(jinja_sandbox, {"PYTHONPATH": str(shadow.parent)})
    assert result.returncode == 2 and "REFUSED" in result.stdout
