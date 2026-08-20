"""
Tools sub-package.

Re-exports ``ToolRegistry`` and ``ToolSpec`` for use by ``SurfaceResolver``
(populates the registry) and ``AgentLoop`` (reads specs, dispatches calls).

Also re-exports builder components for assembling per-run registries.
"""

from app.sandbox.client import SandboxClient
from app.tools.registry import ToolRegistry, ToolSpec
from app.tools.registry_builder import ToolRegistryBuilder
from app.tools.system_registry import (
    SystemToolRegistry,
    get_system_registry,
    system_tool,
)

__all__ = [
    "ToolRegistry",
    "ToolSpec",
    "system_tool",
    "SystemToolRegistry",
    "get_system_registry",
    "ToolRegistryBuilder",
    "SandboxClient",
]
