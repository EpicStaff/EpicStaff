"""Document download and copy resolve every id inside the caller's organization.

Both actions take document and collection ids straight from the request. A
document or collection in another organization must be indistinguishable from a
missing one: the whole request 404s, no content is returned and no row is written.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models import DocumentContent, DocumentMetadata, SourceCollection
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

ACME_CONTENT = b"acme document"
BETA_CONTENT = b"beta confidential document"


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


def _create_document(org, content, name):
    collection = SourceCollection.objects.create(collection_name=f"{name}-source", org=org)
    return DocumentMetadata.objects.create(
        source_collection=collection,
        document_content=DocumentContent.objects.create(content=content),
        file_name=f"{name}.txt",
        file_type="txt",
        file_size=len(content),
    )


@pytest.fixture
def acme_document(acme):
    return _create_document(acme, ACME_CONTENT, "acme")


@pytest.fixture
def beta_document(beta):
    return _create_document(beta, BETA_CONTENT, "beta")


@pytest.fixture
def acme_target_collection(acme):
    return SourceCollection.objects.create(collection_name="acme-target", org=acme)


def _download(client, *documents):
    document_ids = ",".join(str(document.document_id) for document in documents)
    return client.get(reverse("document-download"), {"document_ids": document_ids})


def _copy(client, collection, *documents):
    return client.post(
        reverse("document-copy"),
        {
            "collection_id": collection.collection_id,
            "document_ids": [document.document_id for document in documents],
        },
        format="json",
    )


# ---- download ----------------------------------------------------------------


@pytest.mark.django_db
def test_download_own_document_returns_its_content(acme_admin_client, acme_document):
    response = _download(acme_admin_client, acme_document)

    assert response.status_code == status.HTTP_200_OK
    assert response.content == ACME_CONTENT


@pytest.mark.django_db
def test_download_another_org_document_is_404(acme_admin_client, beta_document):
    response = _download(acme_admin_client, beta_document)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert BETA_CONTENT not in response.content


@pytest.mark.django_db
def test_download_mixing_own_and_another_org_document_is_404(
    acme_admin_client, acme_document, beta_document
):
    response = _download(acme_admin_client, acme_document, beta_document)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.get("Content-Type") != "application/zip"


@pytest.mark.django_db
def test_download_denied_without_export_permission(acme_member_client, acme_document):
    response = _download(acme_member_client, acme_document)

    assert response.status_code == status.HTTP_403_FORBIDDEN


# ---- copy --------------------------------------------------------------------


@pytest.mark.django_db
def test_copy_own_document_into_own_collection(
    acme_admin_client, acme_document, acme_target_collection
):
    response = _copy(acme_admin_client, acme_target_collection, acme_document)

    assert response.status_code == status.HTTP_201_CREATED, response.data
    copied = DocumentMetadata.objects.get(source_collection=acme_target_collection)
    assert copied.document_content_id == acme_document.document_content_id


@pytest.mark.django_db
def test_copy_another_org_document_into_own_collection_is_404(
    acme_admin_client, beta_document, acme_target_collection
):
    response = _copy(acme_admin_client, acme_target_collection, beta_document)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert not DocumentMetadata.objects.filter(
        source_collection=acme_target_collection
    ).exists()


@pytest.mark.django_db
def test_copy_own_document_into_another_org_collection_is_404(
    acme_admin_client, acme_document, beta_document
):
    beta_collection = beta_document.source_collection

    response = _copy(acme_admin_client, beta_collection, acme_document)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert list(
        DocumentMetadata.objects.filter(source_collection=beta_collection)
    ) == [beta_document]


@pytest.mark.django_db
def test_copy_denied_without_create_permission(
    acme_member_client, acme_document, acme_target_collection
):
    response = _copy(acme_member_client, acme_target_collection, acme_document)

    assert response.status_code == status.HTTP_403_FORBIDDEN
