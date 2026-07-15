"""The event envelope (schema v1) — the one shape every telemetry event takes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Request

SCHEMA_V = 1
SEV_INFO = "info"
SEV_WARN = "warn"
SEV_CRITICAL = "critical"
ACTOR_SYSTEM = "system"
ACTOR_HUMAN = "human"


def make_event(
    *,
    category: str,
    action: str,
    outcome: str,
    severity: str = SEV_INFO,
    actor_type: str = ACTOR_SYSTEM,
    actor_id: str | None = None,
    sid: str | None = None,
    tenant_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    ip: str | None = None,
    correlation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a schema-v1 envelope dict (JSON-ready)."""
    return {
        "event_id": uuid.uuid4().hex,
        "ts": datetime.now(UTC).isoformat(),
        "schema_v": SCHEMA_V,
        "actor": {"type": actor_type, "id": actor_id, "sid": sid},
        "tenant_id": tenant_id,
        "category": category,
        "action": action,
        "outcome": outcome,
        "severity": severity,
        "resource": {"type": resource_type, "id": resource_id},
        "correlation_id": correlation_id,
        "ip": ip,
        "metadata": metadata or {},
    }


def client_ip(request: Request) -> str | None:
    """Best-effort client IP: first X-Forwarded-For hop, else peer."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None
