"""
Public surface of the agent service application package.

Re-exports the primary entry-points that ``main.py`` and integration tests
need so they can import from ``app`` directly rather than from sub-modules.
Sits above every layer in the architecture; nothing inside ``app/`` imports
from this file.
"""

from app.data_loader import DataLoader
from app.factory import RunnerFactory
from app.request_handler import RequestHandler
from shared.models.agent_service import (
    AgentRequest,
    AgentSpec,
    CollectionSpec,
    ContextAttachment,
    LoopResult,
    RunType,
    S3FileSpec,
    SearchConfigEntry,
    ToolResult,
)

__all__ = [
    "DataLoader",
    "RunnerFactory",
    "RequestHandler",
    "RunType",
    "AgentRequest",
    "AgentSpec",
    "CollectionSpec",
    "SearchConfigEntry",
    "S3FileSpec",
    "ToolResult",
    "ContextAttachment",
    "LoopResult",
]
