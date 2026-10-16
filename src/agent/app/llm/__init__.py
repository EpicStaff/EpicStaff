"""
Layer 2 — LLM sub-package.

Re-exports the ``LLMClient`` ABC, normalized chunk models, and the concrete
``LiteLLMClient`` with its collaborators ``RetryPolicy`` and ``ConcurrencyLimiter``.
"""

from app.llm.client import LLMChunk, LLMClient, ToolCallFragment
from app.llm.concurrency_limiter import ConcurrencyLimiter, get_concurrency_limiter
from app.llm.litellm_client import LiteLLMClient
from app.llm.retry import RetryPolicy

__all__ = [
    "ConcurrencyLimiter",
    "LLMChunk",
    "LLMClient",
    "LiteLLMClient",
    "RetryPolicy",
    "ToolCallFragment",
    "get_concurrency_limiter",
]
