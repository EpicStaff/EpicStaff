from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, ClassVar

import pandas
from application.commands import RunSearch
from application.orchestrators.graph_output import ensure_graph_indexed
from application.orchestrators.searching.base import AbstractSearchOrchestrator
from application.results import SearchResult
from application.sealed_secrets import open_sealed_secrets
from domain.enums import GraphSearchMethodEnum
from domain.errors import GraphRagConfigNotFoundError, UnsupportedError
from domain.models import GraphPricingConfig, SearchUsage
from domain.usage import UsageTally
from graphrag.api import basic_search, drift_search, global_search, local_search
from graphrag.config.models.basic_search_config import BasicSearchConfig
from graphrag.config.models.drift_search_config import DRIFTSearchConfig
from graphrag.config.models.global_search_config import GlobalSearchConfig
from graphrag.config.models.local_search_config import LocalSearchConfig
from graphrag.data_model import DataReader
from graphrag_storage import Storage, create_storage
from graphrag_storage.tables.table_provider_config import TableProviderConfig
from graphrag_storage.tables.table_provider_factory import create_table_provider
from infrastructure.database.mappers.embedding_arguments import embedding_call_arguments
from infrastructure.database.mappers.graph import graph_rag_cache_config
from infrastructure.graphrag.model_access import (
    apply_request_access,
    completion_call_arguments,
)
from infrastructure.graphrag.usage_metrics import track_usage
from infrastructure.grounding_guard import apply_grounding_guard
from infrastructure.prompt_patching import patch_graphrag_prompts
from infrastructure.token_estimation import qualified_model_name
from infrastructure.usage_cost import embedding_cost, llm_cost
from pydantic import BaseModel as PydanticModel


@dataclass(frozen=True)
class SearchSpecification:
    searcher: Callable
    config_field: str
    config_model: type[PydanticModel]
    required_files: Iterable[str]
    optional_files: Iterable[str] | None = None
    extra_kwargs: Callable[..., dict[str, Any]] | dict[str, Any] = field(default_factory=dict)


def _drift_extra_kwargs(search_config, method_config, files) -> dict[str, Any]:
    # Empty primer folds cause the primer to hallucinate from entity names if folds
    # exceed the number of available community reports — limit folds to the report count.
    usable_reports = min(search_config.drift_k_followups, len(files["community_reports"]))
    method_config.primer_folds = max(1, min(method_config.primer_folds, usable_reports))
    return {
        "response_type": GraphSearchOrchestrator.DEFAULT_RESPONSE_TYPE,
        "community_level": search_config.community_level,
    }


class GraphSearchOrchestrator(AbstractSearchOrchestrator):
    DEFAULT_RESPONSE_TYPE = "Multiple Paragraphs"
    DEFAULT_COMMUNITY_LEVEL = 2
    DEFAULT_DYNAMIC_COMMUNITY_SELECTION = False

    _SEARCH_MAP: ClassVar[dict[GraphSearchMethodEnum, SearchSpecification]] = {
        GraphSearchMethodEnum.BASIC: SearchSpecification(
            searcher=basic_search,
            config_field="basic_search",
            config_model=BasicSearchConfig,
            required_files=["text_units"],
            extra_kwargs={"response_type": DEFAULT_RESPONSE_TYPE},
        ),
        GraphSearchMethodEnum.LOCAL: SearchSpecification(
            searcher=local_search,
            config_field="local_search",
            config_model=LocalSearchConfig,
            required_files=[
                "communities",
                "community_reports",
                "text_units",
                "relationships",
                "entities",
            ],
            optional_files=["covariates"],
            extra_kwargs=lambda search_config, method_config, files: {
                "response_type": GraphSearchOrchestrator.DEFAULT_RESPONSE_TYPE,
                "community_level": search_config.community_level,
            },
        ),
        GraphSearchMethodEnum.GLOBAL: SearchSpecification(
            searcher=global_search,
            config_field="global_search",
            config_model=GlobalSearchConfig,
            required_files=[
                "entities",
                "communities",
                "community_reports",
            ],
            extra_kwargs=lambda search_config, method_config, files: {
                "response_type": GraphSearchOrchestrator.DEFAULT_RESPONSE_TYPE,
                "community_level": search_config.dynamic_search_max_level,
                "dynamic_community_selection": search_config.dynamic_community_selection,
            },
        ),
        GraphSearchMethodEnum.DRIFT: SearchSpecification(
            searcher=drift_search,
            config_field="drift_search",
            config_model=DRIFTSearchConfig,
            required_files=[
                "communities",
                "community_reports",
                "text_units",
                "relationships",
                "entities",
            ],
            extra_kwargs=_drift_extra_kwargs,
        ),
    }

    def __init__(self, uow, cryptographer):
        patch_graphrag_prompts()
        super().__init__(uow, cryptographer)

    async def on_execute(self, command: RunSearch) -> SearchResult:
        async with self.uow:
            config = await self.uow.graph_rag_repo.get_config(command.rag_id)
            pricing = await self._get_pricing(command.rag_id)
        if config is None:
            raise GraphRagConfigNotFoundError(rag_id=command.rag_id)

        secrets = open_sealed_secrets(command, self.cryptographer)
        embedding_model = config.embedding_models["default_embedding_model"]
        completion_model = config.completion_models["default_completion_model"]
        embedding_arguments = embedding_call_arguments(command.embedding_parameters)
        completion_arguments = completion_call_arguments(completion_model, command.llm_parameters)
        apply_request_access(
            embedding_model,
            api_key=secrets.embedding_api_key,
            extra_headers=secrets.embedding_extra_headers,
            connection=secrets.embedding_connection,
            call_arguments=embedding_arguments,
        )
        apply_request_access(
            completion_model,
            api_key=secrets.llm_api_key,
            extra_headers=secrets.llm_extra_headers,
            connection=secrets.llm_connection,
            call_arguments=completion_arguments,
        )
        config.cache = graph_rag_cache_config(
            command.rag_id,
            [(completion_model, completion_arguments), (embedding_model, embedding_arguments)],
        )

        if command.search_config.method not in self._SEARCH_MAP:
            raise UnsupportedError(
                that="graph search method",
                got=command.search_config.method,
            )

        specs = self._SEARCH_MAP[command.search_config.method]
        method_config = specs.config_model.model_validate(command.search_config.model_dump())
        setattr(
            config,
            specs.config_field,
            method_config,
        )
        storage = create_storage(config.output_storage)
        await ensure_graph_indexed(storage, command.rag_id)
        files = await self._resolve_files(
            storage=storage,
            table_provider_config=config.table_provider,
            required_files=specs.required_files,
            optional_files=specs.optional_files,
        )

        extra_kwargs = specs.extra_kwargs
        if callable(extra_kwargs):
            extra_kwargs = extra_kwargs(command.search_config, method_config, files)

        # The grounding judge's LLM call is part of the search, so it is metered too.
        with track_usage(config) as tally:
            result, context = await specs.searcher(
                query=command.query,
                config=config,
                **files,
                **extra_kwargs,
            )

            result = await apply_grounding_guard(
                query=command.query,
                response=result,
                context=context,
                config=config,
                method=command.search_config.method,
                rag_id=command.rag_id,
            )

        return SearchResult(result=result, usage=self._usage(tally, pricing))

    async def _get_pricing(self, rag_id: int) -> GraphPricingConfig | None:
        """Return the RAG's model names and custom prices, None when they cannot be resolved.

        Only the cost of the search depends on it, so a missing pricing config must not
        fail the search itself.
        """
        try:
            return await self.uow.graph_rag_repo.get_pricing_config(rag_id=rag_id)
        except GraphRagConfigNotFoundError:
            return None

    @staticmethod
    def _usage(tally: UsageTally, pricing: GraphPricingConfig | None) -> SearchUsage:
        """Convert the metered `tally` to a `SearchUsage`; a cost is None when unpriced."""
        embedding_cost_usd = None
        llm_cost_usd = None
        if pricing is not None:
            embedding_cost_usd = embedding_cost(
                qualified_model_name(pricing.embedding.provider, pricing.embedding.model),
                tally.embedding_tokens,
            )
            llm_cost_usd = llm_cost(
                qualified_model_name(pricing.llm_provider, pricing.llm_model),
                tally.llm_input_tokens,
                tally.llm_output_tokens,
                pricing.input_cost_per_token,
                pricing.output_cost_per_token,
            )
        return SearchUsage(
            embedding_tokens=tally.embedding_tokens,
            embedding_cost_usd=embedding_cost_usd,
            llm_input_tokens=tally.llm_input_tokens,
            llm_output_tokens=tally.llm_output_tokens,
            llm_cost_usd=llm_cost_usd,
        )

    @staticmethod
    async def _resolve_files(
        storage: Storage,
        table_provider_config: TableProviderConfig,
        required_files: Iterable[str],
        optional_files: Iterable[str] | None = None,
    ) -> dict[str, pandas.DataFrame]:
        table_provider = create_table_provider(table_provider_config, storage)
        reader = DataReader(table_provider)
        files = {n: await getattr(reader, n)() for n in required_files}
        if optional_files:
            for n in optional_files:
                reader_fn = getattr(reader, n, None)
                if reader_fn is None:
                    files[n] = None
                    continue
                try:
                    files[n] = await reader_fn()
                except (ValueError, FileNotFoundError):
                    # optional layer (e.g. covariates) absent from this index
                    files[n] = None
        return files
