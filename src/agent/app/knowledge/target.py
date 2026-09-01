"""
KnowledgeSearchTarget — the minimal wire-ready description of one search call.

Decoupled from ``CollectionSpec`` / ``SearchConfigEntry`` so that
``KnowledgeClient`` and ``KnowledgeSearchExecutor`` have no dependency on the
full collection model.  Carries the resolved embedder/LLM credentials the
knowledge_new REST search endpoint expects.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from shared.models.knowledge import RagSearchConfig


class KnowledgeSearchTarget(BaseModel):
    """Immutable description of a single knowledge search operation.

    Passed to ``KnowledgeSearchExecutor`` and ``KnowledgeClient.search``
    instead of the full ``CollectionSpec``.
    """

    model_config = ConfigDict(frozen=True)

    collection_id: int
    rag_id: int
    rag_type: Literal["naive", "graph"]
    search_config: RagSearchConfig
    embedder_api_key: str | None = None
    llm_api_key: str | None = None
    """Graph RAG runs LLM calls server-side; naive search leaves this ``None``."""
