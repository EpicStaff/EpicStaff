from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, ClassVar

import pandas
from application.commands import RunSearch
from application.orchestrators.searching.base import AbstractSearchOrchestrator
from application.results import SearchResult
from domain.enums import GraphSearchMethodEnum
from domain.errors import UnsupportedError
from graphrag.api import basic_search, drift_search, global_search, local_search
from graphrag.config.models.basic_search_config import BasicSearchConfig
from graphrag.config.models.drift_search_config import DRIFTSearchConfig
from graphrag.config.models.global_search_config import GlobalSearchConfig
from graphrag.config.models.graph_rag_config import GraphRagConfig
from graphrag.config.models.local_search_config import LocalSearchConfig
from graphrag.data_model import DataReader
from graphrag_storage import create_storage
from graphrag_storage.tables.table_provider_factory import create_table_provider
from pydantic import BaseModel as PydanticModel


@dataclass(frozen=True)
class SearchSpecification:
    searcher: Callable
    config_field: str
    config_model: type[PydanticModel]
    required_files: Iterable[str]
    optional_files: Iterable[str] | None = None
    extra_kwargs: dict[str, Any] = field(default_factory=dict)


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
            extra_kwargs={
                "response_type": DEFAULT_RESPONSE_TYPE,
                "community_level": DEFAULT_COMMUNITY_LEVEL,
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
            extra_kwargs={
                "response_type": DEFAULT_RESPONSE_TYPE,
                "community_level": DEFAULT_COMMUNITY_LEVEL,
                "dynamic_community_selection": DEFAULT_DYNAMIC_COMMUNITY_SELECTION,
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
            extra_kwargs={
                "response_type": DEFAULT_RESPONSE_TYPE,
                "community_level": DEFAULT_COMMUNITY_LEVEL,
            },
        ),
    }

    async def on_execute(self, command: RunSearch) -> SearchResult:
        async with self.uow:
            config = await self.uow.graph_rag_repo.get_config(command.rag_id)

        if command.search_config.method not in self._SEARCH_MAP:
            raise UnsupportedError(
                that="graph search method",
                got=command.search_config.method,
            )

        specs = self._SEARCH_MAP[command.search_config.method]
        setattr(
            config,
            specs.config_field,
            specs.config_model.model_validate(command.search_config.model_dump()),
        )
        files = await self._resolve_files(
            config=config,
            required_files=specs.required_files,
            optional_files=specs.optional_files,
        )
        result, _ = await specs.searcher(
            query=command.query,
            config=config,
            **files,
            **specs.extra_kwargs,
        )

        return SearchResult(result=result)

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
            files.update({n: await getattr(reader, n, None)() for n in optional_files})
        return files
