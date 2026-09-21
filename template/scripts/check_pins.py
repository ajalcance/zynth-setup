#!/usr/bin/env python3
"""Dependency pin guard: every requirement exactly pinned, and the lock asks for nothing extra.

A floating spec (``requests>=2``, ``redis``, ``foo~=1.2``) lets a resolver — or an agent — pull a
different version silently on the next install. Combined with CODEOWNERS review on the manifests
(docs/decisions/0004) and behavioural scanning, exact pins make "the version changed" always an
explicit, reviewable diff. Hashes (``--hash=...``) are accepted and encouraged.

Three things this checks, each closing a different hole:

1. **Every requirement is pinned.** ``==``, a ``--hash=``, or a direct reference that names a
   concrete artifact (a ``#sha256=`` fragment or a 40-character commit).
2. **Both directions, where a ``.in``/``.txt`` pair exists.** Checking only that each input
   appears in the lock lets a hash-valid line added *only to the lock* install on every machine
   while appearing in no reviewed input at all. Versions are compared whole: ``0.1.0`` is not
   ``0.1.0rc1``, and a prefix match cannot tell them apart.
3. **It inspected something.** Reading no requirement at all is a failure, not a pass — a rename
   must not be able to turn this gate into a no-op that still prints OK. See EXP-0001.

Comments are stripped *before* the pin test, so ``requests>=2  # --hash=sha256:...`` cannot vouch
for the spec beside it. The exception is a ``#`` inside a URL: there it is a fragment, and
``...#sha256=<64 hex>`` is the very thing that pins a direct reference. pip's own rule — a
comment's ``#`` is preceded by whitespace or starts the line — separates the two exactly.

Usage:  python3 scripts/check_pins.py backend/requirements.txt backend/requirements-dev.txt
Exit code is non-zero if any requirement is unpinned, unreconciled, or if none were read.
"""

from __future__ import annotations

import os
import re
import sys

COMMENT_RE = re.compile(r"(?:^|(?<=\s))#.*$")
# A direct reference pins only when it names a concrete artifact: a hash fragment or a full
# commit sha. `pkg @ https://host/latest.whl` is a moving target wearing an '@'.
DIRECT_PIN_RE = re.compile(r"#sha256=[0-9a-fA-F]{64}\b|@[0-9a-fA-F]{40}\b")
NAME_RE = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*==\s*(?P<version>[^\s\;]+)")
# pip-compile annotates each locked entry with the inputs that asked for it.
VIA_INPUT_RE = re.compile(r"^#\s*(?:via\s+)?-r\s+(?P<input>\S+)")


def canonical(name: str) -> str:
    """PEP 503 normalisation, so Foo_Bar and foo-bar are one package."""
    return re.sub(r"[-_.]+", "-", name).lower()


def strip_comment(line: str) -> str:
    """The requirement text, with any comment and environment marker removed."""
    return COMMENT_RE.sub("", line).split(";", 1)[0].strip()


def is_pinned(spec: str) -> bool:
    if "--hash=" in spec:
        return True
    if "==" in spec:
        return True
    return "@" in spec and bool(DIRECT_PIN_RE.search(spec))


def read(path: str) -> list[str] | None:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().splitlines()
    except OSError:
        return None


def requirements(lines: list[str]) -> dict[str, tuple[str | None, int, str]]:
    """{canonical name: (version or None, line number, spec)} for the real requirements."""
    found: dict[str, tuple[str | None, int, str]] = {}
    for number, raw in enumerate(lines, 1):
        spec = strip_comment(raw)
        if not spec or spec.startswith(("-r", "-c", "-e", "--")):
            continue
        match = NAME_RE.match(spec)
        if match:
            found[canonical(match.group("name"))] = (match.group("version"), number, spec)
        else:
            name = re.split(r"[\s<>=!~@\[]", spec, maxsplit=1)[0]
            if name:
                found[canonical(name)] = (None, number, spec)
    return found


def direct_entries(lines: list[str], input_name: str) -> set[str]:
    """Locked packages whose `# via` block names the given input file — i.e. asked for directly.

    Transitive dependencies are annotated with the package that pulled them in, never with
    `-r <input>`, so this isolates exactly the entries a human chose.
    """
    direct: set[str] = set()
    current: str | None = None
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("#"):
            match = VIA_INPUT_RE.match(stripped)
            if match and current and os.path.basename(match.group("input")) == input_name:
                direct.add(current)
            continue
        spec = strip_comment(raw)
        if not spec or spec.startswith(("-r", "-c", "-e", "--")):
            continue
        match = NAME_RE.match(spec)
        if match:
            current = canonical(match.group("name"))
    return direct


def check_pins(path: str, lines: list[str], errors: list[str]) -> int:
    inspected = 0
    for number, raw in enumerate(lines, 1):
        spec = strip_comment(raw)
        if not spec or spec.startswith(("-r", "-c", "-e", "--")):
            continue
        inspected += 1
        if not is_pinned(spec):
            errors.append(f"{path}:{number}: not exactly pinned (use '==') → {spec!r}")
    return inspected


def reconcile(input_path: str, lock_path: str, errors: list[str]) -> None:
    """Both directions between a pip-compile input and the lock it produced."""
    input_lines, lock_lines = read(input_path), read(lock_path)
    if input_lines is None or lock_lines is None:
        return
    wanted = requirements(input_lines)
    locked = requirements(lock_lines)

    for name, (version, number, spec) in sorted(wanted.items()):
        if name not in locked:
            errors.append(
                f"{input_path}:{number}: {spec!r} is asked for but absent from "
                f"{lock_path} — the lock does not satisfy its own input"
            )
            continue
        locked_version = locked[name][0]
        # Whole-version comparison. A prefix match reads 0.1.0rc1 as 0.1.0 and installs a
        # pre-release where a release was reviewed.
        if version is not None and locked_version != version:
            errors.append(
                f"{lock_path}: {name} is locked at {locked_version!r} but {input_path} "
                f"asks for {version!r} — the reviewed version is not the installed one"
            )

    for name in sorted(direct_entries(lock_lines, os.path.basename(input_path)) - set(wanted)):
        errors.append(
            f"{lock_path}: {name} is a direct requirement of {os.path.basename(input_path)} "
            f"but that file does not ask for it — a line added only to the lock installs "
            f"everywhere and appears in no reviewed input"
        )


def main() -> int:
    paths = sys.argv[1:] or ["backend/requirements.txt", "backend/requirements-dev.txt"]
    errors: list[str] = []
    inspected = 0
    read_files: list[str] = []
    absent: list[str] = []

    for path in paths:
        lines = read(path)
        if lines is None:
            absent.append(path)  # an optional module may not ship this file
            continue
        read_files.append(path)
        inspected += check_pins(path, lines, errors)
        stem, extension = os.path.splitext(path)
        if extension == ".txt" and read(f"{stem}.in") is not None:
            reconcile(f"{stem}.in", path, errors)

    denominator = (
        f"check-pins: inspected {inspected} requirement(s) across {len(read_files)}/{len(paths)} "
        f"file(s)" + (f" — absent: {', '.join(absent)}" if absent else "")
    )
    print(denominator)

    if not inspected:
        print(
            "\ncheck-pins: FAILED — no requirement was read, so nothing was checked.\n"
            "A gate that inspects an empty set reports green forever (EXP-0001). Either the\n"
            "paths above are wrong — a rename is the usual cause — or the manifests are empty."
        )
        return 1

    if errors:
        print("\ncheck-pins: FAILED — dependencies are not reviewably pinned:\n")
        for error in errors:
            print(f"  ✗ {error}")
        print(
            "\nPin every dependency with '==' (or a --hash), and keep each lock reconciled with\n"
            "the input beside it. Then Dependabot proposes bumps as reviewable PRs."
        )
        return 1

    print("check-pins: OK — all dependencies exactly pinned and reconciled.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
