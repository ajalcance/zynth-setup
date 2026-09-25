"""A root copy of a template guard is the template's guard, byte for byte.

`secret_scan.py` and `check_unicode_hazards.py` locate the repository from their own path, so
the root needs its own copy to scan the root. A copy that drifts is a second definition — the
thing the CI-layer-mirroring rule exists to prevent — so the copy is allowed to exist only
while it is identical. Change the template's; copy it over; this goes green again.
"""

from __future__ import annotations

import pytest
from conftest import ROOT

VENDORED = ("secret_scan.py", "check_unicode_hazards.py")


@pytest.mark.parametrize("name", VENDORED)
def test_the_root_copy_is_the_templates_guard(name):
    root_copy = ROOT / "scripts" / name
    original = ROOT / "template" / "scripts" / name
    assert original.is_file(), f"template/scripts/{name} is gone — this test is now vacuous"
    assert root_copy.read_bytes() == original.read_bytes(), (
        f"scripts/{name} has drifted from template/scripts/{name}. Fix the template's, then "
        f"copy it over: cp template/scripts/{name} scripts/{name}"
    )
