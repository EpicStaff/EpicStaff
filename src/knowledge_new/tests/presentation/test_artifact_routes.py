"""Contract of the three artifact routes, wired to the real orchestrators and an in-memory store."""

import io
import tarfile
import tempfile

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from application.ports import AbstractUnitOfWork
from domain.enums import IndexStatusEnum, SlotEnum
from domain.models import Rag
from litestar import Litestar
from litestar.di import Provide
from litestar.testing import TestClient
from presentation.rest.controllers import rag as rag_controller
from presentation.rest.controllers.rag import RagController
from presentation.rest.error_handlers import get_error_handlers
from tests.fakes.artifact_store import InMemoryArtifactStore


class FakeGraphRagRepo:
    def __init__(self):
        self.rag: Rag | None = None

    async def get_rag(self, rag_id: int) -> Rag | None:
        return self.rag


class FakeUoW(AbstractUnitOfWork):
    # A subclass, because Litestar checks every injected value against its annotation.
    naive_rag_repo = None

    def __init__(self, repo: FakeGraphRagRepo):
        self._graph_rag_repo = repo

    @property
    def graph_rag_repo(self) -> FakeGraphRagRepo:
        return self._graph_rag_repo

    async def commit(self): ...

    async def rollback(self): ...


def _parquet(columns: dict[str, list]) -> bytes:
    table = pa.table(
        {name: pa.array(values, type=pa.large_string()) for name, values in columns.items()}
    )
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()


def _tar(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


INDEX = {
    "output/documents.parquet": _parquet({"id": ["2"]}),
    "output/text_units.parquet": _parquet({"id": ["unit-1"], "document_id": ["2"]}),
}


@pytest.fixture
def repo() -> FakeGraphRagRepo:
    return FakeGraphRagRepo()


@pytest.fixture
def store() -> InMemoryArtifactStore:
    return InMemoryArtifactStore()


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    """Where the PUT route spools the uploaded archive."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return tmp_path


@pytest.fixture
def client(monkeypatch, repo, store, upload_dir):
    monkeypatch.setattr(rag_controller, "is_graphrag_available", lambda: True)
    app = Litestar(
        route_handlers=[RagController],
        dependencies={
            "uow": Provide(lambda: FakeUoW(repo), sync_to_thread=False),
            "artifact_store": Provide(lambda: store, sync_to_thread=False),
        },
        exception_handlers=get_error_handlers(),
    )
    with TestClient(app=app) as test_client:
        yield test_client


# --- GET artifacts/ -------------------------------------------------------------------


def test_export_returns_the_index_as_a_tar_download(client, repo, store):
    repo.rag = Rag(id=1, status=IndexStatusEnum.COMPLETED, indexing_document_ids=set(), slot=SlotEnum.B)
    store.objects.update({f"graphrag/rag_1/b/{name}": data for name, data in INDEX.items()})

    response = client.get("/rags/graph/1/artifacts/")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-tar"
    assert response.headers["content-disposition"] == 'attachment; filename="rag_1.tar"'
    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:") as tar:
        assert {member.name: tar.extractfile(member).read() for member in tar} == INDEX


@pytest.mark.parametrize(
    ("rag", "status_code", "code"),
    [
        pytest.param(None, 404, "not_found", id="no rag"),
        pytest.param(
            Rag(id=1, status=IndexStatusEnum.PROCESSING, indexing_document_ids=set(), slot=SlotEnum.B),
            409,
            "rag_in_processing",
            id="indexing",
        ),
        pytest.param(
            Rag(id=1, status=IndexStatusEnum.FAILED, indexing_document_ids=set(), slot=SlotEnum.B),
            409,
            "graph_artifacts_not_ready",
            id="not indexed",
        ),
    ],
)
def test_export_refusals(client, repo, store, rag, status_code, code):
    repo.rag = rag
    store.objects.update({f"graphrag/rag_1/b/{name}": data for name, data in INDEX.items()})

    response = client.get("/rags/graph/1/artifacts/")

    assert response.status_code == status_code
    assert response.json()["code"] == code


# --- PUT artifacts/ -------------------------------------------------------------------


def test_restore_stores_the_uploaded_index_in_slot_a_and_deletes_the_upload(
    client, store, upload_dir
):
    # Above Litestar's default 10 MB request limit: an index is routinely bigger.
    large_vectors = b"\x01" * (11 * 1024 * 1024)
    archive = _tar({**INDEX, "lancedb/entity_description.lance/data/0001.lance": large_vectors})

    response = client.put("/rags/graph/9/artifacts/", content=archive)

    assert response.status_code == 204
    assert store.objects == {
        "graphrag/rag_9/a/output/documents.parquet": INDEX["output/documents.parquet"],
        "graphrag/rag_9/a/output/text_units.parquet": INDEX["output/text_units.parquet"],
        "graphrag/rag_9/a/lancedb/entity_description.lance/data/0001.lance": large_vectors,
    }
    assert list(upload_dir.iterdir()) == []


def test_restore_of_an_invalid_archive_is_a_400_and_deletes_the_upload(client, store, upload_dir):
    response = client.put("/rags/graph/9/artifacts/", content=_tar({"secrets/key.txt": b"x"}))

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_artifact_archive"
    assert store.objects == {}
    assert list(upload_dir.iterdir()) == []


# --- POST artifacts/document-ids/ -----------------------------------------------------


def test_document_id_rewrite_updates_the_restored_index(client, store):
    store.objects.update({f"graphrag/rag_9/a/{name}": data for name, data in INDEX.items()})

    response = client.post(
        "/rags/graph/9/artifacts/document-ids/", json={"document_id_map": {"2": 51}}
    )

    assert response.status_code == 204
    text_units = pq.read_table(
        io.BytesIO(store.objects["graphrag/rag_9/a/output/text_units.parquet"])
    )
    assert text_units.column("document_id").to_pylist() == ["51"]


@pytest.mark.parametrize(
    ("body", "status_code"),
    [
        pytest.param({"document_id_map": {"7": 51}}, 400, id="id of the index not in the map"),
        pytest.param({}, 400, id="no map"),
    ],
)
def test_document_id_rewrite_refusals(client, store, body, status_code):
    store.objects.update({f"graphrag/rag_9/a/{name}": data for name, data in INDEX.items()})
    before = dict(store.objects)

    response = client.post("/rags/graph/9/artifacts/document-ids/", json=body)

    assert response.status_code == status_code
    assert store.objects == before


def test_an_empty_document_id_map_is_refused_before_storage_is_read(client):
    # No index is stored: only the request validation can turn this into a 400, not a 409.
    response = client.post("/rags/graph/9/artifacts/document-ids/", json={"document_id_map": {}})

    assert response.status_code == 400


def test_rewrite_before_a_restore_is_a_409(client):
    response = client.post(
        "/rags/graph/9/artifacts/document-ids/", json={"document_id_map": {"2": 51}}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "graph_artifacts_not_ready"


# --- every route ----------------------------------------------------------------------

ROUTES = [
    pytest.param("get", "artifacts/", {}, id="export"),
    pytest.param("put", "artifacts/", {"content": _tar(INDEX)}, id="restore"),
    pytest.param(
        "post", "artifacts/document-ids/", {"json": {"document_id_map": {"2": 51}}}, id="rewrite"
    ),
]


@pytest.mark.parametrize(("method", "path", "request_kwargs"), ROUTES)
def test_naive_rags_have_no_artifacts_to_transfer(
    client, store, upload_dir, method, path, request_kwargs
):
    response = getattr(client, method)(f"/rags/naive/9/{path}", **request_kwargs)

    assert response.status_code == 400
    assert response.json()["code"] == "unsupported"
    assert store.objects == {}
    assert list(upload_dir.iterdir()) == []


@pytest.mark.parametrize(("method", "path", "request_kwargs"), ROUTES)
def test_graph_routes_are_unavailable_on_a_cpu_without_avx2(
    client, monkeypatch, store, method, path, request_kwargs
):
    monkeypatch.setattr(rag_controller, "is_graphrag_available", lambda: False)

    response = getattr(client, method)(f"/rags/graph/9/{path}", **request_kwargs)

    assert response.status_code == 503
    assert store.objects == {}
