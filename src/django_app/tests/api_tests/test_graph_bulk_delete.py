"""API tests for GraphViewSet bulk delete, through BulkDeleteActionMixin.

Covers the shared response contract (deleted_ids / deletable_ids /
not_found_ids / skipped / usage), `?dry_run=` as a query parameter, and the
permission-aware `in_use_restricted` guard — a Graph embedded as a subgraph
elsewhere is only deletable if the requester can see the Flow that embeds it.
The guard applies identically to bulk_delete and single destroy.
"""

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tables.models import Graph
from tables.models.graph_models import SubGraphNode
from rbac.models import (
    Organization,
    ResourceLastEdit,
)
from rbac.models.enums import Permission, ResourceType
from tests.api_tests.bulk_delete_helpers import custom_role_client, org_admin_client


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _graph(org, name="g"):
    return Graph.objects.create(name=name, metadata={"nodes": [], "edges": []}, org=org)


@pytest.mark.django_db
def test_bulk_delete_happy_path(django_user_model, org_a):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    g1, g2 = _graph(org_a, "g1"), _graph(org_a, "g2")

    resp = client.post(
        "/api/graphs/bulk-delete/", {"ids": [g1.id, g2.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_count"] == 2
    assert sorted(resp.data["deleted_ids"]) == sorted([g1.id, g2.id])
    assert resp.data["not_found_ids"] == []
    assert resp.data["skipped"] == []
    assert not Graph.objects.filter(id__in=[g1.id, g2.id]).exists()


@pytest.mark.django_db
def test_bulk_delete_cross_org_id_not_found(django_user_model, org_a, org_b):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    other = _graph(org_b, "other")

    resp = client.post("/api/graphs/bulk-delete/", {"ids": [other.id]}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["not_found_ids"] == [other.id]
    assert resp.data["deleted_ids"] == []
    assert Graph.objects.filter(id=other.id).exists()


@pytest.mark.django_db
def test_bulk_delete_nonexistent_id_not_found(django_user_model, org_a):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")

    resp = client.post("/api/graphs/bulk-delete/", {"ids": [999999]}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["not_found_ids"] == [999999]


@pytest.mark.django_db
def test_bulk_delete_duplicate_ids_deleted_once(django_user_model, org_a):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    g = _graph(org_a, "g")

    resp = client.post("/api/graphs/bulk-delete/", {"ids": [g.id, g.id]}, format="json")

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_count"] == 1
    assert resp.data["deleted_ids"] == [g.id]


@pytest.mark.django_db
def test_bulk_delete_empty_ids_rejected(django_user_model, org_a):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")

    resp = client.post("/api/graphs/bulk-delete/", {"ids": []}, format="json")

    assert resp.status_code == 400


@pytest.mark.django_db
def test_bulk_delete_without_delete_permission_forbidden(django_user_model, org_a):
    # READ-only on FLOWS: can list/retrieve graphs but not delete them.
    client = custom_role_client(
        django_user_model,
        org_a,
        "viewer@example.com",
        **{ResourceType.FLOWS: Permission.READ},
    )
    g = _graph(org_a, "g")

    resp = client.post("/api/graphs/bulk-delete/", {"ids": [g.id]}, format="json")

    assert resp.status_code == 403
    assert Graph.objects.filter(id=g.id).exists()


@pytest.mark.django_db
def test_bulk_delete_subgraph_usage_visible_proceeds(django_user_model, org_a):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    parent = _graph(org_a, "parent")
    child = _graph(org_a, "child")
    node = SubGraphNode.objects.create(graph=parent, subgraph=child)

    resp = client.post("/api/graphs/bulk-delete/", {"ids": [child.id]}, format="json")

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_ids"] == [child.id]
    assert not Graph.objects.filter(id=child.id).exists()
    node.refresh_from_db()
    assert node.subgraph_id is None
    # Usage is the preview payload: a real delete returns it empty, key
    # present. The visible-usage report is covered by the dry-run test below.
    assert resp.data["usage"] == {}


@pytest.mark.django_db
def test_bulk_delete_subgraph_usage_hidden_blocked(django_user_model, org_a):
    # DELETE on FLOWS, but no READ: can call the action but cannot see the
    # parent Flow that embeds this graph as a subgraph.
    client = custom_role_client(
        django_user_model,
        org_a,
        "deleter@example.com",
        **{ResourceType.FLOWS: Permission.DELETE},
    )
    parent = _graph(org_a, "parent")
    child = _graph(org_a, "child")
    SubGraphNode.objects.create(graph=parent, subgraph=child)

    resp = client.post("/api/graphs/bulk-delete/", {"ids": [child.id]}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["skipped"] == [{"id": child.id, "reason": "in_use_restricted"}]
    assert resp.data["deleted_ids"] == []
    assert Graph.objects.filter(id=child.id).exists()
    # The non-disclosure of the hidden usage is covered by the dry-run test
    # below; a real delete returns usage empty.
    assert resp.data["usage"] == {}


@pytest.mark.django_db
def test_bulk_delete_dry_run_does_not_delete(django_user_model, org_a):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    g = _graph(org_a, "g")

    resp = client.post(
        "/api/graphs/bulk-delete/?dry_run=true", {"ids": [g.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["dry_run"] is True
    # A preview never reports anything as deleted; what would go is deletable.
    assert resp.data["deleted_ids"] == []
    assert resp.data["deleted_count"] == 0
    assert resp.data["deletable_ids"] == [g.id]
    assert Graph.objects.filter(id=g.id).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("value", ["notabool", "maybe"])
def test_bulk_delete_dry_run_that_is_not_a_boolean_is_rejected(
    django_user_model, org_a, value
):
    """A value that is not a boolean is a 400, never a delete.

    A typo must never be read as False and executed.
    """
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    graph = _graph(org_a, "graph")

    resp = client.post(
        f"/api/graphs/bulk-delete/?dry_run={value}", {"ids": [graph.id]}, format="json"
    )

    assert resp.status_code == 400, resp.data
    assert Graph.objects.filter(id=graph.id).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("value", "deleted"),
    [("TRUE", False), ("false", True)],
    ids=["true-in-any-case-previews", "explicit-false-deletes"],
)
def test_bulk_delete_dry_run_reads_true_and_false(
    django_user_model, org_a, value, deleted
):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    graph = _graph(org_a, "graph")

    resp = client.post(
        f"/api/graphs/bulk-delete/?dry_run={value}", {"ids": [graph.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["dry_run"] is not deleted
    assert Graph.objects.filter(id=graph.id).exists() is not deleted


@pytest.mark.django_db
def test_bulk_delete_accepts_exactly_500_ids(django_user_model, org_a):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    ids = list(range(1_000_001, 1_000_501))

    resp = client.post("/api/graphs/bulk-delete/", {"ids": ids}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["not_found_ids"] == ids


@pytest.mark.django_db
def test_bulk_delete_rejects_501_ids(django_user_model, org_a):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    g = _graph(org_a, "g")
    ids = [g.id, *range(1_000_001, 1_000_501)]

    resp = client.post("/api/graphs/bulk-delete/", {"ids": ids}, format="json")

    assert resp.status_code == 400, resp.data
    assert Graph.objects.filter(id=g.id).exists()


@pytest.mark.django_db
def test_bulk_delete_oversized_list_is_rejected_before_its_items(
    django_user_model, org_a
):
    """The cap is checked first: an oversized list costs one error, not one per item."""
    client = org_admin_client(django_user_model, org_a, "admin@example.com")

    resp = client.post(
        "/api/graphs/bulk-delete/", {"ids": ["junk"] * 501}, format="json"
    )

    assert resp.status_code == 400, resp.data
    assert "500" in resp.data["message"]
    assert "valid integer" not in resp.data["message"]


@pytest.mark.django_db
def test_bulk_delete_dry_run_shows_visible_usage(django_user_model, org_a):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    parent = _graph(org_a, "parent")
    child = _graph(org_a, "child")
    SubGraphNode.objects.create(graph=parent, subgraph=child)

    resp = client.post(
        "/api/graphs/bulk-delete/?dry_run=true", {"ids": [child.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["deletable_ids"] == [child.id]
    assert resp.data["deleted_ids"] == []
    assert Graph.objects.filter(id=child.id).exists()  # dry_run: nothing removed
    usage = resp.data["usage"][str(child.id)]
    assert usage["blocked"] is False
    flows_usage = usage["by_resource_type"][0]
    assert flows_usage["resource_type"] == "flows"
    assert flows_usage["visible_count"] == 1
    assert flows_usage["visible_sample"] == [
        {"resource_type": "flows", "id": parent.id, "name": parent.name}
    ]


@pytest.mark.django_db
def test_bulk_delete_dry_run_still_blocks_hidden_usage(django_user_model, org_a):
    # dry_run doesn't relax the in_use_restricted guard — it only skips the
    # actual delete for ids that would otherwise be allowed through.
    client = custom_role_client(
        django_user_model,
        org_a,
        "deleter3@example.com",
        **{ResourceType.FLOWS: Permission.DELETE},
    )
    parent = _graph(org_a, "parent")
    child = _graph(org_a, "child")
    SubGraphNode.objects.create(graph=parent, subgraph=child)

    resp = client.post(
        "/api/graphs/bulk-delete/?dry_run=true", {"ids": [child.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["skipped"] == [{"id": child.id, "reason": "in_use_restricted"}]
    assert resp.data["deleted_ids"] == []
    assert resp.data["deletable_ids"] == []
    assert Graph.objects.filter(id=child.id).exists()
    # Blocked ids still get a usage entry, but visibility is binary per org:
    # a caller without FLOWS:READ learns nothing about what is hiding.
    usage = resp.data["usage"][str(child.id)]
    assert usage["blocked"] is True
    flows_usage = usage["by_resource_type"][0]
    assert flows_usage["visible_count"] == 0
    assert flows_usage["visible_sample"] == []


@pytest.mark.django_db
def test_single_destroy_subgraph_usage_hidden_blocked(django_user_model, org_a):
    # Same guard, single-object destroy path — parity with bulk_delete so the
    # block can't be bypassed by deleting one-by-one.
    client = custom_role_client(
        django_user_model,
        org_a,
        "deleter2@example.com",
        **{ResourceType.FLOWS: Permission.DELETE},
    )
    parent = _graph(org_a, "parent")
    child = _graph(org_a, "child")
    SubGraphNode.objects.create(graph=parent, subgraph=child)

    resp = client.delete(f"/api/graphs/{child.id}/")

    assert resp.status_code == 403, resp.data
    assert resp.data["code"] == "in_use_restricted"
    assert Graph.objects.filter(id=child.id).exists()


@pytest.mark.django_db
def test_delete_by_uuid_runs_the_same_guard(django_user_model, org_a):
    client = custom_role_client(
        django_user_model,
        org_a,
        "deleter4@example.com",
        **{ResourceType.FLOWS: Permission.DELETE},
    )
    parent = _graph(org_a, "parent")
    child = _graph(org_a, "child")
    SubGraphNode.objects.create(graph=parent, subgraph=child)

    resp = client.delete(f"/api/graphs/uuid/{child.uuid}/")

    assert resp.status_code == 403, resp.data
    assert resp.data["code"] == "in_use_restricted"
    assert Graph.objects.filter(id=child.id).exists()


@pytest.mark.django_db
def test_single_destroy_locks_the_row_it_checks(django_user_model, org_a):
    """Check and delete share one transaction and a row lock, as bulk does.

    Without the lock, a reference committed between the usage check and the
    delete would be silently nulled by the cascade.
    """
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    g = _graph(org_a, "g")

    with CaptureQueriesContext(connection) as queries:
        resp = client.delete(f"/api/graphs/{g.id}/")

    assert resp.status_code == 204, resp.data
    statements = [query["sql"] for query in queries.captured_queries]
    first_graph_lock = next(
        index
        for index, sql in enumerate(statements)
        if "FOR UPDATE" in sql and '"tables_graph"' in sql
    )
    # The usage read filters on `subgraph_id`; get_object() also prefetches the
    # graph's own subgraph nodes, which filters on `graph_id` and is not a check.
    first_usage_read = next(
        index
        for index, sql in enumerate(statements)
        if '"tables_subgraphnode"."subgraph_id" IN' in sql
    )
    # DeleteService locks the row itself later, so only the lock taken before the
    # usage read is the one that makes the check stable.
    assert first_graph_lock < first_usage_read


def _deleter_record(graph):
    """(editor id, edit time, binned time) of a binned graph: the deleter lives in its last edit."""
    last_edit = ResourceLastEdit.objects.filter(
        content_type=ContentType.objects.get_for_model(Graph), object_id=graph.pk
    ).first()
    stored = Graph.all_objects.get(pk=graph.pk)
    assert stored.active is False
    return (
        last_edit.edited_by_id if last_edit else "no record",
        last_edit.edited_at if last_edit else None,
        stored.soft_deleted_at,
    )


@pytest.mark.django_db
def test_bulk_delete_records_the_deleter_exactly_as_single_delete_does(
    django_user_model, org_a
):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    admin = django_user_model.objects.get(email="admin@example.com")
    bulk, single = _graph(org_a, "bulk"), _graph(org_a, "single")

    bulk_resp = client.post("/api/graphs/bulk-delete/", {"ids": [bulk.id]}, format="json")
    single_resp = client.delete(f"/api/graphs/{single.id}/")

    assert bulk_resp.status_code == 200, bulk_resp.data
    assert single_resp.status_code == 204
    bulk_editor, bulk_edited_at, bulk_binned_at = _deleter_record(bulk)
    single_editor, single_edited_at, single_binned_at = _deleter_record(single)
    assert bulk_editor == single_editor == admin.pk
    assert bulk_edited_at == bulk_binned_at
    assert single_edited_at == single_binned_at


@pytest.mark.django_db
def test_bulk_dry_run_records_no_deleter(django_user_model, org_a):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    graph = _graph(org_a)

    resp = client.post(
        "/api/graphs/bulk-delete/?dry_run=true", {"ids": [graph.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert Graph.objects.filter(id=graph.id).exists()
    assert not ResourceLastEdit.objects.filter(
        content_type=ContentType.objects.get_for_model(Graph), object_id=graph.pk
    ).exists()


@pytest.mark.django_db
def test_bulk_deleted_graph_shows_who_deleted_it_in_the_bin(django_user_model, org_a):
    client = org_admin_client(django_user_model, org_a, "admin@example.com")
    admin = django_user_model.objects.get(email="admin@example.com")
    graph = _graph(org_a)

    deleted = client.post("/api/graphs/bulk-delete/", {"ids": [graph.id]}, format="json")
    assert deleted.status_code == 200, deleted.data

    entries = client.get("/api/graphs/recycle-bin/").json()["results"]
    deleted_by = next(
        line for line in entries[0]["details"][:2] if line["label"] == "Deleted by"
    )
    assert deleted_by["value"] is not None
    assert deleted_by["value"]["id"] == admin.pk
