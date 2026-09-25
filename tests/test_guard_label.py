"""The guard-label check can fail — run for real against sandbox repositories."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import ROOT

CHECK = ROOT / "scripts" / "check_guard_label.py"


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=t",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path) -> Path:
    """A repository with the check and the template meta-guard it imports, one base commit."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "template" / "scripts").mkdir(parents=True)
    shutil.copy(CHECK, tmp_path / "scripts")
    shutil.copy(ROOT / "template" / "scripts" / "meta_guard.py", tmp_path / "template" / "scripts")
    (tmp_path / "README.md").write_text("x\n")
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    git(tmp_path, "switch", "-qc", "feature")
    return tmp_path


def change(repo: Path, path: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    # Appended, never overwritten: a changed meta_guard.py must still import.
    with target.open("a") as handle:
        handle.write("# changed\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"change {path}")


def check(repo: Path, labelled: bool):
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / "check_guard_label.py"), "--base", "main"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "GUARDRAIL_LABEL": "true" if labelled else "false"},
    )


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/template-test.yml",
        ".claude/settings.json",
        "scripts/check-jinja-syntax.sh",
        "tests/test_repo_policy.py",
        "Makefile",
        "requirements-selftest.txt",
        ".gitleaksignore",
        "copier.yml",
        "template/scripts/meta_guard.py",
        "template/.github/workflows/ci.yml",
        "template/.github/workflows/{% if include_deploy %}release.yml{% endif %}",
        "template/.gitleaks.toml.jinja",
        "template/requirements-ci.txt",
        "template/docs/decisions/0007-agent-permission-model.md",
        "template/.claude/{% if include_claude_hooks %}hooks{% endif %}/block_dangerous_bash.py",
        "template/tests/guards/test_agent_policy.py",
        "template/Makefile.jinja",
    ],
)
def test_a_guard_changed_without_the_label_fails(repo, path):
    change(repo, path)
    result = check(repo, labelled=False)
    assert result.returncode == 1, result.stdout
    assert path in result.stdout


def test_the_owners_label_lets_it_through(repo):
    change(repo, "template/scripts/meta_guard.py")
    assert check(repo, labelled=True).returncode == 0


@pytest.mark.parametrize(
    "path",
    ["README.md", "template/README.md.jinja", "template/docs/OVERVIEW.md.jinja", "MAINTAINING.md"],
)
def test_an_ordinary_change_needs_no_label(repo, path):
    change(repo, path)
    result = check(repo, labelled=False)
    assert result.returncode == 0, result.stdout
    assert "0 of 1" in result.stdout


def test_an_unresolvable_base_is_refused_not_passed(repo):
    change(repo, "README.md")
    result = subprocess.run(
        [sys.executable, str(repo / "scripts" / "check_guard_label.py"), "--base", "origin/nope"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2 and "REFUSED" in result.stdout


def test_a_meta_guard_that_cannot_be_imported_is_refused_not_passed(repo):
    """The definition of "guard" is read from it; unreadable means nothing was checked."""
    (repo / "template" / "scripts" / "meta_guard.py").write_text("this is not python\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "break it")
    result = check(repo, labelled=True)
    assert result.returncode == 2 and "REFUSED" in result.stdout


def test_an_empty_diff_is_refused_not_passed(repo):
    """A range that inspects nothing is the shape every guard here refuses."""
    result = check(repo, labelled=False)
    assert result.returncode == 2 and "changes no files" in result.stdout
