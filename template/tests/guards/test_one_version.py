"""A tool pinned in two manifests is pinned at one version.

pre-commit was pinned at 4.6.2 in requirements-ci.txt and 4.6.1 in
backend/requirements-dev.txt, so the hooks a developer ran locally were not the hooks CI ran.
Each file was exactly pinned — check_pins passes both — and nothing compared them.
"""

from __future__ import annotations

import re
from collections import defaultdict

from conftest import REPO_ROOT

PIN = re.compile(r"^([A-Za-z0-9._-]+)(?:\[[^\]]*\])?==([^\s;#]+)", re.MULTILINE)
SKIP = {".venv", "node_modules", ".git"}


def manifests():
    return sorted(
        path
        for path in REPO_ROOT.rglob("requirements*.txt")
        if not any(part in SKIP for part in path.parts)
    )


def test_the_comparison_reads_more_than_one_manifest():
    found = manifests()
    assert len(found) >= 2, f"only {found} — one file cannot disagree with itself"


def test_every_tool_pinned_twice_is_pinned_at_one_version():
    versions: dict[str, dict[str, str]] = defaultdict(dict)
    for path in manifests():
        for name, version in PIN.findall(path.read_text()):
            canonical = re.sub(r"[-_.]+", "-", name).lower()
            versions[canonical][path.relative_to(REPO_ROOT).as_posix()] = version
    shared = {tool: where for tool, where in versions.items() if len(where) > 1}
    print(
        f"one-version: {len(versions)} tool(s) across {len(manifests())} manifest(s), "
        f"{len(shared)} pinned in more than one"
    )
    drift = {tool: where for tool, where in shared.items() if len(set(where.values())) > 1}
    assert not drift, f"one tool, several versions — local and CI run different code: {drift}"
