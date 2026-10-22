from dataclasses import asdict

import pandas
from application.commands import RunIndex
from application.orchestrators.indexing.base import AbstractIndexOrchestrator
from common.utils import utcnow
from domain.enums import DocumentStatusEnum, IndexStatusEnum, SlotEnum
from domain.errors import (
    DocumentNotFoundError,
    GraphRagConfigNotFoundError,
    RagNotFoundError,
    RepositoryError,
)
from domain.models import GraphPricingConfig, Rag
from domain.usage import IndexingRunUsage, UsageTally
from graphrag.api import build_index
from graphrag.config.models.graph_rag_config import GraphRagConfig
from graphrag_input import TextDocument
from graphrag_storage import create_storage
from infrastructure.graphrag.model_headers import set_extra_headers
from infrastructure.graphrag.storages import create_storage_config
from infrastructure.graphrag.usage_metrics import track_usage
from infrastructure.graphrag.vector_stores import create_vector_store_config
from infrastructure.token_estimation import qualified_model_name
from infrastructure.usage_cost import embedding_cost, llm_cost, sum_costs
from loguru import logger


class GraphIndexOrchestrator(AbstractIndexOrchestrator):
    async def on_execute(self, command: RunIndex):
        async with self.uow:
            rag = await self._get_rag_under_uow(command.rag_id)
            documents = await self._get_documents_under_uow(rag.id, command.document_ids)

        is_update_run = False
        target_slot = None
        if rag.status == IndexStatusEnum.COMPLETED:
            if self._has_indexed_document(documents):
                logger.debug("REINDEX")
                documents += await self._get_indexed_documents_excluding(
                    rag.id, command.document_ids
                )
                target_slot = SlotEnum.A if rag.slot == SlotEnum.B else SlotEnum.B
                self.state["target_slot"] = target_slot
            else:
                is_update_run = True

        config = await self._get_config_under_uow(
            rag.id, target_slot, command.embedding_api_key, command.llm_api_key
        )
        set_extra_headers(
            config.embedding_models["default_embedding_model"], command.embedding_extra_headers
        )
        set_extra_headers(
            config.completion_models["default_completion_model"], command.llm_extra_headers
        )

        rag.mark_as_processing(command.document_ids)
        await self._update_rag(rag)

        input_documents = pandas.DataFrame(data=[asdict(d) for d in documents])
        input_documents["human_readable_id"] = input_documents.index
        with track_usage(config) as usage:
            self.state["usage"] = usage
            results = await build_index(
                config=config,
                input_documents=input_documents,
                verbose=True,
                is_update_run=is_update_run,
            )

        errors = {r.workflow: r.error for r in results if r.error is not None}
        if errors:
            await self._update_status_of_documents(
                rag.id, command.document_ids, status=DocumentStatusEnum.FAILED
            )
            raise ExceptionGroup(
                f"GraphRAG indexing failed for RAG(id={rag.id}) "
                f"in workflow(s): {', '.join(errors.keys())}.",
                list(errors.values()),
            )

        await self._update_status_of_documents(
            rag.id, command.document_ids, DocumentStatusEnum.COMPLETED
        )
        await self._record_usage(rag.id)
        await self._finish_rag(rag, command.document_ids)

        logger.info("Finished indexing in RAG(id={}, status={}).", rag.id, rag.status.value)

    async def on_cancel(self, command: RunIndex):
        rag: Rag | None = self.state.get("rag")
        target_slot: SlotEnum | None = self.state.get("target_slot")

        if rag:
            rag.mark_as_cancelled()
            rag.finish_document(*command.document_ids)
            await self._update_rag(rag)
            await self._record_usage(rag.id)
            if target_slot:
                await self._clear_slot_storage(rag.id, target_slot)

    async def on_error(self, command: RunIndex, error: Exception):
        rag: Rag | None = self.state.get("rag")
        target_slot: SlotEnum | None = self.state.get("target_slot")

        if rag:
            rag.mark_as_failed(error)
            rag.finish_document(*command.document_ids)
            await self._update_rag(rag)
            await self._record_usage(rag.id)
            if target_slot:
                await self._clear_slot_storage(rag.id, target_slot)

    async def _get_rag_under_uow(self, rag_id: int) -> Rag:
        rag = await self.uow.graph_rag_repo.get_rag(rag_id=rag_id)
        if rag is None:
            raise RagNotFoundError(rag_id=rag_id)
        self.state["rag"] = rag
        return rag

    async def _get_config_under_uow(
        self, rag_id: int, slot: SlotEnum, embedding_api_key: str, llm_api_key: str
    ):
        async with self.uow:
            config = await self.uow.graph_rag_repo.get_config(rag_id=rag_id, slot=slot)
        if not config:
            raise GraphRagConfigNotFoundError(rag_id=rag_id)
        config.embedding_models["default_embedding_model"].api_key = embedding_api_key
        config.completion_models["default_completion_model"].api_key = llm_api_key
        return config

    async def _record_usage(self, rag_id: int):
        """Store what the run consumed on the RAG, once per run.

        Token counts are only what graphrag's responses reported; the cost is None when
        the embedding or LLM model has no price. A failure to store is logged, not
        raised: the index already succeeded or failed on its own terms.
        """
        tally = self.state.pop("usage", None)
        if tally is None or tally.is_empty:
            return
        try:
            async with self.uow:
                pricing = await self.uow.graph_rag_repo.get_pricing_config(rag_id=rag_id)
                run = IndexingRunUsage(
                    embedding_tokens=tally.embedding_tokens,
                    llm_input_tokens=tally.llm_input_tokens,
                    llm_output_tokens=tally.llm_output_tokens,
                    cost_usd=self._cost_usd(tally, pricing),
                    completed_at=utcnow(),
                )
                await self.uow.graph_rag_repo.add_indexing_usage(rag_id=rag_id, run=run)
                await self.uow.commit()
        except RepositoryError as error:
            logger.warning("Could not store indexing usage of RAG(id={}): {}", rag_id, error)

    @staticmethod
    def _cost_usd(tally: UsageTally, pricing: GraphPricingConfig | None) -> float | None:
        """None when the RAG's pricing config is gone or a model has no price."""
        if pricing is None:
            return None
        return sum_costs(
            embedding_cost(
                qualified_model_name(pricing.embedding.provider, pricing.embedding.model),
                tally.embedding_tokens,
            ),
            llm_cost(
                qualified_model_name(pricing.llm_provider, pricing.llm_model),
                tally.llm_input_tokens,
                tally.llm_output_tokens,
                pricing.input_cost_per_token,
                pricing.output_cost_per_token,
            ),
        )

    async def _get_documents_under_uow(
        self, rag_id: int, ids: frozenset[int]
    ) -> list[TextDocument]:
        documents = await self.uow.graph_rag_repo.get_documents(rag_id=rag_id, ids=ids)

        if not documents:
            raise DocumentNotFoundError(f"No Document found for RAG(id={rag_id}).")
        return documents

    async def _get_indexed_documents_excluding(self, rag_id: int, ids: frozenset[int]):
        async with self.uow:
            return await self.uow.graph_rag_repo.get_indexed_documents_excluding(
                rag_id=rag_id, ids=ids
            )

    async def _update_rag(self, rag: Rag):
        async with self.uow:
            await self.uow.graph_rag_repo.update_rag(rag)
            await self.uow.commit()

    def _has_indexed_document(self, documents: list[TextDocument]) -> bool:
        return any(d.raw_data["status"] == DocumentStatusEnum.COMPLETED for d in documents)

    async def _update_status_of_documents(
        self,
        rag_id: int,
        ids: frozenset[int],
        status: DocumentStatusEnum,
    ):
        async with self.uow:
            await self.uow.graph_rag_repo.update_status_of_documents(
                rag_id=rag_id,
                ids=ids,
                status=status,
            )
            await self.uow.commit()

    async def _finish_rag(self, rag: Rag, document_ids: set[int]):
        old_slot = rag.slot
        target_slot = self.state.get("target_slot")

        async with self.uow:
            rag.finish_document(*document_ids)

            has_outdated = await self.uow.graph_rag_repo.has_outdated_document(rag_id=rag.id)
            has_completed = await self.uow.graph_rag_repo.has_completed_document(rag_id=rag.id)
            has_failed = await self.uow.graph_rag_repo.has_failed_document(rag_id=rag.id)

            if has_outdated:
                rag.mark_as_outdated()
            elif rag.indexing_document_ids:
                rag.status = IndexStatusEnum.PROCESSING
            elif has_completed:
                rag.mark_as_completed()
            elif has_failed:
                rag.mark_as_failed("Failed to index all documents.")
            else:
                rag.mark_as_new()
                # need to delete indexing result of graph rag

            if not has_outdated:
                rag.outdated_reasons.clear()

            if target_slot:
                rag.slot = target_slot

            await self.uow.graph_rag_repo.update_rag(rag=rag)
            await self.uow.commit()

        if target_slot:
            await self._clear_slot_storage(rag.id, old_slot)

    @staticmethod
    def _swap_slot_for_config(target_slot: SlotEnum, rag_id: int, config: GraphRagConfig):
        config.input_storage = create_storage_config(rag_id=rag_id, subdir=f"{target_slot}/input")
        config.output_storage = create_storage_config(rag_id=rag_id, subdir=f"{target_slot}/output")
        config.update_output_storage = create_storage_config(
            rag_id=rag_id, subdir=f"{target_slot}/update_output"
        )
        config.vector_store = create_vector_store_config(rag_id=rag_id, subdir=target_slot)

    @staticmethod
    async def _clear_slot_storage(rag_id: int, target_slot: SlotEnum):
        storage_config = create_storage_config(rag_id=rag_id, subdir=target_slot)
        storage = create_storage(storage_config)
        await storage.clear()
