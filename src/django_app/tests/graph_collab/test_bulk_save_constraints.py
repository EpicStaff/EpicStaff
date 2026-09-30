"""Bulk-save singleton and org-scoping constraints enforced by
GraphBulkSaveService / GraphFlushService: End/Start singleton guards across a
delete+recreate in one flush, rejection of conflicting deleted/update ids,
and org-scoped FK denial without a request/org_id.
"""

import pytest

from tables.exceptions import BulkSaveValidationError
from tables.graph_collab.flush_service import FlushOutcome, FlushStatus
from tables.graph_collab.graph_state_service import graph_state_service
from rbac.models import Organization
from tables.serializers.graph_bulk_save_serializers import GraphBulkSaveInputSerializer
from tables.services.graph_bulk_save_service import GraphBulkSaveService
from tests.graph_collab.conftest import (
    _create_end_node,
    _create_start_node,
    count_nodes,
    get_node,
)


# ---------------------------------------------------------------------------
# delete-then-create-singleton-in-one-flush deadlock.
#
# GraphBulkSaveService.save() builds its Pass-1 db_map from a live DB query
# (the deletion itself only runs in Pass 2), so a delete-old-End +
# create-new-End in the same flush used to make the singleton guard see the
# still-present old row and reject the create with "Only one end_node_list
# entry allowed per graph" — every autosave tick, forever. Fixed by excluding
# ids pending deletion (``deleted[config.delete_key]``) from Pass-1's db_map.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_delete_and_recreate_end_node_singleton_in_one_flush(
    graph, base_snapshot, empty_deleted, flush_service
):
    """Deleting the persisted End node and creating a new one (temp_id only)
    within the same autosave flush must succeed, leaving exactly one EndNode
    — the new one — instead of deadlocking on the singleton guard."""
    old_end = await _create_end_node(graph)

    new_temp_id = "eeeeffff-0000-0000-0000-000000000001"
    snap = base_snapshot(
        save_version=graph.save_version,
        end_node_list=[
            {
                "temp_id": new_temp_id,
                "graph": graph.id,
                "output_map": {"result": "output"},
            }
        ],
        deleted={**empty_deleted(), "end_node_ids": [old_end.id]},
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). "
        "delete-old-End + create-new-End in one flush deadlocked on the "
        "singleton guard."
    )

    count = await count_nodes("end_node_list", graph.id)
    assert count == 1, "Old and new End node both persisted — singleton violated."

    surviving = await get_node("end_node_list", outcome.result.temp_id_map[new_temp_id])
    assert surviving.id != old_end.id, "The old End node row was not replaced."
    assert surviving.output_map == {"result": "output"}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_delete_and_recreate_start_node_singleton_in_one_flush(
    graph, base_snapshot, empty_deleted, flush_service
):
    """Same deadlock as above, for StartNode (unique_graph_start_node)."""
    old_start = await _create_start_node(graph)

    new_temp_id = "eeeeffff-0000-0000-0000-000000000002"
    snap = base_snapshot(
        save_version=graph.save_version,
        start_node_list=[
            {
                "temp_id": new_temp_id,
                "graph": graph.id,
                "variables": {"variables": {"greeting": "new"}, "persistent": {}},
            }
        ],
        deleted={**empty_deleted(), "start_node_ids": [old_start.id]},
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). "
        "delete-old-Start + create-new-Start in one flush deadlocked on the "
        "singleton guard."
    )

    count = await count_nodes("start_node_list", graph.id)
    assert count == 1, "Old and new Start node both persisted — singleton violated."

    surviving = await get_node(
        "start_node_list", outcome.result.temp_id_map[new_temp_id]
    )
    assert surviving.id != old_start.id, "The old Start node row was not replaced."
    assert surviving.variables["variables"]["greeting"] == "new"


@pytest.mark.django_db
def test_bulk_save_two_end_node_creates_in_one_payload_still_rejected(graph):
    """Regression: without any deletion in the payload, two temp-only End
    creates in one flush must still be rejected by the singleton guard —
    the deletion-aware db_map must not weaken this check."""
    payload = {
        "save_version": graph.save_version,
        "end_node_list": [
            {
                "temp_id": "aaaa0000-0000-0000-0000-000000000001",
                "graph": graph.id,
                "output_map": {},
            },
            {
                "temp_id": "aaaa0000-0000-0000-0000-000000000002",
                "graph": graph.id,
                "output_map": {},
            },
        ],
    }
    serializer = GraphBulkSaveInputSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors

    with pytest.raises(BulkSaveValidationError) as excinfo:
        GraphBulkSaveService().save(graph, serializer.validated_data)

    errors = excinfo.value.errors
    assert "end_node_list" in errors
    assert any(
        "Only one end_node_list entry allowed per graph" in str(entry["errors"])
        for entry in errors["end_node_list"]
    )


@pytest.mark.django_db
def test_bulk_save_update_existing_end_node_not_pending_deletion_still_works(graph):
    """Regression: a normal update to an existing End node (real id present in
    end_node_list, absent from deleted) must still resolve against db_map —
    the deletion-aware filter must not accidentally exclude non-deleted ids."""
    from tables.models.graph_models import EndNode

    end_node = EndNode.objects.create(graph=graph, output_map={"context": "variables"})

    payload = {
        "save_version": graph.save_version,
        "end_node_list": [
            {"id": end_node.id, "graph": graph.id, "output_map": {"result": "updated"}},
        ],
    }
    serializer = GraphBulkSaveInputSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors

    GraphBulkSaveService().save(graph, serializer.validated_data, org_id=graph.org_id)

    assert EndNode.objects.filter(graph=graph).count() == 1
    end_node.refresh_from_db()
    assert end_node.output_map == {"result": "updated"}


@pytest.mark.django_db
def test_bulk_save_end_node_id_in_both_update_list_and_deleted_is_rejected(
    graph, empty_deleted
):
    """Documented edge case: the same real id appears in end_node_list (as an
    update) AND in deleted.end_node_ids in the same payload. The
    deletion-aware db_map excludes it from Pass-1's lookup set, so the
    update branch now reports "not found in graph" instead of silently
    updating a row about to be deleted."""
    from tables.models.graph_models import EndNode

    end_node = EndNode.objects.create(graph=graph, output_map={"context": "variables"})

    payload = {
        "save_version": graph.save_version,
        "end_node_list": [
            {"id": end_node.id, "graph": graph.id, "output_map": {"result": "updated"}},
        ],
        "deleted": {**empty_deleted(), "end_node_ids": [end_node.id]},
    }
    serializer = GraphBulkSaveInputSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors

    with pytest.raises(BulkSaveValidationError) as excinfo:
        GraphBulkSaveService().save(graph, serializer.validated_data)

    errors = excinfo.value.errors
    assert "end_node_list" in errors
    assert any(
        f"id={end_node.id} not found in graph {graph.id}" in str(entry["errors"])
        for entry in errors["end_node_list"]
    )


# ---------------------------------------------------------------------------
# Regression tests for the WS-autosave flush org-scoping fix.
#
# Root cause: GraphFlushService._do_db_flush() called GraphBulkSaveService().save()
# with no `request`, so every org-scoped FK field resolved its context with no
# request AND no org_id and hit the fail-safe deny branch, rejecting every flush.
#
# The fix threads an explicit `org_id` (sourced from `graph.org_id`, never from the
# snapshot/payload) into GraphBulkSaveService.save() and the serializer context.
# Verifies: (1) a same-org org-scoped FK flush now succeeds, (2) with org_id
# threaded in, bulk save still accepts a same-org subgraph and rejects a
# cross-org one, (3) the fail-safe deny holds with no request/org_id.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_same_org_subgraph_succeeds_without_request(
    graph, base_snapshot, flush_service, make_subgraph_node
):
    """A flush (no request in context) whose subgraph_node_list references a
    subgraph in the SAME org as the graph must now succeed and persist —
    previously denied because GraphBulkSaveService().save() was called without
    a request."""
    subgraph, _ = await make_subgraph_node(graph.org)

    temp_id = "eeeeffff-0000-0000-0000-000000000001"
    snap = base_snapshot(
        save_version=graph.save_version,
        subgraph_node_list=[
            {
                "temp_id": temp_id,
                "graph": graph.id,
                "subgraph": subgraph.id,
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert isinstance(outcome, FlushOutcome)
    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). Same-org subgraph FK "
        "should be accepted once org_id is threaded into the flush's bulk save."
    )
    assert await count_nodes("subgraph_node_list", graph.id) == 1
    persisted = await get_node(
        "subgraph_node_list", outcome.result.temp_id_map[temp_id]
    )
    assert persisted.subgraph_id == subgraph.id


def _subgraph_node_payload(graph, subgraph, temp_id: str) -> dict:
    return {
        "save_version": graph.save_version,
        "subgraph_node_list": [
            {"temp_id": temp_id, "graph": graph.id, "subgraph": subgraph.id}
        ],
    }


@pytest.mark.django_db
def test_bulk_save_service_accepts_same_org_subgraph_with_org_id(graph):
    """Control for the cross-org test below: the identical payload shape with
    a same-org subgraph is accepted when org_id is threaded in, so the
    cross-org rejection can only come from the subgraph's org."""
    from tables.models import Graph
    from tables.models.graph_models import SubGraphNode

    same_org_subgraph = Graph.objects.create(name="Same Org Subgraph", org=graph.org)
    temp_id = "eeeeffff-0000-0000-0000-000000000004"
    serializer = GraphBulkSaveInputSerializer(
        data=_subgraph_node_payload(graph, same_org_subgraph, temp_id)
    )
    assert serializer.is_valid(), serializer.errors

    _, temp_id_map = GraphBulkSaveService().save(
        graph, serializer.validated_data, org_id=graph.org_id
    )

    node = SubGraphNode.objects.get(pk=temp_id_map[temp_id])
    assert node.subgraph_id == same_org_subgraph.id


@pytest.mark.django_db
def test_bulk_save_service_rejects_cross_org_subgraph_with_org_id(graph):
    """With org_id threaded from graph.org_id (as the flush does), a
    subgraph belonging to a DIFFERENT org must still be rejected by the
    serializer's org scoping — threading org_id must not reopen the
    cross-org leak. Flush-level cross-org handling (the ref is stripped
    before validation) is covered by
    test_flush_strips_cross_org_llm_config_and_logs_warning."""
    from tables.models import Graph
    from tables.models.graph_models import SubGraphNode

    other_org = Organization.objects.create(name="Other Org")
    foreign_subgraph = Graph.objects.create(name="Foreign Subgraph", org=other_org)
    serializer = GraphBulkSaveInputSerializer(
        data=_subgraph_node_payload(
            graph, foreign_subgraph, "eeeeffff-0000-0000-0000-000000000005"
        )
    )
    assert serializer.is_valid(), serializer.errors

    with pytest.raises(BulkSaveValidationError) as excinfo:
        GraphBulkSaveService().save(
            graph, serializer.validated_data, org_id=graph.org_id
        )

    assert "subgraph_node_list" in excinfo.value.errors
    assert not SubGraphNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_bulk_save_service_denies_without_request_or_org_id(graph):
    """Calling GraphBulkSaveService().save() with neither request nor org_id
    must still deny org-scoped FK fields (e.g. SubGraphNode.graph) — the
    fail-safe from before this fix must remain the default when no context is
    threaded."""
    payload = {
        "save_version": graph.save_version,
        "subgraph_node_list": [
            {
                "temp_id": "eeeeffff-0000-0000-0000-000000000003",
                "graph": graph.id,
                # subgraph omitted deliberately — the `graph` field alone is
                # enough to trigger the org-scoped deny.
            }
        ],
    }
    serializer = GraphBulkSaveInputSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors

    with pytest.raises(BulkSaveValidationError) as excinfo:
        GraphBulkSaveService().save(graph, serializer.validated_data)

    assert "subgraph_node_list" in excinfo.value.errors
