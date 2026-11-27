"""Agents export through an export job (`agent-definitions/export-jobs/`) and import through
the synchronous `import/`, which takes the job's `.zip` as well as a plain `.json` export.
A `.zip` carrying the knowledge collections of the agents' surfaces imports through an
import job instead.

Presentation tests through the real endpoints; the export job runs inline with an
in-memory archive store.
"""

import io
import json
import re

import pytest
from agents.models import (
    AgentDefaultSurface,
    AgentDefinition,
    Surface,
    SurfaceKnowledge,
    SurfaceMcpTool,
    SurfacePlace,
    SurfacePythonTool,
    ToolMode,
)
from rbac.models.enums import Permission, ResourceType
from ai_models.models import LLMConfig, LLMModel, Provider
from tables.import_export.archive import ENVELOPE_MEMBER
from tables.import_export.enums import EntityType
from tables.import_export.schemas import ImportSettings
from tables.models import TransferJob
from tables.models.knowledge_models import DocumentMetadata, SourceCollection
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.user import User
from tables.services.transfer_jobs.archive_store import TransferArchiveStore
from tables.services.transfer_jobs.job_service import TransferJobService
from tables.services.transfer_jobs.runner import TransferJobRunner
from tests.api_tests.role_grant_clients import FULL_CRUD, client_with_grants
from tests.import_export_tests.knowledge_builders import make_document
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_backend_fake import FakeStorageBackend
from tests.transfer_job_helpers import FinishedExport, export_via_job
from tests.knowledge_content import stored_document_bytes

URL = "/api/agent-definitions/"
EXPORT_JOBS_URL = f"{URL}export-jobs/"
EXPORT = int(Permission.EXPORT)
READ = int(Permission.READ)
FULL_GRANTS = {
    ResourceType.AGENTS: FULL_CRUD | EXPORT,
    ResourceType.TOOLS: FULL_CRUD | EXPORT,
    ResourceType.SURFACES: FULL_CRUD,
    ResourceType.LLM_CONFIGS: FULL_CRUD,
}
KNOWLEDGE_GRANTS = {**FULL_GRANTS, ResourceType.KNOWLEDGE_SOURCES: FULL_CRUD | EXPORT}


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


def _start_export(client, ids):
    return client.post(EXPORT_JOBS_URL, {"ids": ids}, format="json")


def _export(client, *agents) -> FinishedExport:
    """Export `agents` through a job, run it, and expect it to complete."""
    exported = export_via_job(client, EXPORT_JOBS_URL, {"ids": [agent.id for agent in agents]})
    assert exported.job.status == TransferJob.Status.COMPLETED, exported.job.error
    return exported


def _upload(content: bytes, name: str) -> io.BytesIO:
    upload = io.BytesIO(content)
    upload.name = name
    return upload


def _import(client, exported: FinishedExport, **fields):
    """Import the job's `.zip`, the file the export's download hands the user."""
    return client.post(f"{URL}import/", {"file": exported.upload(), **fields}, format="multipart")


def _inspect(client, exported: FinishedExport):
    return client.post(
        f"{URL}import/inspect/", {"file": exported.upload()}, format="multipart"
    )


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
def test_export_job_archives_the_agent_and_its_dependencies(acme_client, agent, shared_surface):
    exported = _export(acme_client, agent)

    assert exported.job.main_entity == TransferJob.MainEntity.AGENT_DEFINITION
    assert exported.job.display_name == "Researcher"
    assert re.fullmatch(r"agent_researcher_\d{4}-\d{2}-\d{2}\.zip", exported.job.file_name)
    assert exported.job.result == {"excluded": []}
    data = exported.envelope
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
def test_export_job_of_several_agents_covers_all_ids(acme_client, agent, second_agent):
    exported = _export(acme_client, agent, second_agent)

    assert exported.job.display_name == "2 agents"
    assert re.fullmatch(r"agent_bulk_2_\d{4}-\d{2}-\d{2}\.zip", exported.job.file_name)
    assert exported.envelope["main_entity"] == "AgentDefinition"
    assert {row["id"] for row in exported.envelope["AgentDefinition"]} == {
        agent.id,
        second_agent.id,
    }


@pytest.mark.django_db
@pytest.mark.parametrize("other", ["other-org", "missing"])
def test_export_job_with_an_id_outside_the_org_is_not_found(acme_client, agent, beta, other):
    other_id = (
        AgentDefinition.objects.create(org=beta, name="Theirs").id
        if other == "other-org"
        else agent.id + 999999
    )

    alone = _start_export(acme_client, [other_id])
    with_own = _start_export(acme_client, [agent.id, other_id])

    # The same 404 for another org's agent and a missing one: nothing tells them apart.
    for response in (alone, with_own):
        assert response.status_code == 404, response.content
        assert response.json()["code"] == "export_entities_not_found"
    assert not TransferJob.objects.exists()


@pytest.mark.django_db
def test_a_binned_agent_is_not_exportable(acme_client, agent, second_agent):
    agent.delete()

    for ids in ([agent.id], [agent.id, second_agent.id]):
        response = _start_export(acme_client, ids)
        assert response.status_code == 404, response.content
    assert not TransferJob.objects.exists()


@pytest.mark.django_db
def test_export_without_tools_export_leaves_tools_out_and_names_them_in_the_job(
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

    exported = _export(client, agent)

    assert "PythonCodeTool" not in exported.envelope
    assert "MCPTool" not in exported.envelope
    assert {(item["entity_type"], item["name"]) for item in exported.job.result["excluded"]} == {
        ("PythonCodeTool", "AgentIoPyTool"),
        ("MCPTool", "AgentIoMcpTool"),
    }


# ---- import ----


@pytest.mark.django_db
def test_import_into_the_same_org_creates_a_copy_and_reuses_its_dependencies(
    acme_client, acme, agent, llm_config, python_tool, mcp_tool, shared_surface
):
    exported = _export(acme_client, agent)
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
    resp = _import(beta_client, _export(acme_client, agent))

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
def test_the_archives_export_json_imports_as_a_plain_json_file(
    acme_client, beta_client, beta, agent
):
    envelope = _export(acme_client, agent).envelope

    resp = beta_client.post(
        f"{URL}import/",
        {"file": _upload(json.dumps(envelope).encode(), "agent.json")},
        format="multipart",
    )

    assert resp.status_code == 200, resp.content
    assert AgentDefinition.objects.get(org=beta).name == "Researcher"


@pytest.mark.django_db
def test_reimporting_the_same_file_reuses_identical_dependencies(
    acme_client, beta_client, beta, agent
):
    exported = _export(acme_client, agent)

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
    exported = _export(acme_client, agent)

    _import(acme_client, exported)
    resp = _import(acme_client, exported)

    assert resp.status_code == 200, resp.content
    assert LLMConfig.objects.filter(org=acme).count() == 1
    assert resp.json()["LLMConfig"]["reused"]["count"] == 1
    assert AgentDefinition.objects.filter(org=acme).count() == 3


@pytest.mark.django_db
def test_reimporting_into_another_org_reuses_the_llm_config(acme_client, beta_client, beta, agent):
    exported = _export(acme_client, agent)

    _import(beta_client, exported)
    resp = _import(beta_client, exported)

    assert resp.status_code == 200, resp.content
    assert LLMConfig.objects.filter(org=beta).count() == 1
    assert resp.json()["LLMConfig"]["reused"]["count"] == 1


@pytest.mark.django_db
def test_an_export_of_several_agents_imports_every_agent(
    acme_client, beta_client, beta, agent, second_agent
):
    exported = _export(acme_client, agent, second_agent)

    resp = _import(beta_client, exported)

    assert resp.status_code == 200, resp.content
    assert set(AgentDefinition.objects.filter(org=beta).values_list("name", flat=True)) == {
        "Researcher",
        "Writer",
    }


@pytest.mark.django_db
def test_import_rejects_a_file_of_another_entity_type(acme_client, mcp_tool):
    exported = export_via_job(acme_client, "/api/mcp-tools/export-jobs/", {"ids": [mcp_tool.id]})
    assert exported.job.status == TransferJob.Status.COMPLETED, exported.job.error

    resp = _import(acme_client, exported)

    assert resp.status_code == 400
    assert AgentDefinition.objects.count() == 0


@pytest.mark.django_db
def test_inspect_lists_the_tools_in_the_file(acme_client, agent):
    resp = _inspect(acme_client, _export(acme_client, agent))

    assert resp.status_code == 200, resp.content
    assert "review_items" in resp.json()
    assert len(resp.json()["review_items"]) >= 2
    assert AgentDefinition.objects.count() == 1


# ---- permissions ----


@pytest.mark.django_db
def test_export_job_requires_agents_export(acme, django_user_model, agent, second_agent):
    client = _client(
        acme,
        django_user_model,
        "agent-io-no-export@example.com",
        {**FULL_GRANTS, ResourceType.AGENTS: FULL_CRUD},
    )

    assert _start_export(client, [agent.id]).status_code == 403
    assert _start_export(client, [agent.id, second_agent.id]).status_code == 403
    assert not TransferJob.objects.exists()


@pytest.mark.django_db
def test_import_and_inspect_require_agents_create(acme_client, acme, django_user_model, agent):
    exported = _export(acme_client, agent)
    client = _client(
        acme,
        django_user_model,
        "agent-io-no-create@example.com",
        {**FULL_GRANTS, ResourceType.AGENTS: READ | EXPORT},
    )

    assert _import(client, exported).status_code == 403
    assert _inspect(client, exported).status_code == 403
    assert AgentDefinition.objects.filter(org=acme).count() == 1


# ---- knowledge ----


@pytest.fixture
def collection(acme):
    collection = SourceCollection.objects.create(
        collection_name="Handbook", description="HR docs", org=acme
    )
    make_document(collection, "policy.txt", b"policy bytes")
    return collection


@pytest.fixture
def knowing_agent(acme, collection):
    """An agent whose owned surface has knowledge on `collection`."""
    agent = AgentDefinition.objects.create(org=acme, name="Librarian")
    owned = Surface.objects.create(
        org=acme, name="librarian-owned", instructions="look it up", owner_agent=agent
    )
    SurfaceKnowledge.objects.create(surface=owned, collection=collection)
    return agent


@pytest.fixture
def knowledge_client(acme, django_user_model):
    return _client(acme, django_user_model, "agent-io-knowledge@example.com", KNOWLEDGE_GRANTS)


def _run_import_job(archive: bytes, org, importer: User, tmp_path) -> TransferJob:
    """Start an import job of `archive` into `org` as `importer`, run it, and return it."""
    path = tmp_path / "agent.zip"
    path.write_bytes(archive)
    store = TransferArchiveStore(backend=FakeStorageBackend())
    job = TransferJobService().start_import(
        user=importer,
        org_id=org.id,
        entity_type=EntityType.AGENT_DEFINITION,
        settings=ImportSettings(import_labels=True),
        archive_path=str(path),
        store=store,
    )
    TransferJobRunner(store=store).run(job.id)
    job.refresh_from_db()
    return job


@pytest.mark.django_db
def test_an_agent_export_job_includes_knowledge_unless_asked_otherwise(acme_client, agent):
    default = _start_export(acme_client, [agent.id])
    without = acme_client.post(
        EXPORT_JOBS_URL, {"ids": [agent.id], "include_knowledge": False}, format="json"
    )

    assert (default.status_code, without.status_code) == (202, 202)
    assert TransferJob.objects.get(pk=default.json()["job_id"]).request == {
        "ids": [agent.id],
        "include_knowledge": True,
    }
    assert TransferJob.objects.get(pk=without.json()["job_id"]).request == {
        "ids": [agent.id],
        "include_knowledge": False,
    }


@pytest.mark.django_db
def test_an_agent_archive_carries_the_owned_surfaces_collection_with_its_files(
    knowledge_client, knowing_agent, collection
):
    exported = _export(knowledge_client, knowing_agent)

    assert [entry["id"] for entry in exported.envelope["SourceCollection"]] == [
        collection.collection_id
    ]
    [document] = collection.documents.all()
    assert set(exported.members) == {
        ENVELOPE_MEMBER,
        f"knowledge/documents/{document.document_id}",
    }


@pytest.mark.django_db
def test_an_agent_archive_without_knowledge_carries_no_collection(
    knowledge_client, knowing_agent
):
    exported = export_via_job(
        knowledge_client,
        EXPORT_JOBS_URL,
        {"ids": [knowing_agent.id], "include_knowledge": False},
    )

    assert exported.job.status == TransferJob.Status.COMPLETED, exported.job.error
    assert "SourceCollection" not in exported.envelope
    assert list(exported.members) == [ENVELOPE_MEMBER]


@pytest.mark.django_db
def test_an_import_job_relinks_the_owned_surface_to_the_imported_collection(
    knowledge_client, knowing_agent, collection, beta, django_user_model, tmp_path
):
    exported = _export(knowledge_client, knowing_agent)
    _client(beta, django_user_model, "agent-io-knowledge-beta@example.com", KNOWLEDGE_GRANTS)
    importer = User.objects.get(email="agent-io-knowledge-beta@example.com")

    job = _run_import_job(exported.archive, beta, importer, tmp_path)

    assert job.status == TransferJob.Status.COMPLETED, job.error
    assert job.main_entity == TransferJob.MainEntity.AGENT_DEFINITION
    imported_collection = SourceCollection.objects.get(org=beta)
    assert imported_collection.collection_id != collection.collection_id
    assert imported_collection.collection_name == "Handbook"
    [document] = DocumentMetadata.objects.filter(source_collection=imported_collection)
    assert (document.file_name, stored_document_bytes(document)) == (
        "policy.txt",
        b"policy bytes",
    )
    owned = AgentDefinition.objects.get(org=beta).owned_surfaces.get()
    assert list(owned.knowledge.values_list("collection_id", flat=True)) == [
        imported_collection.collection_id
    ]


@pytest.mark.django_db
def test_the_synchronous_import_sends_an_archive_with_knowledge_to_the_agent_import_job(
    knowledge_client, knowing_agent
):
    exported = _export(knowledge_client, knowing_agent)

    response = _import(knowledge_client, exported)

    assert response.status_code == 400, response.content
    assert response.json()["code"] == "use_import_job"
    assert response.json()["message"] == (
        "This archive carries knowledge collections; import it as an agent import job."
    )
    assert AgentDefinition.objects.count() == 1
