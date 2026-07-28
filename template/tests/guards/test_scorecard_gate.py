"""scorecard_gate must fail a real regression, tolerate an absent result, and stay reachable."""

from __future__ import annotations

import json

from conftest import SCRIPTS, run_guard, write

GUARD = SCRIPTS / "scorecard_gate.py"


def _results(tmp_path, **scores) -> str:
    path = tmp_path / "results.json"
    write(path, json.dumps({"checks": [{"name": k, "score": v} for k, v in scores.items()]}))
    return str(path)


def _healthy(**overrides):
    scores = {
        "Branch-Protection": 4,
        "Token-Permissions": 10,
        "Pinned-Dependencies": 9,
        "Dangerous-Workflow": 10,
    }
    scores.update(overrides)
    return scores


def test_healthy_posture_passes(tmp_path):
    result = run_guard(GUARD, _results(tmp_path, **_healthy()), "--min", "7")
    assert result.returncode == 0, result.stdout


def test_regression_in_a_gated_check_fails(tmp_path):
    result = run_guard(GUARD, _results(tmp_path, **_healthy(**{"Token-Permissions": 5})), "--min", "7")
    assert result.returncode != 0, "a gated check below threshold must fail"
    assert "Token-Permissions" in result.stdout


def test_branch_protection_override_is_reachable_but_still_gates(tmp_path):
    """A solo repo caps Branch-Protection near 4; gating at 7 would be unreachable and vacuous."""
    at_cap = run_guard(GUARD, _results(tmp_path, **_healthy()), "--min", "7")
    below = run_guard(GUARD, _results(tmp_path, **_healthy(**{"Branch-Protection": 3})), "--min", "7")
    assert at_cap.returncode == 0, "the solo-repo ceiling must not fail the gate"
    assert below.returncode != 0, "dropping below the override must still fail"


def test_missing_results_warns_without_failing(tmp_path):
    """Scorecard cannot run on a private repo without a PAT; that is 'inactive', not 'regressed'."""
    result = run_guard(GUARD, str(tmp_path / "absent.json"), "--min", "7")
    assert result.returncode == 0
    assert "WARNING" in result.stdout
