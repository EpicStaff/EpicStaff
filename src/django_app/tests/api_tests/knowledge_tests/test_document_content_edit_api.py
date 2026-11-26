"""PUT /documents/{id}/content/ and the document detail fields the editor relies on.

The new text travels as a multipart file, so texts past Django's 2.5 MB limit on
non-file request data still reach the service and its upload limit.
"""

import hashlib

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from tables.models import DocumentMetadata, SourceCollection
from tables.models.knowledge_models import BaseRagType, NaiveRag, NaiveRagDocumentConfig
from tests.knowledge_content import stored_document_content
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

OLD_TEXT = b"old text"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def acme_admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def acme_member_client(client_as, member_only, acme):
    client = client_as(member_only)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def acme_viewer_client(client_as, viewer_only, acme):
    client = client_as(viewer_only)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _document(org, collection_name, content=None):
    collection = SourceCollection.objects.create(collection_name=collection_name, org=org)
    return DocumentMetadata.objects.create(
        source_collection=collection,
        document_content=content or stored_document_content(OLD_TEXT, org_id=org.id),
        file_name="notes.txt",
        file_type="txt",
        file_size=len(OLD_TEXT),
    )


@pytest.fixture
def acme_document(acme):
    return _document(acme, "acme-notes")


def _put_content(client, document, data, content_hash=None, scope=None):
    body = {
        "file": SimpleUploadedFile(document.file_name, data, content_type="text/plain"),
        "content_hash": content_hash or _sha256(OLD_TEXT),
    }
    if scope:
        body["scope"] = scope
    return client.put(
        reverse("document-content", args=[document.document_id]), body, format="multipart"
    )


@pytest.mark.django_db
def test_put_content_returns_the_new_hash(acme_admin_client, acme_document, knowledge_bucket):
    response = _put_content(acme_admin_client, acme_document, b"new text")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["content_hash"] == _sha256(b"new text")
    assert response.data["file_size"] == len(b"new text")


@pytest.mark.django_db
def test_three_megabyte_text_is_saved(acme_admin_client, acme_document):
    large_text = b"a" * (3 * 1024 * 1024)

    response = _put_content(acme_admin_client, acme_document, large_text)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["content_hash"] == _sha256(large_text)


@pytest.mark.django_db
def test_member_without_update_gets_403(acme_member_client, acme_document):
    response = _put_content(acme_member_client, acme_document, b"new text")

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_document_of_another_org_is_404(acme_admin_client, beta):
    beta_document = _document(beta, "beta-notes")

    response = _put_content(acme_admin_client, beta_document, b"new text")

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_stale_hash_is_409_with_code(acme_admin_client, acme_document):
    response = _put_content(
        acme_admin_client, acme_document, b"new text", content_hash=_sha256(b"other")
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["code"] == "content_hash_conflict"


@pytest.mark.django_db
def test_malformed_content_hash_is_400(acme_admin_client, acme_document):
    response = _put_content(acme_admin_client, acme_document, b"new text", content_hash="abc")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_retrieve_lists_shared_collections(acme_admin_client, acme, acme_document):
    copy = _document(acme, "acme-copies", content=acme_document.document_content)

    response = acme_admin_client.get(reverse("document-detail", args=[acme_document.document_id]))

    assert response.status_code == status.HTTP_200_OK
    assert response.data["content_hash"] == _sha256(OLD_TEXT)
    assert response.data["shared_with_collections"] == [
        {"collection_id": copy.source_collection_id, "collection_name": "acme-copies"}
    ]


@pytest.mark.django_db
def test_retrieve_leaves_out_copies_in_the_recycle_bin(acme_admin_client, acme, acme_document):
    binned_copy = _document(acme, "acme-binned-copy", content=acme_document.document_content)
    DocumentMetadata.all_objects.filter(pk=binned_copy.pk).update(
        active=False, soft_deleted_at=timezone.now()
    )
    copy_in_binned_collection = _document(
        acme, "acme-binned-collection", content=acme_document.document_content
    )
    SourceCollection.all_objects.filter(pk=copy_in_binned_collection.source_collection_id).update(
        active=False, soft_deleted_at=timezone.now()
    )

    response = acme_admin_client.get(reverse("document-detail", args=[acme_document.document_id]))

    assert response.data["shared_with_collections"] == []


@pytest.mark.django_db
def test_retrieve_without_copies_lists_nothing(acme_admin_client, acme_document):
    response = acme_admin_client.get(reverse("document-detail", args=[acme_document.document_id]))

    assert response.data["shared_with_collections"] == []


@pytest.mark.django_db
def test_get_content_returns_the_text_and_its_hash(acme_admin_client, acme_document):
    response = acme_admin_client.get(reverse("document-content", args=[acme_document.document_id]))

    assert response.status_code == status.HTTP_200_OK
    assert response.data["text"] == OLD_TEXT.decode()
    assert response.data["content_hash"] == _sha256(OLD_TEXT)


@pytest.mark.django_db
def test_viewer_reads_the_text_but_cannot_replace_it(acme_viewer_client, acme_document):
    """Reading the text needs READ, like the preview; replacing it needs UPDATE."""
    read = acme_viewer_client.get(reverse("document-content", args=[acme_document.document_id]))
    replace = _put_content(acme_viewer_client, acme_document, b"new text")

    assert read.status_code == status.HTTP_200_OK
    assert replace.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_not_editable_type_is_400(acme_admin_client, acme_document):
    DocumentMetadata.objects.filter(pk=acme_document.pk).update(file_name="a.pdf", file_type="pdf")

    response = _put_content(acme_admin_client, acme_document, b"new text")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "document_not_editable"


@pytest.mark.django_db
def test_missing_file_is_404(acme_admin_client, acme_document, knowledge_bucket):
    knowledge_bucket.files.pop(acme_document.document_content.object_key)

    response = _put_content(acme_admin_client, acme_document, b"new text")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["code"] == "document_content_missing"


@pytest.mark.django_db
def test_indexing_document_is_409_with_code(acme_admin_client, acme_document):
    base = BaseRagType.objects.create(
        source_collection=acme_document.source_collection, rag_type=BaseRagType.RagType.NAIVE
    )
    rag = NaiveRag.objects.create(base_rag_type=base)
    config, _ = NaiveRagDocumentConfig.objects.get_or_create(
        naive_rag=rag,
        document=acme_document,
        defaults={"chunk_strategy": "token", "chunk_size": 1000, "chunk_overlap": 150},
    )
    config.status = NaiveRagDocumentConfig.NaiveRagDocumentStatus.PROCESSING
    config.save(update_fields=["status"])

    response = _put_content(acme_admin_client, acme_document, b"new text")

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["code"] == "document_indexing_in_progress"


@pytest.mark.django_db
def test_scope_all_collections_reaches_the_copy(acme_admin_client, acme, acme_document):
    copy = _document(acme, "acme-copies", content=acme_document.document_content)

    response = _put_content(
        acme_admin_client, acme_document, b"new text", scope="all_collections"
    )

    copy.refresh_from_db()
    assert response.status_code == status.HTTP_200_OK
    assert copy.document_content.content_hash == _sha256(b"new text")


@pytest.mark.django_db
def test_default_scope_leaves_the_copy_alone(acme_admin_client, acme, acme_document):
    copy = _document(acme, "acme-copies", content=acme_document.document_content)

    _put_content(acme_admin_client, acme_document, b"new text")

    copy.refresh_from_db()
    assert copy.document_content.content_hash == _sha256(OLD_TEXT)

