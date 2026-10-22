"""Rows the suspension and run-guard tests build: flows that reach a plugin's resources in every way a run can."""

import itertools
from collections.abc import Callable
from dataclasses import dataclass

from agents.models import AgentDefinition, Surface
from agents.models.surface_models import SurfaceKnowledge, SurfaceMcpTool, SurfacePythonTool
from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django.utils import timezone
from plugins.models import GrantState, PluginGrant, PluginOwnedResource
from tables.models import (
    BaseRagType,
    EmbeddingConfig,
    Graph,
    KeyValueTable,
    LLMConfig,
    McpTool,
    PythonCode,
    PythonCodeTool,
    Secret,
    SourceCollection,
    StorageFile,
    WebhookTrigger,
)
from tables.models.graph_models import (
    AgentNode,
    ClassificationDecisionTableNode,
    ClassificationDecisionTablePrompt,
    GraphStorageFile,
    KeyValueNode,
    KnowledgeNode,
    PythonNode,
    StartNode,
    SubGraphNode,
    TaskNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.models.knowledge_models.naive_rag_models import NaiveRag
from tables.services.secrets import secret_service

from tests.plugins_tests.service_account_helpers import runnable_graph


def own(row: Model, grant: PluginGrant) -> PluginOwnedResource:
    """Record `row` as created by the grant's plugin in the grant's organization."""
    return PluginOwnedResource.objects.create(
        org_id=grant.org_id,
        grant=grant,
        plugin_identifier=grant.plugin.identifier,
        content_type=ContentType.objects.get_for_model(type(row)),
        object_id=row.pk,
    )


def orphan(row: Model, organization, identifier: str = "weather") -> PluginOwnedResource:
    """Record `row` as owned by a plugin whose grant is gone."""
    return PluginOwnedResource.objects.create(
        org=organization,
        grant=None,
        plugin_identifier=identifier,
        content_type=ContentType.objects.get_for_model(type(row)),
        object_id=row.pk,
    )


def set_state(grant: PluginGrant, state: str) -> PluginGrant:
    grant.state = state
    grant.suspended_at = timezone.now() if state == GrantState.SUSPENDED else None
    grant.save(update_fields=["state", "suspended_at", "updated_at"])
    return grant


def secret_row(organization, name: str) -> Secret:
    return secret_service.create(text="sk-weather", org=organization, name=name)


def llm_config(organization, name: str, **fields) -> LLMConfig:
    return LLMConfig.objects.create(org=organization, custom_name=name, **fields)


def agent(organization, name: str, **fields) -> AgentDefinition:
    return AgentDefinition.objects.create(org=organization, name=name, **fields)


def flow(organization, name: str) -> Graph:
    """A runnable flow: a start node and one Python node that uses nothing."""
    return runnable_graph(name, organization)


def surface_of(organization, name: str) -> Surface:
    return Surface.objects.create(org=organization, name=name)


def agent_node_flow(organization, name: str, agent_definition=None, surfaces=()) -> Graph:
    graph = flow(organization, name)
    node = AgentNode.objects.create(graph=graph, node_name="agent", agent_definition=agent_definition)
    node.surface_list.set(surfaces)
    return graph


_numbers = itertools.count(1)


def _unique(name: str) -> str:
    """`name` with a number, so many reaches can be built in one organization."""
    return f"{name} {next(_numbers)}"


@dataclass(frozen=True)
class Reach:
    """A flow of the organization that reaches a row, and the row a plugin would own."""

    flow: Graph
    row: Model


# Each builds, in `organization`, a flow that reaches one row the way a run does, and
# returns both: the guard must refuse the flow once a non-active grant owns the row.
def _agent_definition(organization) -> Reach:
    digest_writer = agent(organization, _unique("digest-writer"))
    return Reach(agent_node_flow(organization, _unique("Digest"), digest_writer), digest_writer)


def _agent_llm_config(organization) -> Reach:
    config = llm_config(organization, _unique("Weather summaries"))
    return Reach(agent_node_flow(organization, _unique("Digest"), agent(organization, _unique("writer"), llm_config=config)), config)


def _agent_fcm_llm_config(organization) -> Reach:
    config = llm_config(organization, _unique("Weather routing"))
    return Reach(
        agent_node_flow(organization, _unique("Digest"), agent(organization, _unique("writer"), fcm_llm_config=config)), config
    )


def _secret_declared_by_code(organization) -> Reach:
    graph = Graph.objects.create(name=_unique("Digest"), org=organization)
    StartNode.objects.create(graph=graph, variables={})
    code = PythonCode.objects.create(code="def main(**kwargs):\n    return 1\n", entrypoint="main")
    secret = secret_row(organization, _unique("Weather · LLM key"))
    code.secrets.set([secret])
    PythonNode.objects.create(graph=graph, python_code=code, node_name="py")
    return Reach(graph, secret)


def _secret_behind_llm_config(organization) -> Reach:
    secret = secret_row(organization, _unique("Weather · LLM key"))
    config = llm_config(organization, _unique("Weather summaries"), api_key_secret=secret)
    return Reach(agent_node_flow(organization, _unique("Digest"), agent(organization, _unique("writer"), llm_config=config)), secret)


def marker(secret: Secret) -> dict[str, str]:
    """Headers whose `epicstaff_secret(<name>)` marker names `secret`."""
    return {"Authorization": f"Bearer epicstaff_secret({secret.name})"}


def _secret_named_by_an_llm_config_header(organization) -> Reach:
    secret = secret_row(organization, _unique("Weather gateway key"))
    graph = flow(organization, _unique("Digest"))
    config = llm_config(organization, _unique("Weather classifier"), extra_headers=marker(secret))
    ClassificationDecisionTableNode.objects.create(graph=graph, node_name="cdt", default_llm_config=config)
    return Reach(graph, secret)


def _secret_named_by_an_embedder_header(organization) -> Reach:
    secret = secret_row(organization, _unique("Weather embeddings key"))
    collection = SourceCollection.objects.create(org=organization, collection_name=_unique("Forecasts"))
    embedder = EmbeddingConfig.objects.create(
        org=organization, custom_name=_unique("Weather embeddings"), extra_headers=marker(secret)
    )
    NaiveRag.objects.create(base_rag_type=BaseRagType.objects.create(rag_type="naive", source_collection=collection), embedder=embedder)
    graph = flow(organization, _unique("Digest"))
    KnowledgeNode.objects.create(graph=graph, node_name="knowledge", source_collection=collection)
    return Reach(graph, secret)


def _key_value_table(organization) -> Reach:
    graph = flow(organization, _unique("Digest"))
    table = KeyValueTable.objects.create(org=organization, name=_unique("weather_cache"))
    KeyValueNode.objects.create(graph=graph, node_name="kv", key_value_table=table)
    return Reach(graph, table)


def _knowledge_node_collection(organization) -> Reach:
    graph = flow(organization, _unique("Digest"))
    collection = SourceCollection.objects.create(org=organization, collection_name=_unique("Forecasts"))
    KnowledgeNode.objects.create(graph=graph, node_name="knowledge", source_collection=collection)
    return Reach(graph, collection)


def _surface_rag_embedder(organization) -> Reach:
    collection = SourceCollection.objects.create(org=organization, collection_name=_unique("Forecasts"))
    embedder = EmbeddingConfig.objects.create(org=organization, custom_name=_unique("Weather embeddings"))
    base = BaseRagType.objects.create(rag_type="naive", source_collection=collection)
    NaiveRag.objects.create(base_rag_type=base, embedder=embedder)
    surface = surface_of(organization, _unique("Research"))
    SurfaceKnowledge.objects.create(surface=surface, collection=collection)
    graph = flow(organization, _unique("Digest"))
    TaskNode.objects.create(graph=graph, node_name="task", agent_definition=agent(organization, _unique("writer"))).surface_list.set(
        [surface]
    )
    return Reach(graph, embedder)


def _python_tool(organization) -> Reach:
    code = PythonCode.objects.create(code="def main(**kwargs):\n    return 1\n", entrypoint="main")
    tool = PythonCodeTool.objects.create(org=organization, name=_unique("forecast"), description="d", python_code=code)
    surface = surface_of(organization, _unique("Tools"))
    SurfacePythonTool.objects.create(surface=surface, python_tool=tool, mode="allow")
    return Reach(agent_node_flow(organization, _unique("Digest"), agent(organization, _unique("writer")), [surface]), tool)


def _mcp_tool(organization) -> Reach:
    tool = McpTool.objects.create(org=organization, name=_unique("weather-mcp"), transport="http://mcp", tool_name="forecast")
    surface = surface_of(organization, _unique("Tools"))
    SurfaceMcpTool.objects.create(surface=surface, mcp_tool=tool, mode="allow")
    return Reach(agent_node_flow(organization, _unique("Digest"), agent(organization, _unique("writer")), [surface]), tool)


def _mcp_tool_auth_secret(organization) -> Reach:
    secret = secret_row(organization, _unique("Weather · MCP token"))
    tool = McpTool.objects.create(
        org=organization, name=_unique("weather-mcp"), transport="http://mcp", tool_name="forecast", auth_secret=secret
    )
    surface = surface_of(organization, _unique("Tools"))
    SurfaceMcpTool.objects.create(surface=surface, mcp_tool=tool, mode="allow")
    return Reach(agent_node_flow(organization, _unique("Digest"), agent(organization, _unique("writer")), [surface]), secret)


def _attached_file(organization) -> Reach:
    graph = flow(organization, _unique("Digest"))
    folder_path = f"weather-{next(_numbers)}/"
    readme = StorageFile.objects.create(org=organization, path=f"{folder_path}README.md", name="README.md", parent_path=folder_path)
    GraphStorageFile.objects.create(graph=graph, storage_file=readme)
    return Reach(graph, readme)


def _file_in_attached_folder(organization) -> Reach:
    graph = flow(organization, _unique("Digest"))
    folder_path = f"weather-{next(_numbers)}/"
    folder = StorageFile.objects.create(org=organization, path=folder_path, name="weather", item_type="folder")
    readme = StorageFile.objects.create(org=organization, path=f"{folder_path}README.md", name="README.md", parent_path=folder_path)
    GraphStorageFile.objects.create(graph=graph, storage_file=folder)
    return Reach(graph, readme)


def _webhook_trigger(organization) -> Reach:
    graph = flow(organization, _unique("Digest"))
    trigger = WebhookTrigger.objects.create(org=organization, path=f"weather-hook-{next(_numbers)}")
    code = PythonCode.objects.create(code="def main(**kwargs):\n    return 1\n", entrypoint="main")
    WebhookTriggerNode.objects.create(graph=graph, node_name="hook", python_code=code, webhook_trigger=trigger)
    return Reach(graph, trigger)


def _telegram_bot_secret(organization) -> Reach:
    graph = flow(organization, _unique("Digest"))
    secret = secret_row(organization, _unique("Weather · bot token"))
    TelegramTriggerNode.objects.create(graph=graph, node_name="bot", telegram_bot_api_key_secret=secret)
    return Reach(graph, secret)


def _decision_table_default_llm_config(organization) -> Reach:
    graph = flow(organization, _unique("Digest"))
    config = llm_config(organization, _unique("Weather classifier"))
    ClassificationDecisionTableNode.objects.create(graph=graph, node_name="cdt", default_llm_config=config)
    return Reach(graph, config)


def _decision_table_prompt_llm_config(organization) -> Reach:
    graph = flow(organization, _unique("Digest"))
    config = llm_config(organization, _unique("Weather classifier"))
    node = ClassificationDecisionTableNode.objects.create(graph=graph, node_name="cdt")
    ClassificationDecisionTablePrompt.objects.create(cdt_node=node, prompt_key="sky", llm_config=config)
    return Reach(graph, config)


def _owned_subflow(organization) -> Reach:
    graph = flow(organization, _unique("Digest"))
    subflow = flow(organization, _unique("Weather forecast"))
    SubGraphNode.objects.create(graph=graph, node_name="sub", subgraph=subflow)
    return Reach(graph, subflow)


def _subflow_using_an_owned_agent(organization) -> Reach:
    graph = flow(organization, _unique("Digest"))
    digest_writer = agent(organization, _unique("digest-writer"))
    subflow = agent_node_flow(organization, _unique("Inner"), digest_writer)
    SubGraphNode.objects.create(graph=graph, node_name="sub", subgraph=subflow)
    return Reach(graph, digest_writer)


REACHES: dict[str, Callable[[object], Reach]] = {
    "agent definition": _agent_definition,
    "agent llm config": _agent_llm_config,
    "agent fcm llm config": _agent_fcm_llm_config,
    "secret declared by python code": _secret_declared_by_code,
    "secret behind an llm config": _secret_behind_llm_config,
    "secret named by an llm config's header": _secret_named_by_an_llm_config_header,
    "secret named by an embedder's header": _secret_named_by_an_embedder_header,
    "key-value table": _key_value_table,
    "knowledge collection of a node": _knowledge_node_collection,
    "embedder of a surface's rag": _surface_rag_embedder,
    "python tool": _python_tool,
    "mcp tool": _mcp_tool,
    "mcp tool's auth secret": _mcp_tool_auth_secret,
    "file attached to the flow": _attached_file,
    "file inside an attached folder": _file_in_attached_folder,
    "webhook trigger": _webhook_trigger,
    "telegram bot secret": _telegram_bot_secret,
    "decision table default llm config": _decision_table_default_llm_config,
    "decision table prompt llm config": _decision_table_prompt_llm_config,
    "owned subflow": _owned_subflow,
    "subflow using an owned agent": _subflow_using_an_owned_agent,
}

