import json
import re

import pytest
from agents.models import (
    AgentDefaultSurface,
    AgentDefinition,
    Surface,
    SurfaceMcpTool,
    SurfacePlace,
    SurfacePythonTool,
    ToolMode,
)
from rbac.models.enums import Permission, ResourceType
from tables.models import LLMConfig, LLMModel, Provider
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from tests.api_tests.role_grant_clients import FULL_CRUD, client_with_grants
from tests.helpers import data_to_json_file
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

URL = "/api/agent-definitions/"
EXPORT = int(Permission.EXPORT)
READ = int(Permission.READ)
FULL_GRANTS = {
    ResourceType.AGENTS: FULL_CRUD | EXPORT,
    ResourceType.TOOLS: FULL_CRUD | EXPORT,
    ResourceType.SURFACES: FULL_CRUD,
    ResourceType.LLM_CONFIGS: FULL_CRUD,
}


def _client(org, django_user_model, email, grants=None):
    return client_with_grants(
        org=org,
        django_user_model=django_user_model,
        email=email,
        resource_permissions={
            resource.value: bitmask for resource, bitmask in (grants or FULL_GRANTS).items()
        },
    )


@pytest.fixture
def acme_client(acme, django_user_model):
    return _client(acme, django_user_model, "agent-io-acme@example.com")


@pytest.fixture
def beta_client(beta, django_user_model):
    return _client(beta, django_user_model, "agent-io-beta@example.com")


@pytest.fixture
def llm_config(acme):
    provider, _ = Provider.objects.get_or_create(name="agent-io-provider")
    model, _ = LLMModel.objects.get_or_create(name="agent-io-model", llm_provider=provider)
    return LLMConfig.objects.create(custom_name="agent-io-llm", model=model, org=acme)


@pytest.fixture
def python_tool(acme):
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    return PythonCodeTool.objects.create(
        name="AgentIoPyTool", description="desc", python_code=code, org=acme
    )


@pytest.fixture
def mcp_tool(acme):
    return McpTool.objects.create(
        name="AgentIoMcpTool", transport="https://example.com/mcp", tool_name="do", org=acme
    )


@pytest.fixture
def shared_surface(acme, python_tool):
    surface = Surface.objects.create(org=acme, name="agent-io-shared", instructions="shared")
    SurfacePythonTool.objects.create(surface=surface, python_tool=python_tool, mode=ToolMode.ALLOW)
    return surface


@pytest.fixture
def agent(acme, llm_config, python_tool, mcp_tool, shared_surface):
    agent = AgentDefinition.objects.create(
        org=acme,
        name="Researcher",
        description="Finds things",
        instruction_list=[{"name": "main.md", "content": "Be thorough."}],
        llm_config=llm_config,
    )
    owned = Surface.objects.create(
        org=acme, name="researcher-owned", instructions="owned", owner_agent=agent
    )
    SurfacePythonTool.objects.create(surface=owned, python_tool=python_tool, mode=ToolMode.ALLOW)
    SurfaceMcpTool.objects.create(surface=owned, mcp_tool=mcp_tool, mode=ToolMode.DENY)
    AgentDefaultSurface.objects.create(
        agent_definition=agent, surface=owned, place=SurfacePlace.ALL
    )
    AgentDefaultSurface.objects.create(
        agent_definition=agent, surface=shared_surface, place=SurfacePlace.CHAT
    )
    return agent


@pytest.fixture
def second_agent(acme):
    return AgentDefinition.objects.create(org=acme, name="Writer")


def _export(client, agent):
    return client.get(f"{URL}{agent.id}/export/")


def _bulk_export(client, ids):
    return client.post(f"{URL}bulk-export/", {"ids": ids}, format="json")


def _import(client, content, **fields):
    upload = data_to_json_file(json.loads(content), "agent.json")
    return client.post(f"{URL}import/", {"file": upload, **fields}, format="multipart")


def _inspect(client, content):
    upload = data_to_json_file(json.loads(content), "agent.json")
    return client.post(f"{URL}import/inspect/", {"file": upload}, format="multipart")


def _imported_agent(org, exclude_ids=()):
    return AgentDefinition.objects.filter(org=org).exclude(id__in=exclude_ids).latest("id")


def _owned_tool_ids(agent):
    surface = agent.owned_surfaces.get()
    return (
        set(surface.python_tools.values_list("python_tool_id", flat=True)),
        set(surface.mcp_tools.values_list("mcp_tool_id", flat=True)),
    )


# ---- export ----


@pytest.mark.django_db
def test_export_returns_a_json_file_with_the_agent_and_its_dependencies(
    acme_client, agent, shared_surface
):
    resp = _export(acme_client, agent)

    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/json"
    assert re.fullmatch(
        r'attachment; filename="agent_researcher_\d{4}-\d{2}-\d{2}\.json"',
        resp["Content-Disposition"],
    )
    assert "X-Export-Excluded" not in resp
    data = resp.json()
    assert data["main_entity"] == "AgentDefinition"
    assert isinstance(data["version"], int)
    assert [row["id"] for row in data["AgentDefinition"]] == [agent.id]
    assert {row["id"] for row in data["Surface"]} == {
        agent.owned_surfaces.get().id,
        shared_surface.id,
    }
    assert [row["id"] for row in data["LLMConfig"]] == [agent.llm_config_id]
    assert [row["name"] for row in data["PythonCodeTool"]] == ["AgentIoPyTool"]
    assert [row["name"] for row in data["MCPTool"]] == ["AgentIoMcpTool"]


@pytest.mark.django_db
def test_export_of_another_orgs_agent_is_404(acme_client, beta):
    foreign = AgentDefinition.objects.create(org=beta, name="Theirs")

    assert _export(acme_client, foreign).status_code == 404


@pytest.mark.django_db
def test_a_binned_agent_is_not_exportable(acme_client, agent, second_agent):
    agent.delete()

    assert _export(acme_client, agent).status_code == 404
    assert _bulk_export(acme_client, [agent.id, second_agent.id]).status_code == 400


@pytest.mark.django_db
def test_bulk_export_covers_all_ids(acme_client, agent, second_agent):
    resp = _bulk_export(acme_client, [agent.id, second_agent.id])

    assert resp.status_code == 200, resp.content
    assert re.fullmatch(
        r'attachment; filename="agent_bulk_2_\d{4}-\d{2}-\d{2}\.json"',
        resp["Content-Disposition"],
    )
    data = resp.json()
    assert data["main_entity"] == "AgentDefinition"
    assert {row["id"] for row in data["AgentDefinition"]} == {agent.id, second_agent.id}


@pytest.mark.django_db
@pytest.mark.parametrize("other", ["other-org", "missing"])
def test_bulk_export_with_an_id_outside_the_org_is_400(acme_client, agent, beta, other):
    other_id = (
        AgentDefinition.objects.create(org=beta, name="Theirs").id
        if other == "other-org"
        else agent.id + 999999
    )

    resp = _bulk_export(acme_client, [agent.id, other_id])

    assert resp.status_code == 400
    assert resp.json()["message"] == "Some entity IDs do not exist"


@pytest.mark.django_db
def test_export_without_tools_export_leaves_tools_out_and_names_them_in_the_header(
    acme, django_user_model, agent
):
    client = _client(
        acme,
        django_user_model,
        "agent-io-no-tools-export@example.com",
        {
            ResourceType.AGENTS: READ | EXPORT,
            ResourceType.TOOLS: READ,
        },
    )

    resp = _export(client, agent)

    assert resp.status_code == 200
    assert "PythonCodeTool" not in resp.json()
    assert "MCPTool" not in resp.json()
    excluded = {entry["type"]: entry for entry in json.loads(resp["X-Export-Excluded"])}
    assert excluded["PythonCodeTool"] == {
        "type": "PythonCodeTool",
        "count": 1,
        "names": ["AgentIoPyTool"],
    }
    assert excluded["MCPTool"] == {"type": "MCPTool", "count": 1, "names": ["AgentIoMcpTool"]}


# ---- import ----


@pytest.mark.django_db
def test_import_into_the_same_org_creates_a_copy_and_reuses_its_dependencies(
    acme_client, acme, agent, llm_config, python_tool, mcp_tool, shared_surface
):
    exported = _export(acme_client, agent).content
    tool_counts = (PythonCodeTool.objects.count(), McpTool.objects.count())

    resp = _import(acme_client, exported)

    assert resp.status_code == 200, resp.content
    assert resp.json()["AgentDefinition"]["created"]["count"] == 1
    imported = _imported_agent(acme, exclude_ids=[agent.id])
    assert imported.name != agent.name
    assert imported.instruction_list == agent.instruction_list
    assert imported.llm_config_id == llm_config.id
    assert (PythonCodeTool.objects.count(), McpTool.objects.count()) == tool_counts
    assert _owned_tool_ids(imported) == ({python_tool.id}, {mcp_tool.id})
    assert imported.owned_surfaces.get().id != agent.owned_surfaces.get().id
    assert set(imported.default_surfaces.values_list("surface_id", "place")) == {
        (imported.owned_surfaces.get().id, SurfacePlace.ALL),
        (shared_surface.id, SurfacePlace.CHAT),
    }


@pytest.mark.django_db
def test_import_into_another_org_recreates_the_agent_with_its_dependencies(
    acme_client, beta_client, beta, agent
):
    resp = _import(beta_client, _export(acme_client, agent).content)

    assert resp.status_code == 200, resp.content
    imported = AgentDefinition.objects.get(org=beta)
    assert imported.name == "Researcher"
    assert imported.description == "Finds things"
    assert imported.llm_config.org_id == beta.id
    owned = imported.owned_surfaces.get()
    assert owned.org_id == beta.id
    assert owned.instructions == "owned"
    python_tool_ids, mcp_tool_ids = _owned_tool_ids(imported)
    assert PythonCodeTool.objects.get(id__in=python_tool_ids).org_id == beta.id
    assert McpTool.objects.get(id__in=mcp_tool_ids).org_id == beta.id
    assert SurfaceMcpTool.objects.get(surface=owned).mode == ToolMode.DENY
    assert set(imported.default_surfaces.values_list("surface__name", "place")) == {
        (owned.name, SurfacePlace.ALL),
        ("agent-io-shared", SurfacePlace.CHAT),
    }


@pytest.mark.django_db
def test_reimporting_the_same_file_reuses_identical_dependencies(
    acme_client, beta_client, beta, agent
):
    exported = _export(acme_client, agent).content

    first = _import(beta_client, exported)
    counts_after_first = (
        PythonCodeTool.objects.filter(org=beta).count(),
        McpTool.objects.filter(org=beta).count(),
        Surface.objects.filter(org=beta, owner_agent__isnull=True).count(),
    )
    second = _import(beta_client, exported)

    assert first.status_code == 200, first.content
    assert second.status_code == 200, second.content
    assert counts_after_first == (1, 1, 1)
    assert (
        PythonCodeTool.objects.filter(org=beta).count(),
        McpTool.objects.filter(org=beta).count(),
        Surface.objects.filter(org=beta, owner_agent__isnull=True).count(),
    ) == counts_after_first
    assert AgentDefinition.objects.filter(org=beta).count() == 2
    assert Surface.objects.filter(org=beta, owner_agent__isnull=False).count() == 2
    assert second.json()["PythonCodeTool"]["reused"]["count"] == 1
    assert second.json()["MCPTool"]["reused"]["count"] == 1
    assert second.json()["Surface"]["reused"]["count"] == 1


@pytest.mark.django_db
def test_reimporting_into_the_source_org_reuses_the_llm_config(
    acme_client, acme, agent, llm_config
):
    exported = _export(acme_client, agent).content

    _import(acme_client, exported)
    resp = _import(acme_client, exported)

    assert resp.status_code == 200, resp.content
    assert LLMConfig.objects.filter(org=acme).count() == 1
    assert resp.json()["LLMConfig"]["reused"]["count"] == 1
    assert AgentDefinition.objects.filter(org=acme).count() == 3


@pytest.mark.django_db
def test_reimporting_into_another_org_reuses_the_llm_config(acme_client, beta_client, beta, agent):
    exported = _export(acme_client, agent).content

    _import(beta_client, exported)
    resp = _import(beta_client, exported)

    assert resp.status_code == 200, resp.content
    assert LLMConfig.objects.filter(org=beta).count() == 1
    assert resp.json()["LLMConfig"]["reused"]["count"] == 1


@pytest.mark.django_db
def test_bulk_exported_file_imports_every_agent(acme_client, beta_client, beta, agent, second_agent):
    exported = _bulk_export(acme_client, [agent.id, second_agent.id]).content

    resp = _import(beta_client, exported)

    assert resp.status_code == 200, resp.content
    assert set(AgentDefinition.objects.filter(org=beta).values_list("name", flat=True)) == {
        "Researcher",
        "Writer",
    }


@pytest.mark.django_db
def test_import_rejects_a_file_of_another_entity_type(acme_client, mcp_tool):
    exported = acme_client.get(f"/api/mcp-tools/{mcp_tool.id}/export/").content

    resp = _import(acme_client, exported)

    assert resp.status_code == 400


@pytest.mark.django_db
def test_inspect_lists_the_tools_in_the_file(acme_client, agent):
    resp = _inspect(acme_client, _export(acme_client, agent).content)

    assert resp.status_code == 200, resp.content
    assert "review_items" in resp.json()
    assert len(resp.json()["review_items"]) >= 2
    assert AgentDefinition.objects.count() == 1


# ---- permissions ----


@pytest.mark.django_db
def test_export_requires_agents_export(acme, django_user_model, agent):
    client = _client(
        acme,
        django_user_model,
        "agent-io-no-export@example.com",
        {**FULL_GRANTS, ResourceType.AGENTS: FULL_CRUD},
    )

    assert _export(client, agent).status_code == 403
    assert _bulk_export(client, [agent.id]).status_code == 403


@pytest.mark.django_db
def test_import_and_inspect_require_agents_create(acme_client, acme, django_user_model, agent):
    exported = _export(acme_client, agent).content
    client = _client(
        acme,
        django_user_model,
        "agent-io-no-create@example.com",
        {**FULL_GRANTS, ResourceType.AGENTS: READ | EXPORT},
    )

    assert _import(client, exported).status_code == 403
    assert _inspect(client, exported).status_code == 403
    assert AgentDefinition.objects.filter(org=acme).count() == 1
