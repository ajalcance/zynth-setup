"""The secret scan must prove it can see — and refuse whenever it cannot.

The scan this replaced reported success for months while reading nothing: it ran through a
pre-commit hook whose entry scans the STAGING AREA, and a CI checkout has nothing staged. A
scanner's "no findings" is identical whether it found nothing or read nothing.

So every test here is about one of two things: a real secret in a real commit is found, or a
scan that could not have seen anything is refused with its own exit code. The fix to a silent
check went silent three separate ways in the audit that motivated this file (a SIGPIPE, an
empty base collapsing to HEAD..HEAD, a grep exiting 1 on the case it existed to report) — so
the matrix below is exhaustive on purpose, and each row asserts a marker only its branch prints.

The binary is downloaded once per session into a shared cache and checksum-verified on every
run, exactly as in CI. These tests need the network the first time; so does the actionlint
step in the same job.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

import pytest
from conftest import (
    REPO_ROOT,
    SCRIPTS,
    git_commit,
    git_init,
    install_guard,
    run,
    run_guard,
    write,
)

GUARD = SCRIPTS / "secret_scan.py"
CONFIG = REPO_ROOT / ".gitleaks.toml"

CLEAN, LEAK, REFUSED = 0, 1, 2


def _fake_token() -> str:
    """A well-formed GitHub token built at RUNTIME so no literal exists in this file."""
    return "ghp_" + os.urandom(18).hex()


@pytest.fixture(scope="session")
def cache(tmp_path_factory) -> dict[str, str]:
    """One download per session. The scan verifies the checksum on every run regardless."""
    return {"SECRET_SCAN_CACHE": str(tmp_path_factory.mktemp("secret-scan-cache"))}


def _with_allowlisted_paths(patterns: list[str]) -> str:
    """The real config with its `paths` allowlist REPLACED: a widened config, not a broken one.

    Appending a second allowlist table is malformed TOML; gitleaks then errors, which is a
    refusal too, but it would exercise the wrong branch. The widening has to be well-formed.
    """
    body = CONFIG.read_text()
    quote = "'" * 3
    replacement = "paths = [\n" + "".join(f"  {quote}{p}{quote},\n" for p in patterns) + "]"
    widened, count = re.subn(r"paths\s*=\s*\[.*?\]", replacement, body, count=1, flags=re.S)
    assert count == 1, "the config has no paths allowlist to widen"
    return widened


def _planted(stdout: str) -> int:
    match = re.search(r"canary (\d+)/(\d+)", stdout)
    assert match, stdout
    return int(match.group(2))


def _sandbox(tmp_path: Path, *, config: Path = CONFIG) -> Path:
    """A repository with the real scanner, the real config, one source tree and one commit."""
    guard = install_guard(tmp_path, "secret_scan.py")
    shutil.copy2(config, tmp_path / ".gitleaks.toml")
    git_init(tmp_path)
    write(tmp_path / "backend" / "main.py", "x = 1\n")
    git_commit(tmp_path, "base")
    return guard


# --- The scanner can see, and the tree this project ships is clean ----------------------


def test_the_canary_finds_a_planted_token_in_every_tree(cache):
    result = run_guard(GUARD, "--canary-only", cwd=REPO_ROOT, env=cache)
    assert result.returncode == CLEAN, result.stdout + result.stderr
    assert "verified by checksum" in result.stdout
    assert "canary" in result.stdout and "found across every tree" in result.stdout


def test_the_history_this_project_ships_is_clean(cache):
    """A fresh project must pass its own scan, or an adopter's first lesson is to skip it."""
    result = run_guard(GUARD, "--all", cwd=REPO_ROOT, env=cache)
    assert result.returncode == CLEAN, result.stdout + result.stderr
    # Two legitimate denominators: commits once history exists, tracked files before the
    # first commit. Either is a real count; what is never acceptable is neither.
    assert "inspected" in result.stdout, result.stdout
    assert "commit(s)" in result.stdout or "tracked file(s)" in result.stdout, result.stdout


# --- A real secret in a real commit is found ----------------------------------------------


def test_a_committed_secret_is_found(tmp_path, cache):
    """The positive control: if this ever passes, the scanner is blind and nothing else matters."""
    guard = _sandbox(tmp_path)
    write(tmp_path / "backend" / "settings.py", f'TOKEN = "{_fake_token()}"\n')
    git_commit(tmp_path, "oops")
    result = run_guard(guard, "--base", "HEAD~1", cwd=tmp_path, env=cache)
    assert result.returncode == LEAK, result.stdout + result.stderr
    assert "backend/settings.py" in result.stdout
    assert "Rotate the credential" in result.stdout


def test_the_ci_shape_is_not_blind(tmp_path, cache):
    """The exact bug: a committed secret on a CLEAN tree — nothing staged — must still be found.

    The staged-only scan passes this case. That is how it read nothing for months.
    """
    guard = _sandbox(tmp_path)
    write(tmp_path / "backend" / "settings.py", f'TOKEN = "{_fake_token()}"\n')
    git_commit(tmp_path, "oops")  # committed, tree clean, index empty
    status = run_guard(guard, "--base", "HEAD~1", cwd=tmp_path, env=cache)
    assert status.returncode == LEAK, "a committed secret on a clean tree was not found"


def test_a_secret_outside_the_range_is_not_reported(tmp_path, cache):
    """The range is honoured, or every scan re-reports history and the signal drowns."""
    guard = _sandbox(tmp_path)
    write(tmp_path / "backend" / "old.py", f'OLD = "{_fake_token()}"\n')
    git_commit(tmp_path, "old leak")
    write(tmp_path / "backend" / "new.py", "y = 2\n")
    git_commit(tmp_path, "clean change")
    result = run_guard(guard, "--base", "HEAD~1", cwd=tmp_path, env=cache)
    assert result.returncode == CLEAN, result.stdout
    assert "inspected 1 commit(s)" in result.stdout


# --- A widened config fails the canary ----------------------------------------------------


def test_an_allowlisted_directory_fails_the_canary(tmp_path, cache):
    """An allowlist widened for one tree is exactly what the canary exists to catch.

    The config this template shipped for months allowlisted every Markdown file under docs/;
    a real token pasted into a decision record passed. The canary plants in every tree, so
    the exemption fails the run for that tree by name.
    """
    widened = tmp_path / "widened.toml"
    widened.write_text(_with_allowlisted_paths(["backend/.*"]))
    guard = _sandbox(tmp_path, config=widened)
    result = run_guard(guard, "--canary-only", cwd=tmp_path, env=cache)
    assert result.returncode == REFUSED, result.stdout
    assert "canary MISSED" in result.stdout and "backend/canary.txt" in result.stdout


def test_a_config_that_allows_everything_fails_the_canary(tmp_path, cache):
    everything = tmp_path / "everything.toml"
    everything.write_text(_with_allowlisted_paths([".*"]))
    guard = _sandbox(tmp_path, config=everything)
    result = run_guard(guard, "--canary-only", cwd=tmp_path, env=cache)
    assert result.returncode == REFUSED
    assert "canary MISSED" in result.stdout


def test_source_trees_are_derived_not_hand_listed(tmp_path, cache):
    """A tree added tomorrow must be planted in tomorrow, without anyone editing a list."""
    guard = _sandbox(tmp_path)
    before = _planted(run_guard(guard, "--canary-only", cwd=tmp_path, env=cache).stdout)
    write(tmp_path / "brand_new_service" / "svc.py", "z = 3\n")
    git_commit(tmp_path, "new tree")
    result = run_guard(guard, "--canary-only", cwd=tmp_path, env=cache)
    assert result.returncode == CLEAN, result.stdout
    assert _planted(result.stdout) == before + 1, result.stdout


# --- Every way to scan nothing is refused, with its own message -----------------------------


def test_an_empty_base_is_refused(tmp_path, cache):
    """'..HEAD' is HEAD..HEAD to git: zero commits, reported clean. That is the SIGPIPE family."""
    guard = _sandbox(tmp_path)
    result = run_guard(guard, "--skip-canary", "--base", "", cwd=tmp_path, env=cache)
    assert result.returncode == REFUSED
    assert "no base given" in result.stdout


def test_an_unknown_ref_is_refused(tmp_path, cache):
    guard = _sandbox(tmp_path)
    result = run_guard(guard, "--skip-canary", "--base", "no-such-ref", cwd=tmp_path, env=cache)
    assert result.returncode == REFUSED
    assert "does not resolve to a commit" in result.stdout


def test_a_zero_commit_range_is_refused(tmp_path, cache):
    guard = _sandbox(tmp_path)
    result = run_guard(guard, "--skip-canary", "--base", "HEAD", cwd=tmp_path, env=cache)
    assert result.returncode == REFUSED
    assert "contains no commits" in result.stdout


def test_a_missing_config_is_refused(tmp_path, cache):
    guard = _sandbox(tmp_path)
    (tmp_path / ".gitleaks.toml").unlink()
    result = run_guard(guard, "--all", cwd=tmp_path, env=cache)
    assert result.returncode == REFUSED
    assert "is missing" in result.stdout


def test_a_tampered_cache_is_refused_and_deleted(tmp_path, cache):
    """The cache is re-verified on every run. A mismatch is refused, and the tarball removed."""
    guard = _sandbox(tmp_path)
    assert run_guard(guard, "--canary-only", cwd=tmp_path, env=cache).returncode == CLEAN
    tarballs = list(Path(cache["SECRET_SCAN_CACHE"]).rglob("*.tar.gz"))
    assert tarballs, "the cache holds no tarball after a successful run"
    with tarballs[0].open("ab") as handle:
        handle.write(b"x")
    result = run_guard(guard, "--canary-only", cwd=tmp_path, env=cache)
    assert result.returncode == REFUSED, result.stdout
    assert "checksum mismatch" in result.stdout
    assert not tarballs[0].exists(), "a tampered tarball must be deleted, not kept for next time"
    # And the next run recovers by downloading afresh.
    assert run_guard(guard, "--canary-only", cwd=tmp_path, env=cache).returncode == CLEAN


def test_the_null_sha_means_full_history_not_refusal(tmp_path, cache):
    """GitHub sends 40 zeros as `before` on the first push. It means no base, not a bad one."""
    guard = _sandbox(tmp_path)
    result = run_guard(guard, "--skip-canary", "--base", "0" * 40, cwd=tmp_path, env=cache)
    assert result.returncode == CLEAN, result.stdout
    assert "scanning full history" in result.stdout


def test_exit_codes_are_distinct(tmp_path, cache):
    """A leak and an inability to scan must never share an exit code.

    Under `set -e`, a grep that exits 1 on zero matches killed the audit's canary with the
    same code a leak uses. Distinct codes are how the caller can tell the two apart.
    """
    guard = _sandbox(tmp_path)
    write(tmp_path / "backend" / "leak.py", f'T = "{_fake_token()}"\n')
    git_commit(tmp_path, "leak")
    leak = run_guard(guard, "--skip-canary", "--base", "HEAD~1", cwd=tmp_path, env=cache)
    refused = run_guard(guard, "--skip-canary", "--base", "HEAD", cwd=tmp_path, env=cache)
    assert leak.returncode == LEAK and refused.returncode == REFUSED
    assert leak.returncode != refused.returncode


# --- The wiring -------------------------------------------------------------------------


def test_the_scan_is_in_the_one_gate_list():
    """A scanner nothing runs scans nothing, however correct it is."""
    body = (REPO_ROOT / "Makefile").read_text()
    assert "scripts/secret_scan.py --auto" in body, "secret_scan.py is not in `make policy`"


def test_ci_does_not_let_the_staged_scan_print_passed():
    """The decorative hook must be skipped in CI, or its Passed line hides the real one."""
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "SKIP: gitleaks" in ci, (
        "the pre-commit gitleaks hook runs in CI: it scans the staging area, which is empty "
        "on a checkout, and prints Passed — which is the bug this file exists to prevent"
    )


def test_ci_passes_the_push_base_to_the_scan():
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "GITHUB_EVENT_BEFORE" in ci, "on a push the scan cannot know its range without this"


def test_the_config_allowlists_no_directory():
    """Placeholders are handled by regex. A path allowlist is an exemption that only grows."""
    import re

    body = CONFIG.read_text()
    paths = re.search(r"paths\s*=\s*\[(.*?)\]", body, re.S)
    assert paths, ".gitleaks.toml has no paths allowlist block"
    entries = re.findall(r"'''(.*?)'''", paths.group(1))
    directories = [e for e in entries if "/" in e and not e.endswith("example$")]
    assert not directories, f"whole directories are allowlisted: {directories}"


# --- A freshly generated project: everything staged, nothing committed --------------------
#
# The adopter is told to run the gate BEFORE the first commit. Refusing there would make a
# fresh project red on day one, which teaches people to skip the gate.


def _fresh(tmp_path: Path, *, secret: bool = False) -> Path:
    guard = install_guard(tmp_path, "secret_scan.py")
    shutil.copy2(CONFIG, tmp_path / ".gitleaks.toml")
    git_init(tmp_path)
    body = f'TOKEN = "{_fake_token()}"\n' if secret else "x = 1\n"
    write(tmp_path / "backend" / "settings.py", body)
    run(["git", "add", "-A"], tmp_path)  # staged, never committed
    return guard


def test_a_fresh_project_with_no_commits_scans_its_tracked_files(tmp_path, cache):
    guard = _fresh(tmp_path)
    result = run_guard(guard, "--all", cwd=tmp_path, env=cache)
    assert result.returncode == CLEAN, result.stdout + result.stderr
    assert "no commits yet" in result.stdout and "tracked file(s)" in result.stdout


def test_a_staged_secret_in_a_fresh_project_is_found(tmp_path, cache):
    """The fallback must not be blind either: a staged token is a leak about to happen."""
    guard = _fresh(tmp_path, secret=True)
    result = run_guard(guard, "--all", cwd=tmp_path, env=cache)
    assert result.returncode == LEAK, result.stdout
    assert "backend/settings.py" in result.stdout


def test_the_fresh_project_fallback_never_reads_untracked_trees(tmp_path, cache):
    """A token inside an untracked virtualenv is a fixture in site-packages, not a leak."""
    guard = _fresh(tmp_path)
    write(tmp_path / ".gitignore", ".venv/\n")
    write(tmp_path / ".venv" / "lib" / "fixture.py", f'T = "{_fake_token()}"\n')
    result = run_guard(guard, "--all", cwd=tmp_path, env=cache)
    assert result.returncode == CLEAN, result.stdout + result.stderr
