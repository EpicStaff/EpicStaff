"""Regression tests for the WS-autosave flush org-scoping fix.

Root cause: GraphFlushService._do_db_flush() called GraphBulkSaveService().save()
with no `request`, so every org-scoped FK field resolved its context with no
request AND no org_id and hit the fail-safe deny branch, rejecting every flush.

The fix threads an explicit `org_id` (sourced from `graph.org_id`, never from the
snapshot/payload) into GraphBulkSaveService.save() and the serializer context.
Verifies: (1) a same-org crew_id FK flush now succeeds, (2) a cross-org crew_id
FK flush is still rejected, (3) the fail-safe deny holds with no request/org_id.
"""

import pytest
from asgiref.sync import sync_to_async

from tables.exceptions import BulkSaveValidationError
from tables.graph_collab.flush_service import FlushOutcome, FlushStatus
from tables.graph_collab.graph_state_service import graph_state_service
from tables.models import Organization
from tables.serializers.graph_bulk_save_serializers import GraphBulkSaveInputSerializer
from tables.services.graph_bulk_save_service import GraphBulkSaveService


@sync_to_async
def _count_crew_nodes(graph_id: int) -> int:
    from tables.models.graph_models import CrewNode

    return CrewNode.objects.filter(graph_id=graph_id).count()


@sync_to_async
def _create_other_org() -> Organization:
    return Organization.objects.create(name="Other Org")


# ---------------------------------------------------------------------------
# 1. The fix: flush with a same-org crew_id FK now succeeds via GraphFlushService
#    (which threads org_id=graph.org_id, no request).
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_same_org_crew_id_succeeds_without_request(
    graph, base_snapshot, flush_service, make_crew_node
):
    """A flush (no request in context) whose crew_node_list references a crew in
    the SAME org as the graph must now succeed and persist — previously denied
    because GraphBulkSaveService().save() was called without a request."""
    crew, _ = await make_crew_node(graph.org)

    temp_id = "eeeeffff-0000-0000-0000-000000000001"
    snap = base_snapshot(
        save_version=graph.save_version,
        crew_node_list=[
            {
                "temp_id": temp_id,
                "graph": graph.id,
                "crew_id": crew.id,
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert isinstance(outcome, FlushOutcome)
    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). Same-org crew_id FK "
        "should be accepted once org_id is threaded into the flush's bulk save."
    )
    assert await _count_crew_nodes(graph.id) == 1


# ---------------------------------------------------------------------------
# 2. Regression guard: a CROSS-org crew_id FK is still rejected.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_cross_org_crew_id_is_still_rejected(
    graph, base_snapshot, flush_service, make_crew_node
):
    """A flush whose crew_node_list references a crew belonging to a DIFFERENT
    org than the graph must still be rejected — threading org_id from
    graph.org_id must not reopen the cross-org leak that CrewNodeSerializer.
    validate_crew_id closes."""
    other_org = await _create_other_org()
    foreign_crew, _ = await make_crew_node(other_org)

    temp_id = "eeeeffff-0000-0000-0000-000000000002"
    snap = base_snapshot(
        save_version=graph.save_version,
        crew_node_list=[
            {
                "temp_id": temp_id,
                "graph": graph.id,
                "crew_id": foreign_crew.id,
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.FAILED
    assert not outcome.saved
    assert not outcome.safe_to_clear
    assert await _count_crew_nodes(graph.id) == 0


# ---------------------------------------------------------------------------
# 3. Fail-safe deny preserved: no request AND no org_id still denies.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_bulk_save_service_denies_without_request_or_org_id(graph):
    """Calling GraphBulkSaveService().save() with neither request nor org_id
    must still deny org-scoped FK fields (e.g. CrewNode.graph) — the fail-safe
    from before this fix must remain the default when no context is threaded."""
    payload = {
        "save_version": graph.save_version,
        "crew_node_list": [
            {
                "temp_id": "eeeeffff-0000-0000-0000-000000000003",
                "graph": graph.id,
                # crew_id omitted deliberately — the `graph` field alone is
                # enough to trigger the org-scoped deny before crew_id is
                # even reached.
                "crew_id": 1,
            }
        ],
    }
    serializer = GraphBulkSaveInputSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors

    with pytest.raises(BulkSaveValidationError) as excinfo:
        GraphBulkSaveService().save(graph, serializer.validated_data)

    assert "crew_node_list" in excinfo.value.errors
