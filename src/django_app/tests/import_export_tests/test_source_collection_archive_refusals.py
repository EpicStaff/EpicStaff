"""What a knowledge collection archive may not carry, and an export of a collection
that changes while it is written. Every refusal is a 400 `invalid_archive` (or
`collection_changed`) that leaves nothing behind."""

import copy
import json
import os
import uuid
import zipfile

import httpx
import pytest
from rest_framework.exceptions import ValidationError

from rbac.models import Organization
from tables.import_export.archive import ENVELOPE_MEMBER, ExportArchiveWriter, ImportArchive
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.import_service import ImportService
from tables.import_export.strategies import source_collection as strategy_module
from tables.import_export.strategies.source_collection import (
    CollectionChangedError,
    SourceCollectionStrategy,
)
from tables.models.knowledge_models import (
    GraphRag,
    GraphRagDocument,
    GraphRagIndexConfig,
    NaiveRagDocumentConfig,
    SourceCollection,
)
from tests.helpers import UNRESTRICTED_EXPORT_POLICY
from tests.knowledge_service_fake import FakeKnowledgeService
from tests.import_export_tests.knowledge_builders import (
    COMPLETED_CONFIG,
    make_chunk,
    make_config,
    make_document,
    make_graph_rag,
    make_naive_rag,
)

pytestmark = pytest.mark.django_db

CHUNKS_KEY = "naive"


@pytest.fixture
def collection(default_org):
    return SourceCollection.objects.create(collection_name="Handbook", org=default_org)


@pytest.fixture
def target_org(db):
    return Organization.objects.create(name="Target Organization")


def _export(collection) -> tuple[dict, dict[str, bytes]]:
    """The envelope and archive files of a real export of `collection`."""
    envelope = json.loads(
        json.dumps(
            ExportService(entity_registry)
            .export_entities(
                EntityType.SOURCE_COLLECTION,
                [collection.collection_id],
                policy=UNRESTRICTED_EXPORT_POLICY,
            )
            .data
        )
    )
    with ExportArchiveWriter() as writer:
        writer.write_envelope(envelope)
        for entry in envelope[EntityType.SOURCE_COLLECTION]:
            SourceCollectionStrategy().write_archive_members(entry, writer)
    try:
        with zipfile.ZipFile(writer.path) as archive:
            members = {
                name: archive.read(name) for name in archive.namelist() if name != ENVELOPE_MEMBER
            }
    finally:
        os.unlink(writer.path)
    return envelope, members


def _import(tmp_path, target_org, envelope: dict, members: dict[str, bytes]):
    path = tmp_path / f"crafted-{uuid.uuid4()}.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(ENVELOPE_MEMBER, json.dumps(envelope))
        for name, data in members.items():
            archive.writestr(name, data)
    with ImportArchive.open(str(path)) as archive:
        ImportService(entity_registry).import_data(
            archive.envelope(),
            main_entity=EntityType.SOURCE_COLLECTION,
            org_id=target_org.id,
            archive=archive,
        )


def _entry(envelope: dict) -> dict:
    [entry] = envelope[EntityType.SOURCE_COLLECTION]
    return entry


def _assert_refused(tmp_path, target_org, envelope, members, *, mentioning: str):
    with pytest.raises(ValidationError) as raised:
        _import(tmp_path, target_org, envelope, members)
    assert raised.value.detail["code"] == "invalid_archive"
    assert mentioning in str(raised.value.detail["detail"])
    assert not SourceCollection.objects.filter(org=target_org).exists()


@pytest.fixture
def indexed_collection(collection):
    """One document, indexed by a naive RAG into two chunks."""
    document = make_document(collection, "policy.txt", b"policy text")
    config = make_config(make_naive_rag(collection), document, status=COMPLETED_CONFIG)
    make_chunk(config, 0, "first", [1.0, 0.0])
    make_chunk(config, 1, "second", [0.0, 1.0])
    return collection


def _chunks_path(envelope: dict) -> str:
    [naive_rag] = _entry(envelope)["naive_rags"]
    [config] = naive_rag["document_configs"]
    return config["chunks_path"]


# --- documents -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("file_name", "mentioning"),
    [
        pytest.param("../escape.txt", "path", id="a path"),
        pytest.param("tool.exe", "exe", id="a type uploads refuse"),
    ],
)
def test_a_document_uploads_would_refuse_is_refused(
    collection, target_org, tmp_path, file_name, mentioning
):
    make_document(collection, "policy.txt", b"policy")
    envelope, members = _export(collection)
    _entry(envelope)["documents"][0]["file_name"] = file_name

    _assert_refused(tmp_path, target_org, envelope, members, mentioning=mentioning)


def test_a_document_over_the_upload_limit_is_refused_before_it_is_read(
    collection, target_org, tmp_path, settings
):
    make_document(collection, "policy.txt", b"x" * 20)
    envelope, members = _export(collection)
    settings.MAX_UPLOAD_FILE_SIZE = 19
    # The file may claim any size; the archive's own size of the member counts.
    _entry(envelope)["documents"][0]["file_size"] = 1

    _assert_refused(tmp_path, target_org, envelope, members, mentioning="policy.txt")


def test_a_document_exactly_at_the_upload_limit_is_accepted(
    collection, target_org, tmp_path, settings
):
    make_document(collection, "policy.txt", b"x" * 20)
    envelope, members = _export(collection)
    settings.MAX_UPLOAD_FILE_SIZE = 20

    _import(tmp_path, target_org, envelope, members)

    assert SourceCollection.objects.filter(org=target_org).count() == 1


def test_a_document_listed_twice_is_refused(collection, target_org, tmp_path):
    make_document(collection, "policy.txt", b"policy")
    envelope, members = _export(collection)
    documents = _entry(envelope)["documents"]
    documents.append(copy.deepcopy(documents[0]))

    _assert_refused(tmp_path, target_org, envelope, members, mentioning="twice")


@pytest.mark.parametrize("file_size", [-1, "12", True], ids=["negative", "text", "bool"])
def test_a_document_without_content_needs_a_whole_size(collection, target_org, tmp_path, file_size):
    make_document(collection, "policy.txt", None)
    envelope, members = _export(collection)
    _entry(envelope)["documents"][0]["file_size"] = file_size

    with pytest.raises(ValidationError) as raised:
        _import(tmp_path, target_org, envelope, members)
    assert raised.value.detail["code"] == "invalid_archive"
    assert not SourceCollection.objects.filter(org=target_org).exists()


# --- chunks --------------------------------------------------------------------------------


def _rewrite_chunks(members: dict, path: str, edit) -> None:
    lines = [json.loads(line) for line in members[path].decode().splitlines()]
    edit(lines)
    members[path] = "".join(json.dumps(line) + "\n" for line in lines).encode()


@pytest.mark.parametrize(
    ("edit", "mentioning"),
    [
        pytest.param(lambda lines: lines[1].update(chunk_index=0), "twice", id="one index twice"),
        pytest.param(lambda lines: lines[0].update(text=42), "chunk", id="text not text"),
        pytest.param(lambda lines: lines[0].update(chunk_index=-1), "chunk", id="negative index"),
        pytest.param(lambda lines: lines[0].update(vector="1,0"), "vector", id="vector not a list"),
    ],
)
def test_a_malformed_chunk_is_refused(indexed_collection, target_org, tmp_path, edit, mentioning):
    envelope, members = _export(indexed_collection)
    _rewrite_chunks(members, _chunks_path(envelope), edit)

    _assert_refused(tmp_path, target_org, envelope, members, mentioning=mentioning)


@pytest.mark.parametrize(("line_limit_delta", "refused"), [(0, False), (-1, True)])
def test_a_chunk_line_past_the_line_limit_is_refused(
    indexed_collection, target_org, tmp_path, monkeypatch, line_limit_delta, refused
):
    envelope, members = _export(indexed_collection)
    longest_line = max(len(line) for line in members[_chunks_path(envelope)].splitlines())
    monkeypatch.setattr(strategy_module, "_MAX_LINE_SIZE", longest_line + line_limit_delta)

    if refused:
        _assert_refused(tmp_path, target_org, envelope, members, mentioning="longer than")
    else:
        _import(tmp_path, target_org, envelope, members)
        assert SourceCollection.objects.filter(org=target_org).count() == 1


# --- statuses a file cannot set ---------------------------------------------------------


@pytest.fixture
def knowledge_service(monkeypatch):
    """The knowledge service, faked; queue one response per expected call."""
    service = FakeKnowledgeService()
    monkeypatch.setattr(strategy_module, "KnowledgeClient", service.client)
    return service


def test_a_config_whose_chunks_travelled_is_completed_whatever_the_file_says(
    indexed_collection, target_org, tmp_path
):
    envelope, members = _export(indexed_collection)
    _entry(envelope)["naive_rags"][0]["document_configs"][0]["status"] = "processing"

    _import(tmp_path, target_org, envelope, members)

    config = NaiveRagDocumentConfig.objects.get(
        naive_rag__base_rag_type__source_collection__org=target_org
    )
    assert config.status == COMPLETED_CONFIG


@pytest.mark.parametrize(
    ("file_status", "stored"),
    [
        pytest.param("processing", GraphRagDocument.Status.NEW, id="not an index state"),
        pytest.param("failed", GraphRagDocument.Status.FAILED, id="failed is kept"),
    ],
)
def test_a_graph_document_keeps_only_a_status_that_describes_its_index(
    collection, target_org, tmp_path, knowledge_service, file_status, stored
):
    document = make_document(collection, "policy.txt", b"policy")
    graph = make_graph_rag(collection, status=GraphRag.GraphRagStatus.COMPLETED)
    GraphRagDocument.objects.create(
        graph_rag=graph, document=document, status=GraphRagDocument.Status.COMPLETED
    )
    knowledge_service.respond_with(httpx.Response(200, content=b"graph tar"))
    envelope, members = _export(collection)
    _entry(envelope)["graph_rags"][0]["documents"][0]["status"] = file_status
    knowledge_service.respond_with(httpx.Response(204), httpx.Response(204))

    _import(tmp_path, target_org, envelope, members)

    link = GraphRagDocument.objects.get(graph_rag__base_rag_type__source_collection__org=target_org)
    assert link.status == stored


# --- graph index config --------------------------------------------------------------------


def test_an_index_config_with_invalid_values_is_refused(collection, target_org, tmp_path):
    make_document(collection, "policy.txt", b"policy")
    make_graph_rag(
        collection,
        status=GraphRag.GraphRagStatus.NEW,
        index_config=GraphRagIndexConfig.objects.create(),
    )
    envelope, members = _export(collection)
    _entry(envelope)["graph_rags"][0]["index_config"]["chunk_size"] = "big"

    with pytest.raises(ValidationError) as raised:
        _import(tmp_path, target_org, envelope, members)
    assert raised.value.detail["code"] == "invalid_archive"
    assert "chunk_size" in str(raised.value.detail["detail"])


def test_an_index_config_cannot_choose_its_primary_key(collection, target_org, tmp_path):
    make_document(collection, "policy.txt", b"policy")
    make_graph_rag(
        collection,
        status=GraphRag.GraphRagStatus.NEW,
        index_config=GraphRagIndexConfig.objects.create(chunk_size=700),
    )
    envelope, members = _export(collection)
    chosen_id = GraphRagIndexConfig.objects.order_by("-pk").first().pk + 1000
    _entry(envelope)["graph_rags"][0]["index_config"]["id"] = chosen_id

    _import(tmp_path, target_org, envelope, members)

    imported = GraphRag.objects.get(base_rag_type__source_collection__org=target_org)
    assert imported.index_config.chunk_size == 700
    assert imported.index_config.pk != chosen_id


def test_a_document_linked_twice_to_one_graph_index_is_refused(collection, target_org, tmp_path):
    document = make_document(collection, "policy.txt", b"policy")
    graph = make_graph_rag(collection, status=GraphRag.GraphRagStatus.NEW)
    GraphRagDocument.objects.create(graph_rag=graph, document=document)
    envelope, members = _export(collection)
    links = _entry(envelope)["graph_rags"][0]["documents"]
    links.append({**links[0], "id": links[0]["id"] + 1000})

    _assert_refused(tmp_path, target_org, envelope, members, mentioning="twice")


# --- a collection that changes during its export -------------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(
            lambda collection: NaiveRagDocumentConfig.objects.update(
                status=NaiveRagDocumentConfig.NaiveRagDocumentStatus.OUTDATED
            ),
            id="document re-indexed",
        ),
        pytest.param(lambda collection: collection.documents.all().delete(), id="document removed"),
    ],
)
def test_an_export_refuses_files_its_entry_names_but_that_changed(indexed_collection, change):
    strategy = SourceCollectionStrategy()
    entry = json.loads(json.dumps(strategy.export_entity(indexed_collection)))
    change(indexed_collection)

    with pytest.raises(CollectionChangedError) as raised:
        with ExportArchiveWriter() as writer:
            strategy.write_archive_members(entry, writer)

    assert raised.value.detail["code"] == "collection_changed"
    # A failed write leaves no temporary archive behind.
    assert not os.path.exists(writer.path)


def test_reuse_finds_a_match_behind_many_newer_copies_with_other_files(collection, default_org):
    make_document(collection, "policy.txt", b"policy")
    entry = json.loads(json.dumps(SourceCollectionStrategy().export_entity(collection)))
    # The match is the oldest renamed copy; more newer copies without its files than
    # the candidate window holds come first by recency.
    collection.collection_name = "Handbook (1)"
    collection.save()
    for number in range(2, 62):
        SourceCollection.objects.create(collection_name=f"Handbook ({number})", org=default_org)

    found = SourceCollectionStrategy().find_existing(entry, IDMapper(), org_id=default_org.id)

    assert found == collection


def test_reuse_needs_an_organization(collection):
    make_document(collection, "policy.txt", b"policy")
    entry = json.loads(json.dumps(SourceCollectionStrategy().export_entity(collection)))

    assert SourceCollectionStrategy().find_existing(entry, IDMapper(), org_id=None) is None
