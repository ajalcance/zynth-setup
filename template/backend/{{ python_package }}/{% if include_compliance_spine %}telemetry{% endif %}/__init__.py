"""Telemetry: envelope, fail-open emitter, and the coverage registry."""

from .emitter import Telemetry, emit, get_telemetry
from .envelope import make_event

__all__ = ["Telemetry", "emit", "get_telemetry", "make_event"]
