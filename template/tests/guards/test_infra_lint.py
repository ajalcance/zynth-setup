"""The workflow and Dockerfile linters: pinned, verified, run through one definition.

actionlint was fetched inline by the CI job, which meant the developer's `make check` never
ran it and the template self-test never linted a generated project's workflows at all. Two
more linters join it here — zizmor for workflow SECURITY (template injection, credential
persistence, unpinned actions) and hadolint for Dockerfiles — and all three run from one
Makefile target that CI, the self-test and a developer invoke alike.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
from pathlib import Path

import pytest
import yaml
from conftest import REPO_ROOT, SCRIPTS, run

MAKEFILE = REPO_ROOT / "Makefile"
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
INSTALLER = SCRIPTS / "ci_tools.sh"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _recipe(name: str) -> str:
    match = re.search(rf"^{name}:\n((?:\t.*\n)+)", MAKEFILE.read_text(), re.M)
    assert match, f"the Makefile has no `{name}:` target"
    return match.group(1)


def _static_runs() -> list[str]:
    jobs = yaml.safe_load(CI.read_text())["jobs"]
    return [s.get("run", "") for s in jobs["static"]["steps"] if "run" in s]


# --- one definition ------------------------------------------------------------------------


def test_the_target_runs_all_three_linters_through_the_installer():
    recipe = _recipe("infra-lint")
    assert "scripts/ci_tools.sh" in recipe, "the linters are not fetched by the pinned installer"
    for tool in ("actionlint", "$(ZIZMOR)", "hadolint"):
        assert tool in recipe, f"`make infra-lint` does not run {tool}"
    assert "--no-online-audits" in recipe, (
        "zizmor's online audits need a token and a network; a gate whose result depends on "
        "either passes differently in two places"
    )
    assert "|| true" not in recipe


def test_ci_runs_the_make_targets_and_never_relists_them():
    """A second copy of a gate's command is where a flag gets added to one and not the other."""
    runs = _static_runs()
    joined = "\n".join(runs)
    for target in ("make infra-lint", "make guard-tests", "make harness"):
        assert target in joined, f"the static job does not run `{target}`"
    direct = re.compile(r"\b(actionlint|zizmor|hadolint)\b|pytest tests/guards|ruff check --config")
    relisted = [
        line.strip()
        for r in runs
        for line in r.splitlines()
        if not line.strip().startswith("#")
        and "make " not in line
        and "pip install" not in line
        and direct.search(line)
    ]
    assert not relisted, f"the static job relists what a make target already defines: {relisted}"


def test_the_full_local_gate_includes_the_linters():
    check = re.search(r"^check:\s*(.+)$", MAKEFILE.read_text(), re.M)
    assert check, "no `check:` target"
    assert "infra-lint" in check.group(1), "`make check` skips the workflow/Dockerfile linters"


# --- pinned and verified ---------------------------------------------------------------------


def test_every_platform_has_a_checksum_for_both_tools():
    text = INSTALLER.read_text()
    for tool in ("actionlint", "hadolint"):
        shas = re.findall(rf"^\s*{tool}_sha=(\S+)", text, re.M)
        assert len(shas) == 4, f"{tool}: expected a sha256 per platform (4), found {len(shas)}"
        bad = [s for s in shas if not SHA256.match(s)]
        assert not bad, f"{tool}: not a sha256: {bad}"
    for tool in ("ACTIONLINT", "HADOLINT"):
        assert re.search(rf"^{tool}_VERSION=\d+\.\d+\.\d+$", text, re.M), f"{tool} has no version"


def test_zizmor_is_pinned_with_the_other_scanners():
    pins = (REPO_ROOT / "requirements-ci.txt").read_text()
    assert re.search(r"^zizmor==\d", pins, re.M), "zizmor is not pinned in requirements-ci.txt"


def _platform() -> tuple[str, str]:
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "amd64"
    return platform.system().lower(), arch


def test_a_tampered_download_is_refused_and_deleted(tmp_path):
    """The cache is not trusted: a wrong file is deleted and the run fails, never used."""
    os_name, arch = _platform()
    version = re.search(r"^ACTIONLINT_VERSION=(\S+)$", INSTALLER.read_text(), re.M).group(1)
    tarball = tmp_path / f"actionlint_{version}_{os_name}_{arch}.tar.gz"
    tarball.write_bytes(b"not the tarball the checksum names")
    result = run(["bash", str(INSTALLER), str(tmp_path)], REPO_ROOT)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "checksum mismatch" in result.stderr
    assert not tarball.exists(), "the tampered file was left in the cache to be trusted next time"
    assert not (tmp_path / "actionlint").exists(), "a binary was produced from a bad tarball"


def test_verified_tools_run(tmp_path):
    """The positive control, from a cache a real run has already filled (CI fills it first)."""
    cache = Path(os.environ.get("CI_TOOLS", Path.home() / ".cache" / "ci-tools"))
    downloads = [p for p in cache.glob("*") if p.name.startswith(("actionlint_", "hadolint-"))]
    if len(downloads) < 2:
        pytest.skip(f"no verified download in {cache} — `make infra-lint` has not run here")
    for download in downloads:
        shutil.copy2(download, tmp_path / download.name)
    result = run(["bash", str(INSTALLER), str(tmp_path)], REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "verified by checksum" in result.stdout
    assert os.access(tmp_path / "actionlint", os.X_OK) and os.access(tmp_path / "hadolint", os.X_OK)
