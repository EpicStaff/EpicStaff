import asyncio

from api import operations
from litestar import Controller, get, post
from litestar.exceptions import NotFoundException
from models import CancelRequest, IndexRequest, PrechunkRequest, SearchRequest
from ....src.shared.enums.kowledge_new import RAGStrategy
from services.task_register import run_cancellable


class KnowledgeController(Controller):
    path = "/"

    @post("/index", status_code=202)
    async def index(self, data: IndexRequest) -> dict:
        # long-running: запускаем фоново (cancellable) и сразу отвечаем 202
        asyncio.create_task(run_cancellable(data, operations.index(data)))  # noqa: RUF006
        return {"rag_id": data.rag_id, "rag_strategy": data.rag_strategy}

    @post("/prechunk")
    async def prechunk(self, data: PrechunkRequest) -> dict:
        response = await run_cancellable(data, operations.prechunk(data))
        return response.model_dump(mode="json")

    @post("/search")
    async def search(self, data: SearchRequest) -> dict:
        response = await run_cancellable(data, operations.search(data))
        return response.model_dump(mode="json")

    @post("/cancel", status_code=204)
    async def cancel(self, data: CancelRequest) -> None:
        operations.cancel(data)

    @get("/index/status")
    async def index_status(self, rag_id: int, rag_strategy: RAGStrategy) -> dict:
        rag = await operations.index_status(rag_id, rag_strategy)
        if rag is None:
            raise NotFoundException(detail=f"Rag {rag_id} ({rag_strategy}) not found")
        return {
            "rag_id": rag_id,
            "rag_strategy": rag_strategy,
            "rag_status": rag.status.value,
            "error_message": rag.error_message,
        }

    @get("/health")
    async def health(self) -> dict:
        return {"status": "ok"}
