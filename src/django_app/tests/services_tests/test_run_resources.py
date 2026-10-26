"""What a run uses: the walk of `RUN_REFERENCES` over real rows.

`World` creates rows the way an organization would, giving every reference its own target
row, so a reference the walk failed to follow leaves its target out of the result.
"""

import dataclasses
import itertools
import uuid
from collections import defaultdict

import pytest
from django.apps import apps
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from rbac.models import Organization
from tables.services.run_admission import RunKind, RunSubject
from tables.services.run_resources import (
    CODE_SLOT_STORAGE_FLAGS,
    RUN_REFERENCES,
    FollowChildren,
    FollowField,
    ResourceRef,
    RunResourceCollector,
    RunResources,
    _Walk,
    _walk_plan,
    unqueried_child_references,
)
from tests.fixtures import _make_secret

SURFACE_SEARCH_CONFIGS = ("NaiveSearchConfig",) + tuple(
    f"Graph{kind}SearchConfig" for kind in ("Basic", "Local", "Global", "Drift")
)
KNOWLEDGE_NODE_SEARCH_CONFIGS = ("tables.KnowledgeNodeNaiveRagSearchConfig",) + tuple(
    f"tables.KnowledgeNodeGraphRag{kind}SearchConfig"
    for kind in ("Basic", "Local", "Global", "Drift")
)


def ref(row) -> ResourceRef:
    return ResourceRef(row._meta.label, row.pk)


class World:
    """Rows of one organization, remembered by model label as they are created."""

    def __init__(self, org):
        self.org = org
        self.made: dict[str, list] = defaultdict(list)
        self._numbers = itertools.count()

    def make(self, label: str, **fields):
        row = apps.get_model(label).objects.create(**fields)
        self.made[label].append(row)
        return row

    def name(self, prefix: str) -> str:
        return f"{prefix}-{next(self._numbers)}"

    def secret(self):
        row = _make_secret(self.org, self.name("secret"), "value")
        self.made["tables.Secret"].append(row)
        return row

    def llm_config(self):
        model = self.make("tables.LLMModel", name=self.name("llm"), org=self.org)
        return self.make(
            "tables.LLMConfig",
            custom_name=self.name("llm-config"),
            model=model,
            api_key_secret=self.secret(),
            org=self.org,
        )

    def embedding_config(self):
        model = self.make("tables.EmbeddingModel", name=self.name("embedding"), org=self.org)
        return self.make(
            "tables.EmbeddingConfig",
            custom_name=self.name("embedding-config"),
            model=model,
            api_key_secret=self.secret(),
            org=self.org,
        )

    def python_code(self):
        code = self.make("tables.PythonCode", code="def main(): return 1", entrypoint="main")
        code.secrets.set([self.secret()])
        return code

    def storage_file(self, *, folder: bool = False):
        name = self.name("item")
        return self.make(
            "tables.StorageFile",
            org=self.org,
            name=name,
            path=f"{name}/" if folder else f"{name}.txt",
            item_type="folder" if folder else "file",
        )

    def collection(self):
        collection = self.make(
            "tables.SourceCollection", collection_name=self.name("collection"), org=self.org
        )
        naive = self.make("tables.BaseRagType", rag_type="naive", source_collection=collection)
        self.make("tables.NaiveRag", base_rag_type=naive, embedder=self.embedding_config())
        graph = self.make("tables.BaseRagType", rag_type="graph", source_collection=collection)
        self.make(
            "tables.GraphRag",
            base_rag_type=graph,
            embedder=self.embedding_config(),
            llm=self.llm_config(),
        )
        return collection

    def python_tool(self):
        return self.make(
            "tables.PythonCodeTool",
            name=self.name("tool"),
            description="tool",
            python_code=self.python_code(),
            org=self.org,
        )

    def mcp_tool(self):
        return self.make(
            "tables.McpTool",
            name=self.name("mcp"),
            transport="https://mcp.example.com/sse",
            tool_name="search",
            auth_secret=self.secret(),
            org=self.org,
        )

    def surface_items(self, prefix: str, parent_field: str, parent) -> None:
        """Give a surface one item of every kind, and its knowledge every search config."""
        self.make(
            f"agents.{prefix}PythonTool",
            **{parent_field: parent},
            python_tool=self.python_tool(),
            mode="allow",
        )
        self.make(
            f"agents.{prefix}McpTool", **{parent_field: parent}, mcp_tool=self.mcp_tool(), mode="deny"
        )
        self.make(
            f"agents.{prefix}StorageItem", **{parent_field: parent}, storage_file=self.storage_file()
        )
        knowledge = self.make(
            f"agents.{prefix}Knowledge", **{parent_field: parent}, collection=self.collection()
        )
        for config in SURFACE_SEARCH_CONFIGS:
            self.make(f"agents.{prefix}{config}", surface_knowledge=knowledge)

    def surface(self, owner_agent=None):
        surface = self.make(
            "agents.Surface", name=self.name("surface"), org=self.org, owner_agent=owner_agent
        )
        self.surface_items("Surface", "surface", surface)
        return surface

    def agent_definition(self):
        agent = self.make(
            "agents.AgentDefinition",
            name=self.name("agent"),
            org=self.org,
            llm_config=self.llm_config(),
            fcm_llm_config=self.llm_config(),
        )
        self.make(
            "agents.AgentDefaultSurface", agent_definition=agent, surface=self.surface(), place="all"
        )
        self.surface(owner_agent=agent)
        self.make(
            "tables.RealtimeAgentDefinition",
            agent_definition=agent,
            openai_config=self.make(
                "tables.OpenAIRealtimeConfig",
                custom_name=self.name("openai"),
                api_key_secret=self.secret(),
                transcription_api_key_secret=self.secret(),
                org=self.org,
            ),
            elevenlabs_config=self.make(
                "tables.ElevenLabsRealtimeConfig",
                custom_name=self.name("elevenlabs"),
                api_key_secret=self.secret(),
                org=self.org,
            ),
            gemini_config=self.make(
                "tables.GeminiRealtimeConfig",
                custom_name=self.name("gemini"),
                api_key_secret=self.secret(),
                org=self.org,
            ),
        )
        return agent

    def webhook_trigger(self, *, tunnel: str, auth_kind: str):
        trigger = self.make("tables.WebhookTrigger", path=self.name("path"), org=self.org)
        self.make("tables.WebhookTriggerAuth", trigger=trigger, kind=auth_kind, secret=self.secret())
        if tunnel == "ngrok":
            self.make(
                "tables.NgrokWebhookConfig",
                name=self.name("ngrok"),
                trigger=trigger,
                auth_token_secret=self.secret(),
            )
        else:
            self.make(
                "tables.LocalhostWebhookConfig",
                name=self.name("localhost"),
                trigger=trigger,
            )
        return trigger

    def flow(self, *, subflow=None, copies: int = 1):
        """A flow with `copies` nodes of every type, each with references of its own."""
        graph = self.make("tables.Graph", name=self.name("flow"), org=self.org)
        self.make("tables.StartNode", graph=graph, variables={"variables": {}})
        self.make("tables.EndNode", graph=graph, output_map={})
        for _ in range(copies):
            self._nodes(graph, subflow)
        return graph

    def _nodes(self, graph, subflow) -> None:
        self.make("tables.PythonNode", graph=graph, python_code=self.python_code())
        knowledge_node = self.make(
            "tables.KnowledgeNode", graph=graph, source_collection=self.collection()
        )
        for config in KNOWLEDGE_NODE_SEARCH_CONFIGS:
            self.make(config, knowledge_node=knowledge_node)
        self.make(
            "tables.KeyValueNode",
            graph=graph,
            key_value_table=self.make(
                "tables.KeyValueTable", name=self.name("table"), org=self.org
            ),
        )
        if subflow is not None:
            self.make("tables.SubGraphNode", graph=graph, subgraph=subflow)
        self.make(
            "tables.WebhookTriggerNode",
            graph=graph,
            node_name=self.name("hook"),
            python_code=self.python_code(),
            webhook_trigger=self.webhook_trigger(tunnel="ngrok", auth_kind="webhook"),
        )
        telegram_node = self.make(
            "tables.TelegramTriggerNode",
            graph=graph,
            node_name=self.name("bot"),
            webhook_trigger=self.webhook_trigger(tunnel="localhost", auth_kind="telegram"),
            telegram_bot_api_key_secret=self.secret(),
        )
        self.make(
            "tables.TelegramTriggerNodeField",
            telegram_trigger_node=telegram_node,
            parent="message",
            field_name="text",
            variable_path="variables.text",
        )
        table = self.make(
            "tables.ClassificationDecisionTableNode",
            graph=graph,
            node_name=self.name("classify"),
            default_llm_config=self.llm_config(),
            pre_python_code=self.python_code(),
            post_python_code=self.python_code(),
        )
        prompt = self.make(
            "tables.ClassificationDecisionTablePrompt",
            cdt_node=table,
            prompt_key="route",
            llm_config=self.llm_config(),
        )
        section = self.make(
            "tables.ClassificationConditionGroupSection",
            id=uuid.uuid4(),
            classification_decision_table_node=table,
        )
        self.make(
            "tables.ClassificationConditionGroup",
            classification_decision_table_node=table,
            group_name="first",
            prompt=prompt,
            section=section,
        )
        task_node = self.make(
            "tables.TaskNode", graph=graph, agent_definition=self.agent_definition()
        )
        task_node.surface_list.set([self.surface()])
        inline = self.make("agents.InlineSurface", task_node=task_node)
        self.surface_items("InlineSurface", "inline_surface", inline)
        agent_node = self.make(
            "tables.AgentNode", graph=graph, agent_definition=self.agent_definition()
        )
        agent_node.surface_list.set([self.surface()])
        agent_inline = self.make("agents.AgentInlineSurface", agent_node=agent_node)
        self.surface_items("AgentInlineSurface", "agent_inline_surface", agent_inline)
        self.make("tables.AgentNodeTask", agent_node=agent_node, name=self.name("task"), order=0)
        self.make("tables.GraphStorageFile", graph=graph, storage_file=self.storage_file())
        self.make("tables.FileExtractorNode", graph=graph)
        self.make("tables.AudioTranscriptionNode", graph=graph)
        self.make("tables.Edge", graph=graph, start_node_id=next(self._numbers), end_node_id=0)
        decision = self.make("tables.DecisionTableNode", graph=graph)
        group = self.make(
            "tables.ConditionGroup",
            decision_table_node=decision,
            group_name=self.name("group"),
            group_type="simple",
        )
        self.make(
            "tables.Condition", condition_group=group, condition_name="c", condition="True"
        )
        self.make("tables.ScheduleTriggerNode", graph=graph, node_name=self.name("schedule"))

    def voice_channel(self, *, auth_token: bool = True, tunnel: bool = True):
        """A voice channel with Twilio settings.

        Saving a Twilio channel copies its auth token secret onto its webhook trigger's
        auth, so a test that needs to see the walk follow each of the two on its own
        builds a channel with only one of them.
        """
        channel = self.make(
            "tables.RealtimeChannel",
            name=self.name("channel"),
            org=self.org,
            realtime_agent_definition=self.agent_definition().realtime_agent,
        )
        self.make(
            "tables.TwilioChannel",
            channel=channel,
            account_sid="AC_test",
            phone_number=self.name("+1555"),
            auth_token_secret=self.secret() if auth_token else None,
            webhook_trigger=(
                self.make("tables.WebhookTrigger", path=self.name("voice"), org=self.org)
                if tunnel
                else None
            ),
        )
        return channel


@pytest.fixture
def world(default_org, mock_telegram_service):
    return World(default_org)


def _collect(kind: RunKind, row) -> RunResources:
    return RunResourceCollector().collect(RunSubject(kind, row.pk, row.org_id))


def _expected_targets(world: World, row: FollowField | FollowChildren) -> set[ResourceRef]:
    """The rows `row` must bring into the walk, read from the created rows themselves."""
    if isinstance(row, FollowChildren):
        return {ref(child) for child in world.made[row.child]}
    expected = set()
    for source in world.made[row.model]:
        field = source._meta.get_field(row.field)
        if field.many_to_many:
            expected |= {ref(target) for target in getattr(source, row.field).all()}
        elif getattr(source, field.attname) is not None:
            expected.add(ResourceRef(field.related_model._meta.label, getattr(source, field.attname)))
    return expected


@pytest.mark.django_db
def test_every_reference_row_brings_its_targets_into_the_walk(world):
    subflow = world.flow()
    flow = world.flow(subflow=subflow)
    channels = [world.voice_channel(tunnel=False), world.voice_channel(auth_token=False)]
    reached = _collect(RunKind.FLOW, flow).refs.union(
        *(_collect(RunKind.VOICE_CHANNEL, channel).refs for channel in channels)
    )
    unqueried = unqueried_child_references()

    rows_without_a_case = [row for row in RUN_REFERENCES if not _expected_targets(world, row)]
    rows_not_followed = [
        row
        for row in RUN_REFERENCES
        if row not in unqueried and not _expected_targets(world, row) <= reached
    ]
    unqueried_rows_reached = [
        row for row in unqueried if _expected_targets(world, row) & reached
    ]

    assert rows_without_a_case == []
    assert rows_not_followed == []
    assert unqueried_rows_reached == []


@pytest.mark.django_db
def test_subflows_are_walked_transitively(world):
    innermost = world.flow()
    middle = world.flow(subflow=innermost)
    outer = world.flow(subflow=middle)

    reached = _collect(RunKind.FLOW, outer).refs

    assert {ref(middle), ref(innermost)} <= reached
    innermost_code = world.made["tables.PythonNode"][0].python_code
    assert ref(innermost_code) in reached


@pytest.mark.django_db
def test_a_subflow_cycle_terminates_with_both_flows(world):
    first = world.make("tables.Graph", name="cycle-a", org=world.org)
    second = world.make("tables.Graph", name="cycle-b", org=world.org)
    world.make("tables.SubGraphNode", graph=first, subgraph=second)
    world.make("tables.SubGraphNode", graph=second, subgraph=first)
    code = world.python_code()
    world.make("tables.PythonNode", graph=second, python_code=code)

    reached = _collect(RunKind.FLOW, first).refs

    assert {ref(first), ref(second), ref(code)} <= reached
    assert _collect(RunKind.FLOW, second).refs == reached


@pytest.mark.django_db
def test_an_attached_folder_gives_its_path_and_a_file_gives_its_row(world):
    flow = world.make("tables.Graph", name="files", org=world.org)
    folder = world.storage_file(folder=True)
    file = world.storage_file()
    world.make("tables.GraphStorageFile", graph=flow, storage_file=folder)
    world.make("tables.GraphStorageFile", graph=flow, storage_file=file)

    resources = _collect(RunKind.FLOW, flow)

    assert resources.storage_prefixes == frozenset({folder.path})
    assert folder.path.endswith("/")
    assert {ref(folder), ref(file)} <= resources.refs
    assert resources.pks_of("tables.StorageFile") == {folder.pk, file.pk}


@pytest.mark.django_db
def test_a_binned_node_is_not_followed(world):
    flow = world.make("tables.Graph", name="binned-node", org=world.org)
    code = world.python_code()
    node = world.make("tables.PythonNode", graph=flow, python_code=code)
    type(node).all_objects.filter(pk=node.pk).update(active=False, soft_deleted_at=timezone.now())

    reached = _collect(RunKind.FLOW, flow).refs

    assert ref(node) not in reached
    assert ref(code) not in reached


@pytest.mark.django_db
def test_a_binned_forward_target_is_still_followed(world):
    flow = world.make("tables.Graph", name="binned-agent", org=world.org)
    agent = world.agent_definition()
    world.make("tables.TaskNode", graph=flow, agent_definition=agent)
    type(agent).all_objects.filter(pk=agent.pk).update(active=False, soft_deleted_at=timezone.now())

    reached = _collect(RunKind.FLOW, flow).refs

    assert ref(agent) in reached
    assert {ref(agent.llm_config), ref(agent.llm_config.api_key_secret)} <= reached


@pytest.mark.django_db
def test_collecting_many_flows_equals_collecting_each(world):
    shared_subflow = world.flow()
    flows = [world.flow(subflow=shared_subflow), world.flow(), shared_subflow]
    collector = RunResourceCollector()

    together = collector.collect_many(RunKind.FLOW, [flow.pk for flow in flows])

    assert together == {
        flow.pk: collector.collect(RunSubject(RunKind.FLOW, flow.pk, flow.org_id))
        for flow in flows
    }
    assert together[flows[0].pk].refs > together[shared_subflow.pk].refs
    assert not together[flows[1].pk].refs & together[shared_subflow.pk].refs


def _queries_to_collect(kind: RunKind, subject_ids: list[int]) -> int:
    with CaptureQueriesContext(connection) as queries:
        RunResourceCollector().collect_many(kind, subject_ids)
    return len(queries.captured_queries)


@pytest.mark.django_db
def test_the_query_count_does_not_grow_with_the_number_of_nodes(world):
    one_of_each = world.flow(subflow=world.flow())
    five_of_each = world.flow(subflow=world.flow(copies=5), copies=5)

    assert _queries_to_collect(RunKind.FLOW, [one_of_each.pk]) == _queries_to_collect(
        RunKind.FLOW, [five_of_each.pk]
    )


@pytest.mark.django_db
def test_each_level_of_subflows_costs_one_query(world):
    flat = world.flow()
    one_level = world.flow(subflow=world.flow())
    two_levels = world.flow(subflow=world.flow(subflow=world.flow()))

    counts = [_queries_to_collect(RunKind.FLOW, [flow.pk]) for flow in (flat, one_level, two_levels)]

    assert counts == [counts[0], counts[0] + 1, counts[0] + 2]
    assert _queries_to_collect(RunKind.FLOW, [flat.pk, one_level.pk, two_levels.pk]) == counts[2]


def _small_flow(world: World):
    flow = world.make("tables.Graph", name=world.name("small"), org=world.org)
    world.make("tables.PythonNode", graph=flow, python_code=world.python_code())
    world.make("tables.TaskNode", graph=flow, agent_definition=world.agent_definition())
    world.make("tables.KnowledgeNode", graph=flow, source_collection=world.collection())
    return flow


@pytest.mark.django_db
def test_the_query_count_does_not_grow_with_the_number_of_flows(world):
    three = [_small_flow(world).pk for _ in range(3)]
    thirty = [_small_flow(world).pk for _ in range(30)]

    assert _queries_to_collect(RunKind.FLOW, three) == _queries_to_collect(RunKind.FLOW, thirty)


@pytest.mark.django_db
def test_a_realtime_start_walks_the_agent_and_its_voice_configs(world):
    agent = world.agent_definition()
    realtime = agent.realtime_agent

    reached = _collect(RunKind.REALTIME, agent).refs

    assert {
        ref(agent),
        ref(agent.llm_config),
        ref(agent.fcm_llm_config),
        ref(realtime),
        ref(realtime.openai_config.api_key_secret),
        ref(realtime.openai_config.transcription_api_key_secret),
        ref(realtime.elevenlabs_config.api_key_secret),
        ref(realtime.gemini_config.api_key_secret),
    } <= reached
    owned_surface = world.made["agents.Surface"][1]
    default_surface = world.made["agents.Surface"][0]
    assert owned_surface.owner_agent_id == agent.pk
    assert {ref(owned_surface), ref(default_surface)} <= reached


@pytest.mark.django_db
def test_a_voice_channel_start_walks_its_agent_and_its_twilio_settings(world):
    channel = world.voice_channel()
    twilio = channel.twilio
    agent = channel.realtime_agent_definition.agent_definition

    reached = _collect(RunKind.VOICE_CHANNEL, channel).refs

    assert {
        ref(channel),
        ref(channel.realtime_agent_definition),
        ref(agent),
        ref(agent.llm_config),
        ref(twilio),
        ref(twilio.auth_token_secret),
        ref(twilio.webhook_trigger),
    } <= reached


@pytest.mark.django_db
def test_a_code_start_walks_the_code_and_adds_what_holds_it_without_walking_it(world):
    flow = world.make("tables.Graph", name="code-holder", org=world.org)
    node_code = world.python_code()
    world.make("tables.PythonNode", graph=flow, python_code=node_code)
    other_agent = world.agent_definition()
    world.make("tables.TaskNode", graph=flow, agent_definition=other_agent)
    tool = world.python_tool()

    node_run = RunResourceCollector().collect(RunSubject(RunKind.CODE, node_code.pk, world.org.pk))
    tool_run = RunResourceCollector().collect(
        RunSubject(RunKind.CODE, tool.python_code_id, world.org.pk)
    )

    assert node_run.refs == {
        ref(node_code),
        *(ref(secret) for secret in node_code.secrets.all()),
        ref(flow),
    }
    assert ref(other_agent) not in node_run.refs
    assert tool_run.refs == {
        ref(tool.python_code),
        *(ref(secret) for secret in tool.python_code.secrets.all()),
        ref(tool),
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    "holder_label, code_fields",
    [
        ("tables.WebhookTriggerNode", ("python_code",)),
        ("tables.ClassificationDecisionTableNode", ("pre_python_code", "post_python_code")),
    ],
)
def test_a_code_start_is_held_by_the_flow_of_every_node_kind_with_code(
    world, holder_label, code_fields
):
    flow = world.make("tables.Graph", name="code-node-flow", org=world.org)
    codes = {field: world.python_code() for field in code_fields}
    world.make(holder_label, graph=flow, node_name="holder", **codes)

    for code in codes.values():
        resources = RunResourceCollector().collect(RunSubject(RunKind.CODE, code.pk, world.org.pk))
        assert ref(flow) in resources.refs


@pytest.fixture
def flow_with_attached_storage(world):
    flow = world.make("tables.Graph", name="attached-storage", org=world.org)
    attached_file = world.storage_file()
    attached_folder = world.storage_file(folder=True)
    for storage_file in (attached_file, attached_folder):
        world.make("tables.GraphStorageFile", graph=flow, storage_file=storage_file)
    return flow, attached_file, attached_folder


@pytest.mark.django_db
@pytest.mark.parametrize("uses_storage", [True, False], ids=["storage-on", "storage-off"])
@pytest.mark.parametrize("model_label, code_field", sorted(CODE_SLOT_STORAGE_FLAGS))
def test_a_code_run_counts_the_flow_s_attached_storage_while_its_slot_uses_storage(
    world, flow_with_attached_storage, model_label, code_field, uses_storage
):
    flow, attached_file, attached_folder = flow_with_attached_storage
    code = world.python_code()
    world.make(
        model_label,
        graph=flow,
        node_name="holder",
        **{code_field: code, CODE_SLOT_STORAGE_FLAGS[(model_label, code_field)]: uses_storage},
    )

    resources = RunResourceCollector().collect(RunSubject(RunKind.CODE, code.pk, world.org.pk))

    attached = {ref(attached_file), ref(attached_folder)}
    assert ref(flow) in resources.refs
    if uses_storage:
        assert attached <= resources.refs
        assert resources.storage_prefixes == {attached_folder.path}
    else:
        assert not attached & resources.refs
        assert resources.storage_prefixes == frozenset()


@pytest.mark.django_db
def test_a_code_run_counts_only_the_storage_of_the_flows_holding_its_code(
    world, flow_with_attached_storage
):
    flow, attached_file, _ = flow_with_attached_storage
    other_flow = world.make("tables.Graph", name="other-storage", org=world.org)
    code = world.python_code()
    world.make("tables.PythonNode", graph=other_flow, python_code=code, use_storage=True)
    unrelated = world.python_code()
    world.make("tables.PythonNode", graph=flow, python_code=unrelated, use_storage=True)

    resources = RunResourceCollector().collect_many(RunKind.CODE, [code.pk, unrelated.pk])

    assert ref(attached_file) not in resources[code.pk].refs
    assert ref(attached_file) in resources[unrelated.pk].refs


def test_every_storage_flag_belongs_to_a_followed_code_slot_of_a_flow_node():
    flow_nodes = {
        row.child for row in RUN_REFERENCES if isinstance(row, FollowChildren) and row.fk == "graph"
    }
    wrong = []
    for (model_label, code_field), flag in CODE_SLOT_STORAGE_FLAGS.items():
        model = apps.get_model(model_label)
        code_slot = model._meta.get_field(code_field)
        if (
            FollowField(model_label, code_field) not in RUN_REFERENCES
            or code_slot.related_model._meta.label != "tables.PythonCode"
            or model_label not in flow_nodes
            or model._meta.get_field(flag).get_internal_type() != "BooleanField"
        ):
            wrong.append((model_label, code_field, flag))

    assert wrong == []


@pytest.mark.django_db
def test_ids_given_as_text_reach_the_same_rows(world):
    flow = world.flow()
    collector = RunResourceCollector()

    as_text = collector.collect(RunSubject(RunKind.FLOW, str(flow.pk), str(world.org.pk)))

    assert as_text == collector.collect(RunSubject(RunKind.FLOW, flow.pk, world.org.pk))
    assert ref(world.made["tables.PythonNode"][0]) in as_text.refs
    assert list(collector.collect_many(RunKind.FLOW, [str(flow.pk)])) == [flow.pk]


@pytest.mark.django_db
def test_a_walk_with_no_place_for_a_reached_model_fails_instead_of_looping(world):
    code = world.python_code()
    plan = _walk_plan()
    without_secrets = dataclasses.replace(
        plan, model_order=tuple(label for label in plan.model_order if label != "tables.Secret")
    )

    with pytest.raises(RuntimeError, match=r"no place for \['tables.Secret'\]"):
        _Walk(without_secrets).run([ref(code)])


@pytest.mark.django_db
def test_a_start_that_does_not_exist_reaches_only_itself():
    resources = RunResourceCollector().collect(RunSubject(RunKind.FLOW, 987654, 1))

    assert resources == RunResources(
        refs=frozenset({ResourceRef("tables.Graph", 987654)}), storage_prefixes=frozenset()
    )


@pytest.mark.django_db
def test_no_starts_cost_no_queries():
    assert _queries_to_collect(RunKind.FLOW, []) == 0


# ---- header markers ----


def _marker_headers(*names: str) -> dict[str, str]:
    return {f"X-Key-{number}": f"Bearer epicstaff_secret({name})" for number, name in enumerate(names)}


def _flow_asking(world: World, *configs):
    """A flow whose decision table asks each of `configs`, one prompt each."""
    flow = world.make("tables.Graph", name=world.name("markers"), org=world.org)
    node = world.make("tables.ClassificationDecisionTableNode", graph=flow, node_name=world.name("cdt"))
    for number, config in enumerate(configs):
        world.make(
            "tables.ClassificationDecisionTablePrompt", cdt_node=node, prompt_key=f"p{number}", llm_config=config
        )
    return flow


def _config_with_headers(world: World, headers: dict[str, str]):
    return world.make("tables.LLMConfig", custom_name=world.name("cfg"), org=world.org, extra_headers=headers)


@pytest.mark.django_db
def test_a_header_marker_reaches_the_live_secret_of_its_name_in_the_row_s_organization(world):
    live = world.secret()
    binned = world.secret()
    type(binned).all_objects.filter(pk=binned.pk).update(active=False, soft_deleted_at=timezone.now())
    elsewhere = _make_secret(Organization.objects.create(name="Markers elsewhere"), live.name, "value")
    config = _config_with_headers(world, _marker_headers(live.name, binned.name, "nobody"))

    resources = _collect(RunKind.FLOW, _flow_asking(world, config))

    assert ref(live) in resources.refs
    assert ref(binned) not in resources.refs
    assert ref(elsewhere) not in resources.refs
    assert resources.secret_marker_names == {live.name, binned.name, "nobody"}


@pytest.mark.django_db
def test_an_embedding_config_s_markers_are_followed_too(world):
    secret = world.secret()
    collection = world.make("tables.SourceCollection", collection_name=world.name("kb"), org=world.org)
    base = world.make("tables.BaseRagType", rag_type="naive", source_collection=collection)
    embedder = world.make(
        "tables.EmbeddingConfig", custom_name=world.name("emb"), org=world.org, extra_headers=_marker_headers(secret.name)
    )
    world.make("tables.NaiveRag", base_rag_type=base, embedder=embedder)
    flow = world.make("tables.Graph", name=world.name("kb-flow"), org=world.org)
    world.make("tables.KnowledgeNode", graph=flow, node_name="knowledge", source_collection=collection)

    resources = _collect(RunKind.FLOW, flow)

    assert ref(secret) in resources.refs
    assert resources.secret_marker_names == {secret.name}


@pytest.mark.django_db
def test_each_run_gets_only_the_marker_names_it_reaches(world):
    first, second = world.secret(), world.secret()
    first_flow = _flow_asking(world, _config_with_headers(world, _marker_headers(first.name)))
    second_flow = _flow_asking(world, _config_with_headers(world, _marker_headers(second.name)))

    together = RunResourceCollector().collect_many(RunKind.FLOW, [first_flow.pk, second_flow.pk])

    assert together[first_flow.pk].secret_marker_names == {first.name}
    assert ref(second) not in together[first_flow.pk].refs
    assert together[second_flow.pk].secret_marker_names == {second.name}


@pytest.mark.django_db
def test_markers_cost_one_query_however_many_rows_and_names_there_are(world):
    without_markers = _flow_asking(world, _config_with_headers(world, {"X-Trace": "t"}))
    one = _flow_asking(world, _config_with_headers(world, _marker_headers(world.secret().name)))
    six = _flow_asking(
        world,
        *(_config_with_headers(world, _marker_headers(world.secret().name, world.secret().name)) for _ in range(6)),
    )

    plain = _queries_to_collect(RunKind.FLOW, [without_markers.pk])

    assert _queries_to_collect(RunKind.FLOW, [one.pk]) == plain + 1
    assert _queries_to_collect(RunKind.FLOW, [six.pk]) == plain + 1
