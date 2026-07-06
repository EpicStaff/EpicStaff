"""
Agent-service-local enumerations.

``RunType`` has moved to ``shared.models.agent_service`` so that the wire
contract is defined in a single place.  Import it from there.

``EmitterMode`` is runtime/agent-only — it is never serialised and is not
part of the cross-service contract.
"""

from enum import Enum

# Re-export RunType from shared so existing intra-agent imports keep working.
from shared.models.agent_service import RunType  # noqa: F401


class EmitterMode(str, Enum):
    """Output transport strategy declared per ``Runner`` subclass.

    ``BATCH`` — buffer all events, publish a single result envelope on
    ``on_final``.
    ``TOOL_EVENTS`` — buffer everything ``BATCH`` does, plus publish live
    ``agent.tool_call`` / ``agent.tool_result`` envelopes as they happen
    (``RedisStreamToolEventEmitter``).
    ``STREAM`` — publish LLM delta chunks in real time; reserved for the
    future ``ChatRunner`` and a ``RedisStreamDeltaEmitter`` implementation.
    """

    BATCH = "BATCH"
    TOOL_EVENTS = "TOOL_EVENTS"
    STREAM = "STREAM"
