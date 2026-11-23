import asyncio
import os
import tempfile
from typing import Annotated, Literal

import anyio
from application import commands
from application.commands import (
    GetEntityDetail,
    GetGraphTableData,
    GetGraphTableSummary,
    GetGraphVisualization,
    GetMetrics,
    GetRelationshipDetail,
    RemoveRag,
)
from application.graph_index_read_limits import (
    GRAPH_SEARCH_MAX_LENGTH,
    GRAPH_TABLE_DEFAULT_PAGE,
    GRAPH_TABLE_DEFAULT_PAGE_SIZE,
    GRAPH_TABLE_MAX_PAGE_SIZE,
    GRAPH_TABLE_MIN_PAGE,
    GRAPH_TABLE_MIN_PAGE_SIZE,
    GRAPH_VISUALIZATION_DEFAULT_MAX_ENTITIES,
    GRAPH_VISUALIZATION_MIN_MAX_ENTITIES,
)
from application.orchestrators.estimating import build_estimator
from application.orchestrators.graph_table_data import (
    build_graph_table_data,
    build_graph_table_summary,
)
from application.orchestrators.graph_visualization import (
    build_entity_detail,
    build_graph_visualization,
    build_relationship_detail,
)
from application.orchestrators.indexing import build_indexer
from application.orchestrators.metrics import build_metrics
from application.orchestrators.prechunking import build_prechunker
from application.orchestrators.removing.factory import build_remover
from application.orchestrators.searching import build_search
from application.orchestrators.transferring.factory import (
    build_artifact_exporter,
    build_artifact_restorer,
    build_document_id_rewriter,
)
from application.ports import AbstractUnitOfWork
from application.ports.artifact_store import AbstractArtifactStore
from application.ports.task_register import AbstractTaskRegister
from common.utils import make_key
from domain.enums import RAGStrategy
from domain.errors import NotRunningOperationError
from foundation.cryptographer import AbstractCryptographer
from infrastructure.graphrag.availability import is_graphrag_available
from litestar import Controller, Request, Response, delete, get, post, put, status_codes
from litestar.connection import ASGIConnection
from litestar.exceptions import HTTPException
from litestar.handlers.base import BaseRouteHandler
from litestar.params import Parameter
from litestar.response import Stream
from presentation.rest import schemas
from presentation.rest.disconnect import HTTP_499_CLIENT_CLOSED_REQUEST, run_until_disconnect


def require_graphrag_available(connection: ASGIConnection, _: BaseRouteHandler) -> None:
    """Reject GRAPH requests with 503 when graphrag cannot run on this host."""
    is_graph = connection.path_params.get("strategy") == RAGStrategy.GRAPH.value
    if is_graph and not is_graphrag_available():
        raise HTTPException(
            status_code=status_codes.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GraphRAG is unavailable on this server: the CPU does not support AVX2.",
        )


class RagController(Controller):
    path = "rags/{strategy:str}/"
    tags = ("RAG",)
    guards = [require_graphrag_available]

    @post(
        path="{rag_id:int}/index/",
        status_code=status_codes.HTTP_202_ACCEPTED,
        summary="Index documents",
    )
    async def index(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        data: schemas.IndexInputSchema,
        uow: AbstractUnitOfWork,
        task_register: AbstractTaskRegister,
        cryptographer: AbstractCryptographer,
    ) -> None:
        command = commands.RunIndex(
            rag_id=rag_id,
            document_ids=data.document_ids,
            embedding_api_key=data.embedding_api_key,
            llm_api_key=data.llm_api_key,
            embedding_extra_headers=data.embedding_extra_headers,
            llm_extra_headers=data.llm_extra_headers,
        )
        orchestrator = build_indexer(strategy, uow, cryptographer)
        task = asyncio.create_task(orchestrator.execute(command))
        key = make_key("rag", strategy, rag_id, "index")
        task_register.register(key, task)

    @post(
        path="{rag_id:int}/search/",
        status_code=status_codes.HTTP_200_OK,
        summary="Search the collection",
    )
    async def search(
        self,
        request: Request,
        strategy: RAGStrategy,
        rag_id: int,
        data: schemas.SearchInputSchema,
        uow: AbstractUnitOfWork,
        cryptographer: AbstractCryptographer,
    ) -> Response[schemas.SearchOutputSchema]:
        command = commands.RunSearch(
            rag_id=rag_id,
            query=data.query,
            search_config=data.search_config,
            embedding_api_key=data.embedding_api_key,
            llm_api_key=data.llm_api_key,
            embedding_extra_headers=data.embedding_extra_headers,
            llm_extra_headers=data.llm_extra_headers,
        )
        orchestrator = build_search(strategy, uow, cryptographer)
        result = await run_until_disconnect(request, orchestrator.execute(command))
        if result is None:
            return Response(content=b"", status_code=HTTP_499_CLIENT_CLOSED_REQUEST)
        return Response(schemas.SearchOutputSchema.model_validate(result))

    @post(
        path="{rag_id:int}/prechunk/",
        status_code=status_codes.HTTP_202_ACCEPTED,
        summary="Preview chunking",
    )
    async def prechunk(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        data: schemas.PrechunkInputSchema,
        uow: AbstractUnitOfWork,
    ) -> schemas.PrechunkOutputSchema:
        command = commands.RunPrechunk(
            rag_id=rag_id,
            document_id=data.document_id,
            chunking_config=data.chunking_config,
        )
        orchestrator = build_prechunker(strategy, uow)
        result = await orchestrator.execute(command)
        return schemas.PrechunkOutputSchema.model_validate(result)

    @post(
        path="{rag_id:int}/index-estimate/",
        status_code=status_codes.HTTP_200_OK,
        summary="Estimate indexing tokens and cost",
    )
    async def index_estimate(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        data: schemas.IndexEstimateInputSchema,
        uow: AbstractUnitOfWork,
    ) -> schemas.IndexEstimateOutputSchema:
        command = commands.GetIndexEstimate(
            rag_id=rag_id,
            document_ids=data.document_ids,
            chunking_overrides={
                override.document_id: override.chunking_config
                for override in data.chunking_overrides
            },
        )
        orchestrator = build_estimator(strategy, uow)
        result = await orchestrator.execute(command)
        return schemas.IndexEstimateOutputSchema.model_validate(result)

    @get(
        path="{rag_id:int}/metrics/",
        status_code=status_codes.HTTP_200_OK,
        summary="Corpus chunk metrics",
    )
    async def metrics(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        uow: AbstractUnitOfWork,
    ) -> schemas.MetricsOutputSchema:
        orchestrator = build_metrics(strategy, uow)
        result = await orchestrator.execute(GetMetrics(rag_id=rag_id))
        return schemas.MetricsOutputSchema.model_validate(result)

    @get(
        path="{rag_id:int}/table-summary/",
        status_code=status_codes.HTTP_200_OK,
        summary="List available tables with row counts",
    )
    async def table_summary(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        uow: AbstractUnitOfWork,
    ) -> list[schemas.GraphTableSummaryOutputSchema]:
        command = GetGraphTableSummary(rag_id=rag_id)
        orchestrator = build_graph_table_summary(strategy, uow)
        result = await orchestrator.execute(command)
        return [
            schemas.GraphTableSummaryOutputSchema.model_validate(item) for item in result.tables
        ]

    @get(
        path="{rag_id:int}/tables/{table_name:str}/",
        status_code=status_codes.HTTP_200_OK,
        summary="Paginated parquet table data",
    )
    async def table_data(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        uow: AbstractUnitOfWork,
        table_name: str,
        page: Annotated[int, Parameter(ge=GRAPH_TABLE_MIN_PAGE)] = GRAPH_TABLE_DEFAULT_PAGE,
        page_size: Annotated[
            int, Parameter(ge=GRAPH_TABLE_MIN_PAGE_SIZE, le=GRAPH_TABLE_MAX_PAGE_SIZE)
        ] = GRAPH_TABLE_DEFAULT_PAGE_SIZE,
        search: Annotated[str | None, Parameter(max_length=GRAPH_SEARCH_MAX_LENGTH)] = None,
        filter_column: Annotated[
            str | None,
            Parameter(
                query="filter_column",
                description=(
                    "Exact-match filter: column name. Must be one of the table's user-facing "
                    "columns and set together with filter_value."
                ),
            ),
        ] = None,
        filter_value: Annotated[
            str | None,
            Parameter(
                query="filter_value",
                description=(
                    "Exact-match filter: the cell value to match as a string. Set together "
                    "with filter_column; applied before `search`."
                ),
            ),
        ] = None,
    ) -> schemas.GraphTableDataOutputSchema:
        command = GetGraphTableData(
            rag_id=rag_id,
            table_name=table_name,
            page=page,
            page_size=page_size,
            search=search,
            filter_column=filter_column,
            filter_value=filter_value,
        )
        orchestrator = build_graph_table_data(strategy, uow)
        result = await orchestrator.execute(command)
        return schemas.GraphTableDataOutputSchema.model_validate(result)

    @get(
        path="{rag_id:int}/visualization/",
        status_code=status_codes.HTTP_200_OK,
        summary="Graph visualization data",
    )
    async def visualization(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        uow: AbstractUnitOfWork,
        max_entities: Annotated[
            int, Parameter(ge=GRAPH_VISUALIZATION_MIN_MAX_ENTITIES)
        ] = GRAPH_VISUALIZATION_DEFAULT_MAX_ENTITIES,
        search: Annotated[str | None, Parameter(max_length=GRAPH_SEARCH_MAX_LENGTH)] = None,
    ) -> schemas.GraphVisualizationOutputSchema:
        command = GetGraphVisualization(rag_id=rag_id, max_entities=max_entities, search=search)
        orchestrator = build_graph_visualization(strategy, uow)
        result = await orchestrator.execute(command)
        return schemas.GraphVisualizationOutputSchema.model_validate(result)

    @get(
        path="{rag_id:int}/entity/{entity_id:str}/",
        status_code=status_codes.HTTP_200_OK,
        summary="Entity description detail",
    )
    async def entity_detail(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        entity_id: str,
        uow: AbstractUnitOfWork,
    ) -> schemas.EntityDetailOutputSchema:
        command = GetEntityDetail(rag_id=rag_id, entity_id=entity_id)
        orchestrator = build_entity_detail(strategy, uow)
        result = await orchestrator.execute(command)
        return schemas.EntityDetailOutputSchema.model_validate(result)

    @get(
        path="{rag_id:int}/relationship/{relationship_id:str}/",
        status_code=status_codes.HTTP_200_OK,
        summary="Relationship description detail",
    )
    async def relationship_detail(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        relationship_id: str,
        uow: AbstractUnitOfWork,
    ) -> schemas.RelationshipDetailOutputSchema:
        command = GetRelationshipDetail(rag_id=rag_id, relationship_id=relationship_id)
        orchestrator = build_relationship_detail(strategy, uow)
        result = await orchestrator.execute(command)
        return schemas.RelationshipDetailOutputSchema.model_validate(result)

    @delete(
        path="{rag_id:int}/cancel/{operation:str}/",
        summary="Cancel a running index",
    )
    async def cancel_operation(
        self,
        strategy: RAGStrategy,
        rag_id: int,
        operation: Literal["index"],
        task_register: AbstractTaskRegister,
    ) -> None:
        key = make_key("rag", strategy, rag_id, operation)
        if not task_register.cancel(key):
            raise NotRunningOperationError(operation=operation, rag_id=rag_id)

    @delete(path="{rag_id:int}/", summary="Delete a RAG and its result storage.")
    async def remove(self, strategy: RAGStrategy, rag_id: int, uow: AbstractUnitOfWork) -> None:
        command = RemoveRag(rag_id=rag_id)
        orchestrator = build_remover(strategy, uow)
        await orchestrator.execute(command)

    @get("{rag_id:int}/artifacts/")
    async def export_artifacts(
        self,
        rag_id: int,
        strategy: RAGStrategy,
        uow: AbstractUnitOfWork,
        artifact_store: AbstractArtifactStore,
    ) -> Stream:
        orchestrator = build_artifact_exporter(strategy, uow, artifact_store)
        command = commands.ExportGraphArtifacts(rag_id=rag_id)
        result = await orchestrator.execute(command)
        return Stream(
            result.stream,
            media_type="application/x-tar",
            headers={"Content-Disposition": f'attachment; filename="rag_{rag_id}.tar"'},
        )

    @put("{rag_id:int}/artifacts/", status_code=204, request_max_body_size=None)
    async def restore_artifacts(
        self,
        request: Request,
        rag_id: int,
        strategy: RAGStrategy,
        uow: AbstractUnitOfWork,
        artifact_store: AbstractArtifactStore,
    ) -> None:
        orchestrator = build_artifact_restorer(strategy, uow, artifact_store)
        # The body goes to disk, not memory: an index archive can be large.
        file_descriptor, archive_path = tempfile.mkstemp(suffix=".tar")
        try:
            # Closed before the restore, so every written byte is flushed before tarfile reads it.
            async with await anyio.open_file(file_descriptor, "wb") as archive:
                async for chunk in request.stream():
                    await archive.write(chunk)
            command = commands.RestoreGraphArtifacts(rag_id=rag_id, archive_path=archive_path)
            await orchestrator.execute(command)
        finally:
            os.unlink(archive_path)

    @post("{rag_id:int}/artifacts/document-ids/", status_code=204)
    async def rewrite_document_ids(
        self,
        data: schemas.DocumentIdRewriteInputSchema,
        rag_id: int,
        strategy: RAGStrategy,
        uow: AbstractUnitOfWork,
        artifact_store: AbstractArtifactStore,
    ) -> None:
        orchestrator = build_document_id_rewriter(strategy, uow, artifact_store)
        command = commands.RewriteGraphDocumentIds(
            rag_id=rag_id, document_id_map=data.document_id_map
        )
        await orchestrator.execute(command)
