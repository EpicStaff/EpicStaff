"""The graph index read endpoints over HTTP: query bounds, defaults and error statuses.

The real controller, orchestrators and error handlers run; the unit of work's graph RAG
repository is faked and points at a temporary directory of parquet files.
"""

import pandas
import pytest
from application.ports import AbstractUnitOfWork
from litestar import Litestar
from litestar.di import Provide
from litestar.testing import TestClient
from presentation.rest.controllers import rag as rag_controller
from presentation.rest.controllers.rag import RagController
from presentation.rest.error_handlers import get_error_handlers

from tests.orchestrators.graph_output_fakes import FakeGraphRagRepo, write_table


class _FileStorageUow(AbstractUnitOfWork):
    def __init__(self, repo: FakeGraphRagRepo):
        self._repo = repo

    @property
    def graph_rag_repo(self):
        return self._repo

    @property
    def naive_rag_repo(self):
        return None

    async def commit(self): ...

    async def rollback(self): ...


def _client_for(monkeypatch, repo: FakeGraphRagRepo):
    monkeypatch.setattr(rag_controller, "is_graphrag_available", lambda: True)
    app = Litestar(
        route_handlers=[RagController],
        signature_types=[AbstractUnitOfWork],
        dependencies={"uow": Provide(lambda: _FileStorageUow(repo), sync_to_thread=False)},
        exception_handlers=get_error_handlers(),
    )
    return TestClient(app=app)


@pytest.fixture
def client(monkeypatch, tmp_path):
    with _client_for(monkeypatch, FakeGraphRagRepo(tmp_path)) as test_client:
        yield test_client


def _write_graph(directory, entity_count: int) -> None:
    write_table(
        directory,
        "entities",
        pandas.DataFrame(
            {
                "id": [f"e{index}" for index in range(entity_count)],
                "title": [f"Entity{index}" for index in range(entity_count)],
                "type": ["ORG"] * entity_count,
                "description": ["d"] * entity_count,
                "degree": list(range(entity_count)),
            }
        ),
    )
    write_table(
        directory,
        "relationships",
        pandas.DataFrame(
            {"id": ["r0"], "source": ["Entity0"], "target": ["Entity1"], "weight": [1.0]}
        ),
    )


@pytest.mark.parametrize(
    "query",
    [
        {"page": 0},
        {"page": "abc"},
        {"page_size": 0},
        {"page_size": -1},
        {"page_size": 101},
        {"search": "x" * 201},
    ],
    ids=["page-0", "page-not-integer", "page-size-0", "page-size-negative", "page-size-101", "search-201"],
)
def test_table_data_rejects_out_of_bounds_query(client, query):
    response = client.get("/rags/graph/1/tables/entities/", params=query)

    assert response.status_code == 400


@pytest.mark.parametrize(
    "query",
    [{"max_entities": 0}, {"max_entities": -1}, {"search": "x" * 201}],
    ids=["max-entities-0", "max-entities-negative", "search-201"],
)
def test_visualization_rejects_out_of_bounds_query(client, query):
    response = client.get("/rags/graph/1/visualization/", params=query)

    assert response.status_code == 400


def test_table_data_accepts_the_bounds_themselves(client, tmp_path):
    _write_graph(tmp_path, 120)

    response = client.get(
        "/rags/graph/1/tables/entities/",
        params={"page": 1, "page_size": 100, "search": "E" * 200},
    )

    assert response.status_code == 200
    assert response.json()["page_size"] == 100


def test_visualization_applies_the_default_of_two_hundred_entities(client, tmp_path):
    _write_graph(tmp_path, 250)

    response = client.get("/rags/graph/1/visualization/")

    assert response.status_code == 200
    assert len(response.json()["entities"]) == 200


def test_visualization_has_no_upper_cap_on_max_entities(client, tmp_path):
    _write_graph(tmp_path, 250)

    response = client.get("/rags/graph/1/visualization/", params={"max_entities": 5000})

    assert response.status_code == 200
    assert len(response.json()["entities"]) == 250


@pytest.mark.parametrize(
    "path",
    [
        "/rags/graph/7/visualization/",
        "/rags/graph/7/entity/e0/",
        "/rags/graph/7/relationship/r0/",
        "/rags/graph/7/tables/entities/",
        "/rags/graph/7/table-summary/",
    ],
    ids=["visualization", "entity-detail", "relationship-detail", "table-data", "table-summary"],
)
def test_every_read_of_a_never_indexed_graph_answers_409(client, path):
    response = client.get(path)

    assert response.status_code == 409
    assert response.json() == {
        "code": "graph_not_indexed",
        "detail": "Graph index output not available for RAG(id=7). Run indexing first.",
    }


def test_entity_detail_decodes_the_path_segment_into_the_entity_id(client, tmp_path):
    write_table(
        tmp_path,
        "entities",
        pandas.DataFrame({"id": ["a?b c", "other"], "description": ["found it", "wrong"]}),
    )

    response = client.get("/rags/graph/1/entity/a%3Fb%20c/")

    assert response.status_code == 200
    assert response.json() == {"description": "found it"}


def test_entity_id_with_an_encoded_slash_does_not_match_the_route(client, tmp_path):
    write_table(
        tmp_path,
        "entities",
        pandas.DataFrame({"id": ["a/b"], "description": ["unreachable"]}),
    )

    response = client.get("/rags/graph/1/entity/a%2Fb/")

    assert response.status_code == 404


def test_unknown_rag_answers_404(monkeypatch):
    with _client_for(monkeypatch, FakeGraphRagRepo(output_directory=None)) as test_client:
        response = test_client.get("/rags/graph/7/table-summary/")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_unknown_table_answers_400(client):
    response = client.get("/rags/graph/1/tables/secrets/")

    assert response.status_code == 400
    assert response.json()["code"] == "unsupported"
