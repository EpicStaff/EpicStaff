from application.commands import RemoveRag
from application.orchestrators.removing.base import AbstractRagRemoveOrchestrator
from domain.enums import IndexStatusEnum
from domain.errors import (
    RagInProcessingError,
    RagNotFoundError,
)
from graphrag_storage import create_storage
from infrastructure.graphrag.storages import create_storage_config


class GraphRagRemoveOrchestrator(AbstractRagRemoveOrchestrator):
    async def on_execute(self, command: RemoveRag):
        async with self.uow:
            rag = await self.uow.graph_rag_repo.get_rag(command.rag_id)
            if not rag:
                raise RagNotFoundError(rag_id=command.rag_id)

        if rag.status == IndexStatusEnum.PROCESSING:
            raise RagInProcessingError(rag_id=command.rag_id)

        storage_config = create_storage_config(rag.id)
        storage = create_storage(storage_config)
        await storage.clear()
