"""Service-level tests for GraphVersionDeleteService.

GraphVersion is the one entity nothing references, so the interesting
properties are that it stays inside the family contract and that, as a
soft-delete root, it is removed row by row.
"""

import pytest
from django.contrib.contenttypes.models import ContentType

from tables.models import Graph, GraphVersion
from rbac.models import Organization, ResourceLastEdit
from tables.services.delete_services import GraphVersionDeleteService
from rbac.access.effective import EffectivePermissions


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _version(org, name="v1"):
    graph = Graph.objects.create(name="g", metadata={"nodes": [], "edges": []}, org=org)
    return GraphVersion.objects.create(graph=graph, name=name, snapshot={})


def _no_permissions():
    return EffectivePermissions(is_superadmin=False, role=None, by_resource={})


@pytest.mark.django_db
def test_response_carries_empty_skipped_and_usage_like_every_sibling(org_a):
    """Present and empty, never absent -- a client needs no special case."""
    version = _version(org_a)

    result = GraphVersionDeleteService(
        org_id=org_a.id, effective=_no_permissions(), user=None
    ).preview([version.id])

    assert result.skipped == []
    assert set(result.usage) == {version.id}
    assert result.usage[version.id].buckets == []
    assert result.usage[version.id].blocked is False
    assert result.is_partial is False


@pytest.mark.django_db
def test_bulk_delete_soft_deletes_the_version_without_recording_a_deleter(
    org_a, django_user_model
):
    """GraphVersion is a soft-delete root; a queryset delete would destroy it.

    It is not last-edit tracked and has no bin tab, so there is no deleter to
    record: it is soft-deleted directly even when a user is passed.
    """
    version = _version(org_a)
    user = django_user_model.objects.create_user(
        email="version-deleter@example.com", password="StrongPass123!"
    )

    result = GraphVersionDeleteService(
        org_id=org_a.id, effective=_no_permissions(), user=user
    ).delete([version.id])

    assert result.deleted_ids == [version.id]
    assert GraphVersion.all_objects.get(id=version.id).active is False
    assert not GraphVersion.objects.filter(id=version.id).exists()
    assert not ResourceLastEdit.objects.filter(
        content_type=ContentType.objects.get_for_model(GraphVersion),
        object_id=version.id,
    ).exists()


@pytest.mark.django_db
def test_another_orgs_version_is_not_found(org_a, org_b):
    """The org is reached through the parent graph; GraphVersion has no org column."""
    foreign = _version(org_b)

    result = GraphVersionDeleteService(
        org_id=org_a.id, effective=_no_permissions(), user=None
    ).delete([foreign.id])

    assert result.not_found_ids == [foreign.id]
    assert GraphVersion.objects.filter(id=foreign.id).exists()
