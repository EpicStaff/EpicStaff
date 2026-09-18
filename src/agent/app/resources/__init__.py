"""
Resources sub-package: resolves per-agent resource references into live executors.

``AgentResolver`` is the single entry point.  It validates tool/rag/s3 refs
against the request-level resource pools, builds a ``ToolRegistry`` for each
agent, and returns a ``ResolvedAgent`` ready for ``AgentLoop.run``.
"""

from app.resources.resolver import AgentResolver, ResolvedAgent

__all__ = ["AgentResolver", "ResolvedAgent"]
