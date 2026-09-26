#!/usr/bin/env python3
"""Secret scan that proves, on every run, that it can see what it is looking for.

The CI secret scan this replaces ran for months and inspected nothing. It went through the
pre-commit hook, whose entry is ``gitleaks protect --staged`` — correct on a laptop at commit
time, where the change is staged — but a CI checkout is clean. Nothing is staged, so the
scanner read no input and reported success on every run. A scanner's "no findings" output is
identical whether it found nothing or read nothing, and every audit that trusted the green
result confirmed the error. The local hook stays; this is what CI runs instead.

Four properties, each of which is a fault test in ``tests/guards/test_secret_scan.py``:

1. **It scans commits, not the staging area** — ``gitleaks detect --log-opts=<base>..HEAD``.
2. **The tool is pinned by version and SHA-256**, verified against the checksum on every run,
   cached tarball included. A mismatch deletes the tarball and refuses.
3. **A canary runs first.** Fake tokens are generated at run time, planted in a throwaway
   repository under every source tree this project has (derived from git, never hand-listed),
   and scanned with the REAL config. Every one must be found. This proves the scanner reads
   input and that the config has not been widened — an allowlist that exempts one directory
   fails the canary for that directory. The audit that motivated this found exactly that hole.
4. **It fails closed** on a checksum mismatch, a canary miss, an unresolvable ref, a range with
   an empty side, a range with no commits, a download that never completes, and any crash. The
   exit codes are distinct on purpose: a leak and an inability to scan must never share one,
   because that is how a fix to a silent check becomes silent itself. Python's own exit code
   for an uncaught exception is 1, the leak code, so no exception is left uncaught.

Baseline: a fresh project's root commit. There is no ignore list — an ignore list is an
exemption that only ever grows. If history is ever triaged, record that commit and pass
``--baseline``; everything reachable from it is excluded (``<range> ^<baseline>``).

Usage:
    python3 scripts/secret_scan.py --auto                # CI event range, or origin/main..HEAD
    python3 scripts/secret_scan.py --base origin/main    # explicit range base
    python3 scripts/secret_scan.py --all                 # full history (first triage)
    python3 scripts/secret_scan.py --canary-only         # prove the scanner can see, and stop

Exit codes: 0 clean · 1 secret found · 2 refused (could not scan — treat as a failure).
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".gitleaks.toml"

# Pinned. The checksums below were verified against the real tarballs, not copied from the
# release page — bump the version and re-verify every one of them by hand.
VERSION = "8.30.1"
CHECKSUMS = {
    "darwin_arm64": "b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5",
    "darwin_x64": "dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709",
    "linux_arm64": "e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080",
    "linux_x64": "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb",
}
RELEASES = "https://github.com/gitleaks/gitleaks/releases/download"
CACHE = Path(os.environ.get("SECRET_SCAN_CACHE", Path.home() / ".cache" / "secret-scan"))
# A proxy can cut a download short: through an agent sandbox's proxy, 3 in a row stopped a few
# KB before the end. Attempts after the first resume where the last stopped. The checksum decides
# whether a tarball is used; the attempts only decide whether one arrives.
DOWNLOAD_ATTEMPTS = 5
RETRY_PAUSE_SECONDS = 2.0

# GitHub's "no previous commit" marker on the first push to a ref. Genuinely means "there is
# no base", not "the base is missing" — so it is the one unresolvable value that is handled
# rather than refused: it triggers a full-history scan, stated out loud.
NULL_SHA = "0" * 40

EXIT_CLEAN, EXIT_LEAK, EXIT_REFUSED = 0, 1, 2


class ScanRefusedError(RuntimeError):
    """The scan could not be performed. Never reported as clean."""


def _git(*args: str, cwd: Path = ROOT) -> str:
    done = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False, timeout=120
    )
    if done.returncode != 0:
        raise ScanRefusedError(
            f"git {' '.join(args)} failed — {done.stderr.strip() or 'no stderr'}"
        )
    return done.stdout


def _platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    key = f"{system}_{arch}"
    if key not in CHECKSUMS:
        raise ScanRefusedError(
            f"no pinned checksum for platform {key!r}; add one after verifying it"
        )
    return key


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _https_only_opener() -> urllib.request.OpenerDirector:
    """An opener that can speak HTTPS and follow redirects, and nothing else.

    `urlopen` accepts any scheme, so a URL assembled at run time could name `file://` and
    read a local file into the tarball slot. This opener has no handler for file, http or
    ftp: an unexpected scheme is an error, by construction rather than by inspection. The
    release URL is built from constants, but the property should not depend on that.
    """
    opener = urllib.request.OpenerDirector()
    for handler in (
        # HTTPS_PROXY / NO_PROXY from the environment: a corporate proxy, or an agent sandbox
        # whose only way out is its proxy. It tunnels HTTPS and adds no scheme: a proxied
        # http:// or ftp:// URL still finds no handler and is refused.
        urllib.request.ProxyHandler(),
        urllib.request.HTTPSHandler(),
        urllib.request.HTTPRedirectHandler(),  # github.com redirects release assets
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
        # Without this, a scheme nobody handles returns None instead of raising — a bare
        # OpenerDirector fails OPEN. The fault test caught exactly that.
        urllib.request.UnknownHandler(),
    ):
        opener.add_handler(handler)
    return opener


def _download(url: str, dest: Path) -> None:
    """Fetch url into dest, resuming a transfer that arrives short.

    A short read raises http.client.IncompleteRead, which is not an OSError: it escaped the
    old handler and crashed the scan with exit 1, the LEAK code. A proxy that cuts transfers
    short tends to cut them all at about the same point, so a plain retry fails the same way:
    the next attempt asks only for the missing bytes (an HTTP Range request) and starts over
    if the server answers with the whole file instead. Nothing is written until the whole
    body has arrived, and the checksum decides whether it is used.
    """
    body = b""
    last: Exception | None = None
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        request = urllib.request.Request(url)
        if body:
            request.add_header("Range", f"bytes={len(body)}-")
        try:
            with _https_only_opener().open(request, timeout=60) as response:
                kept = body if response.status == 206 else b""  # 206: the range was honoured
                try:
                    body = kept + response.read()
                except http.client.IncompleteRead as exc:
                    body = kept + exc.partial
                    raise
        except (OSError, http.client.HTTPException) as exc:
            last = exc
            if attempt < DOWNLOAD_ATTEMPTS:
                time.sleep(RETRY_PAUSE_SECONDS)
            continue
        dest.write_bytes(body)
        return
    raise ScanRefusedError(
        f"could not download {url} in {DOWNLOAD_ATTEMPTS} attempt(s) — last error: {last!r}"
    )


def ensure_binary() -> Path:
    """The pinned gitleaks, verified by checksum on EVERY run — the cache is not trusted."""
    key = _platform_key()
    expected = CHECKSUMS[key]
    version_dir = CACHE / VERSION
    version_dir.mkdir(parents=True, exist_ok=True)
    tarball = version_dir / f"gitleaks_{VERSION}_{key}.tar.gz"
    binary = version_dir / f"gitleaks-{key}"

    if not tarball.is_file():
        _download(f"{RELEASES}/v{VERSION}/gitleaks_{VERSION}_{key}.tar.gz", tarball)

    actual = _sha256(tarball)
    if actual != expected:
        tarball.unlink(missing_ok=True)
        binary.unlink(missing_ok=True)
        raise ScanRefusedError(
            f"checksum mismatch for gitleaks {VERSION} ({key}): expected {expected}, got "
            f"{actual}. The tarball has been deleted. A tampered cache is refused, never used."
        )

    if not binary.is_file():
        with tarfile.open(tarball, "r:gz") as archive:
            member = archive.getmember("gitleaks")
            with archive.extractfile(member) as source, binary.open("wb") as target:
                shutil.copyfileobj(source, target)
        binary.chmod(0o755)
    return binary


WORKTREE = "WORKTREE"  # sentinel: scan the tracked files, because there is no commit yet


def _run_gitleaks(binary: Path, cwd: Path, log_opts: str | None) -> list[dict]:
    """Run a scan and return its findings. Any failure to SCAN is a refusal, not a clean."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as report:
        report_path = Path(report.name)
    try:
        command = [
            str(binary),
            "detect",
            "--no-banner",
            "--source",
            str(cwd),
            "--config",
            str(CONFIG),
            "--report-format",
            "json",
            "--report-path",
            str(report_path),
            "--exit-code",
            "0",
        ]
        if log_opts == WORKTREE:
            command.append("--no-git")
        elif log_opts is not None:
            command.append(f"--log-opts={log_opts}")
        done = subprocess.run(command, capture_output=True, text=True, check=False, timeout=600)
        if done.returncode != 0:
            raise ScanRefusedError(
                f"gitleaks exited {done.returncode} — {done.stderr.strip()[-400:] or 'no stderr'}"
            )
        text = report_path.read_text(encoding="utf-8").strip()
        return json.loads(text) if text else []
    finally:
        report_path.unlink(missing_ok=True)


def source_trees() -> list[str]:
    """Every top-level directory git tracks. Derived, so a new tree cannot be forgotten."""
    names = {line.split("/", 1)[0] for line in _git("ls-files").splitlines() if "/" in line}
    return sorted(names)


def _fake_token() -> str:
    # A well-formed GitHub token, generated at run time. Never a literal: a literal would live
    # in this repository, where the scanner it tests would then find it.
    return "ghp_" + os.urandom(18).hex()


def canary(binary: Path) -> tuple[int, int]:
    """Plant a fake secret in every source tree and require every one to be found.

    Returns (found, planted). A shortfall is a refusal: either the scanner is not reading
    input or the config has been widened, and neither may be reported as clean.
    """
    trees = source_trees()
    if not trees:
        raise ScanRefusedError(
            "no source trees found via git ls-files — nothing to plant a canary in"
        )
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "canary"
        repo.mkdir()
        _git("init", "-q", "-b", "main", cwd=repo)
        _git("config", "user.email", "canary@example.invalid", cwd=repo)
        _git("config", "user.name", "canary", cwd=repo)
        _git("config", "commit.gpgsign", "false", cwd=repo)
        planted: list[str] = []
        for tree in [*trees, "."]:
            target = repo / tree / "canary.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f'token = "{_fake_token()}"\n', encoding="utf-8")
            planted.append(target.relative_to(repo).as_posix())
        _git("add", "-A", cwd=repo)
        _git("commit", "-q", "-m", "canary", cwd=repo)
        findings = _run_gitleaks(binary, repo, "--all")
        found_in = {f.get("File", "") for f in findings}
        missed = [p for p in planted if p not in found_in]
        if missed:
            raise ScanRefusedError(
                "canary MISSED — the scanner did not see a planted secret in: "
                + ", ".join(missed)
                + ". Either it is not reading input or .gitleaks.toml has been widened to "
                "exempt that tree. Fix the config; never widen it further."
            )
        return len(planted) - len(missed), len(planted)


def scan_tracked_files(binary: Path) -> list[dict]:
    """Scan a copy of the tracked files. Never the checkout itself: --no-git walks everything."""
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "tracked"
        for line in _git("ls-files").splitlines():
            source = ROOT / line
            if not source.is_file():
                continue
            target = staging / line
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        return _run_gitleaks(binary, staging, WORKTREE)


def resolve_range(base: str | None, scan_all: bool) -> tuple[str | None, int]:
    """(log_opts, commit_count). Refuses anything that would scan nothing."""
    if scan_all:
        count = int(_git("rev-list", "--count", "--all").strip() or 0)
        if count == 0:
            # A freshly generated project: everything staged, nothing committed, and the
            # adopter is told to run the gate BEFORE the first commit. Refusing here would
            # make a fresh project red on day one, which teaches people to skip the gate.
            # So the tracked files are scanned — exactly what is about to be committed —
            # and the run says so. Untracked trees (a virtualenv, node_modules) are never
            # read: the scan runs over a COPY of the tracked files, not the checkout.
            tracked = [line for line in _git("ls-files").splitlines() if line]
            if not tracked:
                raise ScanRefusedError("the repository has no commits and tracks no files")
            print(f"secret-scan: no commits yet — scanning the {len(tracked)} tracked file(s)")
            return WORKTREE, len(tracked)
        return "--all", count
    if base is None or not base.strip():
        raise ScanRefusedError(
            "no base given. An empty base turns '<base>..HEAD' into '..HEAD', which git reads "
            "as HEAD..HEAD: zero commits, reported clean. Pass --base, --all or --auto."
        )
    if base == NULL_SHA:
        print("secret-scan: base is the null sha (first push to this ref) — scanning full history")
        return resolve_range(None, scan_all=True)
    for ref in (base, "HEAD"):
        done = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if done.returncode != 0:
            raise ScanRefusedError(
                f"ref {ref!r} does not resolve to a commit. Fetch it (a shallow clone has no "
                f"merge base) and re-run — an unknown ref is refused, not scanned as empty."
            )
    count = int(_git("rev-list", "--count", f"{base}..HEAD").strip() or 0)
    if count == 0:
        raise ScanRefusedError(
            f"the range {base}..HEAD contains no commits. Refused rather than reported clean: "
            f"a range that inspects nothing is the exact shape this scan exists to prevent."
        )
    return f"{base}..HEAD", count


def auto_base() -> tuple[str | None, bool]:
    """Pick the range from the CI event, or from origin/main locally. Says which."""
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    if event == "pull_request" and os.environ.get("GITHUB_BASE_REF"):
        base = f"origin/{os.environ['GITHUB_BASE_REF']}"
        print(f"secret-scan: pull request — base {base}")
        return base, False
    if event == "push" and os.environ.get("GITHUB_EVENT_BEFORE"):
        before = os.environ["GITHUB_EVENT_BEFORE"]
        print(f"secret-scan: push — base {before[:12]}")
        return before, False
    if event == "schedule":
        # main against itself is an empty range, which the scan rightly refuses; a scheduled
        # run has no diff to own, so it re-reads the whole history instead.
        print("secret-scan: scheduled run — full history")
        return None, True
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "origin/main^{commit}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if probe.returncode == 0:
        print("secret-scan: local — base origin/main")
        return "origin/main", False
    print("secret-scan: no origin/main — scanning full history")
    return None, True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--auto", action="store_true", help="derive the range from CI or origin/main")
    mode.add_argument("--base", help="scan <base>..HEAD")
    mode.add_argument("--all", action="store_true", help="scan the full history")
    mode.add_argument("--canary-only", action="store_true", help="run the canary and stop")
    parser.add_argument("--baseline", help="exclude commits reachable from this triaged commit")
    parser.add_argument("--skip-canary", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if not CONFIG.is_file():
        print(f"secret-scan: REFUSED — {CONFIG.name} is missing; the scan would use no config")
        return EXIT_REFUSED

    try:
        binary = ensure_binary()
        print(f"secret-scan: gitleaks {VERSION} verified by checksum ({_platform_key()})")

        if not args.skip_canary:
            found, planted = canary(binary)
            print(f"secret-scan: canary {found}/{planted} planted token(s) found across every tree")
        if args.canary_only:
            return EXIT_CLEAN

        base, scan_all = (args.base, args.all)
        if args.auto:
            base, scan_all = auto_base()
        elif base is None and not scan_all:
            parser.error("one of --auto, --base, --all or --canary-only is required")
        log_opts, commits = resolve_range(base, scan_all)
        if log_opts == WORKTREE:
            findings = scan_tracked_files(binary)
        else:
            if args.baseline:
                log_opts = f"{log_opts} ^{args.baseline}"
            findings = _run_gitleaks(binary, ROOT, log_opts)
    except ScanRefusedError as exc:
        print(f"secret-scan: REFUSED — {exc}")
        return EXIT_REFUSED

    unit = "tracked file(s), working tree" if log_opts == WORKTREE else f"commit(s) in {log_opts}"
    print(f"secret-scan: inspected {commits} {unit}")
    if findings:
        print(f"\nsecret-scan: FAILED — {len(findings)} secret(s) in the scanned range:\n")
        for finding in findings:
            print(
                f"  ✗ {finding.get('File')}:{finding.get('StartLine')}  "
                f"{finding.get('RuleID')}  (commit {str(finding.get('Commit', ''))[:12]})"
            )
        print(
            "\nRotate the credential first — it is already in history. Then remove it from the\n"
            "commits (rewriting the branch) and re-push. Do not add it to an allowlist."
        )
        return EXIT_LEAK
    print(
        "secret-scan: OK — no secret in the scanned range, and the canary proved the "
        "scanner can see."
    )
    return EXIT_CLEAN


def run() -> int:
    """main(), with every crash reported as a refusal (2), never as a leak (1)."""
    try:
        return main()
    except Exception as exc:  # every crash means "could not scan"
        print(f"secret-scan: REFUSED — the scan crashed: {exc!r}")
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(run())
