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
    result = run_guard(
        GUARD, _results(tmp_path, **_healthy(**{"Token-Permissions": 5})), "--min", "7"
    )
    assert result.returncode != 0, "a gated check below threshold must fail"
    assert "Token-Permissions" in result.stdout


def test_branch_protection_override_is_reachable_but_still_gates(tmp_path):
    """A solo repo caps Branch-Protection near 4; gating at 7 would be unreachable and vacuous."""
    at_cap = run_guard(GUARD, _results(tmp_path, **_healthy()), "--min", "7")
    below = run_guard(
        GUARD, _results(tmp_path, **_healthy(**{"Branch-Protection": 3})), "--min", "7"
    )
    assert at_cap.returncode == 0, "the solo-repo ceiling must not fail the gate"
    assert below.returncode != 0, "dropping below the override must still fail"


def test_missing_results_warns_without_failing(tmp_path):
    """Scorecard cannot run on a private repo without a PAT; that is 'inactive', not 'regressed'."""
    result = run_guard(GUARD, str(tmp_path / "absent.json"), "--min", "7")
    assert result.returncode == 0
    assert "WARNING" in result.stdout


def test_every_check_skipped_is_a_failure_not_a_pass(tmp_path):
    """The denominator rule (EXP-0001), in the one guard where each skip is legitimate.

    Scorecard returns -1 for "cannot tell", and failing on a single -1 would be vacuous. But
    when EVERY gated check is inconclusive, nothing was measured — and printing OK reports a
    posture this run never looked at, which reads exactly like a healthy repository.
    """
    results = tmp_path / "results.json"
    write(
        results,
        json.dumps(
            {
                "checks": [
                    {"name": "Branch-Protection", "score": -1},
                    {"name": "Token-Permissions", "score": -1},
                    {"name": "Pinned-Dependencies", "score": -1},
                    {"name": "Dangerous-Workflow", "score": -1},
                ]
            }
        ),
    )
    result = run_guard(GUARD, str(results))
    assert result.returncode != 0, "measuring nothing must not print OK"
    assert "never measured" in result.stdout, result.stdout


def test_an_empty_results_document_is_a_failure(tmp_path):
    """No checks at all is the same empty set arriving by a different route."""
    results = tmp_path / "results.json"
    write(results, json.dumps({"checks": []}))
    result = run_guard(GUARD, str(results))
    assert result.returncode != 0, "a results file with no checks must fail"


def test_one_inconclusive_check_among_several_still_passes(tmp_path):
    """The other direction: a single -1 must stay a skip, or the gate becomes noise."""
    results = tmp_path / "results.json"
    write(
        results,
        json.dumps(
            {
                "checks": [
                    {"name": "Branch-Protection", "score": -1},
                    {"name": "Token-Permissions", "score": 9},
                    {"name": "Pinned-Dependencies", "score": 10},
                    {"name": "Dangerous-Workflow", "score": 10},
                ]
            }
        ),
    )
    result = run_guard(GUARD, str(results))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "evaluated 3/4" in result.stdout, result.stdout
