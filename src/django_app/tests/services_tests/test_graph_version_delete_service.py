"""Service-level tests for GraphVersionDeleteService.

GraphVersion is the one entity nothing references, so the interesting
properties are that it stays inside the family contract and that, as a
soft-delete root, it is removed row by row.
"""

import pytest
from django.test import override_settings

from tables.models import Graph, GraphVersion
from tables.models.rbac_models import Organization
from tables.services.delete_services import GraphVersionDeleteService
from tables.services.rbac.effective_permissions import EffectivePermissions


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

    result = GraphVersionDeleteService().bulk_delete(
        [version.id], org_a.id, _no_permissions(), dry_run=True
    )

    assert result.skipped == []
    assert set(result.usage) == {version.id}
    assert result.usage[version.id].buckets == []
    assert result.usage[version.id].blocked is False
    assert result.is_partial is False


@pytest.mark.django_db
@override_settings(SOFT_DELETE=True)
def test_bulk_delete_soft_deletes_when_soft_delete_is_enabled(org_a):
    """GraphVersion is a soft-delete root; a queryset delete would destroy it."""
    version = _version(org_a)

    result = GraphVersionDeleteService().bulk_delete(
        [version.id], org_a.id, _no_permissions()
    )

    assert result.deleted_ids == [version.id]
    row = GraphVersion.all_objects.get(id=version.id)
    assert row.is_soft_deleted is True


@pytest.mark.django_db
def test_another_orgs_version_is_not_found(org_a, org_b):
    """The org is reached through the parent graph; GraphVersion has no org column."""
    foreign = _version(org_b)

    result = GraphVersionDeleteService().bulk_delete(
        [foreign.id], org_a.id, _no_permissions()
    )

    assert result.not_found_ids == [foreign.id]
    assert GraphVersion.objects.filter(id=foreign.id).exists()
