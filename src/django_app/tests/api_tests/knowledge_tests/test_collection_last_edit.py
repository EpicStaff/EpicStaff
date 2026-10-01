"""Collection create, update and copy record the acting user as last editor."""

from datetime import UTC, datetime

import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from rbac.authorship import record_last_edit
from rbac.models import OrganizationUser, ResourceLastEdit
from tables.models.knowledge_models import SourceCollection
from tables.services.knowledge_services.collection_management_service import (
    CollectionManagementService,
)
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

PREVIOUS_EDIT_AT = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)


def _last_edit_of(collection) -> ResourceLastEdit | None:
    return ResourceLastEdit.objects.filter(
        content_type=ContentType.objects.get_for_model(SourceCollection),
        object_id=collection.pk,
    ).first()


def _client_in(client_as, user, org):
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def collection(acme, member_only):
    collection = SourceCollection.objects.create(
        collection_name="Edited collection", description="about", org=acme
    )
    record_last_edit(collection, member_only, edited_at=PREVIOUS_EDIT_AT)
    return collection


@pytest.mark.django_db
def test_create_records_creator(client_as, admin_acme, acme):
    create_started_at = timezone.now()

    response = _client_in(client_as, admin_acme, acme).post(
        reverse("sourcecollection-list"), {"collection_name": "Fresh"}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    last_edit = _last_edit_of(SourceCollection.objects.get(pk=response.data["collection_id"]))
    assert last_edit.edited_by_id == admin_acme.id
    assert last_edit.edited_at >= create_started_at
    assert response.data["last_edited_by"] == admin_acme.id


@pytest.mark.django_db
def test_patch_that_changes_the_collection_records_editor(client_as, admin_acme, acme, collection):
    response = _client_in(client_as, admin_acme, acme).patch(
        reverse("sourcecollection-detail", args=[collection.pk]),
        {"description": "new description"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    last_edit = _last_edit_of(collection)
    assert last_edit.edited_by_id == admin_acme.id
    assert last_edit.edited_at > PREVIOUS_EDIT_AT
    assert response.data["last_edited_by"] == admin_acme.id


@pytest.mark.django_db
def test_patch_that_changes_nothing_records_nothing(
    client_as, admin_acme, member_only, acme, collection
):
    response = _client_in(client_as, admin_acme, acme).patch(
        reverse("sourcecollection-detail", args=[collection.pk]),
        {"collection_name": "Edited collection", "description": "about"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    last_edit = _last_edit_of(collection)
    assert last_edit.edited_by_id == member_only.id
    assert last_edit.edited_at == PREVIOUS_EDIT_AT


@pytest.mark.django_db
def test_patch_from_other_org_is_404_and_records_nothing(
    client_as, django_user_model, role_org_admin, member_only, beta, collection
):
    outsider = django_user_model.objects.create_user(
        email="collection-outsider@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=outsider, org=beta, role=role_org_admin)

    response = _client_in(client_as, outsider, beta).patch(
        reverse("sourcecollection-detail", args=[collection.pk]),
        {"description": "hijack"},
        format="json",
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    last_edit = _last_edit_of(collection)
    assert last_edit.edited_by_id == member_only.id
    assert last_edit.edited_at == PREVIOUS_EDIT_AT


@pytest.mark.django_db
def test_copy_records_copier_on_the_copy_only(
    client_as, admin_acme, member_only, acme, collection
):
    response = _client_in(client_as, admin_acme, acme).post(
        reverse("sourcecollection-copy", args=[collection.pk]), {}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    copied = SourceCollection.objects.get(pk=response.data["collection"]["collection_id"])
    assert _last_edit_of(copied).edited_by_id == admin_acme.id
    assert response.data["collection"]["last_edited_by"] == admin_acme.id
    assert _last_edit_of(collection).edited_by_id == member_only.id


@pytest.mark.django_db
def test_service_calls_without_acting_user_record_nothing(acme, collection):
    created = CollectionManagementService.create_collection(collection_name="x", org_id=acme.id)
    copied = CollectionManagementService.copy_collection(collection.pk, org_id=acme.id)
    CollectionManagementService.update_collection(collection.pk, description="changed")

    assert _last_edit_of(created) is None
    assert _last_edit_of(copied) is None
    assert _last_edit_of(collection).edited_at == PREVIOUS_EDIT_AT
