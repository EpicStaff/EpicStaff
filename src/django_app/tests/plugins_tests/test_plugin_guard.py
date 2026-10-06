import pytest
from agents.models import AgentDefinition

from plugins.exceptions import PluginSuspendedError
from plugins.models import Plugin, PluginResource
from plugins.resource_types import PluginResourceType
from plugins.services.guard import PluginGuard
from plugins.services.lifecycle_service import PluginLifecycleService
from tables.models import Graph, PythonCode, PythonCodeTool, Session
from tables.models.graph_models import StartNode, SubGraphNode, TaskNode
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCodeToolConfig
from tables.services.converter_service import ConverterService
from tables.services.session_manager_service import SessionManagerService
from tables.services.trigger_spec import TriggerSpec
from tests.plugins_tests.helpers import registered_ids

RUN_SESSION_URL = "/api/run-session/"


def _run(graph_id: int, user) -> int:
    return SessionManagerService().run_session(
        graph_id=graph_id, variables={}, user=user, trigger=TriggerSpec.manual()
    )


@pytest.fixture
def plugin_flow(ready_plugin):
    [graph_id] = registered_ids(ready_plugin, "flow")
    yield Graph.objects.get(pk=graph_id)


@pytest.fixture
def suspended_plugin(ready_plugin):
    Plugin.objects.filter(pk=ready_plugin.pk).update(suspended=True)
    ready_plugin.refresh_from_db()
    yield ready_plugin


@pytest.fixture
def own_flow_embedding_the_plugin(acme, plugin_flow):
    """A flow of the org itself that runs the plugin's flow as a subflow, two levels deep."""
    inner = Graph.objects.create(name="Inner", org=acme)
    StartNode.objects.create(graph=inner, variables={"variables": {}})
    SubGraphNode.objects.create(graph=inner, subgraph=plugin_flow, node_name="Plugin chat")
    outer = Graph.objects.create(name="My support flow", org=acme)
    StartNode.objects.create(graph=outer, variables={"variables": {}})
    SubGraphNode.objects.create(graph=outer, subgraph=inner, node_name="Inner")
    yield outer


# --- flows -------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_suspended_plugin_flow_is_refused_before_any_session_exists(
    suspended_plugin, plugin_flow, admin_acme, published_sessions
):
    with pytest.raises(PluginSuspendedError, match="Chat Bot"):
        _run(plugin_flow.pk, admin_acme)

    assert not Session.objects.exists()
    assert published_sessions == []


@pytest.mark.django_db
def test_an_own_flow_embedding_a_suspended_plugin_flow_is_refused(
    suspended_plugin, own_flow_embedding_the_plugin, admin_acme, published_sessions
):
    with pytest.raises(PluginSuspendedError):
        _run(own_flow_embedding_the_plugin.pk, admin_acme)

    assert not Session.objects.exists()
    assert published_sessions == []


@pytest.mark.django_db
def test_run_session_endpoint_answers_409_plugin_suspended(
    suspended_plugin, plugin_flow, admin_client, published_sessions
):
    response = admin_client.post(RUN_SESSION_URL, {"graph_id": plugin_flow.pk}, format="json")

    assert response.status_code == 409, response.content
    assert response.json()["code"] == "plugin_suspended"
    assert "Chat Bot" in response.json()["message"]
    assert not Session.objects.exists()


@pytest.mark.django_db
def test_after_resume_the_plugin_flow_runs_again(
    suspended_plugin, plugin_flow, admin_acme, published_sessions
):
    PluginLifecycleService().resume(suspended_plugin)

    session_id = _run(plugin_flow.pk, admin_acme)

    assert published_sessions == [session_id]
    assert Session.objects.get(pk=session_id).status == Session.SessionStatus.PENDING


@pytest.mark.django_db
def test_after_resume_the_endpoint_runs_the_plugin_flow(
    suspended_plugin, plugin_flow, admin_client, published_sessions
):
    PluginLifecycleService().resume(suspended_plugin)

    response = admin_client.post(RUN_SESSION_URL, {"graph_id": plugin_flow.pk}, format="json")

    assert response.status_code == 201, response.content
    assert published_sessions == [response.json()["session_id"]]


@pytest.mark.django_db
def test_suspending_one_plugin_does_not_refuse_other_flows(suspended_plugin, acme, plugin_flow):
    own = Graph.objects.create(name="Unrelated", org=acme)
    SubGraphNode.objects.create(graph=own, subgraph=Graph.objects.create(name="Mine", org=acme))

    PluginGuard().check_flow(own)


# --- agents ------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_own_flow_using_a_suspended_plugin_agent_cannot_build_its_session(
    suspended_plugin, acme, admin_acme, published_sessions
):
    [agent_id] = registered_ids(suspended_plugin, "agent_definition")
    own = Graph.objects.create(name="Borrowing flow", org=acme)
    StartNode.objects.create(graph=own, variables={"variables": {}})
    TaskNode.objects.create(
        graph=own, node_name="Ask", instructions="hi", agent_definition_id=agent_id
    )

    with pytest.raises(PluginSuspendedError):
        _run(own.pk, admin_acme)

    # The flow itself is the org's, so its run started and failed at the agent.
    assert Session.objects.get(graph=own).status == Session.SessionStatus.ERROR
    assert published_sessions == []


@pytest.mark.django_db
def test_agent_check_refuses_only_suspended_plugin_agents(suspended_plugin, acme):
    [agent_id] = registered_ids(suspended_plugin, "agent_definition")
    own_agent = AgentDefinition.objects.create(organization=acme, name="Mine")

    with pytest.raises(PluginSuspendedError):
        PluginGuard().check_agent_definition(agent_id)
    PluginGuard().check_agent_definition(own_agent.pk)


# --- tools -------------------------------------------------------------------------


@pytest.fixture
def plugin_tools(ready_plugin, acme):
    """A python tool, a config of it and an MCP tool, linked to the plugin."""
    python_tool = PythonCodeTool.objects.create(
        org=acme,
        name="lookup",
        description="Looks things up",
        python_code=PythonCode.objects.create(code="def main():\n    return 'x'"),
    )
    config = PythonCodeToolConfig.objects.create(org=acme, name="default", tool=python_tool)
    mcp_tool = McpTool.objects.create(
        org=acme, name="search", transport="http://mcp.test/sse", tool_name="search"
    )
    PluginResource.objects.bulk_create(
        [
            PluginResource(
                plugin=ready_plugin,
                resource_type=PluginResourceType.PYTHON_CODE_TOOL,
                object_id=python_tool.pk,
            ),
            PluginResource(
                plugin=ready_plugin, resource_type=PluginResourceType.MCP_TOOL, object_id=mcp_tool.pk
            ),
        ]
    )
    yield [python_tool, config, mcp_tool]


@pytest.mark.django_db
def test_tools_of_a_suspended_plugin_cannot_be_built(plugin_tools, ready_plugin):
    Plugin.objects.filter(pk=ready_plugin.pk).update(suspended=True)

    for tool in plugin_tools:
        with pytest.raises(PluginSuspendedError):
            ConverterService().convert_tool_to_base_tool_pydantic(tool)


@pytest.mark.django_db
def test_tools_of_a_running_plugin_are_built(plugin_tools):
    built = [
        ConverterService().convert_tool_to_base_tool_pydantic(tool).unique_name
        for tool in plugin_tools
    ]

    assert built[0].startswith("python-code-tool:")
    assert built[2].startswith("mcp-tool:")


# --- fast path ---------------------------------------------------------------------


@pytest.mark.django_db
def test_with_nothing_suspended_a_check_is_one_query(
    plugin_flow, django_assert_num_queries
):
    with django_assert_num_queries(1):
        PluginGuard().check_flow(plugin_flow)
