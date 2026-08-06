"""Deleting a Crew cascade-deletes its CrewNode rows while the CrewNode's
graph survives untouched — without a broadcast the node would linger on
connected editors' canvases and in the live Redis snapshot until reload.

``handle_crew_pre_delete`` (tables/signals/crew_signals.py) captures the
affected (graph_id, crew_node_id) pairs before the cascade runs, then
broadcasts via ``GraphEditNotifier.broadcast_nodes_deleted`` once the delete
transaction commits.

These tests use ``django_db(transaction=True)`` because ``transaction.on_commit``
callbacks never fire under the default (rollback-wrapping) ``django_db`` fixture.
"""

import asyncio

import pytest
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer

from tables.graph_collab.graph_state_service import graph_state_service
from tables.models.crew_models import Crew
from tables.models.graph_models import CrewNode


@sync_to_async
def _create_crew_node(graph, crew: Crew, node_name: str) -> CrewNode:
    """Attach an additional CrewNode to an already-created Crew — used by the
    multi-graph test, where the same crew is placed on two graphs."""
    return CrewNode.objects.create(graph=graph, node_name=node_name, crew=crew)


@sync_to_async
def _delete_crew(crew):
    crew.delete()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_crew_delete_broadcasts_nodes_deleted_per_graph_and_updates_snapshots(
    test_graph, second_graph, default_org, make_crew_node, base_snapshot
):
    """A crew placed on two graphs triggers one nodes_deleted broadcast per
    graph, scoped to that graph's own channel group, and removes the node
    from both graphs' live snapshots."""
    crew, _ = await make_crew_node(default_org, graph=None)
    node_on_first_graph = await _create_crew_node(test_graph, crew, "Crew-Node #1")
    node_on_second_graph = await _create_crew_node(second_graph, crew, "Crew-Node #2")

    await graph_state_service.seed(
        test_graph.id,
        base_snapshot(
            save_version=test_graph.save_version,
            crew_node_list=[
                {
                    "id": node_on_first_graph.id,
                    "graph": test_graph.id,
                    "node_name": "Crew-Node #1",
                    "crew_id": crew.id,
                }
            ],
        ),
    )
    await graph_state_service.seed(
        second_graph.id,
        base_snapshot(
            save_version=second_graph.save_version,
            crew_node_list=[
                {
                    "id": node_on_second_graph.id,
                    "graph": second_graph.id,
                    "node_name": "Crew-Node #2",
                    "crew_id": crew.id,
                }
            ],
        ),
    )

    channel_layer = get_channel_layer()
    first_channel = await channel_layer.new_channel()
    second_channel = await channel_layer.new_channel()
    await channel_layer.group_add(f"graph_edit_{test_graph.id}", first_channel)
    await channel_layer.group_add(f"graph_edit_{second_graph.id}", second_channel)

    await _delete_crew(crew)

    first_message = await channel_layer.receive(first_channel)
    second_message = await channel_layer.receive(second_channel)

    assert first_message["type"] == "nodes_deleted"
    assert first_message["refs"] == [
        {"list_key": "crew_node_list", "id": node_on_first_graph.id, "temp_id": None}
    ]
    assert second_message["type"] == "nodes_deleted"
    assert second_message["refs"] == [
        {"list_key": "crew_node_list", "id": node_on_second_graph.id, "temp_id": None}
    ]

    first_snapshot = await graph_state_service.get_snapshot(test_graph.id)
    assert first_snapshot["crew_node_list"] == []
    second_snapshot = await graph_state_service.get_snapshot(second_graph.id)
    assert second_snapshot["crew_node_list"] == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_crew_delete_with_no_live_snapshot_is_a_no_op(
    test_graph, default_org, make_crew_node
):
    """When the graph has no live snapshot in Redis (no active collab
    session), broadcast_nodes_deleted must skip silently — no message, no
    crash."""
    crew, _crew_node = await make_crew_node(default_org, graph=test_graph)

    assert await graph_state_service.get_snapshot(test_graph.id) is None

    channel_layer = get_channel_layer()
    channel_name = await channel_layer.new_channel()
    await channel_layer.group_add(f"graph_edit_{test_graph.id}", channel_name)

    await _delete_crew(crew)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(channel_layer.receive(channel_name), timeout=0.5)
