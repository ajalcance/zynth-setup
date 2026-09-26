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

import http.client
import importlib.util
import os
import re
import shutil
import urllib.error
import urllib.request
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


def _load_guard():
    spec = importlib.util.spec_from_file_location("secret_scan", GUARD)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


PROXIES = {
    name: "http://proxy.invalid:3128"
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "FTP_PROXY", "ftp_proxy")
}


@pytest.mark.parametrize("proxied", [False, True], ids=["direct", "behind-a-proxy"])
def test_the_downloader_can_only_speak_https(proxied, monkeypatch):
    """A run-time URL is safe when the opener has no handler for anything but HTTPS.

    Behind a proxy too: routing through one must not hand http:// or ftp:// a handler.
    """
    for name in PROXIES:
        monkeypatch.delenv(name, raising=False)
    if proxied:
        for name, value in PROXIES.items():
            monkeypatch.setenv(name, value)
    opener = _load_guard()._https_only_opener()
    for url in ("file:///etc/hosts", "http://example.invalid/x", "ftp://example.invalid/x"):
        with pytest.raises(urllib.error.URLError, match="unknown url type"):
            opener.open(url, timeout=5)


def test_the_downloader_goes_through_the_proxy_it_is_given(monkeypatch):
    # Without this the scan cannot fetch gitleaks behind a corporate proxy or an agent sandbox,
    # and refuses on every run. Both spellings are cleared: Python prefers the lowercase one.
    for name in PROXIES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("https_proxy", "http://proxy.invalid:3128")
    opener = _load_guard()._https_only_opener()
    proxies = [h for h in opener.handlers if isinstance(h, urllib.request.ProxyHandler)]
    assert proxies and proxies[0].proxies.get("https") == "http://proxy.invalid:3128"


BODY = b"gitleaks-tarball"


class _Transfers:
    """An opener serving BODY. The first `short` transfers stop `cut` bytes early.

    honour_range=False plays a server that ignores Range and sends the whole file again.
    """

    def __init__(self, short: int, cut: int = 4, honour_range: bool = True) -> None:
        self.short, self.cut, self.honour_range = short, cut, honour_range
        self.ranges: list[str | None] = []

    def open(self, request, timeout):
        wanted = request.get_header("Range")
        self.ranges.append(wanted)
        start = int(wanted[len("bytes=") : -1]) if wanted and self.honour_range else 0
        payload = BODY[start:]
        short = len(self.ranges) <= self.short
        cut = self.cut

        class Response:
            status = 206 if start else 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                if short:
                    raise http.client.IncompleteRead(payload[:-cut], cut)
                return payload

        return Response()


@pytest.fixture
def guard(monkeypatch):
    module = _load_guard()
    monkeypatch.setattr(module, "RETRY_PAUSE_SECONDS", 0)
    return module


def _fetch(guard, monkeypatch, tmp_path, transfers):
    monkeypatch.setattr(guard, "_https_only_opener", lambda: transfers)
    guard._download("https://example.invalid/x", tmp_path / "t")
    return (tmp_path / "t").read_bytes()


def test_a_short_download_resumes_where_it_stopped(guard, monkeypatch, tmp_path):
    transfers = _Transfers(short=1, cut=4)
    assert _fetch(guard, monkeypatch, tmp_path, transfers) == BODY
    assert transfers.ranges == [None, f"bytes={len(BODY) - 4}-"], "did not ask for the rest"


def test_short_downloads_keep_resuming(guard, monkeypatch, tmp_path):
    # A proxy that cuts every transfer a few bytes short: each attempt adds what it got.
    transfers = _Transfers(short=guard.DOWNLOAD_ATTEMPTS - 1, cut=2)
    assert _fetch(guard, monkeypatch, tmp_path, transfers) == BODY
    assert len(transfers.ranges) == guard.DOWNLOAD_ATTEMPTS


def test_a_server_that_ignores_the_range_starts_over(guard, monkeypatch, tmp_path):
    # A 200 in answer to a Range request is the whole file: appending it would corrupt the
    # tarball (the checksum would refuse it, but only after wasting every attempt).
    transfers = _Transfers(short=1, cut=4, honour_range=False)
    assert _fetch(guard, monkeypatch, tmp_path, transfers) == BODY


def test_a_download_that_never_completes_is_refused_and_writes_nothing(
    guard, monkeypatch, tmp_path
):
    transfers = _Transfers(short=99, cut=len(BODY))
    with pytest.raises(guard.ScanRefusedError, match="IncompleteRead"):
        _fetch(guard, monkeypatch, tmp_path, transfers)
    assert len(transfers.ranges) == guard.DOWNLOAD_ATTEMPTS >= 2
    assert not (tmp_path / "t").exists(), "a partial tarball was left for the next run"


def test_any_crash_is_a_refusal_never_a_leak(guard, monkeypatch, capsys):
    # An uncaught exception exits 1 — the LEAK code. A crash means "could not scan".
    def crash() -> int:
        raise http.client.IncompleteRead(b"", 1)

    monkeypatch.setattr(guard, "main", crash)
    assert guard.run() == REFUSED
    assert "REFUSED" in capsys.readouterr().out


def test_a_crash_in_a_real_run_exits_refused(tmp_path):
    # End to end: a cache path that is a FILE makes the scan crash before it can download.
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("")
    result = run_guard(
        GUARD, "--canary-only", cwd=REPO_ROOT, env={"SECRET_SCAN_CACHE": str(blocker)}
    )
    assert result.returncode == REFUSED, result.stdout + result.stderr
    assert "REFUSED" in result.stdout


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


def test_a_scheduled_run_reads_the_whole_history(tmp_path, cache):
    """On main, origin/main..HEAD is empty; refusing it would redden every Monday."""
    guard = _sandbox(tmp_path)
    env = {
        **cache,
        "GITHUB_EVENT_NAME": "schedule",
        "GITHUB_BASE_REF": "",
        "GITHUB_EVENT_BEFORE": "",
    }
    result = run_guard(guard, "--auto", cwd=tmp_path, env=env)
    assert result.returncode == CLEAN, result.stdout + result.stderr
    assert "scheduled run — full history" in result.stdout


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
