"""`scripts/check_advisories.py` can fail — and can refuse — every way it is meant to.

The check exists because shipped dependencies went stale for three weeks with nothing to say so,
so the failure modes that matter are the quiet ones: a clean report over nothing inspected, an
audit of the wrong directory, a tool that died and printed nothing. Each is a test here.

The real script runs in a throwaway repository layout, against stand-in `npm` and `pip-audit`
executables that return canned reports and log how they were called. No network.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import ROOT, SCRIPTS

FRONTEND = "template/{% if include_frontend %}frontend{% endif %}"
DOCS = "template/{% if include_docs_site %}docs-site{% endif %}"

FAKE_NPM = """#!/usr/bin/env python3
import json, os, sys
mapping = json.load(open(os.environ["FAKE_NPM_JSON"]))
name = json.load(open("package.json"))["name"]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({"tool": "npm", "argv": sys.argv[1:], "cwd": os.getcwd(),
                          "files": sorted(os.listdir("."))}) + "\\n")
payload = mapping.get(name, mapping.get("*"))
if isinstance(payload, dict) and "died_saying" in payload:
    sys.stderr.write("first line\\n" + payload["died_saying"] + "\\n")
    sys.exit(1)
if isinstance(payload, str):
    sys.stdout.write(payload)
    sys.exit(0 if not payload else 1)
print(json.dumps(payload))
sys.exit(1 if payload.get("vulnerabilities") else 0)
"""

FAKE_PIP = """#!/usr/bin/env python3
import json, os, sys
mapping = json.load(open(os.environ["FAKE_PIP_JSON"]))
argv = sys.argv[1:]
target = argv[argv.index("-r") + 1]
folder = os.path.dirname(target)
text = open(target).read()
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({"tool": "pip-audit", "argv": argv, "file": os.path.basename(target),
                          "text": text, "siblings": sorted(os.listdir(folder))}) + "\\n")
for line in text.splitlines():
    if line.startswith("-r ") and not os.path.exists(os.path.join(folder, line[3:].strip())):
        sys.stderr.write("ERROR: Could not open requirements file: " + line[3:] + "\\n")
        sys.exit(1)
payload = mapping.get(os.path.basename(target), mapping.get("*"))
if isinstance(payload, str):
    sys.stdout.write(payload)
    sys.exit(1)
print(json.dumps(payload))
sys.exit(1 if any(d.get("vulns") for d in payload.get("dependencies", [])) else 0)
"""


def npm_report(total: int, vulnerable: dict | None = None, listed: bool = True) -> dict:
    found = vulnerable or {}
    return {
        "metadata": {
            "vulnerabilities": {"total": len(found)},
            "dependencies": {"total": total},
        },
        "vulnerabilities": found if listed else {},
    }


def carrier(
    severity: str,
    nodes: list[str] | None = None,
    *,
    advisories: int = 1,
    effects: list[str] | None = None,
    fix=False,
    direct: bool = False,
    via_severities: list[str] | None = None,
) -> dict:
    """A package npm names advisories for. `nodes` are its installed copies in the lockfile."""
    severities = via_severities or [severity] * advisories
    return {
        "severity": severity,
        "range": "<9.9.9",
        "isDirect": direct,
        "via": [
            {
                "source": i,
                "title": f"advisory number {i}",
                "url": f"https://github.com/advisories/GHSA-aaaa-bbbb-{i:04d}",
                "severity": s,
                "range": "<9.9.9",
            }
            for i, s in enumerate(severities)
        ],
        "effects": effects or [],
        "nodes": nodes if nodes is not None else [],
        "fixAvailable": fix,
    }


def inheritor(severity: str, *roots: str) -> dict:
    """A package that is only vulnerable because it depends on one that is."""
    return {"severity": severity, "via": list(roots), "effects": [], "nodes": [], "range": "*"}


NEXT_CRITICAL = {
    "next": carrier(
        "critical",
        ["node_modules/next"],
        advisories=3,
        direct=True,
        fix={"name": "next", "version": "16.4.3", "isSemVerMajor": False},
    )
}


def pip_report(count: int, vulns: dict[int, list[dict]] | None = None, skip: int | None = None):
    deps = []
    for i in range(count):
        dep = {"name": f"pkg{i}", "version": "1.0", "vulns": (vulns or {}).get(i, [])}
        if skip == i:
            dep = {"name": f"pkg{i}", "skip_reason": "not on PyPI"}
        deps.append(dep)
    return {"dependencies": deps, "fixes": []}


CLEAN_NPM = {"frontend": npm_report(3), "docs-site": npm_report(2)}
CLEAN_PIP = {
    "requirements-dev.txt": pip_report(4),
    "requirements-ci.txt": pip_report(2),
    "requirements-selftest.txt": pip_report(3),
}


class Sandbox:
    """A repository layout shaped like the real one, with the real script copied in."""

    def __init__(self, root: Path):
        self.root = root
        self.bin = root / "bin"
        self.bin.mkdir()
        (root / "scripts").mkdir()
        shutil.copy(SCRIPTS / "check_advisories.py", root / "scripts")
        for folder, name in ((FRONTEND, "frontend"), (DOCS, "docs-site")):
            app = root / folder
            app.mkdir(parents=True)
            (app / "package.json").write_text(json.dumps({"name": name}))
            (app / "package-lock.json").write_text("{}")
        (root / "template" / "backend").mkdir()
        (root / "template/backend/requirements.txt.jinja").write_text(
            "fastapi==1.0.0\n{%- if include_compliance_spine %}\nredis==8.0.1\n{%- endif %}\n"
        )
        (root / "template/backend/requirements-dev.txt.jinja").write_text(
            "-r requirements.txt\nblack==1.0.0\n{%- if include_compliance_spine %}\n"
            "fakeredis==2.0.0\n{%- endif %}\n"
        )
        (root / "template/requirements-ci.txt").write_text("semgrep==1.0.0\n")
        (root / "requirements-selftest.txt").write_text("ruff==1.0.0\n")
        for name, body in (("npm", FAKE_NPM), ("pip-audit", FAKE_PIP)):
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)
        self.log = root / "calls.jsonl"

    def run(self, npm=None, pip=None, env_extra=None, cwd=None):
        (self.root / "npm.json").write_text(json.dumps(CLEAN_NPM if npm is None else npm))
        (self.root / "pip.json").write_text(json.dumps(CLEAN_PIP if pip is None else pip))
        env = {
            **os.environ,
            "NPM": str(self.bin / "npm"),
            "PIP_AUDIT": str(self.bin / "pip-audit"),
            "FAKE_NPM_JSON": str(self.root / "npm.json"),
            "FAKE_PIP_JSON": str(self.root / "pip.json"),
            "FAKE_LOG": str(self.log),
            **(env_extra or {}),
        }
        return subprocess.run(
            [sys.executable, str(self.root / "scripts/check_advisories.py")],
            cwd=cwd or self.root,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )

    def calls(self, tool: str) -> list[dict]:
        if not self.log.exists():
            return []
        rows = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [r for r in rows if r["tool"] == tool]


@pytest.fixture
def box(tmp_path) -> Sandbox:
    return Sandbox(tmp_path)


def both(result) -> str:
    return result.stdout + result.stderr


# --- clean, and what it must say about how much it looked at --------------------------------


def test_clean_run_passes_and_prints_its_denominator(box):
    result = box.run()
    assert result.returncode == 0, both(result)
    # 3 + 2 lockfile packages and 4 + 2 + 3 pins, across the five files.
    assert "5 file(s), 14 package(s)/pin(s) inspected" in result.stdout
    assert "OK" in result.stdout
    assert "frontend" in result.stdout and "requirements-selftest.txt" in result.stdout


# --- findings --------------------------------------------------------------------------------


def test_an_npm_finding_fails_and_names_package_severity_and_fix(box):
    result = box.run(npm={**CLEAN_NPM, "frontend": npm_report(3, NEXT_CRITICAL)})
    assert result.returncode == 1, both(result)
    out = both(result)
    assert "critical: next" in out and "16.4.3" in out and "3 advisories" in out
    assert "direct" in out and "FAIL" in out
    # The other app is still reported, and clean.
    assert "docs-site" in out


def test_findings_are_listed_worst_first_not_alphabetically(box):
    # The names sort the opposite way to the severities, so sorting by name cannot pass. No node is
    # given, which counts as production, so all four fail and share one list.
    vulns = {
        "aaa-low": carrier("low"),
        "zzz-critical": carrier("critical"),
        "mmm-high": carrier("high"),
        "bbb-moderate": carrier("moderate"),
    }
    result = box.run(npm={**CLEAN_NPM, "frontend": npm_report(4, vulns)})
    named = [
        x.split(":")[2].split()[0]
        for x in result.stdout.splitlines()
        if x.startswith("advisories:   FAIL")
    ]
    assert named == ["zzz-critical", "mmm-high", "bbb-moderate", "aaa-low"], named


def test_npm_reporting_vulnerabilities_it_did_not_list_still_fails(box):
    report = npm_report(3)
    report["metadata"]["vulnerabilities"]["total"] = 2
    result = box.run(npm={**CLEAN_NPM, "frontend": report})
    assert result.returncode == 1, both(result)
    assert "did not list" in both(result)


def test_a_pip_finding_fails_and_names_pin_advisory_and_fix(box):
    vuln = {"id": "GHSA-cg8m-r9f2-5wm2", "fix_versions": ["26.10.1"]}
    pip = {**CLEAN_PIP, "requirements-selftest.txt": pip_report(3, {1: [vuln]})}
    result = box.run(pip=pip)
    assert result.returncode == 1, both(result)
    out = both(result)
    assert "pkg1==1.0" in out and "GHSA-cg8m-r9f2-5wm2" in out and "26.10.1" in out


def test_a_pip_finding_with_no_fix_says_so(box):
    vuln = {"id": "GHSA-none", "fix_versions": []}
    result = box.run(pip={**CLEAN_PIP, "requirements-ci.txt": pip_report(2, {0: [vuln]})})
    assert result.returncode == 1 and "none yet" in both(result)


# --- how npm is called: a copy, with dev dependencies ----------------------------------------


def test_npm_audits_a_copy_never_the_template_directory_and_includes_dev(box):
    assert box.run().returncode == 0
    calls = box.calls("npm")
    assert len(calls) == 2
    template_dirs = {str((box.root / FRONTEND).resolve()), str((box.root / DOCS).resolve())}
    for call in calls:
        assert Path(call["cwd"]).resolve() not in {Path(d) for d in template_dirs}, call
        assert "{%" not in call["cwd"], "npm cannot run inside a {% %} directory"
        assert call["files"] == ["package-lock.json", "package.json"], call
        assert call["argv"] == ["audit", "--json"], "no --omit=dev: dev advisories reach adopters"


# --- how pip-audit is called: rendered pins, optional modules included -----------------------


def test_pip_audit_sees_rendered_pins_with_every_optional_module_on(box):
    assert box.run().returncode == 0
    by_file = {c["file"]: c for c in box.calls("pip-audit")}
    # requirements.txt is audited through the dev file that includes it: three audits, not four.
    assert sorted(by_file) == [
        "requirements-ci.txt",
        "requirements-dev.txt",
        "requirements-selftest.txt",
    ]
    dev = by_file["requirements-dev.txt"]
    assert "fakeredis==2.0.0" in dev["text"], "a conditional module's pin was not checked"
    assert "{%" not in dev["text"] and "{{" not in dev["text"]
    assert "requirements.txt" in dev["siblings"], "the -r include would not resolve"
    for call in by_file.values():
        assert "--no-deps" in call["argv"] and "--disable-pip" in call["argv"]


def test_a_jinja_expression_in_a_pin_file_is_refused_not_guessed(box):
    path = box.root / "template/requirements-ci.txt"
    path.write_text("semgrep=={{ semgrep_version }}\n")
    result = box.run()
    assert result.returncode == 2, both(result)
    assert "Jinja beyond control lines" in both(result)


def test_a_relative_tool_path_still_works_from_the_scratch_directory(box):
    # `make advisories` passes PIP_AUDIT=.venv/bin/pip-audit; the tools run from a temp dir.
    rel = os.path.relpath(box.bin / "pip-audit", box.root)
    result = box.run(
        env_extra={"PIP_AUDIT": rel, "NPM": os.path.relpath(box.bin / "npm", box.root)}
    )
    assert result.returncode == 0, both(result)


# --- refusals: a result that is not a verdict ------------------------------------------------


def test_no_lockfiles_is_refused_not_clean(box):
    shutil.rmtree(box.root / FRONTEND)
    shutil.rmtree(box.root / DOCS)
    result = box.run()
    assert result.returncode == 2 and "nothing to inspect" in both(result)


def test_npm_that_inspected_zero_packages_is_refused(box):
    result = box.run(npm={**CLEAN_NPM, "frontend": npm_report(0)})
    assert result.returncode == 2, both(result)
    assert "inspected no packages" in both(result)


def test_an_npm_error_report_is_refused_and_says_why(box):
    error = {"error": {"code": "ENOTFOUND", "summary": "request to registry failed"}}
    result = box.run(npm={**CLEAN_NPM, "frontend": error})
    assert result.returncode == 2, both(result)
    assert "npm audit failed" in both(result) and "ENOTFOUND" in both(result)


def test_npm_output_that_is_not_json_is_refused_with_the_tools_last_words(box):
    result = box.run(npm={**CLEAN_NPM, "frontend": "npm ERR! something broke"})
    assert result.returncode == 2, both(result)
    assert "not JSON" in both(result) and "something broke" in both(result)


def test_a_tool_that_dies_with_only_stderr_has_its_last_line_reported(box):
    died = {"died_saying": "OSError: Could not find a suitable TLS CA certificate bundle"}
    result = box.run(npm={**CLEAN_NPM, "frontend": died})
    assert result.returncode == 2, both(result)
    assert "suitable TLS CA certificate bundle" in both(result)
    assert "first line" not in both(result), "only the last line says why"


def test_details_print_before_the_verdict_on_one_stream(box):
    # stdout is block-buffered behind a pipe and stderr is not: without a flush the FAIL line
    # leads and the findings it summarises follow it.
    box.run()  # lay down the canned reports
    (box.root / "npm.json").write_text(
        json.dumps({**CLEAN_NPM, "frontend": npm_report(3, NEXT_CRITICAL)})
    )
    env = {
        **os.environ,
        "NPM": str(box.bin / "npm"),
        "PIP_AUDIT": str(box.bin / "pip-audit"),
        "FAKE_NPM_JSON": str(box.root / "npm.json"),
        "FAKE_PIP_JSON": str(box.root / "pip.json"),
        "FAKE_LOG": str(box.log),
    }
    merged = subprocess.run(
        [sys.executable, str(box.root / "scripts/check_advisories.py")],
        cwd=box.root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
        env=env,
    ).stdout
    assert merged.index("critical: next") < merged.index("advisories: FAIL —"), merged


def test_npm_that_prints_nothing_is_refused(box):
    result = box.run(npm={"*": ""})
    assert result.returncode == 2 and "not JSON" in both(result)


def test_json_that_is_not_an_object_is_refused(box):
    result = box.run(npm={"*": "[1, 2]"})
    assert result.returncode == 2 and "not a JSON object" in both(result)


def test_a_missing_npm_is_refused(box):
    result = box.run(env_extra={"NPM": "no-such-npm-binary"})
    assert result.returncode == 2 and "no-such-npm-binary" in both(result)


def test_a_missing_pip_audit_is_refused(box):
    result = box.run(env_extra={"PIP_AUDIT": "no-such-pip-audit"})
    assert result.returncode == 2 and "no-such-pip-audit" in both(result)


def test_a_lockfile_without_its_manifest_is_refused(box):
    (box.root / FRONTEND / "package.json").unlink()
    result = box.run()
    assert result.returncode == 2 and "no package.json" in both(result)


def test_pip_audit_that_inspected_nothing_is_refused(box):
    result = box.run(pip={**CLEAN_PIP, "requirements-ci.txt": {"dependencies": []}})
    assert result.returncode == 2 and "inspected no requirements" in both(result)


def test_a_requirement_pip_audit_skipped_is_refused_not_passed(box):
    result = box.run(pip={**CLEAN_PIP, "requirements-ci.txt": pip_report(2, skip=1)})
    assert result.returncode == 2, both(result)
    assert "skipped pkg1" in both(result)


def test_pip_audit_output_that_is_not_json_is_refused(box):
    result = box.run(pip={**CLEAN_PIP, "requirements-ci.txt": "Traceback (most recent call"})
    assert result.returncode == 2 and "not JSON" in both(result)


def test_a_missing_shipped_pin_file_is_refused(box):
    (box.root / "requirements-selftest.txt").unlink()
    result = box.run()
    assert result.returncode == 2 and "pin file not found" in both(result)


def test_an_unexpected_crash_is_a_refusal_never_a_pass_or_a_traceback(box):
    # npm output shaped in a way nothing anticipated: `vulnerabilities` is not a mapping.
    report = npm_report(3)
    report["vulnerabilities"] = "oops"
    result = box.run(npm={**CLEAN_NPM, "frontend": report})
    assert result.returncode == 2, both(result)
    assert "crashed" in result.stderr and "Traceback" not in result.stderr


def test_a_lockfile_that_is_not_readable_json_is_refused(box):
    (box.root / FRONTEND / "package-lock.json").write_text("{not json")
    result = box.run()
    assert result.returncode == 2 and "lockfile unreadable" in both(result)


def test_a_lockfile_that_is_a_directory_is_refused(box):
    lock = box.root / DOCS / "package-lock.json"
    lock.unlink()
    lock.mkdir()
    result = box.run()
    assert result.returncode == 2 and "lockfile unreadable" in both(result)


def test_a_refusal_does_not_print_ok(box):
    result = box.run(npm={"*": ""})
    assert "OK" not in result.stdout


# --- what fails and what is only a notice ---------------------------------------------------

MM = "node_modules/mm"


def set_lock(box, packages: dict, app: str = FRONTEND) -> None:
    (box.root / app / "package-lock.json").write_text(json.dumps({"packages": packages}))


def run_with(box, vulns: dict, lock: dict, total: int = 3):
    set_lock(box, lock)
    return box.run(npm={**CLEAN_NPM, "frontend": npm_report(total, vulns)})


def test_a_moderate_advisory_in_the_dev_tree_is_a_notice_not_a_failure(box):
    vulns = {"mm": carrier("moderate", [MM], effects=["a", "b", "c"])}
    result = run_with(box, vulns, {MM: {"dev": True}})
    assert result.returncode == 0, both(result)
    assert "notice moderate: mm" in result.stdout
    assert "3 dependent package(s) inherit it" in result.stdout
    assert "dev-only" in result.stdout and "FAIL" not in both(result)
    # Counted, never silent: the verdict says there are notices and tells the maintainer to read.
    assert "1 notice(s)" in result.stdout and "read them" in result.stdout


def test_a_low_advisory_in_the_dev_tree_is_a_notice(box):
    result = run_with(box, {"mm": carrier("low", [MM])}, {MM: {"dev": True}})
    assert result.returncode == 0 and "notice low: mm" in result.stdout


@pytest.mark.parametrize("severity", ["critical", "high"])
def test_a_high_or_critical_advisory_fails_even_in_the_dev_tree(box, severity):
    result = run_with(box, {"mm": carrier(severity, [MM])}, {MM: {"dev": True}})
    assert result.returncode == 1, both(result)
    assert f"FAIL {severity}: mm" in result.stdout and "dev-only" in result.stdout


@pytest.mark.parametrize("severity", ["moderate", "low"])
def test_any_advisory_in_a_production_dependency_fails(box, severity):
    result = run_with(box, {"mm": carrier(severity, [MM])}, {MM: {}})
    assert result.returncode == 1, both(result)
    assert f"FAIL {severity}: mm" in result.stdout and "PRODUCTION" in result.stdout


def test_a_dev_optional_package_counts_as_production(box):
    # `devOptional` means dev OR an optional production dependency: not provably dev-only.
    result = run_with(box, {"mm": carrier("moderate", [MM])}, {MM: {"devOptional": True}})
    assert result.returncode == 1 and "PRODUCTION" in result.stdout


def test_one_production_copy_among_dev_copies_fails(box):
    nested = "node_modules/x/node_modules/mm"
    lock = {MM: {"dev": True}, nested: {}}
    result = run_with(box, {"mm": carrier("moderate", [MM, nested])}, lock)
    assert result.returncode == 1 and "PRODUCTION" in result.stdout


def test_a_copy_the_lockfile_does_not_list_is_treated_as_production(box):
    result = run_with(box, {"mm": carrier("moderate", ["node_modules/ghost"])}, {MM: {"dev": True}})
    assert result.returncode == 1 and "PRODUCTION" in result.stdout


def test_a_package_npm_gives_no_location_for_is_treated_as_production(box):
    result = run_with(box, {"mm": carrier("moderate", [])}, {MM: {"dev": True}})
    assert result.returncode == 1 and "PRODUCTION" in result.stdout


def test_the_worst_of_a_packages_advisories_decides(box):
    # Its summary severity says low; one of its advisories is high. High wins.
    vuln = carrier("low", [MM], via_severities=["low", "high"])
    result = run_with(box, {"mm": vuln}, {MM: {"dev": True}})
    assert result.returncode == 1 and "FAIL high: mm" in result.stdout


def test_packages_that_only_inherit_an_advisory_are_counted_not_listed(box):
    vulns = {
        "mm": carrier("moderate", [MM], effects=["eslint", "plugin-a", "plugin-b"]),
        "eslint": inheritor("moderate", "mm"),
        "plugin-a": inheritor("moderate", "mm"),
        "plugin-b": inheritor("moderate", "mm"),
    }
    result = run_with(box, vulns, {MM: {"dev": True}}, total=9)
    detail = [x for x in result.stdout.splitlines() if x.startswith("advisories:   ")]
    assert len(detail) == 1, detail
    assert "mm" in detail[0] and "3 dependent package(s) inherit it" in detail[0]
    assert result.returncode == 0


def test_vulnerabilities_with_no_advisory_named_anywhere_still_fail(box):
    vulns = {"eslint": inheritor("moderate", "mm")}
    report = npm_report(3, vulns)
    report["metadata"]["vulnerabilities"]["total"] = 1
    set_lock(box, {})
    result = box.run(npm={**CLEAN_NPM, "frontend": report})
    assert result.returncode == 1 and "did not list" in both(result)


def test_a_notice_does_not_hide_a_failure_in_the_same_run(box):
    notice = {"mm": carrier("moderate", [MM])}
    set_lock(box, {MM: {"dev": True}})
    result = box.run(
        npm={"frontend": npm_report(3, notice), "docs-site": npm_report(2, NEXT_CRITICAL)}
    )
    assert result.returncode == 1, both(result)
    assert "FAIL critical: next" in result.stdout and "notice moderate: mm" in result.stdout
    assert "1 finding(s), 1 notice(s)" in result.stderr


@pytest.mark.parametrize(
    ("fix", "expected"),
    [
        ({"name": "next", "version": "16.4.3", "isSemVerMajor": False}, "fix: next@16.4.3"),
        ({"name": "eslint", "version": "4.0.0", "isSemVerMajor": True}, "no compatible fix"),
        (True, "fix: npm audit fix"),
        (False, "no fix available"),
    ],
)
def test_the_fix_status_is_stated_plainly(box, fix, expected):
    result = run_with(box, {"mm": carrier("critical", [MM], fix=fix)}, {MM: {}})
    assert expected in result.stdout


def test_each_advisory_is_named_with_its_ghsa_id(box):
    result = run_with(box, {"mm": carrier("critical", [MM], advisories=4)}, {MM: {}})
    assert "advisory number 0 (GHSA-aaaa-bbbb-0000)" in result.stdout
    assert "advisory number 1 (GHSA-aaaa-bbbb-0001)" in result.stdout, "the second is named too"
    assert "advisory number 2" not in result.stdout, "only two are spelled out"
    assert "+2 more" in result.stdout and "4 advisories" in result.stdout


# --- the real repository: the layout this check depends on still exists ----------------------


def _real():
    spec = importlib.util.spec_from_file_location(
        "check_advisories", SCRIPTS / "check_advisories.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_advisories"] = module
    spec.loader.exec_module(module)
    return module


def test_the_real_tree_has_both_lockfiles_and_every_pin_file():
    module = _real()
    names = sorted(p.parent.name for p in module.npm_lockfiles())
    assert names == [
        "{% if include_docs_site %}docs-site{% endif %}",
        "{% if include_frontend %}frontend{% endif %}",
    ], "an app moved: the check would silently stop inspecting it"
    for _, source, _ in module.PIP_FILES:
        assert (ROOT / source).is_file(), source


def test_the_real_pin_files_contain_only_jinja_control_lines():
    module = _real()
    for _, source, _ in module.PIP_FILES:
        for line in (ROOT / source).read_text().splitlines():
            if "{{" in line or ("{%" in line and not module.JINJA_CONTROL.match(line)):
                pytest.fail(f"{source}: {line!r} needs rendering, not stripping")


def test_make_advisories_is_wired_and_documented():
    makefile = (ROOT / "Makefile").read_text()
    assert "\nadvisories:\n\tPIP_AUDIT=$(PIP_AUDIT) $(PY) scripts/check_advisories.py" in makefile
    assert "pip-audit" in makefile.split("venv:")[1].split("\n\n")[0], "make venv must install it"
    maintaining = (ROOT / "MAINTAINING.md").read_text()
    assert "make advisories" in maintaining.split("## Releasing")[1], "the release procedure"
