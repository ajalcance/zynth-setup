"""One runtime, declared once; every other declaration is checked against it.

A Python or Node version lives in the Dockerfile, the CI matrix, pyproject, the devcontainer,
`.nvmrc` and `engines`. Six declarations drift six ways: the devcontainer shipped on Node 20
while `.nvmrc`, CI and the image said 22, and nothing noticed, because each file was right
about itself. The image is the source of truth — it is what production runs — and the rest
must agree with it.
"""

from __future__ import annotations

import json
import re

import pytest
from conftest import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _text(rel: str) -> str | None:
    path = REPO_ROOT / rel
    return path.read_text() if path.is_file() else None


def _workflow_values(key: str) -> list[tuple[str, str]]:
    found = []
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        for match in re.finditer(
            rf"^\s*{key}:\s*['\"]?([\d.]+)['\"]?\s*$", workflow.read_text(), re.M
        ):
            found.append((workflow.name, match.group(1)))
    return found


def test_every_python_declaration_matches_the_backend_image():
    dockerfile = _text("backend/Dockerfile")
    assert dockerfile, "backend/Dockerfile is missing — the source of truth for Python"
    match = re.search(r"^FROM python:(\d+\.\d+)", dockerfile, re.M)
    assert match, "backend/Dockerfile does not build from an official python:X.Y image"
    python = match.group(1)
    short = "py" + python.replace(".", "")

    checked: list[str] = []
    drift: list[str] = []

    def declare(where: str, value: str, ok: bool) -> None:
        checked.append(where)
        if not ok:
            drift.append(f"{where}: {value} (image is {python})")

    for workflow, value in _workflow_values("python-version"):
        declare(f"{workflow} python-version", value, value == python)

    pyproject = _text("backend/pyproject.toml")
    if pyproject:
        for m in re.finditer(r"^(target-version|python_version)\s*=\s*(.+)$", pyproject, re.M):
            value = m.group(2).strip()
            declare(
                f"backend/pyproject.toml {m.group(1)}", value, python in value or short in value
            )

    harness = _text("ruff-harness.toml")
    if harness:
        m = re.search(r'^target-version\s*=\s*"([^"]+)"', harness, re.M)
        if m:
            declare("ruff-harness.toml target-version", m.group(1), m.group(1) == short)

    devcontainer = _text(".devcontainer/Dockerfile")
    if devcontainer:
        m = re.search(r"devcontainers/python:\S*?(\d+\.\d+)-", devcontainer)
        if m:
            declare(".devcontainer/Dockerfile image", m.group(1), m.group(1) == python)

    assert len(checked) >= 3, f"only {len(checked)} Python declaration(s) found — vacuous"
    print(f"runtime-versions: Python {python} — {len(checked)} declaration(s) checked")
    assert not drift, "Python version drift:\n  " + "\n  ".join(drift)


def test_every_node_declaration_matches_nvmrc():
    nvmrc = _text(".nvmrc")
    if nvmrc is None:
        pytest.skip("no .nvmrc — this project has no Node runtime")
    node = nvmrc.strip()
    assert re.fullmatch(r"\d+", node), f".nvmrc must hold a bare major version, got {node!r}"

    checked: list[str] = []
    drift: list[str] = []

    def declare(where: str, value: str, ok: bool) -> None:
        checked.append(where)
        if not ok:
            drift.append(f"{where}: {value} (.nvmrc is {node})")

    for workflow, value in _workflow_values("node-version"):
        declare(f"{workflow} node-version", value, value.split(".")[0] == node)

    for app in ("frontend", "docs-site"):
        dockerfile = _text(f"{app}/Dockerfile")
        if dockerfile:
            for m in re.finditer(r"^FROM node:(\d+)", dockerfile, re.M):
                declare(f"{app}/Dockerfile image", m.group(1), m.group(1) == node)
        manifest = _text(f"{app}/package.json")
        if manifest:
            engines = json.loads(manifest).get("engines", {}).get("node")
            if engines:
                declare(f"{app}/package.json engines.node", engines, f">={node} " in engines)

    devcontainer = _text(".devcontainer/devcontainer.json")
    if devcontainer:
        m = re.search(r'features/node:\d+"\s*:\s*\{\s*"version"\s*:\s*"(\d+)"', devcontainer)
        if m:
            declare(".devcontainer/devcontainer.json node feature", m.group(1), m.group(1) == node)

    assert checked, "no Node declaration found anywhere — this assertion would be vacuous"
    print(f"runtime-versions: Node {node} — {len(checked)} declaration(s) checked")
    assert not drift, "Node version drift:\n  " + "\n  ".join(drift)
