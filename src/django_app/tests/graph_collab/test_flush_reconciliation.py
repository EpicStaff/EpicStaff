"""reconcile_against_db self-heals drift between the live snapshot and the
DB: stale entries left behind by out-of-band deletes, pre-existing orphan
rows, dangling routing refs, and duplicated singleton entries.
"""

import pytest
from asgiref.sync import sync_to_async

from tables.graph_collab.flush_service import FlushStatus
from tables.graph_collab.graph_state_service import graph_state_service
from tests.graph_collab.conftest import _create_end_node, _create_start_node


# ---------------------------------------------------------------------------
# reconcile_against_db self-heals drift from an external CASCADE delete (e.g.
# deleting a Crew cascade-deletes its CrewNode) that leaves the live snapshot
# holding a stale node entry and/or edge refs to it.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_prunes_stale_crew_node_and_dangling_edge_after_out_of_band_delete(
    graph, base_snapshot, flush_service, make_crew_node
):
    """A Crew row removed out-of-band (e.g. its Crew was deleted,
    cascading the CrewNode) while the live snapshot still carries an UPDATE
    entry for that node plus an edge referencing it must be pruned by
    reconcile_against_db rather than wedging autosave forever."""
    from tables.models.graph_models import CrewNode, Edge, StartNode
    from tables.models.crew_models import Crew

    crew, crew_node = await make_crew_node(graph.org, graph=graph)
    start_node = await _create_start_node(graph)

    snap = base_snapshot(
        save_version=graph.save_version,
        crew_node_list=[
            {
                "id": crew_node.id,
                "graph": graph.id,
                "node_name": "Crew-Node #1",
                "crew_id": crew.id,
            }
        ],
        edge_list=[
            {
                "start_node_id": start_node.id,
                "end_node_id": crew_node.id,
                "graph": graph.id,
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    # Simulate the Crew row vanishing out-of-band — the live snapshot is
    # not told. CrewNode also get deleted due to `on_delete=models.CASCADE`
    await sync_to_async(Crew.objects.filter(id=crew.id).delete)()

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). "
        "reconcile_against_db did not prune the stale crew node / dangling edge."
    )

    # The stale crew node must not have been recreated.
    assert not await sync_to_async(CrewNode.objects.filter(id=crew_node.id).exists)()

    # The dangling edge (referencing the now-gone crew node) must not get created.
    assert not await sync_to_async(
        Edge.objects.filter(graph_id=graph.id, end_node_id=crew_node.id).exists
    )()

    # The untouched, still-valid start node must survive unaffected.
    assert await sync_to_async(
        StartNode.objects.filter(id=start_node.id, graph_id=graph.id).exists
    )()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_reconcile_leaves_valid_payload_untouched(
    graph, base_snapshot, flush_service, make_crew_node
):
    """Sanity check: when every referenced id is still valid in the DB,
    reconcile_against_db must not prune anything."""
    from tables.models.graph_models import CrewNode, Edge

    crew, crew_node = await make_crew_node(graph.org, graph=graph)
    start_node = await _create_start_node(graph)

    snap = base_snapshot(
        save_version=graph.save_version,
        crew_node_list=[
            {
                "id": crew_node.id,
                "graph": graph.id,
                "node_name": "Crew-Node #1",
                "crew_id": crew.id,
            }
        ],
        edge_list=[
            {
                "start_node_id": start_node.id,
                "end_node_id": crew_node.id,
                "graph": graph.id,
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED
    assert await sync_to_async(CrewNode.objects.filter(id=crew_node.id).exists)()
    assert await sync_to_async(
        Edge.objects.filter(
            graph_id=graph.id, start_node_id=start_node.id, end_node_id=crew_node.id
        ).exists
    )()


# ---------------------------------------------------------------------------
# reconcile_against_db reaps pre-existing orphan edges (real DB rows, not
# just payload refs) and nulls dangling decision-table routing refs, instead
# of merely dropping them from this flush's payload.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_reaps_preexisting_orphan_edge_from_db(
    graph, base_snapshot, flush_service, make_crew_node
):
    """An orphan Edge row (its end node already gone from the DB, e.g. via a
    prior crew-cascade delete the live snapshot never learned about) must be
    DELETEd by the flush, not just pruned from this tick's payload — otherwise
    the row survives and reappears on the next seed_from_db."""
    from tables.models.graph_models import CrewNode, Edge

    crew, crew_node = await make_crew_node(graph.org, graph=graph)
    start_node = await _create_start_node(graph)

    orphan_edge = await sync_to_async(Edge.objects.create)(
        graph=graph,
        start_node_id=start_node.id,
        end_node_id=crew_node.id,
        metadata={},
    )

    # The crew node vanishes out-of-band; the live snapshot still carries the
    # now-orphan edge but no longer carries the crew node itself (mirrors a
    # snapshot that was seeded/edited before the out-of-band delete).
    await sync_to_async(CrewNode.objects.filter(id=crew_node.id).delete)()

    snap = base_snapshot(
        save_version=graph.save_version,
        edge_list=[
            {
                "id": orphan_edge.id,
                "start_node_id": start_node.id,
                "end_node_id": crew_node.id,
                "graph": graph.id,
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r})."
    )
    assert not await sync_to_async(Edge.objects.filter(id=orphan_edge.id).exists)()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_nulls_dangling_decision_table_routing_ref(
    graph, base_snapshot, flush_service
):
    """A DecisionTableNode still routing (default_next_node_id,
    next_error_node_id, condition_groups[].next_node_id) to a node already
    gone from the DB must have those refs nulled by reconcile_against_db, so
    the flush succeeds instead of failing with "routing references node IDs
    that do not exist"."""
    from tables.models.graph_models import (
        ConditionGroup,
        DecisionTableNode,
        EndNode,
    )

    end_node = await _create_end_node(graph)
    decision_table_node = await sync_to_async(DecisionTableNode.objects.create)(
        graph=graph,
        node_name="Decision Table #1",
        default_next_node_id=end_node.id,
        next_error_node_id=end_node.id,
    )
    condition_group = await sync_to_async(ConditionGroup.objects.create)(
        decision_table_node=decision_table_node,
        group_name="group-1",
        group_type="simple",
        order=0,
        next_node_id=end_node.id,
    )

    # The routing target vanishes out-of-band — the live snapshot still
    # carries the decision table routing to it.
    await sync_to_async(EndNode.objects.filter(id=end_node.id).delete)()

    snap = base_snapshot(
        save_version=graph.save_version,
        decision_table_node_list=[
            {
                "id": decision_table_node.id,
                "graph": graph.id,
                "node_name": "Decision Table #1",
                "default_next_node_id": end_node.id,
                "next_error_node_id": end_node.id,
                "condition_groups": [
                    {
                        "id": condition_group.id,
                        "group_name": "group-1",
                        "group_type": "simple",
                        "order": 0,
                        "next_node_id": end_node.id,
                    }
                ],
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). "
        "reconcile_against_db did not null the dangling routing ref."
    )

    await sync_to_async(decision_table_node.refresh_from_db)()
    assert decision_table_node.default_next_node_id is None
    assert decision_table_node.next_error_node_id is None

    # DecisionTableNodeSaveable recreates condition_groups wholesale on
    # update (delete-then-recreate, not an in-place update) — the original
    # ConditionGroup row is gone, so assert on the survivor via the FK.
    surviving_group = await sync_to_async(
        lambda: ConditionGroup.objects.get(decision_table_node=decision_table_node)
    )()
    assert surviving_group.next_node_id is None


# ---------------------------------------------------------------------------
# reconcile_against_db collapses a duplicated singleton (start_node_list /
# end_node_list) already stuck in the live snapshot before the op-time dedup
# in apply_op shipped.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_collapses_duplicate_start_node_entries_preferring_real_id(
    graph, base_snapshot, flush_service
):
    """A snapshot corrupted with two start_node_list entries (the persisted
    row plus a stray duplicate create) must be collapsed to one by
    reconcile_against_db, preferring the entry with the real id, and the
    flush must succeed instead of hitting unique_graph_start_node."""
    from tables.models.graph_models import StartNode

    start_node = await _create_start_node(graph)

    snap = base_snapshot(
        save_version=graph.save_version,
        start_node_list=[
            {
                "id": start_node.id,
                "graph": graph.id,
                "variables": {"variables": {"greeting": "hello"}, "persistent": {}},
            },
            {
                # Stray duplicate create — no id, as if a mismatched-temp_id
                # op had appended a second entry before the Bug 5 op-time fix.
                "temp_id": "stray-duplicate",
                "graph": graph.id,
                "variables": {"variables": {}, "persistent": {}},
            },
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). "
        "reconcile_against_db did not collapse the duplicate start_node_list entries."
    )

    count = await sync_to_async(StartNode.objects.filter(graph_id=graph.id).count)()
    assert count == 1, "Duplicate start node entry was persisted instead of collapsed."

    surviving = await sync_to_async(StartNode.objects.get)(graph_id=graph.id)
    assert surviving.id == start_node.id, (
        "The persisted (real-id) start node entry must survive the collapse."
    )
    assert surviving.variables == snap["start_node_list"][0]["variables"]


# ---------------------------------------------------------------------------
# reconcile_against_db reaps pre-existing orphan conditional edges the same
# way it reaps orphan Edge rows — same dangling-endpoint logic, but keyed by
# source_node_id instead of start/end_node_id.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_reaps_preexisting_orphan_conditional_edge_from_db(
    graph, base_snapshot, flush_service, make_crew_node
):
    """An orphan ConditionalEdge row (its source node already gone from the
    DB, e.g. via a prior crew-cascade delete the live snapshot never learned
    about) must be DELETEd by the flush, not just pruned from this tick's
    payload."""
    from tables.models.graph_models import ConditionalEdge, CrewNode
    from tables.models.python_models import PythonCode

    crew, crew_node = await make_crew_node(graph.org, graph=graph)
    python_code = await sync_to_async(PythonCode.objects.create)(
        code="def main(): return 42",
        entrypoint="main",
        libraries="",
        global_kwargs={},
    )

    orphan_conditional_edge = await sync_to_async(ConditionalEdge.objects.create)(
        graph=graph,
        source_node_id=crew_node.id,
        python_code=python_code,
    )

    # The source node vanishes out-of-band; the live snapshot still carries
    # the now-orphan conditional edge but no longer carries the crew node
    # itself.
    await sync_to_async(CrewNode.objects.filter(id=crew_node.id).delete)()

    snap = base_snapshot(
        save_version=graph.save_version,
        conditional_edge_list=[
            {
                "id": orphan_conditional_edge.id,
                "source_node_id": crew_node.id,
                "graph": graph.id,
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r})."
    )
    assert not await sync_to_async(
        ConditionalEdge.objects.filter(id=orphan_conditional_edge.id).exists
    )()
