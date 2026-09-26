#!/usr/bin/env python3
"""The agent's OS sandbox holds for a program the agent launches, not only for the agent.

Claude Code's sandbox (macOS Seatbelt, configured machine-locally in the git-ignored
.claude/settings.local.json — ADR 0004) wraps every command the agent runs and every process
that command starts. Permission rules cannot see those children; this check is one of them.
Each probe runs as a separate child process and tries something the sandbox must refuse — or,
for the controls, something it must allow — and the check fails unless every probe comes out
the right way.

Run it from inside the agent's session: `make sandbox-verify`. It fails outside the sandbox —
in your own terminal or in CI — by design: there, nothing refuses anything.

Not covered here, because a child process cannot observe them: that a standalone `gh` runs
outside the sandbox with the repo-only token, and that the agent's file tools obey the
permission deny rules. ADR 0004 lists them as checks made by hand.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOME = pathlib.Path.home()
DENIED, ALLOWED = "denied", "allowed"
TIMEOUT = 30

# A probe's child prints exactly one of these; anything else is a probe that proved nothing.
_CHILD = """
import sys
try:
{body}
except PermissionError:
    print("{denied}")
except OSError as exc:
    # A refused proxy tunnel is the sandbox's network answer; any other OSError is not.
    print("{denied}" if "403" in str(exc) or "Forbidden" in str(exc) else "error: %r" % exc)
else:
    print("{allowed}")
"""


@dataclasses.dataclass(frozen=True)
class Probe:
    name: str
    expect: str
    body: str  # Python statements; must raise PermissionError when the sandbox refuses
    cleanup: pathlib.Path | None = None


def _write_new(path: pathlib.Path) -> str:
    return f"    open({str(path)!r}, 'x').close()"


def _append_nothing(path: pathlib.Path) -> str:
    # Opens for writing and writes nothing: refused inside the sandbox, a no-op outside it.
    return f"    open({str(path)!r}, 'a').close()"


def _fetch(url: str) -> str:
    return f"    __import__('urllib.request').request.urlopen({url!r}, timeout=20).read(1)"


def probes() -> list[Probe]:
    marker = f".sandbox-probe-{os.getpid()}"
    return [
        Probe("read ~/.ssh", DENIED, f"    __import__('os').listdir({str(HOME / '.ssh')!r})"),
        Probe(
            "read ~/.config/gh (your personal GitHub login)",
            DENIED,
            f"    __import__('os').listdir({str(HOME / '.config' / 'gh')!r})",
        ),
        Probe(
            "list the folder that holds the other projects",
            DENIED,
            f"    __import__('os').listdir({str(ROOT.parent)!r})",
        ),
        Probe(
            "write a new file in $HOME",
            DENIED,
            _write_new(HOME / marker),
            HOME / marker,
        ),
        Probe("open .git/config for writing", DENIED, _append_nothing(ROOT / ".git" / "config")),
        Probe(
            "plant a git hook",
            DENIED,
            _write_new(ROOT / ".git" / "hooks" / marker),
            ROOT / ".git" / "hooks" / marker,
        ),
        Probe(
            "open the agent's settings for writing",
            DENIED,
            _append_nothing(ROOT / ".claude" / "settings.local.json"),
        ),
        Probe(
            "write a new file under .claude/",
            DENIED,
            _write_new(ROOT / ".claude" / marker),
            ROOT / ".claude" / marker,
        ),
        Probe("reach a host not on the allowlist", DENIED, _fetch("https://example.com/")),
        # The controls: a sandbox that refuses everything would pass every probe above.
        Probe(
            "write inside the project",
            ALLOWED,
            _write_new(ROOT / ".copier-test" / marker),
            ROOT / ".copier-test" / marker,
        ),
        Probe("reach an allowed host (pypi.org)", ALLOWED, _fetch("https://pypi.org/simple/")),
    ]


def run(probe: Probe) -> str:
    """Run one probe in its own child process; return what it observed."""
    source = _CHILD.format(body=probe.body, denied=DENIED, allowed=ALLOWED)
    try:
        done = subprocess.run(
            [sys.executable, "-c", source],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            cwd=ROOT,
        )
        return done.stdout.strip() or f"error: no answer ({done.stderr.strip()[-200:]})"
    except subprocess.TimeoutExpired:
        return f"error: no answer in {TIMEOUT}s"
    finally:
        # Outside the sandbox the write succeeds; never leave the probe's file behind.
        if probe.cleanup is not None:
            probe.cleanup.unlink(missing_ok=True)


def judge(results: list[tuple[Probe, str]]) -> int:
    """Print each probe's verdict and a denominator; 0 only if every probe held."""
    held = 0
    for probe, observed in results:
        ok = observed == probe.expect
        held += ok
        print(f"  {'ok  ' if ok else 'FAIL'} {probe.name}: expected {probe.expect}, got {observed}")
    total = len(results)
    if total == 0:
        print("sandbox: FAIL — no probe ran, so nothing was proved")
        return 1
    if held != total:
        print(f"sandbox: FAIL — {held}/{total} probes held (expected outside the agent's sandbox)")
        return 1
    print(f"sandbox: OK — {held}/{total} probes held, each in its own child process")
    return 0


def main() -> int:
    return judge([(probe, run(probe)) for probe in probes()])


if __name__ == "__main__":
    sys.exit(main())
