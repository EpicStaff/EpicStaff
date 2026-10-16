"""Surfaces: what the write serializer stores, what the read serializer shows, what both refuse,
the database's uniqueness rules, and which surfaces an agent ends up with by default.

Plain field storage (a mode or flag read back unchanged) is not retested on its own.
"""

import pytest
from django.db import IntegrityError
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.test import APIRequestFactory

from agents.exceptions import SurfaceValidationError
from agents.models import (
    AgentDefaultSurface,
    AgentDefinition,
    Surface,
    SurfacePlace,
)
from agents.models.surface_models import (
    SurfaceKnowledge,
    SurfacePythonTool,
    SurfaceStorageItem,
)
from agents.serializers.agent_definition_serializers import AgentDefinitionReadSerializer
from agents.serializers.surface_serializers import SurfaceReadSerializer, SurfaceWriteSerializer
from agents.validators.surface_validator import SurfaceValidator
from tables.models.graph_models import StorageFile
from tables.models.knowledge_models.collection_models import (
    BaseRagType,
    SourceCollection,
)
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from rbac.models import Organization


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def org(db):
    return Organization.objects.create(name="test-surface-org")


@pytest.fixture
def org_request(org, superadmin_user):
    """Authenticated request scoped to `org`, for `SurfaceWriteSerializer`
    context. Its FK fields (owner_agent, python_tool, mcp_tool, storage_file,
    collection) resolve org scope from `request` via `OrgContextService` (see
    `rbac/scoping/fields.py`) — without a request they deny
    every pk. `superadmin_user` bypasses the membership check so this fixture
    doesn't need an `OrganizationUser` row wired up.

    Built directly (not through a view), so `force_authenticate` — which only
    takes effect once DRF's `Request` wrapper runs its own authentication —
    would not populate `.user`. Assigning it directly on the raw
    `WSGIRequest` is enough for `OrgContextService`, which only reads
    `request.user` and `request.headers`.
    """
    request = APIRequestFactory().post("/", HTTP_X_ORGANIZATION_ID=str(org.pk))
    request.user = superadmin_user
    return request


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="other-org")


@pytest.fixture
def agent(db, org):
    return AgentDefinition.objects.create(
        org=org,
        name="agent-a",
        instruction_list=[{"name": "Instruction_1.md", "content": "do things"}],
    )


@pytest.fixture
def agent_b(db, org):
    return AgentDefinition.objects.create(
        org=org,
        name="agent-b",
        instruction_list=[{"name": "Instruction_1.md", "content": "do other things"}],
    )


def _python_tool(org, name):
    return PythonCodeTool.objects.create(
        org=org, name=name, description="test", python_code=PythonCode.objects.create(code="def main(): pass")
    )


@pytest.fixture
def py_tool_a(db, org):
    return _python_tool(org, "surface-py-tool-a")


@pytest.fixture
def py_tool_b(db, org):
    return _python_tool(org, "surface-py-tool-b")


@pytest.fixture
def mcp_tool_a(db, org):
    return McpTool.objects.create(org=org, name="mcp-a", transport="http://localhost/sse", tool_name="tool_a")


@pytest.fixture
def mcp_tool_b(db, org):
    return McpTool.objects.create(org=org, name="mcp-b", transport="http://localhost/sse", tool_name="tool_b")


@pytest.fixture
def storage_file_a(db, org):
    return StorageFile.objects.create(org=org, name="file-a", path="a/file.txt")


@pytest.fixture
def storage_file_other_org(db, other_org):
    return StorageFile.objects.create(org=other_org, name="foreign-file", path="c/file.txt")


def _collection(org, name, rag_type):
    collection = SourceCollection.objects.create(collection_name=name, org=org)
    BaseRagType.objects.create(rag_type=rag_type, source_collection=collection)
    return collection


@pytest.fixture
def naive_collection(db, org):
    return _collection(org, "naive-coll", BaseRagType.RagType.NAIVE)


@pytest.fixture
def graph_collection(db, org):
    return _collection(org, "graph-coll", BaseRagType.RagType.GRAPH)


@pytest.fixture
def shared_surface(db, org):
    return Surface.objects.create(org=org, name="shared-surface", instructions="be concise", owner_agent=None)


# ---------------------------------------------------------------------------
# Database uniqueness rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "create",
    [
        lambda f: Surface.objects.create(org=f["org"], name="dup-name"),
        lambda f: SurfacePythonTool.objects.create(surface=f["shared_surface"], python_tool=f["py_tool_a"]),
        lambda f: SurfaceStorageItem.objects.create(surface=f["shared_surface"], storage_file=f["storage_file_a"]),
        lambda f: SurfaceKnowledge.objects.create(surface=f["shared_surface"], collection=f["naive_collection"]),
        lambda f: AgentDefaultSurface.objects.create(
            agent_definition=f["agent"], surface=f["shared_surface"], place=SurfacePlace.ALL
        ),
    ],
    ids=[
        "surface-name-per-org",
        "python-tool-per-surface",
        "storage-file-per-surface",
        "collection-per-surface",
        "default-surface-per-agent-and-place",
    ],
)
@pytest.mark.django_db
def test_database_refuses_duplicates(create, org, agent, shared_surface, py_tool_a, storage_file_a, naive_collection):
    fixtures = locals()
    create(fixtures)

    with pytest.raises(IntegrityError):
        create(fixtures)


# ---------------------------------------------------------------------------
# Write serializer -> stored surface -> read serializer
# ---------------------------------------------------------------------------


def _write(org, org_request, instance=None, **data):
    return SurfaceWriteSerializer(
        instance=instance,
        data=data,
        context={"org_id": org.pk, "request": org_request},
        partial=instance is not None,
    )


def _knowledge(collection, naive=None, graph_basic=None, graph_local=None):
    return {
        "collection": collection.pk,
        "naive_search_config": naive,
        "graph_basic_search_config": graph_basic,
        "graph_local_search_config": graph_local,
    }


def _storage(storage_file, **flags):
    return {
        "storage_file": storage_file.pk,
        "can_list": "unset",
        "can_view": "unset",
        "can_edit": "unset",
        "can_delete": "unset",
        **flags,
    }


@pytest.mark.django_db
def test_written_surface_reads_back_with_its_nested_settings(
    org, agent, py_tool_a, py_tool_b, mcp_tool_a, mcp_tool_b, storage_file_a, naive_collection, org_request
):
    serializer = _write(
        org,
        org_request,
        name="full-surface",
        instructions="be brief",
        owner_agent=agent.pk,
        python_tools=[
            {"python_tool": py_tool_a.pk, "mode": "allow"},
            {"python_tool": py_tool_b.pk, "mode": "deny"},
        ],
        mcp_tools=[{"mcp_tool": mcp_tool_a.pk, "mode": "allow"}, {"mcp_tool": mcp_tool_b.pk, "mode": "deny"}],
        storage_items=[_storage(storage_file_a, can_list="allow", can_view="allow", can_delete="deny")],
        knowledge=[_knowledge(naive_collection, naive={"search_limit": 7, "similarity_threshold": "0.40"})],
    )
    assert serializer.is_valid(), serializer.errors

    data = SurfaceReadSerializer(serializer.save(org_id=org.pk)).data

    assert (data["name"], data["instructions"], data["owner_agent"]) == ("full-surface", "be brief", agent.pk)
    assert {item["python_tool"]: item["mode"] for item in data["python_tools"]} == {
        py_tool_a.pk: "allow",
        py_tool_b.pk: "deny",
    }
    assert {item["mcp_tool"]: item["mode"] for item in data["mcp_tools"]} == {
        mcp_tool_a.pk: "allow",
        mcp_tool_b.pk: "deny",
    }
    (item,) = data["storage_items"]
    assert {key: item[key] for key in ("storage_file", "can_list", "can_view", "can_edit", "can_delete")} == {
        "storage_file": storage_file_a.pk,
        "can_list": "allow",
        "can_view": "allow",
        "can_edit": "unset",
        "can_delete": "deny",
    }
    (knowledge,) = data["knowledge"]
    assert knowledge["collection"] == naive_collection.pk
    assert knowledge["naive_search_config"]["search_limit"] == 7
    assert knowledge["graph_basic_search_config"] is None
    assert knowledge["graph_local_search_config"] is None
    assert {"id", "org", "created_by", "created_at", "updated_at"} <= set(data)


@pytest.mark.parametrize(
    ("config_key", "config", "field", "expected"),
    [
        ("graph_basic", {"k": 15, "max_context_tokens": 8000}, "k", 15),
        ("graph_local", {"top_k_entities": 20, "top_k_relationships": 20}, "top_k_entities", 20),
    ],
)
@pytest.mark.django_db
def test_graph_collection_search_configs_are_stored(
    org, graph_collection, org_request, config_key, config, field, expected
):
    serializer = _write(
        org, org_request, name="graph-surface", knowledge=[_knowledge(graph_collection, **{config_key: config})]
    )
    assert serializer.is_valid(), serializer.errors

    (stored,) = SurfaceReadSerializer(serializer.save(org_id=org.pk)).data["knowledge"]

    assert stored[f"{config_key}_search_config"][field] == expected


@pytest.mark.parametrize(
    ("payload", "field", "error_class"),
    [
        (lambda f: {"name": "taken"}, "__all__", SurfaceValidationError),
        (
            lambda f: {
                "python_tools": [
                    {"python_tool": f["py_tool_a"].pk, "mode": "allow"},
                    {"python_tool": f["py_tool_a"].pk, "mode": "deny"},
                ]
            },
            "python_tools",
            SurfaceValidationError,
        ),
        (lambda f: {"mcp_tools": [{"mcp_tool": f["mcp_tool_a"].pk, "mode": "allow"}] * 2}, "mcp_tools", SurfaceValidationError),
        (
            lambda f: {
                "storage_items": [
                    _storage(f["storage_file_a"], can_list="allow"),
                    _storage(f["storage_file_a"], can_view="allow"),
                ]
            },
            "storage_items",
            SurfaceValidationError,
        ),
        (lambda f: {"knowledge": [_knowledge(f["naive_collection"])] * 2}, "knowledge", SurfaceValidationError),
        # Another org's file looks like one that does not exist (the field is org-scoped).
        (
            lambda f: {"storage_items": [_storage(f["storage_file_other_org"], can_list="allow")]},
            "storage_items",
            DRFValidationError,
        ),
        (
            lambda f: {
                "knowledge": [_knowledge(f["graph_collection"], naive={"search_limit": 5, "similarity_threshold": "0.30"})]
            },
            "knowledge",
            SurfaceValidationError,
        ),
        (
            lambda f: {"knowledge": [_knowledge(f["naive_collection"], graph_basic={"k": 5, "max_context_tokens": 4000})]},
            "knowledge",
            SurfaceValidationError,
        ),
    ],
    ids=[
        "name-taken-in-org",
        "python-tool-twice",
        "mcp-tool-twice",
        "storage-file-twice",
        "collection-twice",
        "other-orgs-file",
        "naive-config-on-graph-collection",
        "graph-config-on-naive-collection",
    ],
)
@pytest.mark.django_db
def test_invalid_surface_is_refused_as_a_validation_error(
    org,
    org_request,
    py_tool_a,
    mcp_tool_a,
    storage_file_a,
    storage_file_other_org,
    naive_collection,
    graph_collection,
    payload,
    field,
    error_class,
):
    """A 400 naming the field, never the IntegrityError (500) the database would raise."""
    Surface.objects.create(org=org, name="taken")
    serializer = _write(org, org_request, **{"name": "new-surface", **payload(locals())})

    with pytest.raises(error_class) as error:
        serializer.is_valid(raise_exception=True)

    assert field in error.value.detail


@pytest.mark.django_db
def test_renaming_checks_uniqueness_against_other_surfaces_only(org, org_request):
    Surface.objects.create(org=org, name="surf-a")
    surface_b = Surface.objects.create(org=org, name="surf-b")

    assert _write(org, org_request, instance=surface_b, name="surf-b").is_valid(raise_exception=True)
    with pytest.raises(SurfaceValidationError):
        _write(org, org_request, instance=surface_b, name="surf-a").is_valid(raise_exception=True)


# ---------------------------------------------------------------------------
# An agent's default surfaces
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_agent_may_default_to_shared_surfaces_but_not_another_agents(org, agent, agent_b, shared_surface):
    agent_b_surface = Surface.objects.create(org=org, name="agent-b-surf", owner_agent=agent_b)

    SurfaceValidator.validate_agent_default_surfaces(
        items=[{"surface": shared_surface, "place": SurfacePlace.ALL}], agent_definition=agent
    )
    with pytest.raises(SurfaceValidationError) as error:
        SurfaceValidator.validate_agent_default_surfaces(
            items=[{"surface": agent_b_surface, "place": SurfacePlace.ALL}], agent_definition=agent
        )
    assert "default_surfaces" in error.value.detail


@pytest.mark.parametrize(
    ("explicit_rows", "expected"),
    [
        # An agent's own surface applies everywhere unless a row says otherwise.
        ({}, {"owned": "all"}),
        ({"owned": SurfacePlace.FLOW}, {"owned": "flow"}),
        # A shared surface applies only where it is explicitly assigned.
        ({"shared": SurfacePlace.CHAT}, {"owned": "all", "shared": "chat"}),
    ],
    ids=["owned-implicit", "owned-explicit-place", "shared-explicit-plus-owned"],
)
@pytest.mark.django_db
def test_agents_default_surfaces_merge_owned_and_assigned(org, agent, shared_surface, explicit_rows, expected):
    surfaces = {"owned": Surface.objects.create(org=org, name="owned", owner_agent=agent), "shared": shared_surface}
    for key, place in explicit_rows.items():
        AgentDefaultSurface.objects.create(agent_definition=agent, surface=surfaces[key], place=place)

    entries = AgentDefinitionReadSerializer(agent).data["default_surfaces"]

    assert sorted((entry["surface"], entry["place"]) for entry in entries) == sorted(
        (surfaces[key].id, place) for key, place in expected.items()
    )
