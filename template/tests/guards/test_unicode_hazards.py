"""check_unicode_hazards must reject source that reads differently from how it runs.

Every fixture here builds its hazard with ``chr()`` at runtime. Writing a bidirectional
override as a literal would put one in this repository's own tree, where this very guard
would then find it — and the remedy would be an exemption, which is how a scanner gets
widened until it stops catching anything.
"""

from __future__ import annotations

import pytest
from conftest import REPO_ROOT, SCRIPTS, run_guard, write

GUARD = SCRIPTS / "check_unicode_hazards.py"

RLO = chr(0x202E)  # right-to-left override — the Trojan Source character
LRI = chr(0x2066)  # left-to-right isolate
ZWSP = chr(0x200B)  # zero-width space
ZWJ = chr(0x200D)
SOFT_HYPHEN = chr(0x00AD)
BOM = chr(0xFEFF)


def test_the_tree_this_project_ships_is_clean():
    """The positive control, and the reason this gate can be turned on at all."""
    result = run_guard(GUARD, cwd=REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "inspected" in result.stdout


@pytest.mark.parametrize(
    ("name", "character"),
    [
        ("right-to-left override", RLO),
        ("left-to-right isolate", LRI),
        ("zero-width space", ZWSP),
        ("zero-width joiner", ZWJ),
        ("soft hyphen", SOFT_HYPHEN),
    ],
)
def test_each_hazard_class_is_caught(tmp_path, name, character):
    source = tmp_path / "app.py"
    write(source, f"if is_admin:  # {character} always false\n    grant()\n")
    result = run_guard(GUARD, str(tmp_path), cwd=REPO_ROOT)
    assert result.returncode != 0, f"a {name} must be rejected"
    assert "app.py" in result.stdout, result.stdout


def test_the_finding_names_the_codepoint_and_the_position(tmp_path):
    """A hazard you cannot see needs the file, line, column and codepoint to be actionable."""
    write(tmp_path / "app.py", f"x = 1  # {RLO}\n")
    result = run_guard(GUARD, str(tmp_path), cwd=REPO_ROOT)
    assert "U+202E" in result.stdout, result.stdout
    assert "app.py:1:" in result.stdout, result.stdout


def test_ordinary_non_ascii_is_allowed(tmp_path):
    """Em dashes, accents, box drawing and emoji are normal writing.

    A gate that rejects them is turned off within a week, and then catches nothing at all.
    """
    write(
        tmp_path / "doc.md",
        "# Über café — naïve résumé\n\n┌───┐\n│ ok │\n└───┘\n\nShipped 🚀 by Ólafur.\n",
    )
    result = run_guard(GUARD, str(tmp_path), cwd=REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_byte_order_mark_at_the_start_of_a_file_is_allowed(tmp_path):
    """Some editors write one and no parser mis-reads it."""
    write(tmp_path / "app.py", f"{BOM}x = 1\n")
    result = run_guard(GUARD, str(tmp_path), cwd=REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_same_character_later_in_the_file_is_not_allowed(tmp_path):
    """Otherwise the BOM exemption is a hole shaped like a zero-width no-break space."""
    write(tmp_path / "app.py", f"x = 1\ny{BOM} = 2\n")
    result = run_guard(GUARD, str(tmp_path), cwd=REPO_ROOT)
    assert result.returncode != 0, "U+FEFF anywhere but the first byte must be rejected"


def test_inspecting_no_file_at_all_fails(tmp_path):
    """The denominator rule: a scan of an empty set reports green forever."""
    (tmp_path / "empty").mkdir()
    result = run_guard(GUARD, str(tmp_path / "empty"), cwd=REPO_ROOT)
    assert result.returncode != 0, "inspecting zero files must fail (EXP-0001)"
    assert "inspected 0 file" in result.stdout, result.stdout


def test_binary_files_are_skipped_not_decoded(tmp_path):
    """A PNG full of high bytes must not produce noise, or the gate gets narrowed."""
    (tmp_path / "logo.png").write_bytes(bytes(range(256)) * 4)
    write(tmp_path / "app.py", "x = 1\n")
    result = run_guard(GUARD, str(tmp_path), cwd=REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
