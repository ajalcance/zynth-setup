"""Detection rules — the declarative threat/anomaly catalog.

Rules are DATA. Coverage is enforced: every emitted action must be named by a specific rule
**or** appear in ``BASELINE_ONLY`` (a reviewed decision that the global catch-alls are enough).
The guard test fails otherwise, so no feature can ship without a detection decision.

(The evaluation engine itself is intentionally left for you to build or plug in — a SIEM, a
worker loop, etc. This module is the *decision registry* the coverage guard enforces.)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Rule:
    """One threshold rule evaluated over a sliding window of the events store."""

    id: str
    title: str
    description: str
    threshold: int
    window_seconds: int
    severity: str
    actions: tuple[str, ...] = ()  # empty = any action (catch-all)
    outcomes: tuple[str, ...] = ()  # empty = any outcome
    min_severity: str | None = None


DEFAULT_RULES: tuple[Rule, ...] = (
    # Global catch-alls (future-proof: cover anything not specifically ruled).
    Rule(
        id="critical-catchall",
        title="Critical event",
        description="Any critical-severity event, from any module — present or future.",
        min_severity="critical",
        threshold=1,
        window_seconds=300,
        severity="critical",
    ),
    Rule(
        id="failure-surge",
        title="System-wide failure surge",
        description="Unusual volume of failed/denied outcomes across the whole system.",
        outcomes=("failure", "denied"),
        threshold=30,
        window_seconds=300,
        severity="warn",
    ),
)

# Actions with NO specific rule — the global catch-alls are their safety net. Adding a new
# telemetry action without either a rule or an entry here fails the coverage guard.
BASELINE_ONLY: frozenset[str] = frozenset(
    {
        "example.viewed",  # benign read; volume anomalies → the surge catch-all
    }
)

RULES_BY_ID: dict[str, Rule] = {r.id: r for r in DEFAULT_RULES}
