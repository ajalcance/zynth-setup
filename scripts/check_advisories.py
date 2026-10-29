#!/usr/bin/env python3
"""Audit what the template SHIPS for known advisories, whatever CI is doing.

Between releases the template's lockfiles and pins go stale on their own: nobody edits them, an
advisory is published against them, and every project generated afterwards inherits it. For three
weeks in October 2026 that was Next.js with three critical remote code executions, and nothing told
the maintainer because the one thing that would have (the self-test's scheduled run) could not run.
This reads no CI. It asks the registries, on the maintainer's machine, about the files that ship:

* each npm lockfile under template/ — `npm audit` on a COPY (npm cannot run inside a directory
  named `{% if ... %}`), dev dependencies included: the generated gate only audits production, and a
  dev-tree advisory still reaches every adopter's machine;
* each shipped Python pin file — `pip-audit --no-deps` over the pinned lines, after the Jinja
  control lines are dropped so every optional module's pins are checked. Direct pins only: the
  template pins nothing else, and an unpinned transitive version is the adopter's install, not ours.

Exit 0: inspected something, found nothing. Exit 1: a finding. Exit 2: could not inspect (no npm, no
pip-audit, a registry error, output it does not understand, or nothing to inspect) — refused rather
than reported clean, because "OK over zero packages" is the failure every guard here was built
against. Run it before every release and weekly (MAINTAINING.md); it needs the network, so it is not
part of `make check`.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXIT_OK, EXIT_FINDINGS, EXIT_REFUSED = 0, 1, 2
TIMEOUT = 600

# Shipped Python pins. The backend pair is audited together (the dev file includes the runtime
# one); the others stand alone. Root requirements-selftest.txt is what judges the template itself.
PIP_FILES = (
    ("backend", "template/backend/requirements-dev.txt.jinja", "requirements-dev.txt"),
    ("backend", "template/backend/requirements.txt.jinja", "requirements.txt"),
    ("ci", "template/requirements-ci.txt", "requirements-ci.txt"),
    ("selftest", "requirements-selftest.txt", "requirements-selftest.txt"),
)
# Only the control lines may be Jinja; an expression in a pin file would need rendering.
JINJA_CONTROL = re.compile(r"^\s*\{%-?.*-?%\}\s*$")


class RefusedError(Exception):
    """The check could not look; that is never a clean result."""


@dataclass
class Result:
    label: str
    inspected: int
    unit: str
    findings: list[str] = field(default_factory=list)


def _tool(env_name: str, default: str) -> str:
    """The executable to run: an env override, else a PATH lookup. A missing one is a refusal."""
    wanted = os.environ.get(env_name, default)
    found = shutil.which(wanted)
    if not found:
        raise RefusedError(f"`{wanted}` not found — set {env_name} or put it on PATH")
    # Absolute: the tools run from a scratch directory, where `.venv/bin/x` means nothing.
    return os.path.abspath(found)


def _run(cmd: list[str], cwd: pathlib.Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise RefusedError(f"`{' '.join(cmd[:2])}` timed out after {TIMEOUT}s") from exc


def _json(proc: subprocess.CompletedProcess[str], what: str) -> dict:
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        # Nothing on stdout usually means the tool died: its last stderr line says why.
        last = (proc.stderr.strip().splitlines() or [""])[-1]
        raise RefusedError(
            f"{what}: output is not JSON (exit {proc.returncode}; stdout "
            f"{proc.stdout.strip()[:100]!r}; stderr ends {last[:200]!r})"
        ) from exc
    if not isinstance(data, dict):
        raise RefusedError(f"{what}: output is not a JSON object")
    return data


def npm_lockfiles() -> list[pathlib.Path]:
    return sorted((ROOT / "template").glob("*/package-lock.json"))


def audit_npm(lock: pathlib.Path, npm: str) -> Result:
    label = str(lock.relative_to(ROOT))
    manifest = lock.with_name("package.json")
    if not manifest.is_file():
        raise RefusedError(f"{label}: no package.json beside the lockfile")
    with tempfile.TemporaryDirectory(prefix="advisories-npm-") as tmp:
        work = pathlib.Path(tmp)
        shutil.copy(manifest, work / "package.json")
        shutil.copy(lock, work / "package-lock.json")
        # Full audit: no --omit=dev. npm exits 1 when it finds something, so read the JSON.
        proc = _run([npm, "audit", "--json"], work)
    data = _json(proc, f"{label}: npm audit")
    if "error" in data:
        raise RefusedError(f"{label}: npm audit failed — {str(data['error'])[:200]}")
    meta = data.get("metadata") or {}
    total = (meta.get("dependencies") or {}).get("total")
    if not isinstance(total, int) or total <= 0:
        raise RefusedError(
            f"{label}: npm audit inspected no packages (metadata.dependencies.total)"
        )
    found = data.get("vulnerabilities") or {}
    counted = (meta.get("vulnerabilities") or {}).get("total", 0)
    result = Result(label, total, "package(s)")
    for name in sorted(found, key=lambda n: (_rank(found[n].get("severity")), n)):
        info = found[name]
        advisories = [v for v in info.get("via", []) if isinstance(v, dict)]
        fix = info.get("fixAvailable")
        fixed = f"{fix['name']}@{fix['version']}" if isinstance(fix, dict) else str(fix)
        result.findings.append(
            f"{info.get('severity', '?')}: {name} {info.get('range', '')} "
            f"({'direct' if info.get('isDirect') else 'transitive'}; "
            f"{len(advisories)} advisor{'y' if len(advisories) == 1 else 'ies'}; fix {fixed})"
        )
    if counted and not result.findings:
        # npm says there are vulnerabilities but listed none: do not trust a clean parse.
        result.findings.append(f"npm reports {counted} vulnerabilit(ies) it did not list")
    return result


def _rank(severity: str | None) -> int:
    order = ("critical", "high", "moderate", "low", "info")
    return order.index(severity) if severity in order else len(order)


def audit_pip(pip_audit: str) -> list[Result]:
    results = []
    with tempfile.TemporaryDirectory(prefix="advisories-pip-") as tmp:
        work = pathlib.Path(tmp)
        rendered: dict[str, pathlib.Path] = {}
        for group, source, name in PIP_FILES:
            src = ROOT / source
            if not src.is_file():
                raise RefusedError(f"{source}: shipped pin file not found")
            folder = work / group
            folder.mkdir(exist_ok=True)
            lines = []
            for line in src.read_text().splitlines():
                if JINJA_CONTROL.match(line):
                    continue
                if "{{" in line or "{%" in line:
                    raise RefusedError(
                        f"{source}: Jinja beyond control lines — this check must render it"
                    )
                lines.append(line)
            target = folder / name
            target.write_text("\n".join(lines) + "\n")
            rendered[source] = target
        for _, source, _ in PIP_FILES:
            if source.endswith("requirements.txt.jinja"):
                continue  # audited through requirements-dev.txt, which includes it
            results.append(_audit_pip_file(source, rendered[source], pip_audit))
    return results


def _audit_pip_file(source: str, path: pathlib.Path, pip_audit: str) -> Result:
    cmd = [pip_audit, "-r", str(path), "--no-deps", "--disable-pip", "--format", "json"]
    cmd += ["--progress-spinner", "off"]
    proc = _run(cmd, path.parent)
    data = _json(proc, f"{source}: pip-audit")
    deps = data.get("dependencies")
    if not isinstance(deps, list) or not deps:
        raise RefusedError(f"{source}: pip-audit inspected no requirements")
    skipped = [d.get("name") for d in deps if d.get("skip_reason")]
    if skipped:
        raise RefusedError(
            f"{source}: pip-audit skipped {', '.join(map(str, skipped))} — not audited"
        )
    result = Result(source, len(deps), "pinned requirement(s)")
    for dep in deps:
        for vuln in dep.get("vulns") or []:
            fixes = ", ".join(vuln.get("fix_versions") or []) or "none yet"
            result.findings.append(
                f"{dep['name']}=={dep['version']}: {vuln.get('id')} (fixed in {fixes})"
            )
    return result


def main() -> int:
    try:
        lockfiles = npm_lockfiles()
        if not lockfiles:
            raise RefusedError("no template/*/package-lock.json found — nothing to inspect")
        npm, pip_audit = _tool("NPM", "npm"), _tool("PIP_AUDIT", "pip-audit")
        results = [audit_npm(lock, npm) for lock in lockfiles] + audit_pip(pip_audit)
    except RefusedError as exc:
        print(f"advisories: REFUSED — {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except Exception as exc:  # noqa: BLE001 — a crash must never read as a pass
        print(f"advisories: REFUSED — crashed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    total = sum(r.inspected for r in results)
    for r in results:
        verdict = f"{len(r.findings)} finding(s)" if r.findings else "clean"
        print(f"advisories: {r.label}: {r.inspected} {r.unit} — {verdict}")
        for finding in r.findings:
            print(f"advisories:   {finding}")
    sys.stdout.flush()  # the details first, then the verdict, even when stderr is a different pipe
    flagged = sum(len(r.findings) for r in results)
    scope = f"{len(results)} file(s), {total} package(s)/pin(s) inspected"
    if flagged:
        print(f"advisories: FAIL — {flagged} finding(s) across {scope}", file=sys.stderr)
        return EXIT_FINDINGS
    print(f"advisories: OK — {scope}, no known advisory")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
