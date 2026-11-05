import asyncio
import io
import tarfile
from pathlib import Path
from typing import BinaryIO

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from application.commands import (
    ExportGraphArtifacts,
    RestoreGraphArtifacts,
    RewriteGraphDocumentIds,
)
from application.orchestrators.transferring.strategies import graph_artifacts
from application.orchestrators.transferring.strategies.graph_artifacts import (
    GraphArtifactExportOrchestrator,
    GraphArtifactRestoreOrchestrator,
    GraphDocumentIdRewriteOrchestrator,
)
from domain.enums import IndexStatusEnum, SlotEnum
from domain.errors import (
    GraphArtifactsNotReadyError,
    InvalidArtifactArchiveError,
    RagInProcessingError,
    RagNotFoundError,
)
from domain.models import Rag
from tests.fakes.artifact_store import InMemoryArtifactStore

DOCUMENTS = "output/documents.parquet"
TEXT_UNITS = "output/text_units.parquet"


class FakeGraphRagRepo:
    def __init__(self, rag: Rag | None):
        self._rag = rag

    async def get_rag(self, rag_id: int) -> Rag | None:
        return self._rag


class FakeUoW:
    def __init__(self, rag: Rag | None = None):
        self.graph_rag_repo = FakeGraphRagRepo(rag)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class NoDatabaseUoW:
    """Restore and rewrite run inside Django's uncommitted import transaction, where the
    RAG row is invisible to this service, so they must never open the unit of work."""

    async def __aenter__(self):
        raise AssertionError("the unit of work was opened")

    async def __aexit__(self, *exc):
        return False


def _rag(status: IndexStatusEnum, slot: SlotEnum | None = SlotEnum.B) -> Rag:
    return Rag(id=1, status=status, indexing_document_ids=set(), slot=slot)


def _parquet(columns: dict[str, list]) -> bytes:
    table = pa.table(
        {name: pa.array(values, type=pa.large_string()) for name, values in columns.items()}
    )
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()


def _read_parquet(data: bytes) -> dict[str, list]:
    return pq.read_table(io.BytesIO(data)).to_pydict()


def _tar(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _read_tar(archive: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
        return {member.name: tar.extractfile(member).read() for member in tar.getmembers()}


def _write_archive(tmp_path: Path, members: dict[str, bytes]) -> str:
    archive_path = tmp_path / "artifacts.tar"
    archive_path.write_bytes(_tar(members))
    return str(archive_path)


VALID_MEMBERS = {
    DOCUMENTS: b"documents",
    TEXT_UNITS: b"text-units",
    "lancedb/entity_description.lance/data/0001.lance": b"\x00vectors",
}


# --- export ---------------------------------------------------------------------------


async def test_export_streams_the_active_slots_index_named_relative_to_the_slot():
    store = InMemoryArtifactStore(
        {
            "graphrag/rag_1/b/output/documents.parquet": b"documents",
            "graphrag/rag_1/b/output/text_units.parquet": b"text-units",
            "graphrag/rag_1/b/input/2.txt": b"source text",
            "graphrag/rag_1/b/lancedb/entity_description.lance/data/0001.lance": b"vectors",
            # Scratch data of an indexing run, not part of the index.
            "graphrag/rag_1/b/update_output/delta/entities.parquet": b"scratch",
            # The inactive slot, and another RAG whose id starts with the same digit.
            "graphrag/rag_1/a/output/documents.parquet": b"old documents",
            "graphrag/rag_10/b/output/documents.parquet": b"other rag",
        }
    )
    orchestrator = GraphArtifactExportOrchestrator(FakeUoW(_rag(IndexStatusEnum.COMPLETED)), store)

    result = await orchestrator.execute(ExportGraphArtifacts(rag_id=1))
    archive = b"".join([chunk async for chunk in result.stream])

    assert _read_tar(archive) == {
        "output/documents.parquet": b"documents",
        "output/text_units.parquet": b"text-units",
        "input/2.txt": b"source text",
        "lancedb/entity_description.lance/data/0001.lance": b"vectors",
    }


COMPLETE_SLOT_B = {
    "graphrag/rag_1/b/output/documents.parquet": b"documents",
    "graphrag/rag_1/b/output/text_units.parquet": b"text-units",
}


@pytest.mark.parametrize(
    ("rag", "objects", "expected_error"),
    [
        pytest.param(None, COMPLETE_SLOT_B, RagNotFoundError, id="no rag row"),
        pytest.param(
            _rag(IndexStatusEnum.PROCESSING), COMPLETE_SLOT_B, RagInProcessingError, id="indexing"
        ),
        *[
            pytest.param(_rag(status), COMPLETE_SLOT_B, GraphArtifactsNotReadyError, id=status)
            for status in IndexStatusEnum
            if status not in (IndexStatusEnum.COMPLETED, IndexStatusEnum.PROCESSING)
        ],
        pytest.param(
            _rag(IndexStatusEnum.COMPLETED, slot=None),
            COMPLETE_SLOT_B,
            GraphArtifactsNotReadyError,
            id="completed without a slot",
        ),
        pytest.param(
            _rag(IndexStatusEnum.COMPLETED),
            {"graphrag/rag_1/b/output/documents.parquet": b"documents"},
            GraphArtifactsNotReadyError,
            id="text_units table missing",
        ),
        pytest.param(
            _rag(IndexStatusEnum.COMPLETED),
            {"graphrag/rag_1/b/output/text_units.parquet": b"text-units"},
            GraphArtifactsNotReadyError,
            id="documents table missing",
        ),
    ],
)
async def test_export_is_refused_before_streaming_when_the_index_cannot_be_imported(
    rag, objects, expected_error
):
    # Raised by execute itself: once the response has started, its status can't change.
    orchestrator = GraphArtifactExportOrchestrator(FakeUoW(rag), InMemoryArtifactStore(objects))

    with pytest.raises(expected_error):
        await orchestrator.execute(ExportGraphArtifacts(rag_id=1))


async def test_exported_tar_restores_into_another_rag_unchanged(tmp_path):
    source = InMemoryArtifactStore(
        {f"graphrag/rag_1/b/{name}": data for name, data in VALID_MEMBERS.items()}
    )
    export = GraphArtifactExportOrchestrator(FakeUoW(_rag(IndexStatusEnum.COMPLETED)), source)
    result = await export.execute(ExportGraphArtifacts(rag_id=1))
    archive_path = tmp_path / "exported.tar"
    archive_path.write_bytes(b"".join([chunk async for chunk in result.stream]))

    target = InMemoryArtifactStore()
    restore = GraphArtifactRestoreOrchestrator(NoDatabaseUoW(), target)
    await restore.execute(RestoreGraphArtifacts(rag_id=2, archive_path=str(archive_path)))

    assert target.objects == {
        f"graphrag/rag_2/a/{name}": data for name, data in VALID_MEMBERS.items()
    }


# --- restore --------------------------------------------------------------------------


async def test_restore_replaces_everything_stored_for_the_rag_with_the_archive_in_slot_a(
    tmp_path,
):
    store = InMemoryArtifactStore(
        {
            "graphrag/rag_9/a/output/stale.parquet": b"stale",
            "graphrag/rag_9/b/output/documents.parquet": b"stale other slot",
            "graphrag/rag_90/a/output/documents.parquet": b"another rag",
        }
    )
    orchestrator = GraphArtifactRestoreOrchestrator(NoDatabaseUoW(), store)

    await orchestrator.execute(
        RestoreGraphArtifacts(rag_id=9, archive_path=_write_archive(tmp_path, VALID_MEMBERS))
    )

    assert store.objects == {
        "graphrag/rag_9/a/output/documents.parquet": b"documents",
        "graphrag/rag_9/a/output/text_units.parquet": b"text-units",
        "graphrag/rag_9/a/lancedb/entity_description.lance/data/0001.lance": b"\x00vectors",
        "graphrag/rag_90/a/output/documents.parquet": b"another rag",
    }


@pytest.mark.parametrize(
    "archive",
    [
        pytest.param(
            _tar({**VALID_MEMBERS, "../rag_8/a/output/x.parquet": b"x"}), id="path escape"
        ),
        pytest.param(_tar({DOCUMENTS: b"documents"}), id="required table missing"),
        pytest.param(b"definitely not a tar archive" * 40, id="not a tar"),
    ],
)
async def test_a_refused_archive_leaves_nothing_stored_for_the_rag(tmp_path, archive):
    # Django deletes the RAG when the import fails, so a half-restored index must not stay.
    archive_path = tmp_path / "upload.tar"
    archive_path.write_bytes(archive)
    store = InMemoryArtifactStore(
        {
            "graphrag/rag_9/a/output/documents.parquet": b"earlier attempt",
            "graphrag/rag_90/a/output/documents.parquet": b"another rag",
        }
    )
    orchestrator = GraphArtifactRestoreOrchestrator(NoDatabaseUoW(), store)

    with pytest.raises(InvalidArtifactArchiveError) as raised:
        await orchestrator.execute(RestoreGraphArtifacts(rag_id=9, archive_path=str(archive_path)))

    assert store.objects == {"graphrag/rag_90/a/output/documents.parquet": b"another rag"}
    # The message goes back to the caller; the server's temp path must not.
    assert str(tmp_path) not in str(raised.value)


class FailingAfterFirstPutStore(InMemoryArtifactStore):
    def __init__(self, error: BaseException):
        super().__init__()
        self.error = error

    async def put(self, key: str, source: BinaryIO, size: int) -> None:
        if self.objects:
            raise self.error
        await super().put(key, source, size)


async def test_a_storage_failure_mid_restore_removes_what_was_already_written(tmp_path):
    store = FailingAfterFirstPutStore(OSError("storage unavailable"))
    orchestrator = GraphArtifactRestoreOrchestrator(NoDatabaseUoW(), store)

    with pytest.raises(OSError, match="storage unavailable"):
        await orchestrator.execute(
            RestoreGraphArtifacts(rag_id=9, archive_path=_write_archive(tmp_path, VALID_MEMBERS))
        )

    assert store.objects == {}


async def test_a_cancelled_restore_removes_what_was_already_written(tmp_path):
    store = FailingAfterFirstPutStore(asyncio.CancelledError())
    orchestrator = GraphArtifactRestoreOrchestrator(NoDatabaseUoW(), store)

    await orchestrator.execute(
        RestoreGraphArtifacts(rag_id=9, archive_path=_write_archive(tmp_path, VALID_MEMBERS))
    )

    assert store.objects == {}


# --- document id rewrite --------------------------------------------------------------


def _restored_store(text_unit_document_ids: list[str]) -> InMemoryArtifactStore:
    return InMemoryArtifactStore(
        {
            f"graphrag/rag_9/a/{DOCUMENTS}": _parquet(
                {"id": ["2", "3"], "title": ["first.txt", "second.txt"]}
            ),
            f"graphrag/rag_9/a/{TEXT_UNITS}": _parquet(
                {
                    "id": ["unit-1", "unit-2", "unit-3"],
                    "document_id": text_unit_document_ids,
                }
            ),
            "graphrag/rag_9/a/output/entities.parquet": b"entities",
        }
    )


async def test_rewrite_gives_both_tables_the_importing_sides_document_ids():
    store = _restored_store(["2", "3", "3"])
    orchestrator = GraphDocumentIdRewriteOrchestrator(NoDatabaseUoW(), store)

    await orchestrator.execute(
        RewriteGraphDocumentIds(rag_id=9, document_id_map={"2": 51, "3": 52, "4": 53})
    )

    assert _read_parquet(store.objects[f"graphrag/rag_9/a/{DOCUMENTS}"]) == {
        "id": ["51", "52"],
        "title": ["first.txt", "second.txt"],
    }
    assert _read_parquet(store.objects[f"graphrag/rag_9/a/{TEXT_UNITS}"]) == {
        "id": ["unit-1", "unit-2", "unit-3"],
        "document_id": ["51", "52", "52"],
    }
    assert store.objects["graphrag/rag_9/a/output/entities.parquet"] == b"entities"


async def test_an_id_missing_from_the_map_leaves_both_tables_unchanged():
    # documents.parquet rewrites fine; text_units.parquet holds an id the map lacks.
    store = _restored_store(["2", "3", "7"])
    before = dict(store.objects)
    orchestrator = GraphDocumentIdRewriteOrchestrator(NoDatabaseUoW(), store)

    with pytest.raises(InvalidArtifactArchiveError):
        await orchestrator.execute(
            RewriteGraphDocumentIds(rag_id=9, document_id_map={"2": 51, "3": 52})
        )

    assert store.objects == before


@pytest.mark.parametrize("missing_table", [DOCUMENTS, TEXT_UNITS])
async def test_rewrite_of_an_index_without_a_document_table_is_refused(missing_table):
    store = _restored_store(["2", "3", "3"])
    del store.objects[f"graphrag/rag_9/a/{missing_table}"]
    before = dict(store.objects)
    orchestrator = GraphDocumentIdRewriteOrchestrator(NoDatabaseUoW(), store)

    with pytest.raises(GraphArtifactsNotReadyError):
        await orchestrator.execute(
            RewriteGraphDocumentIds(rag_id=9, document_id_map={"2": 51, "3": 52})
        )

    assert store.objects == before


@pytest.mark.parametrize(
    ("text_unit_ids", "refused"),
    [
        pytest.param(["2", "3"], False, id="at the row limit"),
        pytest.param(["2", "3", "3"], True, id="one row past it"),
    ],
)
async def test_a_table_with_more_rows_than_its_documents_allow_is_refused(
    monkeypatch, text_unit_ids, refused
):
    # Two documents in the map, one row each: a small parquet file cannot expand to
    # far more rows than the collection could have produced.
    monkeypatch.setattr(graph_artifacts, "_MAX_ROWS_PER_DOCUMENT", 1)
    store = InMemoryArtifactStore(
        {
            f"graphrag/rag_9/a/{DOCUMENTS}": _parquet({"id": ["2", "3"]}),
            f"graphrag/rag_9/a/{TEXT_UNITS}": _parquet(
                {
                    "id": [f"unit-{index}" for index in range(len(text_unit_ids))],
                    "document_id": text_unit_ids,
                }
            ),
        }
    )
    before = dict(store.objects)
    orchestrator = GraphDocumentIdRewriteOrchestrator(NoDatabaseUoW(), store)
    command = RewriteGraphDocumentIds(rag_id=9, document_id_map={"2": 51, "3": 52})

    if refused:
        with pytest.raises(InvalidArtifactArchiveError):
            await orchestrator.execute(command)
        assert store.objects == before
    else:
        await orchestrator.execute(command)
        assert _read_parquet(store.objects[f"graphrag/rag_9/a/{TEXT_UNITS}"])["document_id"] == [
            "51",
            "52",
        ]


async def test_rewrite_in_batches_gives_the_same_tables(monkeypatch):
    monkeypatch.setattr(graph_artifacts, "_REWRITE_BATCH_ROWS", 1)
    store = _restored_store(["2", "3", "3"])
    orchestrator = GraphDocumentIdRewriteOrchestrator(NoDatabaseUoW(), store)

    await orchestrator.execute(
        RewriteGraphDocumentIds(rag_id=9, document_id_map={"2": 51, "3": 52})
    )

    assert _read_parquet(store.objects[f"graphrag/rag_9/a/{TEXT_UNITS}"]) == {
        "id": ["unit-1", "unit-2", "unit-3"],
        "document_id": ["51", "52", "52"],
    }
