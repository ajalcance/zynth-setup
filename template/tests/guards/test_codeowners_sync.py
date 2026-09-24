"""A file the meta-guard gates is a file CODEOWNERS names: one decision, two lists.

The label the meta-guard demands and the review CODEOWNERS requests are the same decision —
"a human looks at this before it merges" — kept in two files that nothing reconciled. The
lesson registry, the decision records and the scanner manifest were gated by the meta-guard
for months while CODEOWNERS, which the two-person posture rests on, listed none of them.
The population is the hand-written one the protected-path reconciliation already keeps.
"""

from __future__ import annotations

import pytest
from conftest import REPO_ROOT
from test_protected_path_reconciliation import CONSEQUENTIAL, _regex

CODEOWNERS = REPO_ROOT / ".github" / "CODEOWNERS"


def _patterns() -> list[str]:
    patterns = []
    for line in CODEOWNERS.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped.split()[0])
    assert patterns, "CODEOWNERS names nothing — this assertion would be vacuous"
    return patterns


def _covered(path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        anchored = pattern.lstrip("/")
        if anchored.endswith("/"):
            if path.startswith(anchored):
                return True
        elif path == anchored:
            return True
    return False


@pytest.mark.parametrize("path", CONSEQUENTIAL)
def test_every_guard_file_has_a_code_owner(path):
    if not _regex("GUARD_FILE_RE").match(path):
        pytest.skip(f"{path} is not a guard file")
    assert _covered(path, _patterns()), (
        f"{path} needs the owner's label on a pull request, but CODEOWNERS requests no review "
        f"for it — with solo_maintainer=false that review is the control. Add it to CODEOWNERS."
    )


def test_the_owner_named_is_the_one_who_answered():
    """CODEOWNERS must name the github_owner the generation recorded, not a placeholder."""
    owners = {
        tok
        for line in CODEOWNERS.read_text().splitlines()
        for tok in line.split()
        if tok.startswith("@")
    }
    assert owners, "CODEOWNERS assigns no owner at all"
    placeholders = {o for o in owners if o.lower() in ("@you", "@owner", "@your-org", "@todo")}
    assert not placeholders, f"CODEOWNERS still carries a placeholder owner: {placeholders}"
