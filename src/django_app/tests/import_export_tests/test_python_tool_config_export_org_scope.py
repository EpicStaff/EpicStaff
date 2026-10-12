"""Exported python-tool configs belong to the exporting organisation only.

A built-in PythonCodeTool is one row shared by every organisation, and each
organisation stores its own PythonCodeToolConfig rows (holding credentials such
as API keys) against it. Exporting the tool, directly or as a dependency of an
agent or a flow, must never carry another organisation's configs.
"""

import json
from io import BytesIO

import pytest

from agents.models import AgentDefinition, Surface, SurfacePythonTool, ToolMode
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.models import AgentNode, Graph, StartNode
from tables.models.python_models import PythonCode, PythonCodeTool, PythonCodeToolConfig

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

ACME_SECRET = "sk-acme-own-key"
BETA_SECRET = "sk-beta-foreign-key"


@pytest.fixture
def client(client_as, admin_acme, acme):
    api_client = client_as(admin_acme)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return api_client


@pytest.fixture
def builtin_tool(db):
    return PythonCodeTool.objects.create(
        name="SharedBuiltInTool",
        description="built-in",
        python_code=PythonCode.objects.create(code="def main(): return 1", entrypoint="main"),
        built_in=True,
        org=None,
    )


@pytest.fixture
def acme_config(builtin_tool, acme):
    return PythonCodeToolConfig.objects.create(
        name="acme-config",
        tool=builtin_tool,
        configuration={"api_key": ACME_SECRET},
        org=acme,
    )


@pytest.fixture
def beta_config(builtin_tool, beta):
    return PythonCodeToolConfig.objects.create(
        name="beta-config",
        tool=builtin_tool,
        configuration={"api_key": BETA_SECRET},
        org=beta,
    )


@pytest.fixture
def acme_agent_using_builtin_tool(acme, builtin_tool):
    definition = AgentDefinition.objects.create(organization=acme, name="acme-agent")
    surface = Surface.objects.create(
        organization=acme, name="acme-surface", owner_agent=definition
    )
    SurfacePythonTool.objects.create(
        surface=surface, python_tool=builtin_tool, mode=ToolMode.ALLOW
    )
    return definition


@pytest.fixture
def acme_agent_node(acme, acme_agent_using_builtin_tool):
    graph = Graph.objects.create(name="acme-flow", org=acme, metadata={"nodes": [], "edges": []})
    StartNode.objects.create(graph=graph, variables={})
    return AgentNode.objects.create(
        graph=graph, node_name="agent", agent_definition=acme_agent_using_builtin_tool
    )


def _tool_entry(export_data: dict, tool_id: int) -> dict:
    return next(row for row in export_data[EntityType.PYTHON_CODE_TOOL] if row["id"] == tool_id)


def _exported_configs(export_data: dict, tool_id: int) -> list[dict]:
    configs = _tool_entry(export_data, tool_id)["python_code_tool_config"]
    for config in configs:
        assert "org" not in config
    return [(config["name"], config["configuration"]) for config in configs]


def _assert_only_acme_config(export_data: dict, tool_id: int) -> None:
    assert BETA_SECRET not in json.dumps(export_data)
    assert _exported_configs(export_data, tool_id) == [
        ("acme-config", {"api_key": ACME_SECRET})
    ]


@pytest.mark.django_db
@pytest.mark.usefixtures("acme_config", "beta_config")
class TestBuiltInToolConfigExportIsOrgScoped:
    def test_single_export_carries_only_own_org_config_without_org_field(
        self, client, builtin_tool
    ):
        response = client.get(f"/api/python-code-tool/{builtin_tool.id}/export/")

        assert response.status_code == 200
        _assert_only_acme_config(json.loads(response.content), builtin_tool.id)

    def test_bulk_export_carries_only_own_org_config_without_org_field(
        self, client, builtin_tool
    ):
        response = client.post(
            "/api/python-code-tool/bulk-export/", {"ids": [builtin_tool.id]}, format="json"
        )

        assert response.status_code == 200
        _assert_only_acme_config(json.loads(response.content), builtin_tool.id)

    def test_agent_export_carries_only_own_org_config_of_dependency_tool(
        self, export_service, acme, builtin_tool, acme_agent_using_builtin_tool
    ):
        export_data = export_service.export_entities(
            EntityType.AGENT_DEFINITION, [acme_agent_using_builtin_tool.id], org_id=acme.id
        )

        _assert_only_acme_config(export_data, builtin_tool.id)

    def test_flow_export_carries_only_own_org_config_of_dependency_tool(
        self, export_service, acme, builtin_tool, acme_agent_node
    ):
        export_data = export_service.export_entities(
            EntityType.GRAPH, [acme_agent_node.graph_id], org_id=acme.id
        )

        _assert_only_acme_config(export_data, builtin_tool.id)

    def test_partial_export_carries_only_own_org_config_of_dependency_tool(
        self, client, builtin_tool, acme_agent_node
    ):
        response = client.post(
            f"/api/graphs/{acme_agent_node.graph_id}/partial-export/",
            {"agent_node_list": [acme_agent_node.id]},
            format="json",
        )

        assert response.status_code == 200
        _assert_only_acme_config(json.loads(response.content), builtin_tool.id)

    def test_export_without_org_carries_no_config(self, export_service, builtin_tool):
        export_data = export_service.export_entities(
            EntityType.PYTHON_CODE_TOOL, [builtin_tool.id]
        )
        strategy_data = entity_registry.get_strategy(
            EntityType.PYTHON_CODE_TOOL
        ).export_entity(builtin_tool)

        assert _tool_entry(export_data, builtin_tool.id)["python_code_tool_config"] == []
        assert strategy_data["python_code_tool_config"] == []


@pytest.fixture
def acme_custom_tool_with_config(acme):
    tool = PythonCodeTool.objects.create(
        name="AcmeCustomTool",
        description="custom",
        python_code=PythonCode.objects.create(code="def main(): return 2", entrypoint="main"),
        org=acme,
    )
    PythonCodeToolConfig.objects.create(
        name="acme-custom-config",
        tool=tool,
        configuration={"api_key": ACME_SECRET},
        org=acme,
    )
    return tool


def _as_upload(content: bytes) -> BytesIO:
    upload = BytesIO(content)
    upload.name = "python_tool.json"
    return upload


@pytest.mark.django_db
def test_custom_tool_config_round_trips_into_importing_org(
    client, acme, acme_custom_tool_with_config
):
    export_response = client.get(
        f"/api/python-code-tool/{acme_custom_tool_with_config.id}/export/"
    )
    assert export_response.status_code == 200
    assert _exported_configs(
        json.loads(export_response.content), acme_custom_tool_with_config.id
    ) == [("acme-custom-config", {"api_key": ACME_SECRET})]

    import_response = client.post(
        "/api/python-code-tool/import/",
        {"file": _as_upload(export_response.content)},
        format="multipart",
    )

    assert import_response.status_code == 200, import_response.data
    imported_tool = (
        PythonCodeTool.objects.filter(org=acme)
        .exclude(id=acme_custom_tool_with_config.id)
        .get()
    )
    assert list(
        PythonCodeToolConfig.objects.filter(tool=imported_tool).values(
            "name", "configuration", "org_id"
        )
    ) == [
        {
            "name": "acme-custom-config",
            "configuration": {"api_key": ACME_SECRET},
            "org_id": acme.id,
        }
    ]


@pytest.mark.django_db
def test_custom_tool_config_imported_by_another_org_lands_in_that_org(
    export_service, import_service, acme, beta, acme_custom_tool_with_config
):
    export_data = export_service.export_entities(
        EntityType.PYTHON_CODE_TOOL, [acme_custom_tool_with_config.id], org_id=acme.id
    )

    import_service.import_data(export_data, EntityType.PYTHON_CODE_TOOL, org_id=beta.id)

    imported_tool = PythonCodeTool.objects.get(org=beta)
    assert list(
        PythonCodeToolConfig.objects.filter(tool=imported_tool).values_list("org_id", flat=True)
    ) == [beta.id]
