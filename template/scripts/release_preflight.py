#!/usr/bin/env python3
"""Release preflight — refuse to cut a release that should not be cut. FAIL-CLOSED.

Tagging is the one path to production that does not go through a pull request, so it is the one
place where every other control can be bypassed by an ordinary git command. This runs the checks
that only matter at a release boundary, and it **fails when it cannot perform a check** rather
than reporting green on an unverified assumption. "I could not tell" is not "all clear".

    make release-preflight TAG=v1.2.3
    python3 scripts/release_preflight.py --tag v1.2.3

Checks:

1. **The tag is well-formed** — ``vMAJOR.MINOR.PATCH`` with an optional pre-release suffix.
   No default is supplied: a release you did not name is a release you did not mean.
2. **The tag does not already exist**, locally or on the remote. A tag is a permanent name for
   one commit; re-pointing one silently changes what "v1.2.3" means for everyone who already has it.
3. **The working tree is clean** and HEAD is reachable from the default branch — the same
   invariant the release workflow enforces, caught before you push instead of after.
4. **The changelog has an entry for this version.** A release with no notes is a release nobody
   downstream can evaluate.
5. **No production blocker is open** (``prod_readiness.py --strict``), and the documentation and
   standards guards pass. Whatever is true at merge time must still be true at release time.
6. **No open issue carries the release-blocker label.** That label is the owner's hold: while one
   is open, nothing ships. Checked through ``gh``; if ``gh`` is missing or unauthenticated the
   preflight FAILS, because an unreadable hold is indistinguishable from an active one.

Exit code is non-zero if any check fails or could not be run.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(-[0-9A-Za-z.-]+)?$")
BLOCKER_LABEL = "release-blocker"
RULE = "─" * 78


def _exec(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    """Run a command, reporting a missing tool as a failed check rather than a traceback.

    A preflight that dies on `git` not being on PATH still exits non-zero, but it exits with a
    stack trace instead of saying which check could not run — and the next person reads that as
    "the tool is broken" rather than "the release was not verified".
    """
    try:
        return subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True, check=False, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(command, 127, "", f"{command[0]}: {exc}")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return _exec(["git", *args], timeout=60)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return _exec(command, timeout=300)


def check_tag_format(tag: str, errors: list[str]) -> None:
    if not TAG_RE.match(tag):
        errors.append(
            f"'{tag}' is not a release tag — expected vMAJOR.MINOR.PATCH (optionally with a "
            f"pre-release suffix, e.g. v1.2.3-rc.1)"
        )


def check_tag_state(tag: str, mode: str, errors: list[str]) -> None:
    """Before tagging the tag must not exist; at tag time it must exist and be HEAD.

    Both directions matter and they are opposites, which is why the mode is explicit rather than
    inferred. Inferring it would make the check pass in whichever direction happened to hold.
    """
    local = _git("tag", "--list", tag).stdout.strip()
    if mode == "pre-tag":
        if local:
            errors.append(
                f"tag '{tag}' already exists locally — a tag is a permanent name for one commit. "
                f"Cut the next version instead of re-pointing this one."
            )
        remote = _git("ls-remote", "--tags", "origin", f"refs/tags/{tag}")
        if remote.returncode != 0:
            errors.append(
                "could not reach the 'origin' remote to check whether the tag already exists — "
                "a tag that exists upstream must never be re-pointed, so this cannot be skipped"
            )
        elif remote.stdout.strip():
            errors.append(
                f"tag '{tag}' already exists on origin — it has been published. "
                f"Cut the next version."
            )
        return

    if not local:
        errors.append(f"tag '{tag}' does not exist — nothing to release")
        return
    tagged = _git("rev-list", "-n", "1", tag).stdout.strip()
    head = _git("rev-parse", "HEAD").stdout.strip()
    if not tagged or not head or tagged != head:
        errors.append(
            f"tag '{tag}' points at {tagged or '<unknown>'} but HEAD is {head or '<unknown>'} — "
            f"the release would not describe the checked-out tree"
        )


def check_tree_and_branch(base_ref: str, mode: str, errors: list[str]) -> None:
    status = _git("status", "--porcelain")
    if status.returncode != 0:
        errors.append("could not read the git status — is this a git repository?")
        return
    if status.stdout.strip():
        errors.append(
            "the working tree has uncommitted changes — the tag would not describe what you built"
        )

    if mode == "pre-tag":
        fetch = _git("fetch", "--quiet", "--no-tags", "origin")
        if fetch.returncode != 0:
            errors.append(
                f"could not fetch from origin ({fetch.stderr.strip()}) — cannot verify HEAD"
            )
            return
    if _git("rev-parse", "--verify", "--quiet", base_ref).returncode != 0:
        errors.append(f"'{base_ref}' cannot be resolved — cannot verify HEAD is releasable")
        return
    ancestor = _git("merge-base", "--is-ancestor", "HEAD", base_ref)
    if ancestor.returncode != 0:
        errors.append(
            f"HEAD is not reachable from {base_ref} — a release tag must be cut from the default "
            f"branch, so that everything shipped has passed review and the merge gate"
        )


VERSION_RE_TEMPLATE = r"^##\s*\[{version}\]"


def check_changelog(tag: str, errors: list[str]) -> None:
    changelog = ROOT / "CHANGELOG.md"
    if not changelog.is_file():
        errors.append("CHANGELOG.md is missing — a release needs notes")
        return
    version = tag[1:]
    pattern = re.compile(VERSION_RE_TEMPLATE.format(version=re.escape(version)), re.MULTILINE)
    if not pattern.search(changelog.read_text(encoding="utf-8")):
        errors.append(
            f"CHANGELOG.md has no '## [{version}]' section — move the Unreleased entries under "
            f"the version you are about to publish"
        )


GATES = (
    ("production-readiness (strict)", ["prod_readiness.py", "--strict"]),
    ("documentation consistency", ["dod-check.py"]),
    ("standards enforcement honesty", ["standards_check.py"]),
)


def check_gates(errors: list[str]) -> None:
    for label, argv in GATES:
        script = SCRIPTS / argv[0]
        if not script.is_file():
            errors.append(f"{label}: {script.relative_to(ROOT)} is missing — cannot verify")
            continue
        result = _run([sys.executable, str(script), *argv[1:]])
        if result.returncode != 0:
            tail = (result.stdout + result.stderr).strip().splitlines()
            detail = tail[-1] if tail else "no output"
            errors.append(f"{label}: failed — {detail}")


def check_release_holds(repo: str | None, errors: list[str]) -> None:
    """No open issue may carry the release-blocker label.

    An unreadable hold is treated exactly like an active one. The alternative — passing when the
    check could not run — turns the owner's hold into something a broken environment can lift.
    """
    if shutil.which("gh") is None:
        errors.append(
            f"the GitHub CLI ('gh') is not installed, so open '{BLOCKER_LABEL}' issues could not "
            f"be checked. Install gh and authenticate, or run this in CI where it is available — "
            f"an unreadable hold is treated as an active one."
        )
        return
    command = ["gh", "issue", "list", "--label", BLOCKER_LABEL, "--state", "open", "--json", "number,title"]
    if repo:
        command += ["--repo", repo]
    result = _run(command)
    if result.returncode != 0:
        errors.append(
            f"could not list '{BLOCKER_LABEL}' issues ({result.stderr.strip() or 'gh failed'}) — "
            f"authenticate with 'gh auth login', then re-run"
        )
        return
    body = result.stdout.strip()
    if body and body != "[]":
        errors.append(
            f"an open '{BLOCKER_LABEL}' issue is holding this release: {body}. "
            f"Close it, or remove the label if the hold no longer applies."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="the release tag to cut, e.g. v1.2.3")
    parser.add_argument("--repo", default=None, help="owner/name, when gh cannot infer it")
    parser.add_argument(
        "--base-ref", default="origin/main", help="the default branch ref HEAD must descend from"
    )
    parser.add_argument(
        "--mode",
        choices=("pre-tag", "at-tag"),
        default="pre-tag",
        help="pre-tag: about to cut it (must not exist). at-tag: in CI (must exist and be HEAD).",
    )
    args = parser.parse_args()

    print(RULE)
    print(f"  RELEASE PREFLIGHT — {args.tag} ({args.mode})")
    print(RULE)

    errors: list[str] = []
    check_tag_format(args.tag, errors)
    check_tag_state(args.tag, args.mode, errors)
    check_tree_and_branch(args.base_ref, args.mode, errors)
    check_changelog(args.tag, errors)
    check_gates(errors)
    check_release_holds(args.repo, errors)

    if errors:
        print(f"\nrelease-preflight: FAILED — {args.tag} is not releasable\n")
        for error in errors:
            print(f"  ✗ {error}")
        print(
            "\nNothing was tagged. Every item above is a reason a release should not happen yet;\n"
            "fix the cause rather than working around the check."
        )
        return 1

    print(f"\nrelease-preflight: OK — {args.tag} is releasable.")
    print(f"  git tag -a {args.tag} -m '{args.tag}' && git push origin {args.tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
