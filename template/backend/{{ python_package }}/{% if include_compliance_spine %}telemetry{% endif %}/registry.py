"""The observability coverage registry.

The contract that makes "monitor everything" mechanical: every API route maps to the envelope
actions it emits. ``tests/test_telemetry_coverage.py`` walks the real FastAPI app and fails the
gate when a route is missing here — so no feature can ship unobserved.

Keys are ``(HTTP method, path)`` exactly as registered on the app.
"""

from __future__ import annotations

# Actions emitted OUTSIDE any request route (e.g. background workers). The coverage guards
# union these in so "every emitted action" stays complete.
NON_ROUTE_ACTIONS: frozenset[str] = frozenset()

# System endpoints intentionally outside the observability contract (no principal, no security
# semantics; /health is probed frequently by the container healthcheck).
EXEMPT: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/"),
        ("GET", "/health"),
    }
)

# route → envelope actions it emits (directly or via the layers it calls).
COVERAGE: dict[tuple[str, str], tuple[str, ...]] = {
    ("GET", "/api/v1/example"): ("example.viewed",),
}
