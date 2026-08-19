"""Telemetry: envelope, fail-open emitter, and the coverage registry."""

from .emitter import Telemetry, emit, get_telemetry
from .envelope import SOURCE_CLIENT, SOURCE_SERVER, make_event

__all__ = ["SOURCE_CLIENT", "SOURCE_SERVER", "Telemetry", "emit", "get_telemetry", "make_event"]
