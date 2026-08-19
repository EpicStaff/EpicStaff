"""
Layer 3 — AgentLoop sub-package.

Re-exports the loop ABC, its runtime context, and the stop-policy hierarchy.
``Runner`` subclasses import from here to drive single-agent tool-use cycles
without depending on internal module paths.
"""

from app.loop.agent_loop import AgentLoop, DefaultAgentLoop
from app.loop.context import AgentContext
from app.loop.stop_policy import MaxIterAndNoToolCalls, StopPolicy

__all__ = [
    "AgentLoop",
    "DefaultAgentLoop",
    "AgentContext",
    "StopPolicy",
    "MaxIterAndNoToolCalls",
]
