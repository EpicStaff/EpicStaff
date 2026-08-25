"""Integration tests for GraphFlushService covering how entries land in the
DB — bulk-save-shape entries, op-created entries missing the `graph` FK, and
seeded entries whose `graph` FK must not be clobbered.
"""

import pytest
from asgiref.sync import sync_to_async

from tables.graph_collab.flush_service import FlushStatus
from tables.graph_collab.graph_state_service import graph_state_service
from tables.graph_collab.protocol import (
    EditorInfo,
    NodeCreatedMessage,
    NodeUpdatedMessage,
)
from tests.graph_collab.conftest import PYTHON_CODE_DATA, count_nodes, first_node


@sync_to_async
def _get_python_code_for_node(node_id: int):
    """Fetch the PythonCode associated with a PythonNode."""
    from tables.models.graph_models import PythonNode

    node = PythonNode.objects.select_related("python_code").get(pk=node_id)
    return node.python_code


@sync_to_async
def _create_start_python_edge_graph(graph):
    """Create a StartNode, PythonNode (with PythonCode), and an Edge between them.

    Returns (start_node, python_node, edge, python_code).
    """
    from tables.models.graph_models import Edge, StartNode, PythonNode
    from tables.models.python_models import PythonCode

    start_node = StartNode.objects.create(
        graph=graph,
        variables={},
    )
    python_code = PythonCode.objects.create(
        code="def main(inputs): return inputs",
        entrypoint="main",
        libraries="",
        global_kwargs={},
    )
    python_node = PythonNode.objects.create(
        graph=graph,
        node_name="Python-Node #1",
        python_code=python_code,
        test_input={},
        use_storage=False,
        stream_config={},
        input_map={},
    )
    edge = Edge.objects.create(
        graph=graph,
        start_node_id=start_node.id,
        end_node_id=python_node.id,
        metadata={},
    )
    return start_node, python_node, edge, python_code


# ---------------------------------------------------------------------------
# Per-node-type payload builders + no-op/extra verification callbacks for
# test_flush_bulk_save_shape_entry_persists_single_row below.
# ---------------------------------------------------------------------------


async def _build_rich_start_entry(graph, make_crew_node) -> dict:
    return {
        "temp_id": "aaaabbbb-1111-0000-0000-000000000001",
        "graph": graph.id,
        "variables": {"variables": {"x": 1}, "persistent": {}},
    }


async def _build_rich_end_entry(graph, make_crew_node) -> dict:
    return {
        "temp_id": "aaaabbbb-2222-0000-0000-000000000002",
        "graph": graph.id,
        "output_map": {"result": "final"},
    }


async def _build_rich_webhook_trigger_entry(graph, make_crew_node) -> dict:
    return {
        "temp_id": "aaaabbbb-3333-0000-0000-000000000003",
        "graph": graph.id,
        "node_name": "Webhook-Seeded",
        # metadata required by WebhookTriggerNodeSerializer (MetadataMixin in explicit field list)
        "metadata": {},
        "python_code": {
            "code": "def main(): return {}",
            "entrypoint": "main",
            "libraries": [],
            "global_kwargs": {},
        },
        "webhook_trigger": None,
    }


async def _build_rich_telegram_trigger_entry(graph, make_crew_node) -> dict:
    return {
        "temp_id": "aaaabbbb-4444-0000-0000-000000000004",
        "graph": graph.id,
        "node_name": "Telegram-Seeded",
        "telegram_bot_api_key": "key_seeded",
        "webhook_trigger": None,
        "fields": [],
    }


async def _build_rich_crew_entry(graph, make_crew_node) -> dict:
    """Crew's own entry needs a pre-existing row: the case under test is a
    bulk-save-shape update against an existing crew node's real id, not a
    brand-new temp_id create."""
    crew, crew_node = await make_crew_node(graph.org, graph=graph)
    return {
        "id": crew_node.id,
        "graph": graph.id,
        "node_name": "Crew-Node #1",
        "crew_id": crew.id,
    }


async def _build_rich_python_entry(graph, make_crew_node) -> dict:
    return {
        "temp_id": "ddddeeee-0000-0000-0000-000000000007",
        "graph": graph.id,
        "node_name": "Seeded-Node",
        "python_code": {
            "code": "def main(): return 'seeded'",
            "entrypoint": "main",
            "libraries": [],
            "global_kwargs": {},
        },
        "test_input": {},
        "use_storage": False,
        "stream_config": {},
        "input_map": {},
        "output_variable_path": None,
    }


async def _verify_python_code_persisted(graph_id: int) -> None:
    node = await first_node("python_node_list", graph_id)
    python_code = await _get_python_code_for_node(node.id)
    assert python_code.code == "def main(): return 'seeded'"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "build_entry, list_key, verify_extra",
    [
        (
            _build_rich_start_entry,
            "start_node_list",
            None,
        ),
        (
            _build_rich_end_entry,
            "end_node_list",
            None,
        ),
        (
            _build_rich_webhook_trigger_entry,
            "webhook_trigger_node_list",
            None,
        ),
        (
            _build_rich_telegram_trigger_entry,
            "telegram_trigger_node_list",
            None,
        ),
        (
            _build_rich_crew_entry,
            "crew_node_list",
            None,
        ),
        (
            _build_rich_python_entry,
            "python_node_list",
            _verify_python_code_persisted,
        ),
    ],
    ids=["start", "end", "webhook_trigger", "telegram_trigger", "crew", "python"],
)
async def test_flush_bulk_save_shape_entry_persists_single_row(
    graph,
    base_snapshot,
    flush_service,
    editor,
    make_crew_node,
    build_entry,
    list_key,
    verify_extra,
):
    """An op entry already in backend bulk-save shape (as opposed to raw
    FE-canvas shape) is accepted and persisted as exactly one row, for
    every affected node type."""
    await graph_state_service.seed(
        graph.id, base_snapshot(save_version=graph.save_version)
    )

    rich_payload = await build_entry(graph, make_crew_node)
    # NodeUpdatedMessage (not NodeCreatedMessage) is required here: 5 of the 6
    # rows build temp_id payloads (creates), but the crew row builds a
    # real-id update against a pre-existing node. This legacy upsert message
    # (changed_fields=None) appends-on-miss for the temp_id creates and
    # updates-in-place for the crew row's real id; NodeCreatedMessage would
    # trip apply_op's stale-id-recreate guard on that real id, since it's not
    # pending deletion.
    msg = NodeUpdatedMessage(node=rich_payload, list_key=list_key, editor=editor)
    await graph_state_service.apply_op(graph.id, msg)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r})."
    )
    assert await count_nodes(list_key, graph.id) == 1
    if verify_extra:
        await verify_extra(graph.id)


# ---------------------------------------------------------------------------
# Bug fix: op-created entries (no `graph` FK) must flush successfully
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_op_created_entries_without_graph_field_succeed(
    graph, base_snapshot, flush_service
):
    """WS-op-created snapshot entries omit the ``graph`` FK field (the FE
    payloads never include it) — inject_bulk_save_fields must fill it in for
    both a node entry (python_node_list) and an edge entry (edge_list)."""
    from tables.models.graph_models import Edge, StartNode

    # Pre-create a start node so the edge can reference a real node ID at one
    # end; the other end is a new python node created via temp_id in this flush.
    start_node = await sync_to_async(StartNode.objects.create)(
        graph=graph, variables={}
    )

    temp_end_id = "ccccdddd-0000-0000-0000-000000000099"

    snap = base_snapshot(
        save_version=graph.save_version,
        python_node_list=[
            {"temp_id": temp_end_id, "python_code": PYTHON_CODE_DATA},
        ],
        edge_list=[
            {"start_node_id": start_node.id, "end_temp_id": temp_end_id},
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status} "
        f"(failure_reason={outcome.failure_reason!r}). "
        "The 'graph' FK was not injected for op-created entries."
    )
    assert outcome.saved

    python_node_count = await count_nodes("python_node_list", graph.id)
    assert python_node_count == 1

    edge_count = await sync_to_async(Edge.objects.filter(graph_id=graph.id).count)()
    assert edge_count == 1

    from tables.models import Graph

    refreshed = await sync_to_async(Graph.objects.get)(pk=graph.id)
    assert refreshed.save_version > graph.save_version


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_seeded_graph_field_not_clobbered(
    test_graph, second_graph, base_snapshot, flush_service
):
    """setdefault must never overwrite a ``graph`` FK already present on a
    DB-seeded entry."""
    snap = base_snapshot(
        save_version=test_graph.save_version,
        python_node_list=[
            {
                "temp_id": "eeeeeeee-0000-0000-0000-000000000001",
                "graph": test_graph.id,  # explicitly set — must not be overwritten
                "python_code": PYTHON_CODE_DATA,
            }
        ],
    )
    await graph_state_service.seed(test_graph.id, snap)

    outcome = await flush_service.flush(test_graph.id)

    assert outcome.status is FlushStatus.SAVED

    # The node must belong to `test_graph`, not `second_graph`.
    python_node_count = await count_nodes("python_node_list", test_graph.id)
    assert python_node_count == 1

    other_count = await count_nodes("python_node_list", second_graph.id)
    assert other_count == 0


# ---------------------------------------------------------------------------
# Real graph shape: START + PYTHON + EDGE together
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_start_node_null_persistent_variables_crashes_with_none_get(
    graph, base_snapshot, flush_service, editor
):
    """A StartNode node_updated op with variables.persistent_variables=null must
    not crash flush() with 'NoneType' object has no attribute 'get' — a JSON null
    persistent_variables must be treated as an empty dict.

    The fix: StartNodeSerializer.validate() must coerce a null persistent_variables
    to {} (or equivalent empty dict) before calling .get() on it, so that a null
    value nested in the top-level `variables` field is treated as "no persistent
    variables configured" rather than causing an unhandled AttributeError.
    """
    start_node, python_node, edge, python_code = await _create_start_python_edge_graph(
        graph
    )

    start_node_hash = await sync_to_async(lambda: start_node.content_hash)()

    # Seed the snapshot with the StartNode in DB-seed shape.
    initial_snap = base_snapshot(
        save_version=graph.save_version,
        start_node_list=[
            {
                "id": start_node.id,
                "graph": graph.id,
                "variables": {},
                "metadata": {},
                "content_hash": start_node_hash,
            }
        ],
    )
    await graph_state_service.seed(graph.id, initial_snap)

    # A node_updated op for the StartNode where the top-level `variables` field
    # contains persistent_variables as null — the key is present but the value
    # is JSON null.
    start_null_persistent_variables = {
        "id": start_node.id,
        "graph": graph.id,
        "node_name": "__start__",
        "variables": {
            "variables": {},
            "persistent_variables": None,  # null in JSON — the exact bug trigger
        },
    }
    msg = NodeUpdatedMessage(
        node=start_null_persistent_variables,
        list_key="start_node_list",
        editor=editor,
    )
    await graph_state_service.apply_op(graph.id, msg)

    # Before the fix this raised AttributeError from StartNodeSerializer.validate()
    # (persistent_variables.get(...) on None). After the fix flush() must not raise.
    try:
        outcome = await flush_service.flush(graph.id)
    except AttributeError as exc:
        raise AssertionError(
            f"flush() propagated AttributeError to the caller — it must be caught "
            f"internally and returned as a FAILED outcome: {exc}"
        ) from exc

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). "
        "Null persistent_variables in initialState should be treated as empty "
        "and the flush should succeed."
    )


# ---------------------------------------------------------------------------
# Regression: superadmin-set ngrok_webhook_config must survive the WS flush
# ---------------------------------------------------------------------------


@sync_to_async
def _create_ngrok_config():
    from tables.models.webhook_models import NgrokWebhookConfig

    return NgrokWebhookConfig.objects.create(
        name="test-ngrok-config",
        auth_token="test-auth-token",
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_superadmin_ngrok_webhook_config_survives_ws_flush(
    graph, base_snapshot, flush_service, editor
):
    """The reported bug: a superadmin sets ngrok_webhook_config on a
    webhook-trigger node via the WS collaborative flow; the value must land
    in the DB after the autosave flush, not get silently nulled."""
    ngrok_config = await _create_ngrok_config()

    await graph_state_service.seed(
        graph.id, base_snapshot(save_version=graph.save_version)
    )

    node_payload = {
        "temp_id": "aaaabbbb-5555-0000-0000-000000000005",
        "graph": graph.id,
        "node_name": "Webhook-Superadmin",
        "metadata": {},
        "python_code": {
            "code": "def main(): return {}",
            "entrypoint": "main",
            "libraries": [],
            "global_kwargs": {},
        },
        "webhook_trigger": {
            "path": "superadmin-path",
            "ngrok_webhook_config": ngrok_config.id,
        },
    }
    msg = NodeCreatedMessage(
        node=node_payload, list_key="webhook_trigger_node_list", editor=editor
    )
    result = await graph_state_service.apply_op(graph.id, msg, is_superadmin=True)
    assert result.details is None, "superadmin write must not be pinned"

    outcome = await flush_service.flush(graph.id)
    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r})."
    )

    node = await first_node("webhook_trigger_node_list", graph.id)
    assert node is not None

    @sync_to_async
    def _get_ngrok_config_id(webhook_trigger_node):
        return webhook_trigger_node.webhook_trigger.ngrok_webhook_config_id

    assert await _get_ngrok_config_id(node) == ngrok_config.id
