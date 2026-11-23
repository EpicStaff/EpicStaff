"""A session stop interrupts a running knowledge search instead of waiting for its result.

Cancelling the request closes its connection, which is what tells knowledge_new to
cancel the search on its side.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from services.graph.events import STOP_CHECK_INTERVAL_S, StopEvent
from services.graph.exceptions import StopSession
from services.knowledge_search_service import KnowledgeSearchService

pytestmark = pytest.mark.asyncio

STOP_AFTER_S = 0.1


class HangingKnowledgeClient:
    """A knowledge_new that never answers; records whether the request was cancelled."""

    def __init__(self) -> None:
        self.cancelled = False

    async def search_with_usage(self, **kwargs):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


async def test_stop_interrupts_a_running_search_and_cancels_the_request():
    knowledge_client = HangingKnowledgeClient()
    service = KnowledgeSearchService(redis_service=MagicMock(), knowledge_client=knowledge_client)
    stop_event = StopEvent()
    loop = asyncio.get_running_loop()
    loop.call_later(STOP_AFTER_S, stop_event.set)
    started_at = loop.time()

    searching = service.search_knowledges(
        sender="node",
        knowledge_collection_id=1,
        rag_type_id="naive:2",
        query="q",
        rag_search_config={"search_limit": 3, "similarity_threshold": 0.2},
        stop_event=stop_event,
    )
    # A stop that is ignored would hang forever; fail with TimeoutError instead.
    with pytest.raises(StopSession):
        await asyncio.wait_for(searching, timeout=5)
    interrupted_after = loop.time() - started_at
    await asyncio.sleep(0.05)

    assert knowledge_client.cancelled
    assert interrupted_after < STOP_AFTER_S + STOP_CHECK_INTERVAL_S + 0.25
