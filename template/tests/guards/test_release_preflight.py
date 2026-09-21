"""Tagging bypasses every other control, so the preflight must fail closed.

A tag is an ordinary git command: it does not go through a pull request, code-owner review, or
the merge gate. The preflight is the check that runs at that boundary, which makes its failure
modes unusually costly — a preflight that passes because it *could not check* something is worse
than none, since the release then carries a green tick nobody earned.

Each test builds a real sandbox repository with a real origin and runs the real script.
"""

from __future__ import annotations

import os
import stat

from conftest import SCRIPTS, git_commit, git_init, install_guard, run, run_guard, write

GUARD = SCRIPTS / "release_preflight.py"

CHANGELOG = """# Changelog

## [Unreleased]

## [1.2.3] - 2026-07-31

### Added

- A thing.
"""

CURRENT_STATE = """# Current State

Version 1.2.3.

```
scripts/                    guards
```
"""

GATES = ("prod_readiness.py", "dod-check.py", "standards_check.py")


def _fake_gh(tmp_path, stdout: str = "[]", exit_code: int = 0):
    """A stub `gh` earlier on PATH, so the release-hold check is deterministic.

    Returns the PATH override; the real `gh` may or may not exist on the machine running these
    tests, and a check whose result depends on that is not a test. It lives OUTSIDE the sandbox
    work tree — an untracked file inside it would trip the preflight's own clean-tree check.
    """
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(f"#!/bin/sh\ncat <<'EOF'\n{stdout}\nEOF\nexit {exit_code}\n")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return {"PATH": f"{bin_dir}:{os.environ['PATH']}"}


def _repo(tmp_path, *, changelog: str = CHANGELOG):
    """A sandbox repo with the guards the preflight runs, plus a real `origin`."""
    work = tmp_path / "work"
    guard = install_guard(work, "release_preflight.py")
    for name in GATES:
        install_guard(work, name)
    write(work / "CHANGELOG.md", changelog)
    write(work / "README.md", "# Sandbox\n\nVersion 1.2.3.\n")
    write(work / "docs" / "architecture" / "current-state.md", CURRENT_STATE)

    origin = tmp_path / "origin.git"
    run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], tmp_path)
    git_init(work)
    git_commit(work, "initial")
    run(["git", "remote", "add", "origin", str(origin)], work)
    run(["git", "push", "-q", "origin", "main"], work)
    run(["git", "fetch", "-q", "origin"], work)
    return work, guard


def _preflight(guard, *args, env=None):
    return run_guard(guard, "--tag", "v1.2.3", *args, env=env)


# --- The happy path must actually be reachable ----------------------------------------------


def test_a_releasable_state_passes(tmp_path):
    """Without this, every check below would pass on a guard that fails unconditionally."""
    work, guard = _repo(tmp_path)
    result = _preflight(guard, env=_fake_gh(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr


# --- Tag hygiene -----------------------------------------------------------------------------


def test_a_malformed_tag_is_rejected(tmp_path):
    work, guard = _repo(tmp_path)
    result = run_guard(guard, "--tag", "1.2.3", env=_fake_gh(tmp_path))
    assert result.returncode != 0, "a tag without the v prefix is not a release tag"


def test_an_existing_tag_is_rejected(tmp_path):
    """Re-pointing a published tag silently changes what that version means for everyone."""
    work, guard = _repo(tmp_path)
    run(["git", "tag", "v1.2.3"], work)
    result = _preflight(guard, env=_fake_gh(tmp_path))
    assert result.returncode != 0, "an existing tag must not be re-cut"
    assert "already exists" in result.stdout


def test_at_tag_mode_requires_the_tag_to_exist(tmp_path):
    """The CI direction is the opposite of the local one, so it is checked separately."""
    work, guard = _repo(tmp_path)
    result = _preflight(guard, "--mode", "at-tag", env=_fake_gh(tmp_path))
    assert result.returncode != 0, "at-tag mode with no tag must fail"
    assert "does not exist" in result.stdout


def test_at_tag_mode_passes_when_the_tag_is_head(tmp_path):
    work, guard = _repo(tmp_path)
    run(["git", "tag", "v1.2.3"], work)
    result = _preflight(guard, "--mode", "at-tag", env=_fake_gh(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr


def test_at_tag_mode_rejects_a_tag_that_is_not_head(tmp_path):
    work, guard = _repo(tmp_path)
    run(["git", "tag", "v1.2.3"], work)
    write(work / "later.txt", "later\n")
    git_commit(work, "a commit after the tag")
    result = _preflight(guard, "--mode", "at-tag", env=_fake_gh(tmp_path))
    assert result.returncode != 0, "the release must describe the tree that was tagged"


# --- The tree and the branch -----------------------------------------------------------------


def test_a_dirty_tree_is_rejected(tmp_path):
    work, guard = _repo(tmp_path)
    write(work / "scratch.txt", "uncommitted\n")
    result = _preflight(guard, env=_fake_gh(tmp_path))
    assert result.returncode != 0, "a tag on a dirty tree does not describe what was built"


def test_a_commit_not_on_the_default_branch_is_rejected(tmp_path):
    """The same invariant the release workflow enforces, caught before the tag is pushed."""
    work, guard = _repo(tmp_path)
    run(["git", "switch", "-q", "-c", "feat/unmerged"], work)
    write(work / "feature.txt", "unreviewed\n")
    git_commit(work, "unreviewed work")
    result = _preflight(guard, env=_fake_gh(tmp_path))
    assert result.returncode != 0, "a tag must be cut from the default branch"
    assert "not reachable" in result.stdout


# --- Release notes ---------------------------------------------------------------------------


def test_a_missing_changelog_entry_is_rejected(tmp_path):
    work, guard = _repo(tmp_path, changelog="# Changelog\n\n## [Unreleased]\n\n- pending\n")
    result = _preflight(guard, env=_fake_gh(tmp_path))
    assert result.returncode != 0, "a release with no notes cannot be evaluated downstream"
    assert "CHANGELOG.md" in result.stdout


# --- Holds -----------------------------------------------------------------------------------


def test_an_open_release_blocker_denies_the_release(tmp_path):
    work, guard = _repo(tmp_path)
    blocker = '[{"number": 7, "title": "auth rewrite unfinished"}]'
    result = _preflight(guard, env=_fake_gh(tmp_path, stdout=blocker))
    assert result.returncode != 0, "an open release-blocker issue must deny the release"
    assert "release-blocker" in result.stdout


def test_an_unreadable_hold_is_treated_as_an_active_one(tmp_path):
    """'I could not check' must never be reported as 'all clear'."""
    work, guard = _repo(tmp_path)
    result = _preflight(guard, env=_fake_gh(tmp_path, stdout="", exit_code=1))
    assert result.returncode != 0, "a failing hold lookup must fail the preflight"


def test_a_missing_gh_fails_closed(tmp_path):
    """With no `gh` at all the holds cannot be read, so the release does not proceed."""
    _work, guard = _repo(tmp_path)
    empty = tmp_path / "emptybin"
    empty.mkdir(parents=True, exist_ok=True)
    result = _preflight(guard, env={"PATH": str(empty)})
    assert result.returncode != 0, "a missing gh must fail closed, not be skipped"
    assert "is not installed" in result.stdout, "and it must say so, not fail for another reason"


# --- The release-boundary gates --------------------------------------------------------------


def test_an_open_production_blocker_denies_the_release(tmp_path):
    """prod_readiness is advisory during development and blocking at the release boundary."""
    work, guard = _repo(tmp_path)
    register = (work / "scripts" / "prod_readiness.py").read_text()
    (work / "scripts" / "prod_readiness.py").write_text(
        register.replace(
            "BLOCKERS: tuple[tuple[str, str], ...] = ()",
            'BLOCKERS: tuple[tuple[str, str], ...] = (("auth-stub", "replace before launch"),)',
        )
    )
    write(work / "app.py", "# PROD-" + "BLOCKER(auth-stub): dev-only\n")
    git_commit(work, "add a stub")
    result = _preflight(guard, env=_fake_gh(tmp_path))
    assert result.returncode != 0, "an open production blocker must deny the release"
    assert "production-readiness" in result.stdout


def test_drifting_docs_deny_the_release(tmp_path):
    work, guard = _repo(tmp_path)
    write(work / "docs" / "GUIDE.md", "See `scripts/does_not_exist.py` for details.\n")
    git_commit(work, "add a stale reference")
    result = _preflight(guard, env=_fake_gh(tmp_path))
    assert result.returncode != 0, "documentation drift must deny the release"
    assert "documentation consistency" in result.stdout


def test_a_dishonest_standard_denies_the_release(tmp_path):
    work, guard = _repo(tmp_path)
    write(
        work / "docs" / "standards" / "test.md",
        "| ID | Rule | Enforcement | Mechanism |\n|---|---|---|---|\n"
        "| BE-001 | A rule. | `[CI]` | `scripts/absent.py` |\n",
    )
    git_commit(work, "add a dishonest standard")
    result = _preflight(guard, env=_fake_gh(tmp_path))
    assert result.returncode != 0, "a standard claiming a gate that does not exist must deny it"
    assert "standards enforcement honesty" in result.stdout
