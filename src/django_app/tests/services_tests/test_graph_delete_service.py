"""Service-level tests for GraphDeleteService and the shared BaseDeleteService.

These exercise the algorithm directly rather than through the API, so the
shared rules -- scope, usage, skip, delete -- are pinned once, on the entity
with a soft-delete root. The HTTP wiring is covered in tests/api_tests/.
"""

from unittest import mock

import pytest
from django.db import connection
from django.db.models.deletion import ProtectedError
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from tables.models import Graph
from tables.models.graph_models import SubGraphNode
from tables.models.rbac_models import Organization
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.services.delete_services import GraphDeleteService
from tables.services.delete_services.usage import SkipEntry, SkipReason
from tables.services.rbac.effective_permissions import EffectivePermissions


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _graph(org, name="g"):
    return Graph.objects.create(name=name, metadata={"nodes": [], "edges": []}, org=org)


def _permissions(**by_resource):
    """EffectivePermissions with an exact mask per resource type.

    Built directly rather than through a Role so a service test does not depend
    on the built-in role seed.
    """
    return EffectivePermissions(
        is_superadmin=False,
        role=None,
        by_resource={
            resource_type: int(permission)
            for resource_type, permission in by_resource.items()
        },
    )


def _can_see_flows():
    return _permissions(**{ResourceType.FLOWS.value: Permission.READ})


def _cannot_see_flows():
    return _permissions()


@pytest.mark.django_db
@override_settings(SOFT_DELETE=True)
def test_bulk_delete_soft_deletes_when_soft_delete_is_enabled(org_a):
    """The regression guard for the soft-delete root rule.

    `SoftDeleteMixin.delete()` is an override on the *instance*, so a
    `QuerySet.delete()` would bypass it and hard-delete the row even with the
    flag on. That is what `BaseDeleteService._delete_rows` branches to avoid,
    and this test is what stops the per-row loop being "simplified" away later.

    `SOFT_DELETE` is overridden explicitly rather than relied on: the project
    default is `env.bool("DJANGO_SOFT_DELETE", False)`, i.e. OFF, so a test
    that assumed otherwise would silently assert nothing.

    `Graph.objects` is an ActiveManager, so `assert not Graph.objects.filter(
    ...).exists()` passes under a hard delete too. Only `all_objects` can tell
    the two apart.
    """
    graph = _graph(org_a)

    result = GraphDeleteService().bulk_delete([graph.id], org_a.id, _can_see_flows())

    assert result.deleted_ids == [graph.id]
    assert not Graph.objects.filter(id=graph.id).exists()

    row = Graph.all_objects.get(id=graph.id)
    assert row.is_soft_deleted is True
    assert row.soft_deleted_at is not None


@pytest.mark.django_db
@override_settings(SOFT_DELETE=False)
def test_bulk_delete_hard_deletes_when_soft_delete_is_disabled(org_a):
    """The project default. Row leaves the table entirely, `all_objects` included."""
    graph = _graph(org_a)

    GraphDeleteService().bulk_delete([graph.id], org_a.id, _can_see_flows())

    assert not Graph.all_objects.filter(id=graph.id).exists()


@pytest.mark.django_db
def test_visible_usage_does_not_block(org_a):
    """Seeing the usage makes the deletion the caller's call to make."""
    child = _graph(org_a, "child")
    parent = _graph(org_a, "parent")
    node = SubGraphNode.objects.create(graph=parent, subgraph=child)

    result = GraphDeleteService().bulk_delete([child.id], org_a.id, _can_see_flows())

    assert result.deleted_ids == [child.id]
    assert result.skipped == []
    node.refresh_from_db()
    assert node.subgraph_id is None


@pytest.mark.django_db
def test_hidden_usage_blocks_without_disclosing_it(org_a):
    child = _graph(org_a, "child")
    parent = _graph(org_a, "parent")
    SubGraphNode.objects.create(graph=parent, subgraph=child)

    result = GraphDeleteService().bulk_delete([child.id], org_a.id, _cannot_see_flows())

    assert result.deleted_ids == []
    assert result.skipped == [
        SkipEntry(id=child.id, reason=SkipReason.IN_USE_RESTRICTED)
    ]
    assert Graph.objects.filter(id=child.id).exists()
    # Usage is the preview payload -- a real delete returns it empty.
    assert result.usage == {}

    preview = GraphDeleteService().bulk_delete(
        [child.id], org_a.id, _cannot_see_flows(), dry_run=True
    )
    bucket = preview.usage[child.id].buckets[0]
    assert preview.usage[child.id].blocked is True
    assert bucket.visible_count == 0
    assert bucket.visible_sample == []


@pytest.mark.django_db
def test_one_flow_embedding_the_same_subgraph_twice_counts_once(org_a):
    """Two SubGraphNodes in one parent are one reference, not two."""
    child = _graph(org_a, "child")
    parent = _graph(org_a, "parent")
    SubGraphNode.objects.create(graph=parent, subgraph=child)
    SubGraphNode.objects.create(graph=parent, subgraph=child)

    result = GraphDeleteService().bulk_delete(
        [child.id], org_a.id, _can_see_flows(), dry_run=True
    )

    bucket = result.usage[child.id].buckets[0]
    assert bucket.visible_count == 1
    assert [ref.id for ref in bucket.visible_sample] == [parent.id]
    assert bucket.truncated is False


@pytest.mark.django_db
def test_dry_run_reports_what_would_go_and_deletes_nothing(org_a):
    """A preview must never report ids as deleted."""
    graph = _graph(org_a)

    result = GraphDeleteService().bulk_delete(
        [graph.id], org_a.id, _can_see_flows(), dry_run=True
    )

    assert result.dry_run is True
    assert result.deletable_ids == [graph.id]
    assert result.deleted_ids == []
    assert result.deleted_count == 0
    assert Graph.objects.filter(id=graph.id).exists()


@pytest.mark.django_db
def test_duplicate_ids_are_collapsed_everywhere(org_a):
    """A repeated id is deleted once and reported once."""
    graph = _graph(org_a)

    result = GraphDeleteService().bulk_delete(
        [graph.id, graph.id], org_a.id, _can_see_flows()
    )

    assert result.deleted_ids == [graph.id]
    assert result.deleted_count == 1

    missing = GraphDeleteService().bulk_delete(
        [999_999, 999_999], org_a.id, _can_see_flows()
    )
    assert missing.not_found_ids == [999_999]


@pytest.mark.django_db
def test_cross_org_and_unknown_ids_are_indistinguishable(org_a, org_b):
    """Both land in not_found_ids so existence is never leaked."""
    other = _graph(org_b, "other-org")

    result = GraphDeleteService().bulk_delete(
        [other.id, 999_999], org_a.id, _can_see_flows()
    )

    assert sorted(result.not_found_ids) == sorted([other.id, 999_999])
    assert result.deleted_ids == []
    assert Graph.objects.filter(id=other.id).exists()


@pytest.mark.django_db
def test_usage_covers_every_found_id(org_a):
    """The response shape does not vary between rows."""
    plain = _graph(org_a, "plain")
    child = _graph(org_a, "child")
    parent = _graph(org_a, "parent")
    SubGraphNode.objects.create(graph=parent, subgraph=child)

    result = GraphDeleteService().bulk_delete(
        [plain.id, child.id, 999_999], org_a.id, _cannot_see_flows(), dry_run=True
    )

    assert set(result.usage) == {plain.id, child.id}
    assert result.usage[plain.id].blocked is False
    assert result.usage[plain.id].buckets[0].visible_count == 0
    assert result.usage[child.id].blocked is True


@pytest.mark.django_db
def test_is_partial_reports_anything_the_caller_did_not_get(org_a):
    """The 200/207 rule, defined once and asserted here rather than per ViewSet."""
    graph = _graph(org_a)

    clean = GraphDeleteService().bulk_delete([graph.id], org_a.id, _can_see_flows())
    assert clean.is_partial is False

    missing = GraphDeleteService().bulk_delete([999_999], org_a.id, _can_see_flows())
    assert missing.is_partial is True


@pytest.mark.django_db
@override_settings(SOFT_DELETE=False)
def test_a_row_refused_at_delete_time_costs_that_row_not_the_batch(org_a):
    """The savepoint path: one refused row is skipped, the rest still go.

    No FK in the schema uses PROTECT or RESTRICT today, so the refusal is
    simulated -- *after* the row's own delete has run, so the refused row
    survives only if its savepoint really rolls back. The refusal is reported
    after the usage skips, which are decided before any row is touched.
    """
    kept = _graph(org_a, "kept")
    refused = _graph(org_a, "refused")
    in_use = _graph(org_a, "in-use")
    SubGraphNode.objects.create(graph=_graph(org_a, "parent"), subgraph=in_use)
    real_delete = Graph.delete

    def delete_then_refuse(self, *args, **kwargs):
        pk = self.pk
        outcome = real_delete(self, *args, **kwargs)
        if pk == refused.id:
            raise ProtectedError("refused", set())
        return outcome

    with mock.patch.object(Graph, "delete", delete_then_refuse):
        result = GraphDeleteService().bulk_delete(
            [kept.id, refused.id, in_use.id], org_a.id, _cannot_see_flows()
        )

    assert result.deleted_ids == [kept.id]
    assert result.skipped == [
        SkipEntry(id=in_use.id, reason=SkipReason.IN_USE_RESTRICTED),
        SkipEntry(id=refused.id, reason=SkipReason.PROTECTED),
    ]
    assert not Graph.all_objects.filter(id=kept.id).exists()
    assert Graph.objects.filter(id__in=[refused.id, in_use.id]).count() == 2


@pytest.mark.django_db
def test_another_orgs_flow_embedding_the_graph_is_not_usage(org_a, org_b):
    """Referencing rows are org-scoped too: a foreign parent neither leaks nor blocks.

    A cross-org SubGraphNode cannot be created through the API, but the delete
    guard must not depend on that: its own org filter is what keeps another
    org's flow name out of the sample.
    """
    child = _graph(org_a, "child")
    SubGraphNode.objects.create(graph=_graph(org_b, "foreign parent"), subgraph=child)

    preview = GraphDeleteService().bulk_delete(
        [child.id], org_a.id, _can_see_flows(), dry_run=True
    )
    assert preview.usage[child.id].buckets[0].total_count == 0

    result = GraphDeleteService().bulk_delete([child.id], org_a.id, _cannot_see_flows())
    assert result.deleted_ids == [child.id]


@pytest.mark.django_db
def test_rows_are_locked_in_primary_key_order(org_a):
    """Two overlapping bulk deletes lock in the same order, so they cannot deadlock."""
    first, second = _graph(org_a, "first"), _graph(org_a, "second")

    with CaptureQueriesContext(connection) as queries:
        GraphDeleteService().bulk_delete(
            [second.id, first.id], org_a.id, _can_see_flows()
        )

    (locking,) = [
        q["sql"] for q in queries.captured_queries if "FOR UPDATE" in q["sql"]
    ]
    assert "ORDER BY" in locking
