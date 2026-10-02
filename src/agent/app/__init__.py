"""
Public surface of the agent service application package.

Re-exports the primary entry-points that ``main.py`` and integration tests
need so they can import from ``app`` directly rather than from sub-modules.
Sits above every layer in the architecture; nothing inside ``app/`` imports
from this file.
"""

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

from app.data_loader import DataLoader
from app.factory import RunnerFactory
from app.request_handler import RequestHandler

__all__ = [
    "AgentRequest",
    "AgentSpec",
    "CollectionSpec",
    "ContextAttachment",
    "DataLoader",
    "LoopResult",
    "RequestHandler",
    "RunType",
    "RunnerFactory",
    "S3FileSpec",
    "SearchConfigEntry",
    "ToolResult",
]
