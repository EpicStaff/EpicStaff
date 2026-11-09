"""A flow export bundles only the dependencies the caller may export.

The main entity is always exported. A dependency whose resource the caller lacks
EXPORT on is left out together with everything reachable only through it, and the
export job's result names what was left out (`result.excluded`).
"""

import json

import pytest
from django.urls import reverse

from agents.models import (
    AgentDefaultSurface,
    AgentDefinition,
    AgentInlineSurface,
    AgentInlineSurfacePythonTool,
    Surface,
    SurfaceMcpTool,
    SurfacePlace,
    SurfacePythonTool,
    ToolMode,
)
from rbac.access.effective import EffectivePermissions
from rbac.models import OrganizationUser, Role
from rbac.models.enums import Permission, ResourceType
from rbac.models.role import RolePermission
from tables.import_export.enums import EntityType
from tables.import_export.permissions import ExportAccessPolicy
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.models import (
    AgentNode,
    ClassificationDecisionTableNode,
    Graph,
    McpTool,
    PythonCode,
    PythonCodeTool,
    StartNode,
    SubGraphNode,
    TaskNode,
    TransferJob,
)
from tables.models.label_models import Label
from tests.helpers import data_to_json_file
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.transfer_job_helpers import FinishedExport, export_via_job

READ_AND_EXPORT = int(Permission.READ | Permission.EXPORT)
READ_ONLY = int(Permission.READ)
NO_PERMISSION = 0


@pytest.fixture
def make_user(django_user_model, acme):
    """Factory: an Acme member who may read and export flows, plus the given bits per resource."""

    def _make(email: str, **bits_by_resource: int):
        role = Role.objects.create(name=f"role-{email}", org=acme, is_built_in=False)
        RolePermission.objects.create(
            role=role, resource_type=ResourceType.FLOWS, permissions=READ_AND_EXPORT
        )
        for resource, bits in bits_by_resource.items():
            RolePermission.objects.create(role=role, resource_type=resource, permissions=bits)
        user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
        OrganizationUser.objects.create(user=user, org=acme, role=role)
        return user

    return _make


@pytest.fixture
def client_in_acme(client_as, acme):
    def _client(user):
        client = client_as(user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
        return client

    return _client


def _python_tool(org, name):
    return PythonCodeTool.objects.create(
        org=org,
        name=name,
        description="description",
        python_code=PythonCode.objects.create(
            code="def main(): return 1", entrypoint="main"
        ),
    )


def _agent(org, name):
    return AgentDefinition.objects.create(
        org=org,
        name=name,
        description="description",
        instruction_list=[{"name": "Instruction_1.md", "content": "instructions"}],
    )


def _flow(org, name):
    graph = Graph.objects.create(name=name, metadata={"nodes": [], "edges": []}, org=org)
    StartNode.objects.create(graph=graph, variables={})
    return graph


@pytest.fixture
def flow_with_agent(acme):
    """One flow whose agent node reaches tools along three different paths.

    - `agent` (with its owned surface and owned tools) is reached only through the
      agent definition.
    - `node surface` is attached to the agent node, so it is reached from the flow.
      It is also the agent's default surface and carries `surface tool`.
    - `inline tool` sits on the agent node's inline surface, reached from the flow.
    """
    agent = _agent(acme, "secret agent")
    owned_tool = _python_tool(acme, "owned tool")
    owned_mcp = McpTool.objects.create(
        org=acme, name="owned mcp", transport="https://example.com/mcp", tool_name="search"
    )
    owned_surface = Surface.objects.create(
        org=acme, name="owned surface", instructions="owned", owner_agent=agent
    )
    SurfacePythonTool.objects.create(
        surface=owned_surface, python_tool=owned_tool, mode=ToolMode.ALLOW
    )
    SurfaceMcpTool.objects.create(surface=owned_surface, mcp_tool=owned_mcp, mode=ToolMode.ALLOW)

    node_surface = Surface.objects.create(org=acme, name="node surface", instructions="shared")
    surface_tool = _python_tool(acme, "surface tool")
    SurfacePythonTool.objects.create(
        surface=node_surface, python_tool=surface_tool, mode=ToolMode.ALLOW
    )
    AgentDefaultSurface.objects.create(
        agent_definition=agent, surface=node_surface, place=SurfacePlace.FLOW
    )

    graph = _flow(acme, "agent flow")
    graph.labels.add(Label.objects.create(org=acme, name="flow label"))
    agent_node = AgentNode.objects.create(
        graph=graph, node_name="agent_node_1", agent_definition=agent
    )
    agent_node.surface_list.add(node_surface)
    inline_surface = AgentInlineSurface.objects.create(agent_node=agent_node)
    AgentInlineSurfacePythonTool.objects.create(
        agent_inline_surface=inline_surface,
        python_tool=_python_tool(acme, "inline tool"),
        mode=ToolMode.ALLOW,
    )
    TaskNode.objects.create(graph=graph, agent_definition=agent, instructions="t")

    return {"graph": graph, "agent": agent, "agent_node": agent_node}


def _export(user, graph):
    """What a flow export job of `graph`, started by `user`, writes and reports."""
    return _bulk_export(user, [graph])


def _bulk_export(user, graphs):
    org_id = graphs[0].org_id
    return ExportService(entity_registry).export_entities(
        EntityType.GRAPH,
        [graph.id for graph in graphs],
        org_id=org_id,
        policy=ExportAccessPolicy.for_user(user, org_id),
    )


def _payload(exported) -> dict:
    if isinstance(exported, FinishedExport):
        return exported.envelope
    return json.loads(json.dumps(exported.data))


def _names(payload: dict, entity_type: EntityType) -> set[str]:
    return {entry["name"] for entry in payload.get(entity_type, [])}


def _excluded(exported) -> list[dict]:
    if isinstance(exported, FinishedExport):
        return exported.job.result["excluded"]
    return [
        {"entity_type": str(item.entity_type), "entity_id": item.entity_id, "name": item.name}
        for item in exported.excluded
    ]


def _excluded_by_type(exported) -> dict[str, dict]:
    by_type: dict[str, dict] = {}
    for item in _excluded(exported):
        entry = by_type.setdefault(
            item["entity_type"], {"type": item["entity_type"], "count": 0, "names": []}
        )
        entry["count"] += 1
        if item["name"]:
            entry["names"].append(item["name"])
    return by_type


@pytest.mark.django_db
class TestFullExport:
    def test_member_without_agent_and_tool_export_gets_flow_alone(
        self, flow_with_agent, make_user
    ):
        user = make_user("flows-only@example.com")

        response = _export(user, flow_with_agent["graph"])

        payload = _payload(response)
        assert payload["main_entity"] == "Flow"
        assert _names(payload, EntityType.GRAPH) == {"agent flow"}
        assert EntityType.AGENT_DEFINITION not in payload
        assert EntityType.PYTHON_CODE_TOOL not in payload
        assert EntityType.MCP_TOOL not in payload
        assert _names(payload, EntityType.SURFACE) == {"node surface"}
        assert _names(payload, EntityType.LABEL) == {"flow label"}
        excluded = _excluded_by_type(response)
        assert excluded["AgentDefinition"]["count"] == 1
        # The flow's inline tool and the node surface's tool; the owned tools sit behind the agent.
        assert excluded["PythonCodeTool"]["count"] == 2
        assert "MCPTool" not in excluded

    def test_tools_export_without_agents_export_keeps_tools_reached_from_allowed_paths(
        self, flow_with_agent, make_user
    ):
        user = make_user("tools-only@example.com", tools=READ_AND_EXPORT)

        response = _export(user, flow_with_agent["graph"])

        payload = _payload(response)
        assert EntityType.AGENT_DEFINITION not in payload
        assert _names(payload, EntityType.PYTHON_CODE_TOOL) == {"surface tool", "inline tool"}
        assert EntityType.MCP_TOOL not in payload
        assert _names(payload, EntityType.SURFACE) == {"node surface"}
        assert list(_excluded_by_type(response)) == ["AgentDefinition"]

    def test_agents_export_without_tools_export_keeps_agent_and_drops_every_tool(
        self, flow_with_agent, make_user
    ):
        user = make_user("agents-only@example.com", agents=READ_AND_EXPORT)

        response = _export(user, flow_with_agent["graph"])

        payload = _payload(response)
        assert _names(payload, EntityType.AGENT_DEFINITION) == {"secret agent"}
        assert _names(payload, EntityType.SURFACE) == {"node surface", "owned surface"}
        assert EntityType.PYTHON_CODE_TOOL not in payload
        assert EntityType.MCP_TOOL not in payload
        excluded = _excluded_by_type(response)
        assert excluded["PythonCodeTool"]["count"] == 3
        assert excluded["MCPTool"]["count"] == 1
        assert "AgentDefinition" not in excluded

    def test_superadmin_export_excludes_nothing(self, flow_with_agent, superadmin):
        response = _export(superadmin, flow_with_agent["graph"])

        payload = _payload(response)
        assert _names(payload, EntityType.AGENT_DEFINITION) == {"secret agent"}
        assert len(payload[EntityType.PYTHON_CODE_TOOL]) == 3
        assert len(payload[EntityType.MCP_TOOL]) == 1
        assert _excluded(response) == []

    def test_member_with_every_export_right_has_nothing_excluded(self, flow_with_agent, make_user):
        user = make_user("everything@example.com", agents=READ_AND_EXPORT, tools=READ_AND_EXPORT)

        response = _export(user, flow_with_agent["graph"])

        assert _excluded(response) == []
        assert _names(_payload(response), EntityType.AGENT_DEFINITION) == {"secret agent"}


@pytest.mark.django_db
class TestBulkAndPartialExport:
    def test_bulk_export_counts_a_shared_agent_once(self, acme, flow_with_agent, make_user):
        second = _flow(acme, "second flow")
        AgentNode.objects.create(
            graph=second, node_name="agent_node_1", agent_definition=flow_with_agent["agent"]
        )
        user = make_user("bulk@example.com")

        response = _bulk_export(user, [flow_with_agent["graph"], second])

        payload = _payload(response)
        assert _names(payload, EntityType.GRAPH) == {"agent flow", "second flow"}
        assert EntityType.AGENT_DEFINITION not in payload
        assert _excluded_by_type(response)["AgentDefinition"]["count"] == 1

    def test_partial_export_leaves_out_denied_dependencies_and_names_them(
        self, flow_with_agent, make_user, client_in_acme
    ):
        user = make_user("partial@example.com")

        response = _partial_export(client_in_acme(user), flow_with_agent)

        assert response.job.status == TransferJob.Status.COMPLETED, response.job.error
        payload = _payload(response)
        assert len(payload[EntityType.AGENT_NODE]) == 1
        assert EntityType.AGENT_DEFINITION not in payload
        assert EntityType.PYTHON_CODE_TOOL not in payload
        assert _excluded_by_type(response)["AgentDefinition"]["count"] == 1

    def test_partial_export_keeps_dependencies_the_caller_may_export(
        self, flow_with_agent, make_user, client_in_acme
    ):
        user = make_user(
            "partial-agents@example.com", agents=READ_AND_EXPORT, tools=READ_AND_EXPORT
        )
        response = _partial_export(client_in_acme(user), flow_with_agent)

        assert _names(_payload(response), EntityType.AGENT_DEFINITION) == {"secret agent"}
        assert _excluded(response) == []


@pytest.mark.django_db
class TestExcludedNames:
    def test_names_are_listed_when_the_caller_can_read_the_type(self, flow_with_agent, make_user):
        user = make_user("reader@example.com", agents=READ_ONLY)

        response = _export(user, flow_with_agent["graph"])

        assert _excluded_by_type(response)["AgentDefinition"] == {
            "type": "AgentDefinition",
            "count": 1,
            "names": ["secret agent"],
        }

    def test_names_are_withheld_when_the_caller_cannot_read_the_type(
        self, flow_with_agent, make_user
    ):
        user = make_user("blind@example.com", agents=NO_PERMISSION, tools=READ_ONLY)

        response = _export(user, flow_with_agent["graph"])

        excluded = _excluded_by_type(response)
        assert excluded["AgentDefinition"] == {
            "type": "AgentDefinition",
            "count": 1,
            "names": [],
        }
        assert sorted(excluded["PythonCodeTool"]["names"]) == ["inline tool", "surface tool"]
        assert "secret agent" not in json.dumps(_excluded(response))

    def test_names_are_capped_but_count_stays_exact(self, acme, make_user):
        graph = _flow(acme, "many agents")
        for index in range(7):
            AgentNode.objects.create(
                graph=graph,
                node_name=f"agent_node_{index}",
                agent_definition=_agent(acme, f"agent {index}"),
            )
        user = make_user("capped@example.com", agents=READ_ONLY)

        response = _export(user, graph)

        entry = _excluded_by_type(response)["AgentDefinition"]
        assert entry["count"] == 7
        assert len(entry["names"]) == 5

    def test_non_ascii_names_are_kept(self, acme, make_user):
        graph = _flow(acme, "unicode")
        AgentNode.objects.create(
            graph=graph, node_name="agent_node_1", agent_definition=_agent(acme, "Агент ☃")
        )
        user = make_user("unicode@example.com", agents=READ_ONLY)

        response = _export(user, graph)

        assert _excluded_by_type(response)["AgentDefinition"]["names"] == ["Агент ☃"]

class TestExportAccessPolicy:
    @staticmethod
    def _policy(**bits_by_resource: int) -> ExportAccessPolicy:
        return ExportAccessPolicy(
            EffectivePermissions(is_superadmin=False, role=None, by_resource=bits_by_resource)
        )

    @pytest.mark.parametrize(
        "entity_type",
        [
            EntityType.LABEL,
            EntityType.SURFACE,
            EntityType.WEBHOOK_TRIGGER,
            EntityType.LLM_CONFIG,
            EntityType.OPENAI_REALTIME_CONFIG,
            EntityType.LLM_MODEL,
            EntityType.GRAPH_TAG,
        ],
    )
    def test_ungated_types_are_always_allowed(self, entity_type):
        policy = self._policy()

        assert policy.allows(entity_type) is True
        assert policy.can_reveal_names(entity_type) is True

    @pytest.mark.parametrize(
        ("entity_type", "resource"),
        [
            (EntityType.AGENT_DEFINITION, "agents"),
            (EntityType.PYTHON_CODE_TOOL, "tools"),
            (EntityType.MCP_TOOL, "tools"),
            (EntityType.GRAPH, "flows"),
        ],
    )
    def test_gated_types_follow_the_export_and_read_bits_of_their_resource(
        self, entity_type, resource
    ):
        assert self._policy().allows(entity_type) is False
        assert self._policy(**{resource: READ_ONLY}).allows(entity_type) is False
        assert self._policy(**{resource: int(Permission.EXPORT)}).allows(entity_type) is True
        assert self._policy().can_reveal_names(entity_type) is False
        assert self._policy(**{resource: READ_ONLY}).can_reveal_names(entity_type) is True


@pytest.mark.django_db
class TestNameLookupOrgScoping:
    def test_a_foreign_org_row_counts_as_excluded_but_its_name_is_never_revealed(
        self, acme, beta, flow_with_agent, make_user
    ):
        foreign_agent = _agent(beta, "beta secret agent")
        TaskNode.objects.create(
            graph=flow_with_agent["graph"], agent_definition=foreign_agent, instructions="x"
        )
        user = make_user("scoped-reader@example.com", agents=READ_ONLY)

        response = _export(user, flow_with_agent["graph"])

        entry = _excluded_by_type(response)["AgentDefinition"]
        assert entry["count"] == 2
        assert entry["names"] == ["secret agent"]
        assert "beta secret agent" not in json.dumps(_excluded(response))


@pytest.mark.django_db
class TestNullReferences:
    def test_unset_references_are_neither_counted_nor_looked_up(self, acme, make_user):
        graph = _flow(acme, "bare flow")
        TaskNode.objects.create(graph=graph, agent_definition=None, instructions="t")
        policy = ExportAccessPolicy.for_user(make_user("nulls@example.com"), acme.id)

        result = ExportService(entity_registry).export_entities(
            EntityType.GRAPH, [graph.id], org_id=acme.id, policy=policy
        )

        assert result.excluded == []


@pytest.mark.django_db
class TestClassificationDecisionTableExport:
    def test_restricted_user_exports_a_cdt_node_with_nothing_excluded(
        self, acme, make_user, client_in_acme
    ):
        graph = _flow(acme, "cdt flow")
        node = ClassificationDecisionTableNode.objects.create(graph=graph, node_name="cdt_node")
        user = make_user("cdt@example.com")

        response = export_via_job(
            client_in_acme(user),
            "/api/classification-decision-table-node/export-jobs/",
            {"ids": [node.id], "export_format": "json"},
        )

        assert response.job.status == TransferJob.Status.COMPLETED, response.job.error
        cdt_entries = _payload(response)[EntityType.CLASSIFICATION_DECISION_TABLE_NODE]
        assert [entry["node_name"] for entry in cdt_entries] == ["cdt_node"]
        assert _excluded(response) == []


@pytest.fixture
def flow_with_owned_and_shared_surfaces(acme):
    """A flow whose agent node carries both an owned surface and a shared one."""
    agent = _agent(acme, "surface owner")
    owned = Surface.objects.create(
        org=acme, name="agent private", instructions="private", owner_agent=agent
    )
    SurfacePythonTool.objects.create(
        surface=owned, python_tool=_python_tool(acme, "private tool"), mode=ToolMode.ALLOW
    )
    shared = Surface.objects.create(org=acme, name="team shared", instructions="shared")
    graph = _flow(acme, "owned surface flow")
    agent_node = AgentNode.objects.create(
        graph=graph, node_name="agent_node_1", agent_definition=agent
    )
    agent_node.surface_list.add(owned, shared)
    return {"graph": graph, "agent_node": agent_node}


def _partial_export(client, flow) -> FinishedExport:
    return export_via_job(
        client,
        f"/api/graphs/{flow['graph'].id}/partial-export-jobs/",
        {"agent_node_list": [flow["agent_node"].id]},
    )


@pytest.mark.django_db
class TestOwnedSurfaceFollowsItsAgent:
    def test_full_export_drops_owned_surface_when_agent_export_is_denied(
        self, flow_with_owned_and_shared_surfaces, make_user
    ):
        user = make_user("owned-full@example.com", tools=READ_AND_EXPORT)

        response = _export(user, flow_with_owned_and_shared_surfaces["graph"])

        payload = _payload(response)
        assert EntityType.AGENT_DEFINITION not in payload
        assert _names(payload, EntityType.SURFACE) == {"team shared"}
        assert EntityType.PYTHON_CODE_TOOL not in payload
        excluded = _excluded_by_type(response)
        assert list(excluded) == ["AgentDefinition"]
        assert excluded["AgentDefinition"]["count"] == 1

    def test_bulk_export_drops_owned_surface_when_agent_export_is_denied(
        self, flow_with_owned_and_shared_surfaces, make_user
    ):
        user = make_user("owned-bulk@example.com", tools=READ_AND_EXPORT)

        response = _bulk_export(user, [flow_with_owned_and_shared_surfaces["graph"]])

        payload = _payload(response)
        assert _names(payload, EntityType.SURFACE) == {"team shared"}
        assert list(_excluded_by_type(response)) == ["AgentDefinition"]

    def test_partial_export_drops_owned_surface_when_agent_export_is_denied(
        self, flow_with_owned_and_shared_surfaces, make_user, client_in_acme
    ):
        user = make_user("owned-partial@example.com", tools=READ_AND_EXPORT)

        response = _partial_export(client_in_acme(user), flow_with_owned_and_shared_surfaces)

        payload = _payload(response)
        assert _names(payload, EntityType.SURFACE) == {"team shared"}
        assert EntityType.PYTHON_CODE_TOOL not in payload
        assert list(_excluded_by_type(response)) == ["AgentDefinition"]

    def test_owned_surface_is_exported_when_agent_export_is_allowed(
        self, flow_with_owned_and_shared_surfaces, make_user, client_in_acme
    ):
        user = make_user(
            "owned-allowed@example.com", agents=READ_AND_EXPORT, tools=READ_AND_EXPORT
        )
        client = client_in_acme(user)

        full = _export(user, flow_with_owned_and_shared_surfaces["graph"])
        partial = _partial_export(client, flow_with_owned_and_shared_surfaces)

        for response in (full, partial):
            payload = _payload(response)
            assert _names(payload, EntityType.SURFACE) == {"agent private", "team shared"}
            assert _names(payload, EntityType.PYTHON_CODE_TOOL) == {"private tool"}
            assert _excluded(response) == []

    def test_shared_surface_is_exported_when_agent_export_is_denied(
        self, flow_with_owned_and_shared_surfaces, make_user
    ):
        user = make_user("shared-only@example.com")

        response = _export(user, flow_with_owned_and_shared_surfaces["graph"])

        assert _names(_payload(response), EntityType.SURFACE) == {"team shared"}

    def test_export_without_owned_surface_imports_cleanly(
        self, acme, flow_with_owned_and_shared_surfaces, make_user, client_in_acme, admin_acme
    ):
        restricted = make_user("owned-roundtrip@example.com")
        exported = _payload(_export(restricted, flow_with_owned_and_shared_surfaces["graph"]))

        response = client_in_acme(admin_acme).post(
            reverse("graphs-import-entity"),
            {"file": data_to_json_file(exported, "flow.json")},
            format="multipart",
        )

        assert response.status_code == 200, response.content
        imported = Graph.objects.exclude(
            pk=flow_with_owned_and_shared_surfaces["graph"].pk
        ).get(org=acme)
        node = imported.agent_node_list.get()
        assert node.agent_definition is None
        assert {surface.name for surface in node.surface_list.all()} == {"team shared"}


@pytest.mark.django_db
class TestRoundTrip:
    def test_a_restricted_export_imports_cleanly_with_agent_references_nulled(
        self, acme, flow_with_agent, make_user, client_in_acme, admin_acme
    ):
        restricted = make_user("roundtrip@example.com")
        exported = _payload(_export(restricted, flow_with_agent["graph"]))
        assert EntityType.AGENT_DEFINITION not in exported

        response = client_in_acme(admin_acme).post(
            reverse("graphs-import-entity"),
            {"file": data_to_json_file(exported, "flow.json")},
            format="multipart",
        )

        assert response.status_code == 200, response.content
        imported = Graph.objects.exclude(pk=flow_with_agent["graph"].pk).get(org=acme)
        assert imported.agent_node_list.get().agent_definition is None
        assert imported.task_node_list.get().agent_definition is None
        assert imported.labels.count() == 1

    def test_stripped_subgraph_and_inline_tools_import_without_error(
        self, acme, flow_with_agent, client_in_acme, admin_acme
    ):
        graph = flow_with_agent["graph"]
        child = _flow(acme, "child flow")
        SubGraphNode.objects.create(graph=graph, node_name="sub", subgraph=child)
        # Flow endpoints already require flows EXPORT, so a missing flows EXPORT bit
        # is only reachable at the service level.
        policy = ExportAccessPolicy(
            EffectivePermissions(is_superadmin=False, role=None, by_resource={})
        )
        result = ExportService(entity_registry).export_entities(
            EntityType.GRAPH, [graph.id], org_id=acme.id, policy=policy
        )
        exported = json.loads(json.dumps(result.data))
        assert _names(exported, EntityType.GRAPH) == {"agent flow"}
        assert EntityType.PYTHON_CODE_TOOL not in exported

        response = client_in_acme(admin_acme).post(
            reverse("graphs-import-entity"),
            {"file": data_to_json_file(exported, "flow.json")},
            format="multipart",
        )

        assert response.status_code == 200, response.content
        imported = Graph.objects.exclude(pk__in=[graph.pk, child.pk]).get(org=acme)
        assert imported.subgraph_node_list.get().subgraph is None
        assert imported.agent_node_list.get().inline_surface.python_tools.count() == 0
