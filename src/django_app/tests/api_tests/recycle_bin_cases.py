"""The resources every recycle bin holds, as test cases: how to make one and where its API lives."""

from collections.abc import Callable
from dataclasses import dataclass

from agents.models import AgentDefinition, Surface, SurfacePythonTool
from agents.models.surface_models import ToolMode
from django.db.models import Model
from rbac.models import Organization
from rbac.models.enums import ResourceType
from tables.models import (
    DocumentContent,
    DocumentMetadata,
    Graph,
    KeyValueTable,
    KeyValueTableEntry,
    PythonCode,
    PythonCodeTool,
    RealtimeChannel,
    SourceCollection,
    TaskNode,
    WebhookTrigger,
)
from tables.models.mcp_models import McpTool
from tables.services.recycle_bin.registry import bin_resources
from tables.services.secrets.secret_service import secret_service

FLOWS_URL = "/api/graphs/"
PYTHON_TOOLS_URL = "/api/python-code-tool/"
AGENTS_URL = "/api/agent-definitions/"
SURFACES_URL = "/api/surfaces/"
KEY_VALUE_TABLES_URL = "/api/key-value-tables/"


def make_flow(org: Organization, name: str) -> Model:
    return Graph.objects.create(org=org, name=name)


def make_python_tool(org: Organization, name: str) -> Model:
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    return PythonCodeTool.objects.create(name=name, description="d", python_code=code, org=org)


def make_mcp_tool(org: Organization, name: str) -> Model:
    return McpTool.objects.create(name=name, org=org, transport="https://example.com/mcp", tool_name="some_tool")


def make_agent(org: Organization, name: str) -> Model:
    return AgentDefinition.objects.create(org=org, name=name, instruction_list=[{"name": "Instruction_1.md", "content": "Do things."}])


def make_surface(org: Organization, name: str) -> Model:
    return Surface.objects.create(org=org, name=name)


def make_key_value_table(org: Organization, name: str) -> Model:
    return KeyValueTable.objects.create(org=org, name=name)


def make_secret(org: Organization, name: str) -> Model:
    return secret_service.create(text="value", org=org, name=name)


def make_realtime_channel(org: Organization, name: str) -> Model:
    return RealtimeChannel.objects.create(org=org, name=name)


def make_webhook_trigger(org: Organization, name: str) -> Model:
    # The ORM skips the path validator, and every test here uses its own name.
    return WebhookTrigger.objects.create(org=org, path=name)


def make_collection(org: Organization, name: str) -> Model:
    return SourceCollection.objects.create(org=org, collection_name=name)


def add_flow_contents(flow: Graph) -> None:
    TaskNode.objects.create(graph=flow, node_name=f"{flow.name} task")


def add_agent_contents(agent: AgentDefinition) -> None:
    Surface.objects.create(org=agent.org, name=f"{agent.name} surface", owner_agent=agent)


def add_surface_contents(surface: Surface) -> None:
    tool = make_python_tool(surface.org, f"{surface.name} tool")
    SurfacePythonTool.objects.create(surface=surface, python_tool=tool, mode=ToolMode.ALLOW)


def add_key_value_table_contents(table: KeyValueTable) -> None:
    KeyValueTableEntry.objects.create(table=table, key="inside", value="x")


def add_collection_contents(collection: SourceCollection) -> None:
    DocumentMetadata.objects.create(
        source_collection=collection,
        document_content=DocumentContent.objects.create(content=b"inside"),
        file_name="inside.txt",
        file_type="txt",
        file_size=6,
    )


@dataclass(frozen=True)
class BinCase:
    key: str
    url: str
    delete_status: int
    make: Callable[[Organization, str], Model]
    # What used the item is connected again on restore: it kept its links in the bin.
    links_restored: bool = False
    # Gives a row something its restore brings back (its contents_total); None for a
    # resource with nothing inside.
    add_contents: Callable[[Model], None] | None = None

    @property
    def model(self) -> type[Model]:
        return bin_resources()[self.key].model

    @property
    def resource_type(self) -> ResourceType:
        return bin_resources()[self.key].resource_type


CASES = [
    BinCase("flow", FLOWS_URL, 204, make_flow, add_contents=add_flow_contents),
    BinCase("python_tool", PYTHON_TOOLS_URL, 204, make_python_tool),
    BinCase("mcp_tool", "/api/mcp-tools/", 204, make_mcp_tool),
    BinCase("agent", AGENTS_URL, 204, make_agent, add_contents=add_agent_contents),
    BinCase("surface", SURFACES_URL, 204, make_surface, add_contents=add_surface_contents),
    BinCase("collection", "/api/source-collections/", 200, make_collection, add_contents=add_collection_contents),
    BinCase("key_value_table", KEY_VALUE_TABLES_URL, 204, make_key_value_table, add_contents=add_key_value_table_contents),
    BinCase("secret", "/api/secrets/", 204, make_secret, links_restored=True),
    BinCase("realtime_channel", "/api/realtime-channels/", 204, make_realtime_channel, links_restored=True),
    BinCase("webhook_trigger", "/api/webhook-triggers/", 204, make_webhook_trigger, links_restored=True),
]
