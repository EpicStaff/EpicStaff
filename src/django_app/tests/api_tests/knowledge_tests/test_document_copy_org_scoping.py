"""Document copy, download and bulk delete never cross an organization boundary."""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models import DocumentContent, DocumentMetadata, SourceCollection
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _document(collection) -> DocumentMetadata:
    return DocumentMetadata.objects.create(
        source_collection=collection,
        document_content=DocumentContent.objects.create(content=b"text"),
        file_name="notes.txt",
        file_type="txt",
        file_size=4,
    )


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def own_collection(acme):
    return SourceCollection.objects.create(collection_name="Own collection", org=acme)


@pytest.fixture
def foreign_collection(beta):
    return SourceCollection.objects.create(collection_name="Foreign collection", org=beta)


def _copy(client, collection, documents):
    return client.post(
        reverse("document-copy"),
        {
            "collection_id": collection.collection_id,
            "document_ids": [document.document_id for document in documents],
        },
        format="json",
    )


@pytest.mark.django_db
def test_copy_into_another_orgs_collection_is_404(
    admin_client, own_collection, foreign_collection
):
    response = _copy(admin_client, foreign_collection, [_document(own_collection)])

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert not foreign_collection.documents.exists()


@pytest.mark.django_db
def test_copy_of_another_orgs_documents_is_404(admin_client, own_collection, foreign_collection):
    response = _copy(admin_client, own_collection, [_document(foreign_collection)])

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert not own_collection.documents.exists()


@pytest.mark.django_db
def test_copy_mixing_own_and_foreign_documents_is_404_and_copies_nothing(
    admin_client, acme, own_collection, foreign_collection
):
    source = SourceCollection.objects.create(collection_name="Source", org=acme)

    response = _copy(
        admin_client, own_collection, [_document(source), _document(foreign_collection)]
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert not own_collection.documents.exists()


@pytest.mark.django_db
def test_copy_within_the_active_org_succeeds(admin_client, acme, own_collection):
    source = SourceCollection.objects.create(collection_name="Source", org=acme)

    response = _copy(admin_client, own_collection, [_document(source)])

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert own_collection.documents.count() == 1


def _download(client, documents):
    return client.get(
        reverse("document-download"),
        {"document_ids": ",".join(str(document.document_id) for document in documents)},
    )


@pytest.mark.django_db
def test_download_of_another_orgs_document_is_404(admin_client, foreign_collection):
    response = _download(admin_client, [_document(foreign_collection)])

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_download_mixing_own_and_foreign_documents_is_404(
    admin_client, own_collection, foreign_collection
):
    response = _download(admin_client, [_document(own_collection), _document(foreign_collection)])

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_download_names_no_missing_or_foreign_id(admin_client, foreign_collection):
    foreign_document = _document(foreign_collection)

    response = _download(admin_client, [foreign_document])

    assert str(foreign_document.document_id) not in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize("document_count", [1, 2], ids=["single-file", "archive"])
def test_download_of_own_documents_succeeds(admin_client, own_collection, document_count):
    documents = [_document(own_collection) for _ in range(document_count)]

    response = _download(admin_client, documents)

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_bulk_delete_of_only_foreign_documents_deletes_nothing_and_answers_empty(
    admin_client, foreign_collection
):
    foreign_document = _document(foreign_collection)

    response = admin_client.post(
        reverse("document-bulk-delete"),
        {"document_ids": [foreign_document.document_id]},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["deleted_documents"] == []
    assert DocumentMetadata.objects.filter(pk=foreign_document.pk).exists()


@pytest.mark.django_db
def test_bulk_delete_of_only_missing_documents_answers_like_foreign_ones(admin_client):
    response = admin_client.post(
        reverse("document-bulk-delete"), {"document_ids": [987654321]}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["deleted_documents"] == []
