"""reconcile_against_db self-heals drift between the live snapshot and the
DB: stale entries left behind by out-of-band deletes, pre-existing orphan
rows, dangling routing refs, and duplicated singleton entries.
"""

import pytest
from asgiref.sync import sync_to_async

from tables.graph_collab.flush_service import FlushStatus
from tables.graph_collab.graph_state_service import graph_state_service
from tests.graph_collab.conftest import (
    _create_end_node,
    _create_start_node,
    _drain_connect,
    _make_communicator,
    _model_for,
)


@sync_to_async
def _content_hash_for(list_key: str, node_id: int) -> str:
    """Fetch a node's DB-computed content_hash from a fresh, synchronous
    query. Needed instead of a plain `get_node(...).content_hash` because
    ContentHashMixin.generate_hash() reads forward FK fields, which lazily
    queries the DB the first time they're accessed — content_hash must be
    computed inside the same sync_to_async call that loads the row."""
    return _model_for(list_key).objects.get(pk=node_id).content_hash


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
                # Stray duplicate create — no id, simulating a mismatched-temp_id
                # op that appended a second entry instead of resolving to the
                # existing node's id.
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
    assert (
        surviving.id == start_node.id
    ), "The persisted (real-id) start node entry must survive the collapse."
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


# ---------------------------------------------------------------------------
# reconcile_against_db (via find_dead_external_refs) nulls a surviving node's
# outward FK/M2M ref — LLMConfig, subgraph Graph, NgrokWebhookConfig, Secret,
# AgentDefinition, Surface — whose target was deleted or moved to another org
# out-of-band, instead of failing the whole flush's PrimaryKeyRelatedField
# validation and wedging autosave forever. Unlike the node/edge pruning above,
# the referencing node ROW survives here; only the stale ref is nulled.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_nulls_dead_llm_config_on_code_agent_node(
    graph, base_snapshot, flush_service
):
    """A CodeAgentNode.llm_config whose LLMConfig was deleted out-of-band
    (SET_NULL fires on the DB row immediately) must be nulled in the stale
    live-snapshot payload too, or the flush fails validation forever."""
    from tables.models.graph_models import CodeAgentNode
    from tables.models.llm_models import LLMConfig

    llm_config = await sync_to_async(LLMConfig.objects.create)(
        custom_name="dead-llm-config", org=graph.org
    )
    node = await sync_to_async(CodeAgentNode.objects.create)(
        graph=graph, node_name="CodeAgent-1", llm_config=llm_config
    )
    dead_llm_config_id = llm_config.id
    await sync_to_async(llm_config.delete)()

    snap = base_snapshot(
        save_version=graph.save_version,
        code_agent_node_list=[
            {
                "id": node.id,
                "graph": graph.id,
                "node_name": "CodeAgent-1",
                "llm_config": dead_llm_config_id,
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). "
        "The dead llm_config ref was not nulled before validation."
    )

    await sync_to_async(node.refresh_from_db)()
    assert node.llm_config_id is None

    snapshot = await graph_state_service.get_snapshot(graph.id)
    entry = snapshot["code_agent_node_list"][0]
    assert entry["llm_config"] is None, (
        "The retained live snapshot must not keep the dead llm_config pk — "
        "otherwise the next flush hits the identical validation failure again."
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_nulls_dead_subgraph_on_subgraph_node(
    graph, base_snapshot, flush_service
):
    """A SubGraphNode.subgraph whose target Graph was deleted out-of-band
    must be nulled the same way as any other outward ref."""
    from tables.models import Graph
    from tables.models.graph_models import SubGraphNode

    subgraph = await sync_to_async(Graph.objects.create)(
        name="dead-subgraph", org=graph.org
    )
    node = await sync_to_async(SubGraphNode.objects.create)(
        graph=graph, node_name="Subgraph-1", subgraph=subgraph
    )
    dead_subgraph_id = subgraph.id
    await sync_to_async(subgraph.delete)()

    snap = base_snapshot(
        save_version=graph.save_version,
        subgraph_node_list=[
            {
                "id": node.id,
                "graph": graph.id,
                "node_name": "Subgraph-1",
                "subgraph": dead_subgraph_id,
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r})."
    )

    await sync_to_async(node.refresh_from_db)()
    assert node.subgraph_id is None

    snapshot = await graph_state_service.get_snapshot(graph.id)
    assert snapshot["subgraph_node_list"][0]["subgraph"] is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_nulls_dead_llm_config_nested_in_prompt_configs(
    graph, base_snapshot, flush_service
):
    """ClassificationDecisionTablePrompt.llm_config (nested inside the
    prompt_configs list) whose LLMConfig was deleted out-of-band must be
    nulled per-item, not just for the node's own default_llm_config."""
    from tables.models.graph_models import (
        ClassificationDecisionTableNode,
        ClassificationDecisionTablePrompt,
    )
    from tables.models.llm_models import LLMConfig

    llm_config = await sync_to_async(LLMConfig.objects.create)(
        custom_name="dead-prompt-llm-config", org=graph.org
    )
    node = await sync_to_async(ClassificationDecisionTableNode.objects.create)(
        graph=graph, node_name="CDT-1"
    )
    prompt = await sync_to_async(ClassificationDecisionTablePrompt.objects.create)(
        cdt_node=node, prompt_key="p1", llm_config=llm_config
    )
    dead_llm_config_id = llm_config.id
    await sync_to_async(llm_config.delete)()

    snap = base_snapshot(
        save_version=graph.save_version,
        classification_decision_table_node_list=[
            {
                "id": node.id,
                "graph": graph.id,
                "node_name": "CDT-1",
                "prompt_configs": [
                    {
                        "id": prompt.id,
                        "prompt_key": "p1",
                        "llm_config": dead_llm_config_id,
                    }
                ],
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r})."
    )

    snapshot = await graph_state_service.get_snapshot(graph.id)
    entry = snapshot["classification_decision_table_node_list"][0]
    assert entry["prompt_configs"][0]["llm_config"] is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_nulls_dead_ngrok_config_nested_in_webhook_trigger_and_broadcasts(
    graph, test_user, base_snapshot, flush_service
):
    """The ngrok_webhook_config nested inside webhook_trigger must be nulled,
    and since it is a nested field, the frontend merges by TOP-LEVEL key —
    so the broadcast must carry the WHOLE webhook_trigger object with
    changed_fields=["webhook_trigger"], not a bare ngrok_webhook_config key."""
    from tables.models.graph_models import TelegramTriggerNode
    from tables.models.webhook_models import NgrokWebhookConfig, WebhookTrigger

    ngrok_config = await sync_to_async(NgrokWebhookConfig.objects.create)(
        name="dead-ngrok", auth_token="dead-ngrok-token"
    )
    webhook_trigger = await sync_to_async(WebhookTrigger.objects.create)(
        path="dead-ngrok-path", ngrok_webhook_config=ngrok_config
    )
    node = await sync_to_async(TelegramTriggerNode.objects.create)(
        graph=graph, node_name="Telegram-1", webhook_trigger=webhook_trigger
    )
    dead_ngrok_id = ngrok_config.id
    await sync_to_async(ngrok_config.delete)()

    snap = base_snapshot(
        save_version=graph.save_version,
        telegram_trigger_node_list=[
            {
                "id": node.id,
                "graph": graph.id,
                "node_name": "Telegram-1",
                "webhook_trigger": {
                    "path": webhook_trigger.path,
                    "ngrok_webhook_config": dead_ngrok_id,
                },
                "fields": [],
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    communicator = _make_communicator(graph.pk, test_user)
    connected, _ = await communicator.connect()
    assert connected
    await _drain_connect(communicator)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r})."
    )

    message = await communicator.receive_json_from()
    assert message["type"] == "node_updated"
    assert message["changed_fields"] == ["webhook_trigger"]
    assert message["node"]["id"] == node.id
    assert message["node"]["webhook_trigger"]["ngrok_webhook_config"] is None
    assert message["node"]["webhook_trigger"]["path"] == webhook_trigger.path

    await sync_to_async(webhook_trigger.refresh_from_db)()
    assert webhook_trigger.ngrok_webhook_config_id is None

    snapshot = await graph_state_service.get_snapshot(graph.id)
    entry = snapshot["telegram_trigger_node_list"][0]
    assert entry["webhook_trigger"]["ngrok_webhook_config"] is None

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_nulls_dead_secret_on_telegram_trigger(
    graph, base_snapshot, flush_service
):
    """TelegramTriggerNode.telegram_bot_api_key_secret_id whose Secret was
    deleted out-of-band must be nulled like any other scalar outward ref."""
    from tables.models.graph_models import TelegramTriggerNode
    from tables.models.secret_models import Secret

    secret = await sync_to_async(Secret.objects.create)(
        org=graph.org, name="dead-telegram-secret", value="ciphertext"
    )
    node = await sync_to_async(TelegramTriggerNode.objects.create)(
        graph=graph, node_name="Telegram-2", telegram_bot_api_key_secret=secret
    )
    dead_secret_id = secret.id
    await sync_to_async(secret.delete)()

    snap = base_snapshot(
        save_version=graph.save_version,
        telegram_trigger_node_list=[
            {
                "id": node.id,
                "graph": graph.id,
                "node_name": "Telegram-2",
                "telegram_bot_api_key_secret_id": dead_secret_id,
                "webhook_trigger": None,
                "fields": [],
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r})."
    )

    await sync_to_async(node.refresh_from_db)()
    assert node.telegram_bot_api_key_secret_id is None

    snapshot = await graph_state_service.get_snapshot(graph.id)
    entry = snapshot["telegram_trigger_node_list"][0]
    assert entry["telegram_bot_api_key_secret_id"] is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_nulls_dead_agent_definition_on_task_node(
    graph, base_snapshot, flush_service
):
    """TaskNode.agent_definition whose AgentDefinition was deleted
    out-of-band must be nulled — org-scoped target model, organization_id
    lookup rather than org_id."""
    from agents.models.agent_models import AgentDefinition
    from tables.models.graph_models import TaskNode

    agent_definition = await sync_to_async(AgentDefinition.objects.create)(
        organization=graph.org, name="dead-agent-def", instructions="do things"
    )
    node = await sync_to_async(TaskNode.objects.create)(
        graph=graph, node_name="Task-1", agent_definition=agent_definition
    )
    dead_agent_definition_id = agent_definition.id
    await sync_to_async(agent_definition.delete)()

    snap = base_snapshot(
        save_version=graph.save_version,
        task_node_list=[
            {
                "id": node.id,
                "graph": graph.id,
                "node_name": "Task-1",
                "agent_definition": dead_agent_definition_id,
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r})."
    )

    await sync_to_async(node.refresh_from_db)()
    assert node.agent_definition_id is None

    snapshot = await graph_state_service.get_snapshot(graph.id)
    assert snapshot["task_node_list"][0]["agent_definition"] is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_nulls_dead_surface_on_agent_node(
    graph, base_snapshot, flush_service
):
    """AgentNode.surface_list (M2M) must have only the dead Surface pk
    stripped out, leaving any other still-valid pks in the list untouched."""
    from agents.models.surface_models import Surface
    from tables.models.graph_models import AgentNode

    live_surface = await sync_to_async(Surface.objects.create)(
        organization=graph.org, name="live-surface", owner_agent=None
    )
    dead_surface = await sync_to_async(Surface.objects.create)(
        organization=graph.org, name="dead-surface", owner_agent=None
    )
    node = await sync_to_async(AgentNode.objects.create)(
        graph=graph, node_name="Agent-1"
    )
    await sync_to_async(node.surface_list.set)([live_surface, dead_surface])
    dead_surface_id = dead_surface.id
    live_surface_id = live_surface.id
    await sync_to_async(dead_surface.delete)()

    snap = base_snapshot(
        save_version=graph.save_version,
        agent_node_list=[
            {
                "id": node.id,
                "graph": graph.id,
                "node_name": "Agent-1",
                "surface_list": [live_surface_id, dead_surface_id],
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r})."
    )

    await sync_to_async(node.refresh_from_db)()
    surviving_surface_ids = await sync_to_async(
        lambda: list(node.surface_list.values_list("id", flat=True))
    )()
    assert surviving_surface_ids == [live_surface_id]

    snapshot = await graph_state_service.get_snapshot(graph.id)
    assert snapshot["agent_node_list"][0]["surface_list"] == [live_surface_id]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_strips_cross_org_llm_config_and_logs_warning(
    graph, base_snapshot, flush_service, mocker
):
    """A live-snapshot ref to an LLMConfig that exists but belongs to a
    DIFFERENT org must be rejected exactly like a non-existent pk (no
    cross-org existence leak) — stripped and logged as a warning, not info,
    since it is a more serious drift than a plain delete."""
    from tables.models.graph_models import CodeAgentNode
    from tables.models.llm_models import LLMConfig
    from tables.models.rbac_models import Organization

    other_org = await sync_to_async(Organization.objects.create)(
        name="cross-org-llm-config-owner"
    )
    other_org_llm_config = await sync_to_async(LLMConfig.objects.create)(
        custom_name="other-org-llm-config", org=other_org
    )
    node = await sync_to_async(CodeAgentNode.objects.create)(
        graph=graph, node_name="CodeAgent-CrossOrg"
    )

    snap = base_snapshot(
        save_version=graph.save_version,
        code_agent_node_list=[
            {
                "id": node.id,
                "graph": graph.id,
                "node_name": "CodeAgent-CrossOrg",
                "llm_config": other_org_llm_config.id,
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    warning_spy = mocker.patch("tables.graph_collab.external_refs.logger.warning")

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r})."
    )

    await sync_to_async(node.refresh_from_db)()
    assert node.llm_config_id is None

    snapshot = await graph_state_service.get_snapshot(graph.id)
    assert snapshot["code_agent_node_list"][0]["llm_config"] is None

    warning_spy.assert_called_once()
    warning_message = warning_spy.call_args[0][0]
    assert "cross-org" in warning_message

    # The other org's LLMConfig row itself is untouched — only the stale
    # reference to it was stripped.
    assert await sync_to_async(
        LLMConfig.objects.filter(id=other_org_llm_config.id, org=other_org).exists
    )()


# ---------------------------------------------------------------------------
# null_external_refs must also refresh the touched node's cached
# content_hash in the live snapshot — otherwise the pre-delete hash stays
# armed as `_expected_hash` and every subsequent flush hits a false
# ContentHashConflictError forever, even though the ref itself was already
# correctly nulled. Only list_keys whose model participates in content_hash
# (the FK/O2O lives directly on `_meta.fields`, not a nested row or an M2M)
# can actually arm this — see the four cases below.
#
# For each: seed the snapshot via seed_from_db so the entry carries the REAL
# pre-delete content_hash (not a hand-typed stand-in), delete the referenced
# entity out-of-band (fires SET_NULL immediately, moving the DB row's real
# hash), then flush. The first flush is expected to hit
# ContentHashConflictError (the payload built from the still-stale snapshot),
# but the second flush — built from the snapshot null_external_refs already
# refreshed — must succeed.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_second_flush_succeeds_after_dead_subgraph_ref_refreshes_content_hash(
    graph, flush_service
):
    """SubGraphNode.subgraph deleted out-of-band must have the live
    snapshot's cached content_hash refreshed alongside the nulled ref, or the
    autosave loop wedges forever on ContentHashConflictError."""
    from tables.models import Graph
    from tables.models.graph_models import SubGraphNode

    subgraph = await sync_to_async(Graph.objects.create)(
        name="dead-subgraph-for-hash-refresh", org=graph.org
    )
    node = await sync_to_async(SubGraphNode.objects.create)(
        graph=graph, node_name="Subgraph-Hash-1", subgraph=subgraph
    )

    seeded = await graph_state_service.seed_from_db(graph.id)
    assert seeded is True

    await sync_to_async(subgraph.delete)()

    first = await flush_service.flush(graph.id)
    assert first.status is FlushStatus.FAILED
    assert first.failure_reason == "version_conflict", (
        "The first flush is expected to hit ContentHashConflictError — the "
        "payload built from the pre-refresh snapshot still carries the stale "
        f"hash. Got {first.failure_reason!r} instead."
    )

    second = await flush_service.flush(graph.id)
    assert second.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {second.status!r} "
        f"(failure_reason={second.failure_reason!r}). "
        "null_external_refs did not refresh the live snapshot's content_hash."
    )

    real_content_hash = await _content_hash_for("subgraph_node_list", node.id)
    snapshot = await graph_state_service.get_snapshot(graph.id)
    entry = snapshot["subgraph_node_list"][0]
    assert entry["subgraph"] is None
    assert entry["content_hash"] == real_content_hash


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_second_flush_succeeds_after_dead_telegram_secret_ref_refreshes_content_hash(
    graph, flush_service
):
    """TelegramTriggerNode.telegram_bot_api_key_secret_id deleted out-of-band
    must have the live snapshot's cached content_hash refreshed alongside the
    nulled ref."""
    from tables.models.graph_models import TelegramTriggerNode
    from tables.models.secret_models import Secret

    secret = await sync_to_async(Secret.objects.create)(
        org=graph.org, name="dead-telegram-secret-for-hash-refresh", value="ciphertext"
    )
    node = await sync_to_async(TelegramTriggerNode.objects.create)(
        graph=graph,
        node_name="Telegram-Hash-1",
        telegram_bot_api_key_secret=secret,
    )

    seeded = await graph_state_service.seed_from_db(graph.id)
    assert seeded is True

    await sync_to_async(secret.delete)()

    first = await flush_service.flush(graph.id)
    assert first.status is FlushStatus.FAILED
    assert first.failure_reason == "version_conflict", (
        f"Expected the first flush to hit ContentHashConflictError, got "
        f"{first.failure_reason!r}."
    )

    second = await flush_service.flush(graph.id)
    assert second.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {second.status!r} "
        f"(failure_reason={second.failure_reason!r}). "
        "null_external_refs did not refresh the live snapshot's content_hash."
    )

    real_content_hash = await _content_hash_for("telegram_trigger_node_list", node.id)
    snapshot = await graph_state_service.get_snapshot(graph.id)
    entry = snapshot["telegram_trigger_node_list"][0]
    assert entry["telegram_bot_api_key_secret_id"] is None
    assert entry["content_hash"] == real_content_hash


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_second_flush_succeeds_after_dead_task_agent_definition_ref_refreshes_content_hash(
    graph, flush_service
):
    """TaskNode.agent_definition deleted out-of-band must have the live
    snapshot's cached content_hash refreshed alongside the nulled ref."""
    from agents.models.agent_models import AgentDefinition
    from tables.models.graph_models import TaskNode

    agent_definition = await sync_to_async(AgentDefinition.objects.create)(
        organization=graph.org,
        name="dead-agent-def-for-hash-refresh",
        instructions="do things",
    )
    node = await sync_to_async(TaskNode.objects.create)(
        graph=graph, node_name="Task-Hash-1", agent_definition=agent_definition
    )

    seeded = await graph_state_service.seed_from_db(graph.id)
    assert seeded is True

    await sync_to_async(agent_definition.delete)()

    first = await flush_service.flush(graph.id)
    assert first.status is FlushStatus.FAILED
    assert first.failure_reason == "version_conflict", (
        f"Expected the first flush to hit ContentHashConflictError, got "
        f"{first.failure_reason!r}."
    )

    second = await flush_service.flush(graph.id)
    assert second.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {second.status!r} "
        f"(failure_reason={second.failure_reason!r}). "
        "null_external_refs did not refresh the live snapshot's content_hash."
    )

    real_content_hash = await _content_hash_for("task_node_list", node.id)
    snapshot = await graph_state_service.get_snapshot(graph.id)
    entry = snapshot["task_node_list"][0]
    assert entry["agent_definition"] is None
    assert entry["content_hash"] == real_content_hash


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_second_flush_succeeds_after_dead_agent_agent_definition_ref_refreshes_content_hash(
    graph, flush_service
):
    """AgentNode.agent_definition deleted out-of-band must have the live
    snapshot's cached content_hash refreshed alongside the nulled ref."""
    from agents.models.agent_models import AgentDefinition
    from tables.models.graph_models import AgentNode

    agent_definition = await sync_to_async(AgentDefinition.objects.create)(
        organization=graph.org,
        name="dead-agent-def-for-agent-node-hash-refresh",
        instructions="do things",
    )
    node = await sync_to_async(AgentNode.objects.create)(
        graph=graph, node_name="Agent-Hash-1", agent_definition=agent_definition
    )

    seeded = await graph_state_service.seed_from_db(graph.id)
    assert seeded is True

    await sync_to_async(agent_definition.delete)()

    first = await flush_service.flush(graph.id)
    assert first.status is FlushStatus.FAILED
    assert first.failure_reason == "version_conflict", (
        f"Expected the first flush to hit ContentHashConflictError, got "
        f"{first.failure_reason!r}."
    )

    second = await flush_service.flush(graph.id)
    assert second.status is FlushStatus.SAVED, (
        f"Expected SAVED but got {second.status!r} "
        f"(failure_reason={second.failure_reason!r}). "
        "null_external_refs did not refresh the live snapshot's content_hash."
    )

    real_content_hash = await _content_hash_for("agent_node_list", node.id)
    snapshot = await graph_state_service.get_snapshot(graph.id)
    entry = snapshot["agent_node_list"][0]
    assert entry["agent_definition"] is None
    assert entry["content_hash"] == real_content_hash


# ---------------------------------------------------------------------------
# Fields that must NOT arm CAS: agent_node_list.surface_list is an M2M
# (excluded from ContentHashMixin.generate_hash's `self._meta.fields` scan),
# and the nested webhook_trigger.ngrok_webhook_config only affects the
# WebhookTrigger row — TelegramTriggerNode's own hash is computed over
# webhook_trigger_id, which is unchanged by that nested delete. Neither
# out-of-band delete should ever cause a ContentHashConflictError, and the
# refresh call must not fabricate a content_hash key where the snapshot entry
# never carried one (both built by hand here, mirroring the FE's
# node_created payload shape rather than a DB reseed).
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_succeeds_first_try_after_dead_surface_ref(
    graph, base_snapshot, flush_service
):
    """Deleting a Surface referenced via AgentNode.surface_list (M2M) must not
    arm CAS — the flush must succeed on the FIRST attempt, unlike the scalar
    ref cases above which need a second attempt to recover."""
    from agents.models.surface_models import Surface
    from tables.models.graph_models import AgentNode

    live_surface = await sync_to_async(Surface.objects.create)(
        organization=graph.org, name="live-surface-hash-guard", owner_agent=None
    )
    dead_surface = await sync_to_async(Surface.objects.create)(
        organization=graph.org, name="dead-surface-hash-guard", owner_agent=None
    )
    node = await sync_to_async(AgentNode.objects.create)(
        graph=graph, node_name="Agent-Hash-Guard"
    )
    await sync_to_async(node.surface_list.set)([live_surface, dead_surface])
    dead_surface_id = dead_surface.id
    live_surface_id = live_surface.id
    await sync_to_async(dead_surface.delete)()

    snap = base_snapshot(
        save_version=graph.save_version,
        agent_node_list=[
            {
                "id": node.id,
                "graph": graph.id,
                "node_name": "Agent-Hash-Guard",
                "surface_list": [live_surface_id, dead_surface_id],
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED on the first attempt but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). A dead M2M ref must "
        "never arm CAS."
    )

    snapshot = await graph_state_service.get_snapshot(graph.id)
    entry = snapshot["agent_node_list"][0]
    assert entry["surface_list"] == [live_surface_id]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_flush_succeeds_first_try_after_dead_ngrok_ref(
    graph, base_snapshot, flush_service
):
    """Deleting the NgrokWebhookConfig nested under webhook_trigger must not
    arm CAS — TelegramTriggerNode's own content_hash is computed over
    webhook_trigger_id, not the nested ngrok row, so the flush must succeed
    on the FIRST attempt, unlike the scalar ref cases above."""
    from tables.models.graph_models import TelegramTriggerNode
    from tables.models.webhook_models import NgrokWebhookConfig, WebhookTrigger

    ngrok_config = await sync_to_async(NgrokWebhookConfig.objects.create)(
        name="dead-ngrok-hash-guard", auth_token="dead-ngrok-hash-guard-token"
    )
    webhook_trigger = await sync_to_async(WebhookTrigger.objects.create)(
        path="dead-ngrok-hash-guard-path", ngrok_webhook_config=ngrok_config
    )
    node = await sync_to_async(TelegramTriggerNode.objects.create)(
        graph=graph, node_name="Telegram-Hash-Guard", webhook_trigger=webhook_trigger
    )
    await sync_to_async(ngrok_config.delete)()

    snap = base_snapshot(
        save_version=graph.save_version,
        telegram_trigger_node_list=[
            {
                "id": node.id,
                "graph": graph.id,
                "node_name": "Telegram-Hash-Guard",
                "webhook_trigger": {
                    "path": webhook_trigger.path,
                    "ngrok_webhook_config": ngrok_config.id,
                },
                "fields": [],
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    outcome = await flush_service.flush(graph.id)

    assert outcome.status is FlushStatus.SAVED, (
        f"Expected SAVED on the first attempt but got {outcome.status!r} "
        f"(failure_reason={outcome.failure_reason!r}). A dead nested ngrok "
        "ref must never arm CAS on the containing node."
    )

    snapshot = await graph_state_service.get_snapshot(graph.id)
    entry = snapshot["telegram_trigger_node_list"][0]
    assert entry["webhook_trigger"]["ngrok_webhook_config"] is None


# ---------------------------------------------------------------------------
# White-box: null_external_refs itself must never fabricate a content_hash
# key for a snapshot entry that never carried one — regardless of whether the
# ref that got nulled would have armed CAS. This is exercised directly
# against null_external_refs (bypassing the full flush pipeline) because a
# SAVED flush always separately runs apply_id_remap's
# _refresh_flushed_content_hashes, which itself unconditionally ADDS
# content_hash to any entry missing it (see test_content_hash_refresh.py) —
# going through a full successful flush would conflate that pre-existing
# behavior with null_external_refs's own guard.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_null_external_refs_does_not_fabricate_content_hash_for_surface_list(
    graph, base_snapshot
):
    """surface_list is an M2M, excluded from ContentHashMixin.generate_hash's
    `_meta.fields` scan — null_external_refs's content_hash refresh must
    still respect the `"content_hash" in entry` guard and not invent the key."""
    from agents.models.surface_models import Surface
    from tables.graph_collab.external_refs import DeadRef
    from tables.models.graph_models import AgentNode
    from tables.services.graph_bulk_save_service.registry import NODE_TYPE_REGISTRY

    dead_surface = await sync_to_async(Surface.objects.create)(
        organization=graph.org, name="dead-surface-null-refs", owner_agent=None
    )
    node = await sync_to_async(AgentNode.objects.create)(
        graph=graph, node_name="Agent-Null-Refs"
    )
    dead_surface_id = dead_surface.id

    snap = base_snapshot(
        save_version=graph.save_version,
        agent_node_list=[
            {
                "id": node.id,
                "graph": graph.id,
                "node_name": "Agent-Null-Refs",
                "surface_list": [dead_surface_id],
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    ref_field = next(
        f
        for config in NODE_TYPE_REGISTRY
        if config.list_key == "agent_node_list"
        for f in config.external_ref_fields
        if f.top_level_field == "surface_list"
    )
    dead_ref = DeadRef(
        "agent_node_list", node.id, ref_field, dead_surface_id, "deleted"
    )

    broadcasts = await graph_state_service.null_external_refs(graph.id, [dead_ref])

    assert len(broadcasts) == 1
    assert "content_hash" not in broadcasts[0]["node"]

    snapshot = await graph_state_service.get_snapshot(graph.id)
    entry = snapshot["agent_node_list"][0]
    assert entry["surface_list"] == []
    assert "content_hash" not in entry, (
        "The entry never carried a content_hash key — null_external_refs "
        "must not fabricate one."
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_null_external_refs_does_not_fabricate_content_hash_for_nested_ngrok(
    graph, base_snapshot
):
    """TelegramTriggerNode's content_hash is computed over webhook_trigger_id,
    not the nested ngrok row — null_external_refs's content_hash refresh
    must still respect the `"content_hash" in entry` guard and not invent
    the key when nulling the nested ngrok_webhook_config ref."""
    from tables.graph_collab.external_refs import DeadRef
    from tables.models.graph_models import TelegramTriggerNode
    from tables.models.webhook_models import NgrokWebhookConfig, WebhookTrigger
    from tables.services.graph_bulk_save_service.registry import NODE_TYPE_REGISTRY

    ngrok_config = await sync_to_async(NgrokWebhookConfig.objects.create)(
        name="dead-ngrok-null-refs", auth_token="dead-ngrok-null-refs-token"
    )
    webhook_trigger = await sync_to_async(WebhookTrigger.objects.create)(
        path="dead-ngrok-null-refs-path", ngrok_webhook_config=ngrok_config
    )
    node = await sync_to_async(TelegramTriggerNode.objects.create)(
        graph=graph, node_name="Telegram-Null-Refs", webhook_trigger=webhook_trigger
    )
    dead_ngrok_id = ngrok_config.id

    snap = base_snapshot(
        save_version=graph.save_version,
        telegram_trigger_node_list=[
            {
                "id": node.id,
                "graph": graph.id,
                "node_name": "Telegram-Null-Refs",
                "webhook_trigger": {
                    "path": webhook_trigger.path,
                    "ngrok_webhook_config": dead_ngrok_id,
                },
                "fields": [],
            }
        ],
    )
    await graph_state_service.seed(graph.id, snap)

    ref_field = next(
        f
        for config in NODE_TYPE_REGISTRY
        if config.list_key == "telegram_trigger_node_list"
        for f in config.external_ref_fields
        if f.top_level_field == "webhook_trigger"
    )
    dead_ref = DeadRef(
        "telegram_trigger_node_list", node.id, ref_field, dead_ngrok_id, "deleted"
    )

    broadcasts = await graph_state_service.null_external_refs(graph.id, [dead_ref])

    assert len(broadcasts) == 1
    assert "content_hash" not in broadcasts[0]["node"]

    snapshot = await graph_state_service.get_snapshot(graph.id)
    entry = snapshot["telegram_trigger_node_list"][0]
    assert entry["webhook_trigger"]["ngrok_webhook_config"] is None
    assert "content_hash" not in entry, (
        "The entry never carried a content_hash key — null_external_refs "
        "must not fabricate one."
    )
