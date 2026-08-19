"""
KnowledgeSearchTarget — the minimal wire-ready description of one search call.

Decoupled from ``CollectionSpec`` / ``SearchConfigEntry`` so that
``KnowledgeClient`` and ``KnowledgeSearchExecutor`` have no dependency on the
full collection model.  Maps 1-to-1 onto the fields required by
``BaseKnowledgeSearchMessage``.

Note: ``embedder`` is intentionally absent.  It lives on ``SearchConfigEntry``
for forward-compatibility but is not part of the Redis wire message.
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
