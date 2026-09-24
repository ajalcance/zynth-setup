"""Every manifest in the tree has a Dependabot entry — derived from the tree, not a list.

docs-site shipped for months with no Dependabot coverage: a whole Next.js app whose
dependencies, security fixes included, were never proposed. It was wired into the Makefile
and CI, but nothing checked that the cross-cutting systems knew about it. Adding a module
means N systems must learn about it; this asserts one of them, and it lives in the project
so the check runs on every change, not only in the template's own self-test.
"""

from __future__ import annotations

import yaml
from conftest import REPO_ROOT

SKIP = {"node_modules", ".venv", ".next", ".git", "__pycache__", ".pytest_cache"}
MANIFESTS = {"package.json": "npm", "Dockerfile": "docker"}


def _required() -> set[tuple[str, str]]:
    required = set()
    for path in REPO_ROOT.rglob("*"):
        if any(part in SKIP for part in path.parts) or not path.is_file():
            continue
        ecosystem = MANIFESTS.get(path.name)
        if path.name.startswith("requirements") and path.suffix == ".txt":
            ecosystem = "pip"
        if ecosystem is None:
            continue
        relative = path.parent.relative_to(REPO_ROOT).as_posix()
        required.add((ecosystem, "/" if relative == "." else "/" + relative))
    if (REPO_ROOT / ".github" / "workflows").is_dir():
        required.add(("github-actions", "/"))
    return required


def test_every_manifest_location_has_a_dependabot_entry():
    config = yaml.safe_load((REPO_ROOT / ".github" / "dependabot.yml").read_text())
    covered = {
        (u["package-ecosystem"], u["directory"].rstrip("/") or "/") for u in config["updates"]
    }
    required = _required()
    assert required, "no manifest found anywhere — this assertion would be vacuous"
    missing = sorted(required - covered)
    print(f"dependabot-coverage: {len(required)} manifest location(s), {len(missing)} uncovered")
    assert not missing, f"manifest location(s) with no Dependabot entry: {missing}"


def test_every_entry_has_the_cooldown_the_waiver_assumes():
    """Mirrors the CI waiver's premise for the SAME file, so the two checks cannot disagree."""
    config = yaml.safe_load((REPO_ROOT / ".github" / "dependabot.yml").read_text())
    short = [
        f"{u['package-ecosystem']} {u['directory']}"
        for u in config["updates"]
        if int(u.get("cooldown", {}).get("default-days", 0)) < 7
    ]
    assert (
        not short
    ), f"entries without the 7-day cooldown the sensitive-path waiver assumes: {short}"
