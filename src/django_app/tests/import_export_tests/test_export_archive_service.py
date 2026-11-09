"""Archives in the import/export services: writing an export archive, importing one
through the job path, version 6, and inspecting a zip upload."""

import io
import json
import os
import zipfile

import pytest
from rest_framework.exceptions import ValidationError

from tables.import_export.archive import ENVELOPE_MEMBER, ExportArchiveWriter, InvalidArchiveError
from tables.import_export.constants import IMPORT_VERSION, MAIN_ENTITY_KEY
from tables.import_export.enums import EntityType
from tables.import_export.export_format_strategies import ArchiveExportFormatStrategy
from tables.import_export.registry import entity_registry
from tables.import_export.schemas import ImportSettings
from tables.import_export.services.export_service import ExportService
from tables.import_export.version_conversions.base import VersionConverter
from tables.models import Graph, KnowledgeNode
from tables.models.knowledge_models import SourceCollection
from tables.services.import_export_service import ViewSetImportExportService
from tests.helpers import UNRESTRICTED_EXPORT_POLICY
from tests.import_export_tests.knowledge_builders import make_document, make_naive_rag


@pytest.fixture
def flow_service():
    return ViewSetImportExportService(EntityType.GRAPH)


@pytest.fixture
def collection(default_org):
    collection = SourceCollection.objects.create(collection_name="Handbook", org=default_org)
    make_document(collection, "policy.txt", b"policy bytes")
    return collection


@pytest.fixture
def flow_with_knowledge(default_org, collection):
    graph = Graph.objects.create(
        name="knowledge flow", metadata={"nodes": [], "edges": []}, org=default_org
    )
    rag = make_naive_rag(collection)
    KnowledgeNode.objects.create(
        graph=graph, source_collection=collection, rag_type="naive", rag_id=rag.naive_rag_id
    )
    return graph


@pytest.fixture
def written_archives():
    paths = []
    yield paths
    for path in paths:
        if os.path.exists(path):
            os.unlink(path)


def _render(graph, written_archives, *, include_knowledge=True) -> str:
    result = ExportService(entity_registry).export_entities(
        EntityType.GRAPH,
        [graph.id],
        policy=UNRESTRICTED_EXPORT_POLICY,
        include_knowledge=include_knowledge,
    )
    path = ArchiveExportFormatStrategy().render_to_file(result)
    written_archives.append(path)
    return path


def _archive_with_envelope(tmp_path, envelope: dict) -> str:
    path = tmp_path / "upload.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(ENVELOPE_MEMBER, json.dumps(envelope))
    return str(path)


# --- writing -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_archive_holds_the_version_6_envelope_and_the_collection_files(
    flow_with_knowledge, collection, written_archives
):
    path = _render(flow_with_knowledge, written_archives)

    with zipfile.ZipFile(path) as archive:
        envelope = json.loads(archive.read(ENVELOPE_MEMBER))
        names = set(archive.namelist())
    assert (envelope["version"], envelope[MAIN_ENTITY_KEY]) == (6, EntityType.GRAPH)
    [document] = collection.documents.all()
    assert names == {ENVELOPE_MEMBER, f"knowledge/documents/{document.document_id}"}


@pytest.mark.django_db
def test_without_knowledge_the_archive_holds_only_the_envelope(
    flow_with_knowledge, written_archives
):
    path = _render(flow_with_knowledge, written_archives, include_knowledge=False)

    with zipfile.ZipFile(path) as archive:
        assert archive.namelist() == [ENVELOPE_MEMBER]
        assert EntityType.SOURCE_COLLECTION not in json.loads(archive.read(ENVELOPE_MEMBER))


# --- importing through the job path ------------------------------------------------------


@pytest.mark.django_db
def test_import_archive_brings_the_flow_with_its_collection(
    flow_service, flow_with_knowledge, collection, written_archives, default_org, regular_user
):
    path = _render(flow_with_knowledge, written_archives)

    summary = flow_service.import_archive(
        path,
        org_id=default_org.id,
        user=regular_user,
        settings=ImportSettings(),
        main_entity=EntityType.GRAPH,
    )

    assert summary[EntityType.GRAPH]["created"]["count"] == 1
    # Same key fields in the same org: the collection is reused, not copied.
    assert summary[EntityType.SOURCE_COLLECTION]["reused"]["count"] == 1
    imported_graph_id = summary[EntityType.GRAPH]["created"]["items"][0]["id"]
    node = KnowledgeNode.objects.get(graph_id=imported_graph_id)
    assert node.source_collection_id == collection.collection_id


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("envelope", "code"),
    [
        pytest.param(
            {MAIN_ENTITY_KEY: EntityType.GRAPH, "version": 5}, "use_sync_import", id="version 5"
        ),
        pytest.param({MAIN_ENTITY_KEY: EntityType.GRAPH}, "use_sync_import", id="no version"),
    ],
)
def test_import_archive_refuses_files_older_than_archives(
    flow_service, tmp_path, default_org, regular_user, envelope, code
):
    with pytest.raises(ValidationError) as raised:
        flow_service.import_archive(
            _archive_with_envelope(tmp_path, envelope),
            org_id=default_org.id,
            user=regular_user,
            settings=ImportSettings(),
            main_entity=EntityType.GRAPH,
        )

    assert raised.value.detail["code"] == code


@pytest.mark.django_db
def test_import_archive_refuses_another_main_entity(
    flow_service, tmp_path, default_org, regular_user
):
    path = _archive_with_envelope(
        tmp_path, {MAIN_ENTITY_KEY: EntityType.PYTHON_CODE_TOOL, "version": IMPORT_VERSION}
    )

    with pytest.raises(ValidationError, match="Provided wrong entity"):
        flow_service.import_archive(
            path,
            org_id=default_org.id,
            user=regular_user,
            settings=ImportSettings(),
            main_entity=EntityType.GRAPH,
        )


def test_version_5_converts_to_6_unchanged():
    data = {
        MAIN_ENTITY_KEY: EntityType.GRAPH,
        "version": 5,
        EntityType.GRAPH: [{"id": 1, "name": "flow", "nodes": []}],
    }

    converted = VersionConverter.convert(json.loads(json.dumps(data)))

    assert converted == {**data, "version": 6}
    assert IMPORT_VERSION == 6


# --- inspecting --------------------------------------------------------------------------


@pytest.mark.django_db
def test_inspect_reads_the_envelope_of_a_zip_like_the_json_itself(flow_service, default_org):
    envelope = {
        MAIN_ENTITY_KEY: EntityType.GRAPH,
        "version": IMPORT_VERSION,
        EntityType.GRAPH: [
            {
                "id": 1,
                "name": "flow",
                "nodes": [
                    {
                        "id": 7,
                        "node_name": "code",
                        "node_type": "PythonNode",
                        "python_code": {"code": "x"},
                    }
                ],
            }
        ],
    }
    with ExportArchiveWriter() as writer:
        writer.write_envelope(envelope)
        writer.add_bytes("knowledge/documents/1", b"never read")
    try:
        with open(writer.path, "rb") as upload:
            from_zip = flow_service.inspect_entity(upload, org_id=default_org.id)
    finally:
        os.unlink(writer.path)

    from_json = flow_service.inspect_entity(
        io.BytesIO(json.dumps(envelope).encode()), org_id=default_org.id
    )
    assert from_zip == from_json
    assert [item["node_id"] for item in from_zip["review_items"]] == [7]


@pytest.mark.django_db
def test_inspect_refuses_an_unsafe_zip(flow_service, default_org):
    upload = io.BytesIO()
    with zipfile.ZipFile(upload, "w") as archive:
        archive.writestr(ENVELOPE_MEMBER, "{}")
        archive.writestr("../escape", "x")
    upload.seek(0)

    with pytest.raises(InvalidArchiveError):
        flow_service.inspect_entity(upload, org_id=default_org.id)


class _UploadWithoutSize(io.RawIOBase):
    """An upload whose size is only known by reading it."""

    def __init__(self, data: bytes):
        self._stream = io.BytesIO(data)

    def readable(self):
        return True

    def seekable(self):
        return True

    def readinto(self, buffer):
        chunk = self._stream.read(len(buffer))
        buffer[: len(chunk)] = chunk
        return len(chunk)

    def seek(self, offset, whence=0):
        return self._stream.seek(offset, whence)


def _small_zip_upload() -> bytes:
    upload = io.BytesIO()
    with zipfile.ZipFile(upload, "w") as archive:
        archive.writestr(
            ENVELOPE_MEMBER,
            json.dumps({MAIN_ENTITY_KEY: EntityType.GRAPH, "version": IMPORT_VERSION}),
        )
        archive.writestr("padding", bytes(2000))
    return upload.getvalue()


class _UnreadableSizedUpload(io.BytesIO):
    """An upload whose measured size is all that may be used: copying it fails."""

    def __init__(self, data: bytes, size: int):
        super().__init__(data)
        self._size = size
        self._head_read = False

    @property
    def size(self) -> int:
        return self._size

    def read(self, size=-1):
        # The first bytes tell a zip from JSON; anything after that is a copy.
        if self._head_read:
            raise AssertionError("an upload past the limit must not be copied")
        self._head_read = True
        return super().read(size)


@pytest.mark.django_db
def test_inspect_refuses_an_oversized_upload_before_copying_any_of_it(
    flow_service, default_org, settings
):
    data = _small_zip_upload()
    settings.MAX_KNOWLEDGE_ARCHIVE_SIZE = len(data)

    with pytest.raises(InvalidArchiveError):
        flow_service.inspect_entity(
            _UnreadableSizedUpload(data, size=len(data) + 1), org_id=default_org.id
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "make_upload",
    [
        pytest.param(lambda data: _SizedUpload(data), id="size known up front"),
        pytest.param(lambda data: io.BufferedReader(_UploadWithoutSize(data)), id="size unknown"),
    ],
)
def test_inspect_refuses_an_upload_past_the_archive_size_limit(
    flow_service, default_org, settings, make_upload
):
    data = _small_zip_upload()
    settings.MAX_KNOWLEDGE_ARCHIVE_SIZE = len(data) - 1

    with pytest.raises(InvalidArchiveError):
        flow_service.inspect_entity(make_upload(data), org_id=default_org.id)


@pytest.mark.django_db
def test_inspect_takes_an_upload_exactly_at_the_limit(flow_service, default_org, settings):
    data = _small_zip_upload()
    settings.MAX_KNOWLEDGE_ARCHIVE_SIZE = len(data)

    assert flow_service.inspect_entity(_SizedUpload(data), org_id=default_org.id) == {
        "review_items": []
    }


class _SizedUpload(io.BytesIO):
    """An upload Django already measured, like an UploadedFile."""

    @property
    def size(self) -> int:
        return len(self.getvalue())
