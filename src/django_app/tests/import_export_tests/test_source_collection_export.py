"""Export of a knowledge collection: its export.json entry, the files written next to
it in the archive, and the configs it depends on."""

import json
import os
import zipfile

import httpx
import pytest

from rbac.access.effective import EffectivePermissions
from rbac.models import Organization
from rbac.models.enums import Permission, ResourceType
from tables.import_export.archive import ENVELOPE_MEMBER, ExportArchiveWriter, ImportArchive
from tables.import_export.enums import EntityType
from tables.import_export.permissions import ExportAccessPolicy
from tables.import_export.strategies import source_collection as strategy_module
from tables.import_export.strategies.source_collection import SourceCollectionStrategy
from tables.models import LLMConfig
from tables.models.knowledge_models import (
    GraphRag,
    GraphRagDocument,
    GraphRagIndexConfig,
    SourceCollection,
)
from tests.import_export_tests.knowledge_builders import (
    COMPLETED_CONFIG,
    bin_row,
    make_chunk,
    make_config,
    make_document,
    make_graph_rag,
    make_naive_rag,
)
from tests.knowledge_service_fake import FakeKnowledgeService

GRAPH_TAR = b"graph index tar" * 1000


@pytest.fixture
def strategy():
    return SourceCollectionStrategy()


@pytest.fixture
def knowledge_service(monkeypatch):
    """The knowledge service, faked; queue one response per expected artifact download."""
    service = FakeKnowledgeService()
    monkeypatch.setattr(strategy_module, "KnowledgeClient", service.client)
    return service


@pytest.fixture
def collection(default_org):
    return SourceCollection.objects.create(
        collection_name="Handbook", description="HR docs", org=default_org
    )


@pytest.fixture
def export_archive():
    """Write a collection's files into a fresh archive and return its members by name."""
    paths = []

    def _export(strategy, collection) -> dict[str, bytes]:
        with ExportArchiveWriter() as writer:
            writer.write_envelope({})
            strategy.write_archive_members(strategy.export_entity(collection), writer)
        paths.append(writer.path)
        # The import's own reader must accept what the export produced.
        ImportArchive.open(writer.path).close()
        with zipfile.ZipFile(writer.path) as archive:
            return {
                name: archive.read(name) for name in archive.namelist() if name != ENVELOPE_MEMBER
            }

    yield _export
    for path in paths:
        os.unlink(path)


def _paths_in(entry: dict) -> set[str]:
    paths = {document["content_path"] for document in entry["documents"]}
    paths |= {
        config["chunks_path"] for rag in entry["naive_rags"] for config in rag["document_configs"]
    }
    paths |= {rag["artifacts_path"] for rag in entry["graph_rags"]}
    return paths - {None}


# --- export.json entry ------------------------------------------------------------------


@pytest.mark.django_db
def test_entry_points_only_at_files_that_travel(strategy, collection, embedding_config, llm_config):
    stored = make_document(collection, "policy.txt", b"policy text")
    empty = make_document(collection, "lost.txt", None)
    naive = make_naive_rag(collection, embedder=embedding_config)
    indexed = make_config(naive, stored, status=COMPLETED_CONFIG, indexed_chunk_size=500)
    pending = make_config(naive, empty)
    graph = make_graph_rag(
        collection,
        status=GraphRag.GraphRagStatus.COMPLETED,
        embedder=embedding_config,
        llm=llm_config,
        index_config=GraphRagIndexConfig.objects.create(chunk_size=800),
    )
    graph_document = GraphRagDocument.objects.create(graph_rag=graph, document=stored)
    unindexed_graph = make_graph_rag(collection, status=GraphRag.GraphRagStatus.NEW)

    entry = strategy.export_entity(collection)

    assert entry["id"] == collection.collection_id
    assert (entry["collection_name"], entry["description"]) == ("Handbook", "HR docs")
    assert {document["file_name"]: document["content_path"] for document in entry["documents"]} == {
        "policy.txt": f"knowledge/documents/{stored.document_id}",
        "lost.txt": None,
    }

    [naive_entry] = entry["naive_rags"]
    assert (naive_entry["id"], naive_entry["embedder"]) == (naive.naive_rag_id, embedding_config.id)
    assert [
        (config["id"], config["document"], config["chunks_path"])
        for config in naive_entry["document_configs"]
    ] == [
        (
            indexed.naive_rag_document_id,
            stored.document_id,
            f"knowledge/naive/{naive.naive_rag_id}/{indexed.naive_rag_document_id}.jsonl",
        ),
        (pending.naive_rag_document_id, empty.document_id, None),
    ]
    assert naive_entry["document_configs"][0]["indexed_chunk_size"] == 500

    graphs = {graph_entry["id"]: graph_entry for graph_entry in entry["graph_rags"]}
    completed = graphs[graph.graph_rag_id]
    assert completed["artifacts_path"] == f"knowledge/graph/{graph.graph_rag_id}.tar"
    assert (completed["embedder"], completed["llm"]) == (embedding_config.id, llm_config.id)
    assert completed["index_config"]["chunk_size"] == 800
    # The GraphRAG index stores the link row's id, so that is the id the import remaps.
    assert completed["documents"] == [
        {
            "id": graph_document.graph_rag_document_id,
            "document": stored.document_id,
            "status": "new",
        }
    ]
    assert graphs[unindexed_graph.graph_rag_id]["artifacts_path"] is None
    assert graphs[unindexed_graph.graph_rag_id]["index_config"] is None
    # The entry has to survive the trip into export.json.
    json.dumps(entry)


@pytest.mark.django_db
def test_binned_rows_are_left_out(strategy, collection, export_archive):
    kept = make_document(collection, "kept.txt", b"kept")
    binned = make_document(collection, "binned.txt", b"binned")
    bin_row(binned)
    naive = make_naive_rag(collection)
    binned_config = make_config(naive, kept, status=COMPLETED_CONFIG)
    bin_row(binned_config)
    graph = make_graph_rag(collection, status=GraphRag.GraphRagStatus.NEW)
    bin_row(GraphRagDocument.objects.create(graph_rag=graph, document=kept))

    entry = strategy.export_entity(collection)

    assert [document["file_name"] for document in entry["documents"]] == ["kept.txt"]
    assert entry["naive_rags"][0]["document_configs"] == []
    assert entry["graph_rags"][0]["documents"] == []
    assert set(export_archive(strategy, collection)) == {f"knowledge/documents/{kept.document_id}"}


@pytest.mark.django_db
def test_other_collections_are_not_exported(
    strategy, collection, default_org, knowledge_service, export_archive
):
    other = SourceCollection.objects.create(collection_name="Other", org=default_org)
    other_document = make_document(other, "other.txt", b"other")
    other_config = make_config(make_naive_rag(other), other_document, status=COMPLETED_CONFIG)
    make_chunk(other_config, 0, "foreign", [1.0, 0.0, 0.0])
    # The fake service has no response queued, so fetching this index fails the test.
    make_graph_rag(other, status=GraphRag.GraphRagStatus.COMPLETED)

    entry = strategy.export_entity(collection)

    assert (entry["documents"], entry["naive_rags"], entry["graph_rags"]) == ([], [], [])
    assert export_archive(strategy, collection) == {}


# --- archive members ---------------------------------------------------------------------


@pytest.mark.django_db
def test_archive_holds_exactly_the_files_the_entry_points_to(
    strategy, collection, knowledge_service, export_archive
):
    stored = make_document(collection, "policy.bin", b"\x00policy\xffbytes")
    make_document(collection, "zero.txt", b"")
    make_document(collection, "lost.txt", None)
    naive = make_naive_rag(collection)
    indexed = make_config(naive, stored, status=COMPLETED_CONFIG)
    pending = make_config(make_naive_rag(collection), stored)
    make_chunk(pending, 0, "not indexed", [0.5, 0.5, 0.5])
    graph = make_graph_rag(collection, status=GraphRag.GraphRagStatus.COMPLETED)
    make_graph_rag(collection, status=GraphRag.GraphRagStatus.PROCESSING)
    knowledge_service.respond_with(httpx.Response(200, content=GRAPH_TAR))

    members = export_archive(strategy, collection)

    assert set(members) == _paths_in(strategy.export_entity(collection))
    assert members[f"knowledge/documents/{stored.document_id}"] == b"\x00policy\xffbytes"
    chunks_member = f"knowledge/naive/{naive.naive_rag_id}/{indexed.naive_rag_document_id}.jsonl"
    assert members[chunks_member] == b""
    assert members[f"knowledge/graph/{graph.graph_rag_id}.tar"] == GRAPH_TAR
    # Only the completed graph index is fetched.
    assert [(method, url) for method, url, _ in knowledge_service.requests] == [
        ("GET", f"/rags/graph/{graph.graph_rag_id}/artifacts/")
    ]


@pytest.mark.django_db
def test_chunks_are_written_one_json_line_each_in_chunk_order(strategy, collection, export_archive):
    document = make_document(collection, "policy.txt", b"policy")
    naive = make_naive_rag(collection)
    config = make_config(naive, document, status=COMPLETED_CONFIG)
    # Created out of order, so the order in the file has to come from chunk_index.
    make_chunk(config, 1, "second", None)
    make_chunk(config, 0, "first", [0.25, -1.0, 2.5])
    make_chunk(config, 2, "third", [1.0, 0.0, 0.0])

    members = export_archive(strategy, collection)
    lines = members[f"knowledge/naive/{naive.naive_rag_id}/{config.naive_rag_document_id}.jsonl"]

    assert [json.loads(line) for line in lines.decode().splitlines()] == [
        {
            "chunk_index": 0,
            "text": "first",
            "token_count": 5,
            "overlap_start_index": 0,
            "overlap_end_index": 2,
            "metadata": {"page": 1},
            "vector": [0.25, -1.0, 2.5],
        },
        {
            "chunk_index": 1,
            "text": "second",
            "token_count": 6,
            "overlap_start_index": 0,
            "overlap_end_index": 2,
            "metadata": {"page": 2},
            "vector": None,
        },
        {
            "chunk_index": 2,
            "text": "third",
            "token_count": 5,
            "overlap_start_index": 0,
            "overlap_end_index": 2,
            "metadata": {"page": 3},
            "vector": [1.0, 0.0, 0.0],
        },
    ]


@pytest.mark.django_db
def test_no_completed_graph_index_means_no_call_to_the_knowledge_service(
    strategy, collection, knowledge_service, export_archive
):
    make_graph_rag(collection, status=GraphRag.GraphRagStatus.FAILED)

    export_archive(strategy, collection)

    assert knowledge_service.requests == []


# --- dependencies, scope, permission -----------------------------------------------------


@pytest.mark.django_db
def test_dependencies_name_each_config_once_and_skip_unset_ones(
    strategy, collection, embedding_config, llm_config
):
    second_llm_config = LLMConfig.objects.create(
        custom_name="Second", model=llm_config.model, org=llm_config.org
    )
    make_naive_rag(collection, embedder=embedding_config)
    make_naive_rag(collection)
    make_graph_rag(
        collection, status=GraphRag.GraphRagStatus.NEW, embedder=embedding_config, llm=llm_config
    )
    make_graph_rag(collection, status=GraphRag.GraphRagStatus.NEW, llm=llm_config)
    make_graph_rag(collection, status=GraphRag.GraphRagStatus.NEW, llm=second_llm_config)
    make_graph_rag(collection, status=GraphRag.GraphRagStatus.NEW)

    assert strategy.extract_dependencies_from_instance(collection) == {
        EntityType.EMBEDDING_CONFIG: [embedding_config.id],
        EntityType.LLM_CONFIG: sorted([llm_config.id, second_llm_config.id]),
    }


@pytest.mark.django_db
def test_org_scope_keeps_only_the_callers_collections(strategy, collection):
    other_org = Organization.objects.create(name="Other Organization")
    SourceCollection.objects.create(collection_name="Foreign", org=other_org)

    scoped = SourceCollection.objects.filter(strategy.get_org_scope_q(collection.org_id))

    assert list(scoped) == [collection]


@pytest.mark.parametrize(
    ("bits", "allowed"),
    [
        pytest.param(int(Permission.READ | Permission.EXPORT), True, id="may export"),
        pytest.param(int(Permission.READ), False, id="read only"),
    ],
)
def test_collection_travels_only_with_knowledge_export_permission(bits, allowed):
    policy = ExportAccessPolicy(
        EffectivePermissions(
            is_superadmin=False, role=None, by_resource={ResourceType.KNOWLEDGE_SOURCES: bits}
        )
    )

    assert policy.allows(EntityType.SOURCE_COLLECTION) is allowed
