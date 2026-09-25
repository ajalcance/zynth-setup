#!/usr/bin/env bash
# ==============================================================================
# Maintainer check: every .jinja file must compile as a Jinja template.
#
# Copier reports a syntax error as `TemplateSyntaxError: Missing end of comment
# tag` with no filename and a line number into the rendered stream, which sends
# you looking through 190 files by hand. This names the file and the line.
#
# The trap that motivated it: Jinja opens a comment on `{` followed by `#`, and
# the shell's array-length form is exactly that. A valid shell script became an
# unterminated Jinja comment, and generation failed for the whole template.
# Same class as never interpolating a copier value into a linted line.
# ==============================================================================
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"${PYTHON:-python3}" - "$here" <<'PYEOF'
import sys
from pathlib import Path

# REFUSED, never skipped. This used to print "SKIPPED" and exit 0 when jinja2 was missing, so
# a maintainer's local run read green while parsing nothing — the empty-set trap this
# repository's own guards are built to refuse. Exit 2: "could not check" is its own outcome.
try:
    from jinja2 import Environment, TemplateSyntaxError
except ImportError:
    print("jinja-syntax: REFUSED — jinja2 is not installed, so nothing was parsed. Run `make venv`.")
    raise SystemExit(2)

root = Path(sys.argv[1]) / "template"
env = Environment()
checked = 0
failures = []

for path in sorted(root.rglob("*")):
    # A conditional in a PATH is rendered too, so a bad one breaks generation just as surely —
    # and the module toggles live in DIRECTORY names (`{% if include_deploy %}deploy...`). This
    # used to skip every directory, so a broken toggle compiled "OK" until copier hit it.
    body = path.is_file() and path.suffix == ".jinja"
    for text, where in ((path.name, "name"), *([(path.read_text(errors="ignore"), "body")]
                                               if body else [])):
        if "{" not in text:
            continue
        checked += 1
        try:
            env.parse(text)
        except TemplateSyntaxError as exc:
            rel = path.relative_to(root.parent)
            failures.append(f"{rel} ({where}, line {exc.lineno}): {exc.message}")
        except UnicodeDecodeError:
            pass

print(f"jinja-syntax: parsed {checked} template(s)")
if not checked:
    print("\njinja-syntax: FAILED — nothing was parsed. Has template/ moved?")
    raise SystemExit(1)
if failures:
    print("\njinja-syntax: FAILED — these do not compile, so generation dies for everyone:\n")
    for failure in failures:
        print(f"  ✗ {failure}")
    print("\nA '{' immediately followed by '#' opens a Jinja comment. In shell that is the")
    print("array-length form; write it with a counter variable instead.")
    raise SystemExit(1)
print("jinja-syntax: OK — every template compiles.")
PYEOF
