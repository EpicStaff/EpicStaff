"""Service-level tests for GraphDeleteService and the shared BaseDeleteService.

These exercise the algorithm directly rather than through the API, so the
shared rules -- scope, usage, skip, delete -- are pinned once, on the entity
with a soft-delete root. The HTTP wiring is covered in tests/api_tests/.
"""

from unittest import mock

import pytest
from django.db import connection
from django.db.models.deletion import ProtectedError
from django.test.utils import CaptureQueriesContext

from django.contrib.contenttypes.models import ContentType

from rbac.authorship import record_last_edit
from rbac.models import Organization, ResourceLastEdit
from tables.exceptions import CrossOrgCascadeError
from tables.models import Graph
from tables.models.graph_models import SubGraphNode
from tables.services.recycle_bin.deleting import move_to_recycle_bin
from rbac.models.enums import Permission, ResourceType
from tables.services.delete_services import GraphDeleteService
from tables.services.delete_services.usage import SkipEntry, SkipReason
from rbac.access.effective import EffectivePermissions


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
def test_bulk_delete_moves_graphs_to_the_recycle_bin(org_a):
    """The regression guard for the soft-delete root rule.

    `SoftDeleteMixin.delete()` is an override on the *instance*, so a
    `QuerySet.delete()` would bypass it and hard-delete the row. That is what
    `BaseDeleteService._delete_rows` branches to avoid, and this test is what
    stops the per-row loop being "simplified" away later.

    `Graph.objects` is an ActiveManager, so `assert not Graph.objects.filter(
    ...).exists()` passes under a hard delete too. Only `all_objects` can tell
    the two apart.
    """
    graph = _graph(org_a)

    result = GraphDeleteService(org_id=org_a.id, effective=_can_see_flows(), user=None).delete([graph.id])

    assert result.deleted_ids == [graph.id]
    assert not Graph.objects.filter(id=graph.id).exists()

    row = Graph.all_objects.get(id=graph.id)
    assert row.active is False
    assert row.soft_deleted_at is not None


def _last_edit_of(graph):
    return ResourceLastEdit.objects.filter(
        content_type=ContentType.objects.get_for_model(Graph), object_id=graph.pk
    ).first()


@pytest.fixture
def deleter(django_user_model):
    return django_user_model.objects.create_user(
        email="bulk-deleter@example.com", password="StrongPass123!"
    )


@pytest.mark.django_db
def test_bulk_delete_records_the_deleter_like_a_single_delete(org_a, deleter):
    """Same call as RecycleBinActionsMixin.perform_destroy: the deleter is the
    root's last edit, stamped at its `soft_deleted_at`."""
    bulk, single = _graph(org_a, "bulk"), _graph(org_a, "single")

    GraphDeleteService(
        org_id=org_a.id, effective=_can_see_flows(), user=deleter
    ).delete([bulk.id])
    move_to_recycle_bin(single, deleter)

    bulk_edit, single_edit = _last_edit_of(bulk), _last_edit_of(single)
    assert bulk_edit is not None
    assert bulk_edit.edited_by_id == single_edit.edited_by_id == deleter.pk
    assert bulk_edit.edited_at == Graph.all_objects.get(pk=bulk.pk).soft_deleted_at


@pytest.mark.django_db
def test_bulk_delete_replaces_an_earlier_editor_with_the_deleter(
    org_a, deleter, django_user_model
):
    earlier_editor = django_user_model.objects.create_user(
        email="earlier-editor@example.com", password="StrongPass123!"
    )
    graph = _graph(org_a)
    record_last_edit(graph, earlier_editor)

    GraphDeleteService(
        org_id=org_a.id, effective=_can_see_flows(), user=deleter
    ).delete([graph.id])

    assert _last_edit_of(graph).edited_by_id == deleter.pk


@pytest.mark.django_db
def test_bulk_delete_without_a_user_records_no_editor(org_a, django_user_model):
    """No person (None) records a NULL editor, never the previous one."""
    earlier_editor = django_user_model.objects.create_user(
        email="earlier-editor@example.com", password="StrongPass123!"
    )
    graph = _graph(org_a)
    record_last_edit(graph, earlier_editor)

    GraphDeleteService(org_id=org_a.id, effective=_can_see_flows(), user=None).delete([graph.id])

    assert _last_edit_of(graph).edited_by_id is None


@pytest.mark.django_db
def test_dry_run_records_no_deleter_and_deletes_nothing(org_a, deleter):
    graph = _graph(org_a)

    result = GraphDeleteService(
        org_id=org_a.id, effective=_can_see_flows(), user=deleter
    ).preview([graph.id])

    assert result.deletable_ids == [graph.id]
    assert Graph.objects.filter(id=graph.id).exists()
    assert _last_edit_of(graph) is None


@pytest.mark.django_db
def test_visible_usage_does_not_block(org_a):
    """Seeing the usage makes the deletion the caller's call to make."""
    child = _graph(org_a, "child")
    parent = _graph(org_a, "parent")
    node = SubGraphNode.objects.create(graph=parent, subgraph=child)

    result = GraphDeleteService(org_id=org_a.id, effective=_can_see_flows(), user=None).delete([child.id])

    assert result.deleted_ids == [child.id]
    assert result.skipped == []
    node.refresh_from_db()
    assert node.subgraph_id is None


@pytest.mark.django_db
def test_hidden_usage_blocks_without_disclosing_it(org_a):
    child = _graph(org_a, "child")
    parent = _graph(org_a, "parent")
    SubGraphNode.objects.create(graph=parent, subgraph=child)

    result = GraphDeleteService(org_id=org_a.id, effective=_cannot_see_flows(), user=None).delete([child.id])

    assert result.deleted_ids == []
    assert result.skipped == [
        SkipEntry(id=child.id, reason=SkipReason.IN_USE_RESTRICTED)
    ]
    assert Graph.objects.filter(id=child.id).exists()
    # Usage is the preview payload -- a real delete returns it empty.
    assert result.usage == {}

    preview = GraphDeleteService(
        org_id=org_a.id, effective=_cannot_see_flows(), user=None
    ).preview([child.id])
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

    result = GraphDeleteService(
        org_id=org_a.id, effective=_can_see_flows(), user=None
    ).preview([child.id])

    bucket = result.usage[child.id].buckets[0]
    assert bucket.visible_count == 1
    assert [ref.id for ref in bucket.visible_sample] == [parent.id]
    assert bucket.truncated is False


@pytest.mark.django_db
def test_dry_run_reports_what_would_go_and_deletes_nothing(org_a):
    """A preview must never report ids as deleted."""
    graph = _graph(org_a)

    result = GraphDeleteService(
        org_id=org_a.id, effective=_can_see_flows(), user=None
    ).preview([graph.id])

    assert result.dry_run is True
    assert result.deletable_ids == [graph.id]
    assert result.deleted_ids == []
    assert result.deleted_count == 0
    assert Graph.objects.filter(id=graph.id).exists()


@pytest.mark.django_db
def test_duplicate_ids_are_collapsed_everywhere(org_a):
    """A repeated id is deleted once and reported once."""
    graph = _graph(org_a)

    result = GraphDeleteService(
        org_id=org_a.id, effective=_can_see_flows(), user=None
    ).delete([graph.id, graph.id])

    assert result.deleted_ids == [graph.id]
    assert result.deleted_count == 1

    missing = GraphDeleteService(
        org_id=org_a.id, effective=_can_see_flows(), user=None
    ).delete([999_999, 999_999])
    assert missing.not_found_ids == [999_999]


@pytest.mark.django_db
def test_cross_org_and_unknown_ids_are_indistinguishable(org_a, org_b):
    """Both land in not_found_ids so existence is never leaked."""
    other = _graph(org_b, "other-org")

    result = GraphDeleteService(
        org_id=org_a.id, effective=_can_see_flows(), user=None
    ).delete([other.id, 999_999])

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

    result = GraphDeleteService(
        org_id=org_a.id, effective=_cannot_see_flows(), user=None
    ).preview([plain.id, child.id, 999_999])

    assert set(result.usage) == {plain.id, child.id}
    assert result.usage[plain.id].blocked is False
    assert result.usage[plain.id].buckets[0].visible_count == 0
    assert result.usage[child.id].blocked is True


@pytest.mark.django_db
def test_is_partial_reports_anything_the_caller_did_not_get(org_a):
    """The 200/207 rule, defined once and asserted here rather than per ViewSet."""
    graph = _graph(org_a)

    clean = GraphDeleteService(org_id=org_a.id, effective=_can_see_flows(), user=None).delete([graph.id])
    assert clean.is_partial is False

    missing = GraphDeleteService(org_id=org_a.id, effective=_can_see_flows(), user=None).delete([999_999])
    assert missing.is_partial is True


@pytest.mark.django_db
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
        result = GraphDeleteService(
            org_id=org_a.id, effective=_cannot_see_flows(), user=None
        ).delete([kept.id, refused.id, in_use.id])

    assert result.deleted_ids == [kept.id]
    assert result.skipped == [
        SkipEntry(id=in_use.id, reason=SkipReason.IN_USE_RESTRICTED),
        SkipEntry(id=refused.id, reason=SkipReason.PROTECTED),
    ]
    assert not Graph.objects.filter(id=kept.id).exists()
    assert Graph.objects.filter(id__in=[refused.id, in_use.id]).count() == 2
    # A refused row is not binned, so nothing is recorded for it.
    assert _last_edit_of(refused) is None


@pytest.mark.django_db
def test_another_orgs_flow_embedding_the_graph_is_not_usage(org_a, org_b):
    """Referencing rows are org-scoped too: a foreign parent neither leaks nor blocks.

    A cross-org SubGraphNode cannot be created through the API, but the delete
    guard must not depend on that: its own org filter is what keeps another
    org's flow name out of the sample.
    """
    child = _graph(org_a, "child")
    SubGraphNode.objects.create(graph=_graph(org_b, "foreign parent"), subgraph=child)

    preview = GraphDeleteService(
        org_id=org_a.id, effective=_can_see_flows(), user=None
    ).preview([child.id])
    assert preview.usage[child.id].buckets[0].total_count == 0


@pytest.mark.django_db
def test_a_delete_reaching_another_orgs_rows_fails_the_request(org_a, org_b):
    """CrossOrgCascadeError means a link no API path creates: it is a bug to
    surface (409), not a row to skip, and it rolls back the rows deleted before it."""
    fine = _graph(org_a, "fine")
    child = _graph(org_a, "child")
    foreign_node = SubGraphNode.objects.create(
        graph=_graph(org_b, "foreign parent"), subgraph=child
    )

    with pytest.raises(CrossOrgCascadeError):
        GraphDeleteService(
            org_id=org_a.id, effective=_cannot_see_flows(), user=None
        ).delete([fine.id, child.id])

    assert Graph.objects.filter(id__in=[fine.id, child.id]).count() == 2
    foreign_node.refresh_from_db()
    assert foreign_node.subgraph_id == child.id


@pytest.mark.django_db
def test_rows_are_locked_in_primary_key_order(org_a):
    """Two overlapping bulk deletes lock in the same order, so they cannot deadlock."""
    first, second = _graph(org_a, "first"), _graph(org_a, "second")

    with CaptureQueriesContext(connection) as queries:
        GraphDeleteService(
            org_id=org_a.id, effective=_can_see_flows(), user=None
        ).delete([second.id, first.id])

    # DeleteService also locks each row with .first(), which orders by itself, so
    # only the batch lock (the one over an IN list) proves the ordering.
    (batch_lock,) = [
        q["sql"]
        for q in queries.captured_queries
        if "FOR UPDATE" in q["sql"] and "IN (" in q["sql"]
    ]
    assert "ORDER BY" in batch_lock
