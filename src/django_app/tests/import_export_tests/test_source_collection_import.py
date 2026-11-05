"""Import of a knowledge collection from an export archive: what is created, what is
reused, what is refused, and what a failed import leaves behind."""

import json
import os
import zipfile

import httpx
import pytest
from rest_framework.exceptions import PermissionDenied, ValidationError

from rbac.access.effective import EffectivePermissions
from rbac.models import Organization
from rbac.models.enums import Permission, ResourceType
from tables.clients.errors import ClientValidationError
from tables.import_export.archive import (
    ENVELOPE_MEMBER,
    ArchiveMemberMissingError,
    ExportArchiveWriter,
    ImportArchive,
    InvalidArchiveError,
)
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.import_service import ImportService
from tables.import_export.strategies import source_collection as strategy_module
from tables.models import EmbeddingConfig, LLMConfig
from tables.models.knowledge_models import (
    GraphRag,
    GraphRagDocument,
    GraphRagIndexConfig,
    NaiveRag,
    NaiveRagChunk,
    NaiveRagDocumentConfig,
    SourceCollection,
)
from tests.helpers import UNRESTRICTED_EXPORT_POLICY
from tests.import_export_tests.knowledge_builders import (
    COMPLETED_CONFIG,
    make_chunk,
    make_config,
    make_document,
    make_graph_rag,
    make_naive_rag,
)
from tests.knowledge_service_fake import FakeKnowledgeService

NEW_CONFIG = NaiveRagDocumentConfig.NaiveRagDocumentStatus.NEW
GRAPH_TAR = b"graph index tar" * 1000
NO_CONTENT = 204


@pytest.fixture
def knowledge_service(monkeypatch):
    """The knowledge service, faked; queue one response per expected call."""
    service = FakeKnowledgeService()
    monkeypatch.setattr(strategy_module, "KnowledgeClient", service.client)
    return service


@pytest.fixture
def collection(default_org):
    return SourceCollection.objects.create(
        collection_name="Handbook", description="HR docs", org=default_org
    )


@pytest.fixture
def target_org(db):
    return Organization.objects.create(name="Target Organization")


@pytest.fixture
def archive_of(tmp_path):
    """Export a collection into an archive; `members=False` leaves its files out."""

    def _archive(collection, *, members: bool = True) -> str:
        export_data = (
            ExportService(entity_registry)
            .export_entities(
                EntityType.SOURCE_COLLECTION,
                [collection.collection_id],
                policy=UNRESTRICTED_EXPORT_POLICY,
            )
            .data
        )
        with ExportArchiveWriter() as writer:
            writer.write_envelope(export_data)
            if members:
                strategy_module.SourceCollectionStrategy().write_archive_members(collection, writer)
        path = tmp_path / f"export-{len(list(tmp_path.iterdir()))}.zip"
        os.replace(writer.path, path)
        return str(path)

    return _archive


def _import(path: str, org, **options):
    with ImportArchive.open(path) as archive:
        id_mapper, _ = ImportService(entity_registry).import_data(
            archive.envelope(),
            main_entity=EntityType.SOURCE_COLLECTION,
            org_id=org.id,
            archive=archive,
            **options,
        )
    return id_mapper


def _imported(id_mapper, collection) -> SourceCollection:
    return SourceCollection.objects.get(
        pk=id_mapper.get(EntityType.SOURCE_COLLECTION, collection.collection_id)
    )


def _naive_collection(collection, embedding_config):
    """A collection with one indexed document and one that never got indexed."""
    indexed_document = make_document(collection, "policy.txt", b"\x00policy\xffbytes")
    unindexed_document = make_document(collection, "notes.txt", b"notes")
    naive_rag = make_naive_rag(collection, embedder=embedding_config)
    indexed = make_config(
        naive_rag,
        indexed_document,
        status=COMPLETED_CONFIG,
        chunk_size=400,
        indexed_chunk_size=400,
        indexed_chunk_strategy="token",
    )
    make_chunk(indexed, 1, "second", None)
    make_chunk(indexed, 0, "first", [0.25, -1.0, 2.5])
    make_config(
        naive_rag, unindexed_document, status=NaiveRagDocumentConfig.NaiveRagDocumentStatus.FAILED
    )
    return naive_rag


# --- naive collections --------------------------------------------------------------------


@pytest.mark.django_db
def test_naive_collection_arrives_in_the_other_org_with_its_chunks_and_vectors(
    collection, embedding_config, target_org, archive_of
):
    source_rag = _naive_collection(collection, embedding_config)

    id_mapper = _import(archive_of(collection), target_org)

    imported = _imported(id_mapper, collection)
    assert (imported.org_id, imported.collection_name, imported.description) == (
        target_org.id,
        "Handbook",
        "HR docs",
    )
    contents = {
        document.file_name: (bytes(document.document_content.content), document.file_size)
        for document in imported.documents.all()
    }
    assert contents == {"policy.txt": (b"\x00policy\xffbytes", 13), "notes.txt": (b"notes", 5)}

    [naive_rag] = NaiveRag.objects.filter(base_rag_type__source_collection=imported)
    assert id_mapper.get("NaiveRag", source_rag.naive_rag_id) == naive_rag.naive_rag_id
    # The embedder is the copy imported into the target org, not the source's.
    assert EmbeddingConfig.objects.get(pk=naive_rag.embedder_id).org_id == target_org.id
    assert naive_rag.rag_status == NaiveRag.NaiveRagStatus.COMPLETED

    # The configs the RAG created for itself are filled in, never duplicated.
    configs = {
        config.document.file_name: config
        for config in NaiveRagDocumentConfig.objects.filter(naive_rag=naive_rag)
    }
    assert set(configs) == {"policy.txt", "notes.txt"}
    indexed = configs["policy.txt"]
    assert (indexed.status, indexed.chunk_size, indexed.indexed_chunk_size) == (
        COMPLETED_CONFIG,
        400,
        400,
    )
    chunks = [
        (chunk.chunk_index, chunk.text, chunk.metadata)
        for chunk in NaiveRagChunk.objects.filter(naive_rag_document_config=indexed)
    ]
    assert chunks == [(0, "first", {"page": 1}), (1, "second", {"page": 2})]
    vectors = {
        chunk.chunk_index: getattr(getattr(chunk, "embedding", None), "vector", None)
        for chunk in NaiveRagChunk.objects.filter(naive_rag_document_config=indexed)
    }
    assert list(vectors[0]) == [0.25, -1.0, 2.5]
    assert vectors[1] is None
    # Nothing indexed came over for this one, so it starts over.
    assert configs["notes.txt"].status == NEW_CONFIG
    assert configs["notes.txt"].indexed_chunk_size is None

    # The import summary has to cope with the RAG sub-mappings.
    assert set(id_mapper.get_detailed_summary(entity_registry)) >= {EntityType.SOURCE_COLLECTION}
    assert "NaiveRag" not in id_mapper.get_detailed_summary(entity_registry)


@pytest.mark.django_db
def test_imported_collection_is_authored_by_the_importing_user(
    collection, target_org, archive_of, django_user_model
):
    make_document(collection, "policy.txt", b"policy")
    importer = django_user_model.objects.create_user(
        email="importer@example.com", password="StrongPass123!"
    )

    id_mapper = _import(archive_of(collection), target_org, user=importer)

    assert _imported(id_mapper, collection).created_by_id == importer.id


# --- graph collections --------------------------------------------------------------------


@pytest.mark.django_db
def test_graph_index_is_restored_with_the_new_graph_document_ids(
    collection, embedding_config, llm_config, target_org, archive_of, knowledge_service
):
    first = make_document(collection, "a.txt", b"a")
    second = make_document(collection, "b.txt", b"b")
    source_graph = make_graph_rag(
        collection,
        status=GraphRag.GraphRagStatus.COMPLETED,
        embedder=embedding_config,
        llm=llm_config,
        index_config=GraphRagIndexConfig.objects.create(chunk_size=800),
    )
    old_links = [
        GraphRagDocument.objects.create(
            graph_rag=source_graph, document=document, status=GraphRagDocument.Status.COMPLETED
        )
        for document in (first, second)
    ]
    knowledge_service.respond_with(httpx.Response(200, content=GRAPH_TAR))
    path = archive_of(collection)
    knowledge_service.requests.clear()
    knowledge_service.respond_with(httpx.Response(NO_CONTENT), httpx.Response(NO_CONTENT))

    id_mapper = _import(path, target_org)

    imported = _imported(id_mapper, collection)
    graph = GraphRag.objects.get(base_rag_type__source_collection=imported)
    assert id_mapper.get("GraphRag", source_graph.graph_rag_id) == graph.graph_rag_id
    assert (graph.slot, graph.rag_status) == (GraphRag.Slot.A, GraphRag.GraphRagStatus.COMPLETED)
    assert LLMConfig.objects.get(pk=graph.llm_id).org_id == target_org.id
    assert graph.index_config.chunk_size == 800
    new_links = {
        link.document.file_name: link.graph_rag_document_id
        for link in GraphRagDocument.objects.filter(graph_rag=graph)
    }

    (put_method, put_path, put_body), (post_method, post_path, post_body) = (
        knowledge_service.requests
    )
    assert (put_method, put_path, put_body) == (
        "PUT",
        f"/rags/graph/{graph.graph_rag_id}/artifacts/",
        GRAPH_TAR,
    )
    assert (post_method, post_path) == (
        "POST",
        f"/rags/graph/{graph.graph_rag_id}/artifacts/document-ids/",
    )
    assert json.loads(post_body) == {
        "document_id_map": {
            str(old_links[0].graph_rag_document_id): new_links["a.txt"],
            str(old_links[1].graph_rag_document_id): new_links["b.txt"],
        }
    }


@pytest.mark.django_db
def test_graph_without_index_data_starts_over_and_never_calls_the_service(
    collection, target_org, archive_of, knowledge_service
):
    document = make_document(collection, "a.txt", b"a")
    graph = make_graph_rag(collection, status=GraphRag.GraphRagStatus.FAILED)
    GraphRagDocument.objects.create(
        graph_rag=graph, document=document, status=GraphRagDocument.Status.FAILED
    )

    id_mapper = _import(archive_of(collection), target_org)

    imported_graph = GraphRag.objects.get(
        base_rag_type__source_collection=_imported(id_mapper, collection)
    )
    assert imported_graph.rag_status == GraphRag.GraphRagStatus.NEW
    assert list(
        GraphRagDocument.objects.filter(graph_rag=imported_graph).values_list("status", flat=True)
    ) == [GraphRagDocument.Status.NEW]
    assert knowledge_service.requests == []


# --- reuse --------------------------------------------------------------------------------


@pytest.mark.django_db
def test_importing_the_same_collection_again_reuses_it(
    collection, embedding_config, target_org, archive_of
):
    source_rag = _naive_collection(collection, embedding_config)
    path = archive_of(collection)
    first = _imported(_import(path, target_org), collection)

    id_mapper = _import(path, target_org)

    assert _imported(id_mapper, collection) == first
    assert id_mapper.was_created(EntityType.SOURCE_COLLECTION, collection.collection_id) is False
    assert SourceCollection.objects.filter(org=target_org).count() == 1
    # Knowledge links in the same file still find the reused collection's RAG.
    assert id_mapper.get("NaiveRag", source_rag.naive_rag_id) == (
        NaiveRag.objects.get(base_rag_type__source_collection=first).naive_rag_id
    )


@pytest.mark.django_db
def test_a_renamed_copy_from_an_earlier_import_is_reused(collection, target_org, archive_of):
    make_document(collection, "policy.txt", b"policy")
    SourceCollection.objects.create(
        collection_name="Handbook", description="something else", org=target_org
    )
    path = archive_of(collection)
    first = _imported(_import(path, target_org), collection)
    assert first.collection_name == "Handbook (1)"

    second = _imported(_import(path, target_org), collection)

    assert second == first


def _change_description(imported):
    imported.description = "changed"
    imported.save()


def _change_file_size(imported):
    imported.documents.update(file_size=999)


def _add_graph_rag(imported):
    make_graph_rag(imported, status=GraphRag.GraphRagStatus.NEW)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "change",
    [
        pytest.param(_change_description, id="description"),
        pytest.param(_change_file_size, id="file size"),
        pytest.param(_add_graph_rag, id="rag types"),
    ],
)
def test_a_collection_that_differs_in_a_key_field_is_not_reused(
    collection, target_org, archive_of, change
):
    make_document(collection, "policy.txt", b"policy")
    make_naive_rag(collection)
    path = archive_of(collection)
    first = _imported(_import(path, target_org), collection)
    change(first)

    second = _imported(_import(path, target_org), collection)

    assert second != first
    assert second.collection_name == "Handbook (1)"


# --- refusals -----------------------------------------------------------------------------


def _assert_nothing_written(target_org):
    assert not SourceCollection.objects.filter(org=target_org).exists()
    assert not EmbeddingConfig.objects.filter(org=target_org).exists()


@pytest.mark.django_db
def test_vectors_of_different_lengths_in_one_rag_are_refused(collection, target_org, archive_of):
    naive_rag = make_naive_rag(collection)
    for name, vector in (("a.txt", [1.0, 0.0, 0.0]), ("b.txt", [1.0, 0.0])):
        config = make_config(
            naive_rag, make_document(collection, name, b"x"), status=COMPLETED_CONFIG
        )
        make_chunk(config, 0, name, vector)

    with pytest.raises(ValidationError) as raised:
        _import(archive_of(collection), target_org)

    assert raised.value.detail["code"] == "invalid_archive"
    _assert_nothing_written(target_org)


@pytest.mark.django_db
def test_a_file_the_entry_points_to_but_the_archive_lacks_is_refused(
    collection, target_org, archive_of
):
    make_document(collection, "policy.txt", b"policy")

    with pytest.raises(ArchiveMemberMissingError):
        _import(archive_of(collection, members=False), target_org)

    _assert_nothing_written(target_org)


@pytest.mark.django_db
def test_a_collection_without_an_archive_is_refused(collection, target_org, archive_of):
    make_document(collection, "policy.txt", b"policy")
    with ImportArchive.open(archive_of(collection)) as archive:
        export_data = archive.envelope()

    with pytest.raises(ValidationError) as raised:
        ImportService(entity_registry).import_data(
            export_data, main_entity=EntityType.SOURCE_COLLECTION, org_id=target_org.id
        )

    assert raised.value.detail["code"] == "archive_required"
    _assert_nothing_written(target_org)


@pytest.mark.django_db
def test_an_archive_that_unpacks_past_the_cap_is_a_bad_request(
    collection, target_org, archive_of, settings
):
    make_document(collection, "policy.txt", b"x" * 5000)
    path = archive_of(collection)
    with zipfile.ZipFile(path) as zipped:
        envelope_size = zipped.getinfo(ENVELOPE_MEMBER).file_size
        settings.MAX_KNOWLEDGE_ARCHIVE_UNCOMPRESSED_SIZE = sum(
            info.file_size for info in zipped.infolist()
        )

    with ImportArchive.open(path) as archive:
        # Reading export.json twice spends its size again, so the document read
        # then passes the cap although every declared size fits.
        archive.envelope()
        export_data = archive.envelope()
        assert envelope_size < 5000
        with pytest.raises(InvalidArchiveError):
            ImportService(entity_registry).import_data(
                export_data,
                main_entity=EntityType.SOURCE_COLLECTION,
                org_id=target_org.id,
                archive=archive,
            )

    _assert_nothing_written(target_org)


@pytest.mark.django_db
def test_a_failed_import_removes_every_graph_index_it_restored(
    collection, target_org, archive_of, knowledge_service
):
    for name in ("a.txt", "b.txt"):
        graph = make_graph_rag(collection, status=GraphRag.GraphRagStatus.COMPLETED)
        GraphRagDocument.objects.create(
            graph_rag=graph,
            document=make_document(collection, name, b"x"),
            status=GraphRagDocument.Status.COMPLETED,
        )
    knowledge_service.respond_with(
        httpx.Response(200, content=GRAPH_TAR), httpx.Response(200, content=GRAPH_TAR)
    )
    path = archive_of(collection)
    knowledge_service.requests.clear()
    refused = httpx.Response(400, json={"code": "invalid_artifact_archive", "detail": "refused"})
    knowledge_service.respond_with(
        httpx.Response(NO_CONTENT),
        httpx.Response(NO_CONTENT),
        refused,
        httpx.Response(NO_CONTENT),
        httpx.Response(NO_CONTENT),
    )

    with pytest.raises(ClientValidationError):
        _import(path, target_org)

    restored = [url for method, url, _ in knowledge_service.requests if method == "PUT"]
    deleted = [url for method, url, _ in knowledge_service.requests if method == "DELETE"]
    assert len(restored) == 2
    # The first index was restored, the second half-way: both are removed.
    assert deleted == [url.replace("artifacts/", "") for url in restored]
    _assert_nothing_written(target_org)


@pytest.mark.django_db
def test_import_needs_create_on_knowledge_sources(collection, target_org, archive_of):
    make_document(collection, "policy.txt", b"policy")
    everything_but_knowledge = {
        resource: int(Permission.READ | Permission.CREATE)
        for resource in ResourceType
        if resource != ResourceType.KNOWLEDGE_SOURCES
    }

    with pytest.raises(PermissionDenied):
        _import(
            archive_of(collection),
            target_org,
            effective_permissions=EffectivePermissions(
                is_superadmin=False, role=None, by_resource=everything_but_knowledge
            ),
        )

    _assert_nothing_written(target_org)
