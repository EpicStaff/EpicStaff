"""
Backwards-compatibility shim — all DTOs have moved to ``shared.models.agent_service``.

This module is retained only to avoid import churn in files not yet
migrated.  New code must import from ``shared.models.agent_service`` directly.
"""

# Re-export everything so existing ``from app.models import X`` still works.
from shared.models.agent_service import (  # noqa: F401
    AgentRequest,
    ContextAttachment,
    LoopResult,
    ToolResult,
)
