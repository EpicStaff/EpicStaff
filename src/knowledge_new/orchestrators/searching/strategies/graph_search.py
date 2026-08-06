from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, ClassVar

import pandas
from enums import GraphSearchMethodEnum
from errors import UnsupportedError
from graphrag.api import basic_search, drift_search, global_search, local_search
from graphrag.config.models.basic_search_config import BasicSearchConfig
from graphrag.config.models.drift_search_config import DRIFTSearchConfig
from graphrag.config.models.global_search_config import GlobalSearchConfig
from graphrag.config.models.graph_rag_config import GraphRagConfig
from graphrag.config.models.local_search_config import LocalSearchConfig
from graphrag.data_model import DataReader
from graphrag_storage import create_storage
from graphrag_storage.tables.table_provider_factory import create_table_provider
from models import SearchRequest, SearchResponse
from orchestrators.searching import AbstractSearch
from pydantic import BaseModel as PydanticModel
from services.grounding_guard import apply_grounding_guard


DEFAULT_RESPONSE_TYPE = "Multiple Paragraphs"


@dataclass(frozen=True)
class SearchSpecification:
    searcher: Callable
    config_field: str
    config_model: type[PydanticModel]
    required_files: Iterable[str]
    optional_files: Iterable[str] | None = None
    extra_kwargs: Callable[..., dict[str, Any]] | dict[str, Any] = field(
        default_factory=dict
    )


def _drift_extra_kwargs(search_config, method_config, files) -> dict[str, Any]:
    # Empty primer folds cause the primer to hallucinate from entity names if folds
    # exceed the number of available community reports — limit folds to the report count.
    usable_reports = min(
        search_config.drift_k_followups, len(files["community_reports"])
    )
    method_config.primer_folds = max(1, min(method_config.primer_folds, usable_reports))
    return {
        "response_type": DEFAULT_RESPONSE_TYPE,
        "community_level": search_config.community_level,
    }


class GraphSearch(AbstractSearch):
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
                "response_type": DEFAULT_RESPONSE_TYPE,
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
                "response_type": DEFAULT_RESPONSE_TYPE,
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

    async def on_execute(self, request: SearchRequest) -> SearchResponse:
        async with self.uow:
            config = await self.uow.graph_rag_repo.get_config(request.rag_id)

        if request.search_config.method not in self._SEARCH_MAP:
            raise UnsupportedError(
                that="graph search method",
                got=request.search_config.method,
            )

        specs = self._SEARCH_MAP[request.search_config.method]
        method_config = specs.config_model.model_validate(
            request.search_config.model_dump()
        )

        setattr(
            config,
            specs.config_field,
            method_config,
        )
        files = await self._resolve_files(
            config=config,
            required_files=specs.required_files,
            optional_files=specs.optional_files,
        )

        extra_kwargs = specs.extra_kwargs
        if callable(extra_kwargs):
            extra_kwargs = extra_kwargs(request.search_config, method_config, files)

        result, context = await specs.searcher(
            query=request.query, config=config, **files, **extra_kwargs
        )

        result = await apply_grounding_guard(
            query=request.query,
            response=result,
            context=context,
            config=config,
            method=request.search_config.method,
        )

        return SearchResponse(request=request, result=result)

    @staticmethod
    async def _resolve_files(
        config: GraphRagConfig,
        required_files: Iterable[str],
        optional_files: Iterable[str] | None = None,
    ) -> dict[str, pandas.DataFrame]:
        storage = create_storage(config.output_storage)
        table_provider = create_table_provider(config.table_provider, storage)
        reader = DataReader(table_provider)
        files = {n: await getattr(reader, n)() for n in required_files}
        if optional_files:
            files.update(
                {
                    n: (
                        await getattr(reader, n)()
                        if await table_provider.has(n)
                        else None
                    )
                    for n in optional_files
                }
            )
        return files
