"""Document and RAG-settings changes are edits of their collection; system writes are not."""

from datetime import UTC, datetime

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from rbac.authorship import record_last_edit
from rbac.models import OrganizationUser, ResourceLastEdit
from tables.models import DocumentContent, DocumentMetadata, SourceCollection
from tables.models.embedding_models import EmbeddingConfig, EmbeddingModel
from tables.models.knowledge_models import (
    BaseRagType,
    NaiveRag,
    NaiveRagDocumentConfig,
)
from tables.models.llm_models import LLMConfig, LLMModel
from tables.models.provider import Provider
from tables.services.knowledge_services.graph_rag_service import GraphRagService
from tables.services.knowledge_services.naive_rag_service import NaiveRagService
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

PREVIOUS_EDIT_AT = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
LAST_EDIT_UPSERT_PREFIX = 'INSERT INTO "rbac_resourcelastedit"'


def _last_edit_of(collection) -> ResourceLastEdit | None:
    return ResourceLastEdit.objects.filter(
        content_type=ContentType.objects.get_for_model(SourceCollection),
        object_id=collection.pk,
    ).first()


def _assert_edited_by(collection, user) -> None:
    last_edit = _last_edit_of(collection)
    assert last_edit is not None
    assert last_edit.edited_by_id == user.id
    assert last_edit.edited_at > PREVIOUS_EDIT_AT


def _assert_untouched(collection, editor) -> None:
    last_edit = _last_edit_of(collection)
    assert last_edit.edited_by_id == editor.id
    assert last_edit.edited_at == PREVIOUS_EDIT_AT


def _upserts(context) -> int:
    return sum(
        query["sql"].startswith(LAST_EDIT_UPSERT_PREFIX) for query in context.captured_queries
    )


def _client_in(client_as, user, org):
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


def _collection(org, editor, name="Edited collection") -> SourceCollection:
    collection = SourceCollection.objects.create(collection_name=name, org=org)
    record_last_edit(collection, editor, edited_at=PREVIOUS_EDIT_AT)
    return collection


def _document(collection, file_name="notes.txt") -> DocumentMetadata:
    return DocumentMetadata.objects.create(
        source_collection=collection,
        document_content=DocumentContent.objects.create(content=b"text"),
        file_name=file_name,
        file_type="txt",
        file_size=4,
    )


def _embedder(org, name="embedder", provider_name="embedding-provider") -> EmbeddingConfig:
    provider, _ = Provider.objects.get_or_create(name=provider_name)
    model, _ = EmbeddingModel.objects.get_or_create(
        name=f"{provider_name}-model", defaults={"embedding_provider": provider}
    )
    return EmbeddingConfig.objects.create(custom_name=name, model=model, org=org)


def _llm_config(org) -> LLMConfig:
    provider, _ = Provider.objects.get_or_create(name="llm-provider")
    model = LLMModel.objects.create(name="llm-model", llm_provider=provider)
    return LLMConfig.objects.create(custom_name="llm", model=model, org=org)


@pytest.fixture
def collection(acme, member_only):
    return _collection(acme, member_only)


@pytest.fixture
def foreign_collection(beta, member_only):
    return _collection(beta, member_only, name="Foreign collection")


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    return _client_in(client_as, admin_acme, acme)


@pytest.fixture
def naive_rag(collection, acme, member_only):
    rag = NaiveRag.objects.create(
        base_rag_type=BaseRagType.objects.create(
            source_collection=collection, rag_type=BaseRagType.RagType.NAIVE
        ),
        embedder=_embedder(acme),
    )
    record_last_edit(collection, member_only, edited_at=PREVIOUS_EDIT_AT)
    return rag


@pytest.fixture
def document_config(naive_rag, collection, member_only):
    config = NaiveRagDocumentConfig.objects.create(
        naive_rag=naive_rag,
        document=_document(collection),
        chunk_strategy="token",
        chunk_size=1000,
        chunk_overlap=150,
    )
    record_last_edit(collection, member_only, edited_at=PREVIOUS_EDIT_AT)
    return config


@pytest.fixture
def graph_rag(collection, acme, member_only):
    rag = GraphRagService.create_or_update_graph_rag(
        collection.collection_id, _embedder(acme).id, _llm_config(acme).id
    )
    record_last_edit(collection, member_only, edited_at=PREVIOUS_EDIT_AT)
    return rag


# ---- documents ----


@pytest.mark.django_db
def test_upload_of_several_documents_records_collection_in_one_statement(
    admin_client, admin_acme, collection
):
    files = [
        SimpleUploadedFile("first.txt", b"one", content_type="text/plain"),
        SimpleUploadedFile("second.txt", b"two", content_type="text/plain"),
    ]

    with CaptureQueriesContext(connection) as context:
        response = admin_client.post(
            reverse("document-upload", args=[collection.collection_id]),
            {"files": files},
            format="multipart",
        )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    _assert_edited_by(collection, admin_acme)
    assert _upserts(context) == 1


@pytest.mark.django_db
def test_delete_of_a_document_records_its_collection(admin_client, admin_acme, collection):
    document = _document(collection)

    response = admin_client.delete(reverse("document-detail", args=[document.document_id]))

    assert response.status_code == status.HTTP_200_OK, response.content
    _assert_edited_by(collection, admin_acme)


@pytest.mark.django_db
def test_bulk_delete_records_every_affected_collection_in_one_statement(
    admin_client, admin_acme, acme, member_only, collection
):
    other_collection = _collection(acme, member_only, name="Other collection")
    document_ids = [
        _document(collection).document_id,
        _document(other_collection).document_id,
    ]

    with CaptureQueriesContext(connection) as context:
        response = admin_client.post(
            "/api/documents/bulk-delete/", {"document_ids": document_ids}, format="json"
        )

    assert response.status_code == status.HTTP_200_OK, response.content
    _assert_edited_by(collection, admin_acme)
    _assert_edited_by(other_collection, admin_acme)
    assert _upserts(context) == 1


@pytest.mark.django_db
def test_copy_of_documents_records_the_target_collection_only(
    admin_client, admin_acme, acme, member_only, collection
):
    source = _collection(acme, member_only, name="Source collection")
    document = _document(source)

    response = admin_client.post(
        reverse("document-copy"),
        {"collection_id": collection.collection_id, "document_ids": [document.document_id]},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    _assert_edited_by(collection, admin_acme)
    _assert_untouched(source, member_only)


@pytest.mark.django_db
def test_copy_that_skips_every_document_records_nothing(
    admin_client, member_only, collection
):
    document = _document(collection)

    response = admin_client.post(
        reverse("document-copy"),
        {"collection_id": collection.collection_id, "document_ids": [document.document_id]},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert response.data["skipped"]
    _assert_untouched(collection, member_only)


@pytest.mark.django_db
def test_collection_status_update_records_nothing(member_only, collection):
    _document(collection)

    collection.update_collection_status()

    _assert_untouched(collection, member_only)


@pytest.mark.django_db
def test_cross_org_upload_is_404_and_records_nothing(
    admin_client, member_only, foreign_collection
):
    response = admin_client.post(
        reverse("document-upload", args=[foreign_collection.collection_id]),
        {"files": [SimpleUploadedFile("x.txt", b"x", content_type="text/plain")]},
        format="multipart",
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    _assert_untouched(foreign_collection, member_only)


@pytest.mark.django_db
def test_cross_org_document_delete_is_404_and_records_nothing(
    admin_client, member_only, foreign_collection
):
    document = _document(foreign_collection)

    response = admin_client.delete(reverse("document-detail", args=[document.document_id]))

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert DocumentMetadata.objects.filter(pk=document.pk).exists()
    _assert_untouched(foreign_collection, member_only)


# ---- naive RAG settings ----


@pytest.mark.django_db
def test_naive_rag_creation_records_collection(admin_client, admin_acme, acme, collection):
    embedder = _embedder(acme)

    response = admin_client.post(
        reverse("naive-rag-collection", args=[collection.collection_id]),
        {"embedder_id": embedder.id},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    _assert_edited_by(collection, admin_acme)


@pytest.mark.django_db
def test_naive_rag_embedder_change_records_collection(
    admin_client, admin_acme, acme, collection, naive_rag
):
    other_embedder = _embedder(acme, name="other embedder")

    response = admin_client.post(
        reverse("naive-rag-collection", args=[collection.collection_id]),
        {"embedder_id": other_embedder.id},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    _assert_edited_by(collection, admin_acme)


@pytest.mark.django_db
def test_naive_rag_resave_with_same_embedder_records_nothing(
    admin_client, member_only, collection, naive_rag
):
    response = admin_client.post(
        reverse("naive-rag-collection", args=[collection.collection_id]),
        {"embedder_id": naive_rag.embedder_id},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    _assert_untouched(collection, member_only)


@pytest.mark.django_db
def test_naive_rag_document_config_change_records_collection(
    admin_client, admin_acme, collection, naive_rag, document_config
):
    response = admin_client.put(
        reverse("document-config-detail", args=[naive_rag.pk, document_config.pk]),
        {"chunk_size": 1200},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    _assert_edited_by(collection, admin_acme)


@pytest.mark.django_db
def test_naive_rag_document_config_identical_save_records_nothing(
    admin_client, member_only, collection, naive_rag, document_config
):
    single = admin_client.put(
        reverse("document-config-detail", args=[naive_rag.pk, document_config.pk]),
        {"chunk_size": 1000, "chunk_overlap": 150},
        format="json",
    )
    bulk = admin_client.put(
        reverse("document-config-bulk-update", args=[naive_rag.pk]),
        [{"id": document_config.pk, "chunk_size": 1000}],
        format="json",
    )

    assert single.status_code == status.HTTP_200_OK, single.content
    assert bulk.status_code == status.HTTP_200_OK, bulk.content
    _assert_untouched(collection, member_only)


@pytest.mark.django_db
def test_naive_rag_document_config_bulk_change_records_collection(
    admin_client, admin_acme, collection, naive_rag, document_config
):
    response = admin_client.put(
        reverse("document-config-bulk-update", args=[naive_rag.pk]),
        [{"id": document_config.pk, "chunk_size": 1300}],
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    _assert_edited_by(collection, admin_acme)


@pytest.mark.django_db
def test_naive_rag_document_config_delete_records_collection(
    admin_client, admin_acme, collection, naive_rag, document_config
):
    response = admin_client.delete(
        reverse("document-config-detail", args=[naive_rag.pk, document_config.pk])
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    _assert_edited_by(collection, admin_acme)


@pytest.mark.django_db
def test_naive_rag_delete_records_collection(admin_client, admin_acme, collection, naive_rag):
    response = admin_client.delete(reverse("naive-rag-detail", args=[naive_rag.pk]))

    assert response.status_code == status.HTTP_200_OK, response.content
    _assert_edited_by(collection, admin_acme)


@pytest.mark.django_db
def test_naive_rag_created_by_system_writer_records_nothing(acme, member_only, collection):
    _document(collection)

    NaiveRagService.create_or_update_naive_rag(collection.collection_id, _embedder(acme).id)

    _assert_untouched(collection, member_only)


@pytest.mark.django_db
def test_cross_org_naive_rag_change_is_404_and_records_nothing(
    client_as, django_user_model, role_org_admin, beta, member_only, collection, naive_rag
):
    outsider = django_user_model.objects.create_user(
        email="rag-outsider@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=outsider, org=beta, role=role_org_admin)

    response = _client_in(client_as, outsider, beta).delete(
        reverse("naive-rag-detail", args=[naive_rag.pk])
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert NaiveRag.objects.filter(pk=naive_rag.pk).exists()
    _assert_untouched(collection, member_only)


# ---- graph RAG settings ----


@pytest.mark.django_db
def test_graph_rag_index_config_change_records_collection(
    admin_client, admin_acme, collection, graph_rag
):
    response = admin_client.put(
        reverse("graph-rag-index-config", args=[graph_rag.pk]),
        {"chunk_size": graph_rag.index_config.chunk_size + 100},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    _assert_edited_by(collection, admin_acme)


@pytest.mark.django_db
def test_graph_rag_identical_index_config_records_nothing(
    admin_client, member_only, collection, graph_rag
):
    response = admin_client.put(
        reverse("graph-rag-index-config", args=[graph_rag.pk]),
        {"chunk_size": graph_rag.index_config.chunk_size},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    _assert_untouched(collection, member_only)


@pytest.mark.django_db
def test_graph_rag_creation_and_model_change_record_collection_only_when_changed(
    acme, admin_acme, member_only, collection
):
    embedder = _embedder(acme)
    llm_config = _llm_config(acme)

    GraphRagService.create_or_update_graph_rag(
        collection.collection_id, embedder.id, llm_config.id, user=admin_acme
    )
    _assert_edited_by(collection, admin_acme)

    record_last_edit(collection, member_only, edited_at=PREVIOUS_EDIT_AT)
    GraphRagService.create_or_update_graph_rag(
        collection.collection_id, embedder.id, llm_config.id, user=admin_acme
    )
    _assert_untouched(collection, member_only)

    other_embedder = _embedder(acme, name="other embedder")
    GraphRagService.create_or_update_graph_rag(
        collection.collection_id, other_embedder.id, llm_config.id, user=admin_acme
    )
    _assert_edited_by(collection, admin_acme)


@pytest.mark.django_db
def test_graph_rag_document_removal_records_collection(
    admin_client, admin_acme, member_only, collection
):
    document = _document(collection)
    rag = GraphRagService.create_or_update_graph_rag(
        collection.collection_id,
        _embedder(collection.org).id,
        _llm_config(collection.org).id,
    )
    record_last_edit(collection, member_only, edited_at=PREVIOUS_EDIT_AT)

    response = admin_client.delete(
        reverse("graph-rag-document-delete", args=[rag.pk, document.document_id])
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    _assert_edited_by(collection, admin_acme)


@pytest.mark.django_db
def test_graph_rag_initialize_with_nothing_to_add_records_nothing(
    admin_client, member_only, collection, graph_rag
):
    response = admin_client.post(reverse("graph-rag-documents-initialize", args=[graph_rag.pk]))

    assert response.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED), response.content
    _assert_untouched(collection, member_only)


@pytest.mark.django_db
def test_graph_rag_initialize_adding_documents_records_collection(
    admin_client, admin_acme, collection, graph_rag
):
    _document(collection)

    response = admin_client.post(reverse("graph-rag-documents-initialize", args=[graph_rag.pk]))

    assert response.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED), response.content
    _assert_edited_by(collection, admin_acme)


@pytest.mark.django_db
def test_cross_org_graph_rag_index_config_change_is_404_and_records_nothing(
    client_as, django_user_model, role_org_admin, beta, member_only, collection, graph_rag
):
    outsider = django_user_model.objects.create_user(
        email="graph-outsider@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=outsider, org=beta, role=role_org_admin)

    response = _client_in(client_as, outsider, beta).put(
        reverse("graph-rag-index-config", args=[graph_rag.pk]),
        {"chunk_size": graph_rag.index_config.chunk_size + 100},
        format="json",
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    _assert_untouched(collection, member_only)


@pytest.mark.django_db
def test_graph_rag_delete_records_collection(
    admin_client, admin_acme, collection, graph_rag, mocker
):
    mocker.patch("tables.services.knowledge_services.graph_rag_service.KnowledgeClient")

    response = admin_client.delete(reverse("graph-rag-detail", args=[graph_rag.pk]))

    assert response.status_code == status.HTTP_200_OK, response.content
    _assert_edited_by(collection, admin_acme)


@pytest.mark.django_db
def test_graph_rag_document_bulk_removal_records_collection(
    admin_client, admin_acme, member_only, collection
):
    documents = [_document(collection, "a.txt"), _document(collection, "b.txt")]
    rag = GraphRagService.create_or_update_graph_rag(
        collection.collection_id,
        _embedder(collection.org).id,
        _llm_config(collection.org).id,
    )
    record_last_edit(collection, member_only, edited_at=PREVIOUS_EDIT_AT)

    response = admin_client.post(
        reverse("graph-rag-documents-bulk-delete", args=[rag.pk]),
        {"document_ids": [document.document_id for document in documents]},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    _assert_edited_by(collection, admin_acme)

