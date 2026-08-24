"""
KnowledgeEventSink: narrow protocol knowledge-search executors depend on
instead of the full ``Emitter`` ABC (Interface Segregation — executors have
no business seeing ``on_chunk``/``on_final``/etc).

``ToolRegistryBuilder`` registers each knowledge tool's final (post-collision
-suffix) name via ``register_knowledge_tool`` so the emitter can recognise
which live ``agent.tool_call``/``agent.tool_result`` envelopes to suppress in
favour of the richer ``agent.knowledge_search`` envelope.
"""

from __future__ import annotations

from typing import Protocol

from shared.models.knowledge import BaseKnowledgeSearchMessageResponse


class KnowledgeEventSink(Protocol):
    def register_knowledge_tool(self, name: str) -> None: ...

    async def on_knowledge_search(
        self, response: BaseKnowledgeSearchMessageResponse
    ) -> None: ...
