"""
Layer 2 — LLM sub-package.

Re-exports the ``LLMClient`` ABC, normalized chunk models, and the concrete
``LiteLLMClient`` with its collaborators ``RetryPolicy`` and ``RouterPool``.
"""

from app.llm.client import LLMChunk, LLMClient, ToolCallFragment
from app.llm.litellm_client import LiteLLMClient
from app.llm.retry import RetryPolicy
from app.llm.router_pool import RouterPool, get_router_pool

__all__ = [
    "LLMClient",
    "LLMChunk",
    "ToolCallFragment",
    "LiteLLMClient",
    "RetryPolicy",
    "RouterPool",
    "get_router_pool",
]
