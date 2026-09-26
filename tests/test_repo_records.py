"""The repository's records stay true: cited paths exist, releases are recorded, ADRs contiguous.

MAINTAINING.md's release section described only v3.0.0 through three later releases, and its
"add a new prompt" advice contradicted the owner tier. Records nobody checks drift.
"""

from __future__ import annotations

import os
import re
import subprocess

import pytest
from conftest import ROOT, SCRIPTS

DOCS = [
    ROOT / "CLAUDE.md",
    ROOT / "AGENTS.md",
    ROOT / "MAINTAINING.md",
    *sorted((ROOT / "docs").rglob("*.md")),
]
# A repository path: a known top-level directory or a root file. Spaces only inside a Jinja
# conditional, which is how the template's module directories are named.
SEGMENT = r"(?:[\w./-]|\{%[^%]*%\})"
CITED = re.compile(
    r"(?<![\w/.-])((?:\.claude|\.github|scripts|tests|docs|template)/" + SEGMENT + r"*[\w}]"
    r"|(?:Makefile|CLAUDE\.md|AGENTS\.md|MAINTAINING\.md|CHANGELOG\.md|copier\.yml"
    r"|requirements-selftest\.txt|\.pre-commit-config\.yaml|\.gitleaks\.toml|\.gitleaksignore))"
    r"(?=[`)\s,.:;]|$)"
)


def cited_paths() -> list[tuple[str, str]]:
    found = []
    for doc in DOCS:
        for match in CITED.finditer(doc.read_text()):
            path = match.group(1).rstrip(".")
            if "*" in path or "<" in path or path.endswith("/"):
                continue
            found.append((doc.name, path))
    return found


def test_the_docs_cite_something():
    assert (
        len(cited_paths()) > 20
    ), "the path pattern matches almost nothing — this would be vacuous"


# Files the docs discuss that exist only on a maintainer's machine, never in the repository.
MACHINE_LOCAL = {".claude/settings.local.json"}


def tracked() -> set[str]:
    """Every tracked file and every directory above one.

    Resolved against git, never the working tree: a file that exists only on the machine that
    ran the test (an ignored local settings file) passed here and failed in CI.
    """
    files = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split("\n")
    paths = set()
    for name in filter(None, files):
        parts = name.split("/")
        paths.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
    return paths


TRACKED = tracked()


def resolves(path: str) -> bool:
    """Tracked at the root, or — for a doc describing what adopters get — as the template's."""
    if path in MACHINE_LOCAL:
        return True
    candidates = (path, f"{path}.jinja", f"template/{path}", f"template/{path}.jinja")
    return any(c in TRACKED for c in candidates)


@pytest.mark.parametrize("doc,path", cited_paths())
def test_every_cited_path_exists(doc, path):
    assert resolves(path), f"{doc} cites {path}, which does not exist here or in template/"


def test_every_release_is_in_the_changelog():
    tags = subprocess.run(
        ["git", "tag", "--list", "v*"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert tags, "no tags visible — fetch with tags, or this passes over nothing"
    changelog = (ROOT / "CHANGELOG.md").read_text()
    missing = [t for t in tags if f"## [{t[1:]}]" not in changelog]
    assert not missing, f"released but never recorded in CHANGELOG.md: {missing}"


def test_the_changelog_keeps_an_unreleased_section():
    assert "## [Unreleased]" in (ROOT / "CHANGELOG.md").read_text()


def test_adr_numbers_are_contiguous_from_one():
    numbers = sorted(
        int(p.name[:4]) for p in (ROOT / "docs" / "decisions").glob("[0-9][0-9][0-9][0-9]-*.md")
    )
    assert numbers, "no ADRs found"
    assert numbers == list(range(1, len(numbers) + 1)), f"ADR numbering has a gap: {numbers}"


def test_verify_refuses_without_copier_rather_than_passing():
    result = subprocess.run(
        ["bash", str(SCRIPTS / "verify-generations.sh"), "minimal"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "COPIER": "/nonexistent/copier"},
    )
    assert result.returncode == 2 and "REFUSED" in result.stderr


def test_verify_refuses_an_unknown_variant(tmp_path):
    fake = tmp_path / "copier"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    result = subprocess.run(
        ["bash", str(SCRIPTS / "verify-generations.sh"), "no-such-variant"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "COPIER": str(fake)},
    )
    assert result.returncode == 2 and "unknown variant" in result.stderr


def _verify_output(tmp_path, **env: str) -> str:
    """Run verify up to its first refusal; return the output folder it announced."""
    fake = tmp_path / "copier"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    base = {k: v for k, v in os.environ.items() if k != "SANDBOX_RUNTIME"}
    result = subprocess.run(
        ["bash", str(SCRIPTS / "verify-generations.sh"), "no-such-variant"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env={**base, "COPIER": str(fake), **env},
    )
    announced = [x for x in result.stdout.splitlines() if x.startswith("verify: output in ")]
    assert announced, f"verify did not say where it writes: {result.stdout!r}"
    return announced[0].removeprefix("verify: output in ")


def test_verify_writes_inside_the_project_outside_the_sandbox(tmp_path):
    assert _verify_output(tmp_path, TMPDIR=str(tmp_path)) == str(ROOT / ".copier-test")


def test_verify_writes_to_tmpdir_inside_the_sandbox(tmp_path):
    # Under the project the sandbox refuses a generated project's .git/config, hooks and *.pem.
    out = _verify_output(tmp_path, SANDBOX_RUNTIME="1", TMPDIR=f"{tmp_path}/")
    assert out == str(tmp_path / "zynth-setup-verify")
    assert (tmp_path / "zynth-setup-verify").is_dir()


def test_verify_refuses_inside_the_sandbox_without_tmpdir(tmp_path):
    fake = tmp_path / "copier"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "TMPDIR"}
    result = subprocess.run(
        ["bash", str(SCRIPTS / "verify-generations.sh"), "minimal"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env={**env, "COPIER": str(fake), "SANDBOX_RUNTIME": "1"},
    )
    assert result.returncode != 0 and "TMPDIR is unset" in result.stderr
