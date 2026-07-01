"""
Integration tests for the Surface model rewrite.

Covers:
- Surface CRUD (shared/agent-specific)
- SurfacePythonTool / SurfaceMcpTool with allow & deny modes
- SurfaceStorageItem with the 4 boolean flags and Surface.allow_creation
- SurfaceKnowledge with naive, graph-basic, graph-local configs
- AgentDefaultSurface places (all/flow/chat)
- Round-trip GET returns nested shape
- Reject cases: duplicate tool id, cross-agent default surface, wrong-org storage item,
  rag-type mismatch
"""

import pytest
from rest_framework.test import APIClient

from tables.exceptions import SurfaceValidationError
from tables.models.agent_models import (
    AgentDefaultSurface,
    AgentDefinition,
    Surface,
    SurfacePlace,
)
from tables.models.agent_models.surface_models import (
    StorageAccess,
    SurfaceKnowledge,
    SurfaceMcpTool,
    SurfaceNaiveSearchConfig,
    SurfacePythonTool,
    SurfaceStorageItem,
    ToolMode,
)
from tables.models.graph_models import StorageFile
from tables.models.knowledge_models.collection_models import (
    BaseRagType,
    SourceCollection,
)
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.rbac_models import Organization
from tables.serializers.model_serializers.surface_serializers import (
    SurfaceWriteSerializer,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def org(db):
    return Organization.objects.create(name="test-surface-org")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="other-org")


@pytest.fixture
def agent(db, org):
    return AgentDefinition.objects.create(
        organization=org,
        name="agent-a",
        instructions="do things",
    )


@pytest.fixture
def agent_b(db, org):
    return AgentDefinition.objects.create(
        organization=org,
        name="agent-b",
        instructions="do other things",
    )


@pytest.fixture
def py_tool_a(db):
    code = PythonCode.objects.create(code="def main(): pass")
    return PythonCodeTool.objects.create(
        name="surface-py-tool-a",
        description="test",
        python_code=code,
    )


@pytest.fixture
def py_tool_b(db):
    code = PythonCode.objects.create(code="def main(): pass")
    return PythonCodeTool.objects.create(
        name="surface-py-tool-b",
        description="test",
        python_code=code,
    )


@pytest.fixture
def mcp_tool_a(db):
    return McpTool.objects.create(
        name="mcp-a", transport="http://localhost/sse", tool_name="tool_a"
    )


@pytest.fixture
def mcp_tool_b(db):
    return McpTool.objects.create(
        name="mcp-b", transport="http://localhost/sse", tool_name="tool_b"
    )


@pytest.fixture
def storage_file_a(db, org):
    return StorageFile.objects.create(org=org, name="file-a", path="a/file.txt")


@pytest.fixture
def storage_file_b(db, org):
    return StorageFile.objects.create(org=org, name="file-b", path="b/file.txt")


@pytest.fixture
def storage_file_other_org(db, other_org):
    return StorageFile.objects.create(
        org=other_org, name="foreign-file", path="c/file.txt"
    )


@pytest.fixture
def naive_collection(db):
    coll = SourceCollection.objects.create(collection_name="naive-coll")
    BaseRagType.objects.create(
        rag_type=BaseRagType.RagType.NAIVE,
        source_collection=coll,
    )
    return coll


@pytest.fixture
def graph_collection(db):
    coll = SourceCollection.objects.create(collection_name="graph-coll")
    BaseRagType.objects.create(
        rag_type=BaseRagType.RagType.GRAPH,
        source_collection=coll,
    )
    return coll


@pytest.fixture
def shared_surface(db, org):
    return Surface.objects.create(
        organization=org,
        name="shared-surface",
        description="shared desc",
        instructions="be concise",
        owner_agent=None,
        allow_creation=False,
    )


# ---------------------------------------------------------------------------
# Surface CRUD
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_shared_surface_owner_agent_null(org):
    surface = Surface.objects.create(
        organization=org,
        name="shared",
        instructions="shared instructions",
        owner_agent=None,
    )

    assert surface.pk is not None
    assert surface.owner_agent is None
    assert surface.organization == org


@pytest.mark.django_db
def test_create_agent_specific_surface(org, agent):
    surface = Surface.objects.create(
        organization=org,
        name="agent-specific",
        instructions="agent instructions",
        owner_agent=agent,
    )

    assert surface.owner_agent == agent


@pytest.mark.django_db
def test_surface_allow_creation_defaults_false(org):
    surface = Surface.objects.create(organization=org, name="no-create")
    assert surface.allow_creation is False


@pytest.mark.django_db
def test_surface_allow_creation_true(org):
    surface = Surface.objects.create(
        organization=org, name="with-create", allow_creation=True
    )
    assert surface.allow_creation is True


@pytest.mark.django_db
def test_surface_unique_constraint_per_org_name(org):
    Surface.objects.create(organization=org, name="dup-name")

    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        Surface.objects.create(organization=org, name="dup-name")


@pytest.mark.django_db
def test_serializer_duplicate_org_name_returns_surface_validation_error(org):
    """Duplicate (org, name) via serializer raises SurfaceValidationError (400), not IntegrityError (500)."""
    serializer_first = SurfaceWriteSerializer(
        data={"name": "dup-via-serializer"},
        context={"organization": org},
    )
    assert serializer_first.is_valid(), serializer_first.errors
    serializer_first.save()

    serializer_second = SurfaceWriteSerializer(
        data={"name": "dup-via-serializer"},
        context={"organization": org},
    )

    with pytest.raises(SurfaceValidationError) as exc_info:
        serializer_second.is_valid(raise_exception=True)

    assert exc_info.value.detail is not None


# ---------------------------------------------------------------------------
# SurfacePythonTool — allow / deny modes
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_python_tool_allow_mode_stored(shared_surface, py_tool_a):
    entry = SurfacePythonTool.objects.create(
        surface=shared_surface,
        python_tool=py_tool_a,
        mode=ToolMode.ALLOW,
    )

    assert entry.mode == ToolMode.ALLOW


@pytest.mark.django_db
def test_python_tool_deny_mode_stored(shared_surface, py_tool_a):
    entry = SurfacePythonTool.objects.create(
        surface=shared_surface,
        python_tool=py_tool_a,
        mode=ToolMode.DENY,
    )

    assert entry.mode == ToolMode.DENY


@pytest.mark.django_db
def test_python_tool_not_absent_means_not_present(shared_surface, py_tool_a):
    """No SurfacePythonTool row = tool absent from surface (tri-state)."""
    count = SurfacePythonTool.objects.filter(
        surface=shared_surface, python_tool=py_tool_a
    ).count()
    assert count == 0


@pytest.mark.django_db
def test_python_tool_unique_constraint_per_surface(shared_surface, py_tool_a):
    SurfacePythonTool.objects.create(
        surface=shared_surface, python_tool=py_tool_a, mode=ToolMode.ALLOW
    )

    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        SurfacePythonTool.objects.create(
            surface=shared_surface, python_tool=py_tool_a, mode=ToolMode.DENY
        )


# ---------------------------------------------------------------------------
# SurfaceMcpTool — allow / deny modes
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_mcp_tool_allow_mode_stored(shared_surface, mcp_tool_a):
    entry = SurfaceMcpTool.objects.create(
        surface=shared_surface,
        mcp_tool=mcp_tool_a,
        mode=ToolMode.ALLOW,
    )

    assert entry.mode == ToolMode.ALLOW


@pytest.mark.django_db
def test_mcp_tool_deny_mode_stored(shared_surface, mcp_tool_a):
    entry = SurfaceMcpTool.objects.create(
        surface=shared_surface,
        mcp_tool=mcp_tool_a,
        mode=ToolMode.DENY,
    )

    assert entry.mode == ToolMode.DENY


# ---------------------------------------------------------------------------
# SurfaceStorageItem — 4 boolean flags + allow_creation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_storage_item_all_flags_false_by_default(shared_surface, storage_file_a):
    item = SurfaceStorageItem.objects.create(
        surface=shared_surface,
        storage_file=storage_file_a,
    )

    assert item.can_list == StorageAccess.UNSET
    assert item.can_view == StorageAccess.UNSET
    assert item.can_edit == StorageAccess.UNSET
    assert item.can_delete == StorageAccess.UNSET


@pytest.mark.django_db
def test_storage_item_flags_set(shared_surface, storage_file_a):
    item = SurfaceStorageItem.objects.create(
        surface=shared_surface,
        storage_file=storage_file_a,
        can_list="allow",
        can_view="allow",
        can_edit="unset",
        can_delete="deny",
    )

    assert item.can_list == StorageAccess.ALLOW
    assert item.can_view == StorageAccess.ALLOW
    assert item.can_edit == StorageAccess.UNSET
    assert item.can_delete == StorageAccess.DENY


@pytest.mark.django_db
def test_storage_item_unique_constraint(shared_surface, storage_file_a):
    SurfaceStorageItem.objects.create(
        surface=shared_surface, storage_file=storage_file_a, can_view="allow"
    )

    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        SurfaceStorageItem.objects.create(
            surface=shared_surface, storage_file=storage_file_a, can_edit="allow"
        )


# ---------------------------------------------------------------------------
# SurfaceKnowledge + search config
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_knowledge_entry_created(shared_surface, naive_collection):
    sk = SurfaceKnowledge.objects.create(
        surface=shared_surface,
        collection=naive_collection,
    )

    assert sk.pk is not None
    assert sk.surface == shared_surface
    assert sk.collection == naive_collection


@pytest.mark.django_db
def test_naive_search_config_attached_to_knowledge(shared_surface, naive_collection):
    sk = SurfaceKnowledge.objects.create(
        surface=shared_surface,
        collection=naive_collection,
    )
    SurfaceNaiveSearchConfig.objects.create(
        surface_knowledge=sk,
        search_limit=5,
        similarity_threshold="0.50",
    )

    sk.refresh_from_db()
    assert sk.naive_search_config.search_limit == 5


@pytest.mark.django_db
def test_knowledge_unique_constraint(shared_surface, naive_collection):
    SurfaceKnowledge.objects.create(surface=shared_surface, collection=naive_collection)

    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        SurfaceKnowledge.objects.create(
            surface=shared_surface, collection=naive_collection
        )


# ---------------------------------------------------------------------------
# AgentDefaultSurface — places (all / flow / chat)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_agent_default_surface_all_place(org, agent, shared_surface):
    ads = AgentDefaultSurface.objects.create(
        agent_definition=agent,
        surface=shared_surface,
        place=SurfacePlace.ALL,
    )

    assert ads.place == SurfacePlace.ALL


@pytest.mark.django_db
def test_agent_default_surface_flow_place(org, agent, shared_surface):
    ads = AgentDefaultSurface.objects.create(
        agent_definition=agent,
        surface=shared_surface,
        place=SurfacePlace.FLOW,
    )

    assert ads.place == SurfacePlace.FLOW


@pytest.mark.django_db
def test_agent_default_surface_chat_place(org, agent, shared_surface):
    ads = AgentDefaultSurface.objects.create(
        agent_definition=agent,
        surface=shared_surface,
        place=SurfacePlace.CHAT,
    )

    assert ads.place == SurfacePlace.CHAT


@pytest.mark.django_db
def test_agent_default_surface_mix_shared_and_agent_specific(
    org, agent, shared_surface
):
    agent_surface = Surface.objects.create(
        organization=org,
        name="agent-surf",
        owner_agent=agent,
    )
    AgentDefaultSurface.objects.create(
        agent_definition=agent,
        surface=shared_surface,
        place=SurfacePlace.FLOW,
    )
    AgentDefaultSurface.objects.create(
        agent_definition=agent,
        surface=agent_surface,
        place=SurfacePlace.CHAT,
    )

    places = set(
        AgentDefaultSurface.objects.filter(agent_definition=agent).values_list(
            "place", flat=True
        )
    )
    assert places == {SurfacePlace.FLOW, SurfacePlace.CHAT}


@pytest.mark.django_db
def test_agent_default_surface_unique_constraint(org, agent, shared_surface):
    AgentDefaultSurface.objects.create(
        agent_definition=agent,
        surface=shared_surface,
        place=SurfacePlace.ALL,
    )

    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        AgentDefaultSurface.objects.create(
            agent_definition=agent,
            surface=shared_surface,
            place=SurfacePlace.ALL,
        )


# ---------------------------------------------------------------------------
# SurfaceWriteSerializer — create round-trip
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_serializer_create_shared_surface(org):
    serializer = SurfaceWriteSerializer(
        data={
            "name": "new-shared",
            "description": "desc",
            "instructions": "be brief",
            "allow_creation": False,
        },
        context={"organization": org},
    )
    assert serializer.is_valid(), serializer.errors

    surface = serializer.save()

    assert surface.pk is not None
    assert surface.owner_agent is None
    assert surface.name == "new-shared"


@pytest.mark.django_db
def test_serializer_create_with_owner_agent(org, agent):
    serializer = SurfaceWriteSerializer(
        data={
            "name": "owned-surface",
            "owner_agent": agent.pk,
        },
        context={"organization": org},
    )
    assert serializer.is_valid(), serializer.errors

    surface = serializer.save()

    assert surface.owner_agent == agent


@pytest.mark.django_db
def test_serializer_create_with_python_tools(org, py_tool_a, py_tool_b):
    serializer = SurfaceWriteSerializer(
        data={
            "name": "tools-surface",
            "python_tools": [
                {"python_tool": py_tool_a.pk, "mode": "allow"},
                {"python_tool": py_tool_b.pk, "mode": "deny"},
            ],
        },
        context={"organization": org},
    )
    assert serializer.is_valid(), serializer.errors

    surface = serializer.save()

    entries = {
        e.python_tool_id: e.mode
        for e in SurfacePythonTool.objects.filter(surface=surface)
    }
    assert entries[py_tool_a.pk] == ToolMode.ALLOW
    assert entries[py_tool_b.pk] == ToolMode.DENY


@pytest.mark.django_db
def test_serializer_create_with_mcp_tools(org, mcp_tool_a, mcp_tool_b):
    serializer = SurfaceWriteSerializer(
        data={
            "name": "mcp-tools-surface",
            "mcp_tools": [
                {"mcp_tool": mcp_tool_a.pk, "mode": "allow"},
                {"mcp_tool": mcp_tool_b.pk, "mode": "deny"},
            ],
        },
        context={"organization": org},
    )
    assert serializer.is_valid(), serializer.errors

    surface = serializer.save()

    entries = {
        e.mcp_tool_id: e.mode for e in SurfaceMcpTool.objects.filter(surface=surface)
    }
    assert entries[mcp_tool_a.pk] == ToolMode.ALLOW
    assert entries[mcp_tool_b.pk] == ToolMode.DENY


@pytest.mark.django_db
def test_serializer_create_with_storage_items(org, storage_file_a):
    serializer = SurfaceWriteSerializer(
        data={
            "name": "storage-surface",
            "allow_creation": True,
            "storage_items": [
                {
                    "storage_file": storage_file_a.pk,
                    "can_list": "allow",
                    "can_view": "allow",
                    "can_edit": "unset",
                    "can_delete": "deny",
                }
            ],
        },
        context={"organization": org},
    )
    assert serializer.is_valid(), serializer.errors

    surface = serializer.save()

    item = SurfaceStorageItem.objects.get(surface=surface, storage_file=storage_file_a)
    assert item.can_list == StorageAccess.ALLOW
    assert item.can_view == StorageAccess.ALLOW
    assert item.can_edit == StorageAccess.UNSET
    assert item.can_delete == StorageAccess.DENY
    assert surface.allow_creation is True


@pytest.mark.django_db
def test_serializer_create_with_naive_search_config(org, naive_collection):
    serializer = SurfaceWriteSerializer(
        data={
            "name": "knowledge-surface",
            "knowledge": [
                {
                    "collection": naive_collection.pk,
                    "naive_search_config": {
                        "search_limit": 7,
                        "similarity_threshold": "0.40",
                    },
                    "graph_basic_search_config": None,
                    "graph_local_search_config": None,
                }
            ],
        },
        context={"organization": org},
    )
    assert serializer.is_valid(), serializer.errors

    surface = serializer.save()

    sk = SurfaceKnowledge.objects.get(surface=surface, collection=naive_collection)
    assert sk.naive_search_config.search_limit == 7


@pytest.mark.django_db
def test_serializer_create_with_graph_basic_config(org, graph_collection):
    serializer = SurfaceWriteSerializer(
        data={
            "name": "graph-basic-surface",
            "knowledge": [
                {
                    "collection": graph_collection.pk,
                    "naive_search_config": None,
                    "graph_basic_search_config": {"k": 15, "max_context_tokens": 8000},
                    "graph_local_search_config": None,
                }
            ],
        },
        context={"organization": org},
    )
    assert serializer.is_valid(), serializer.errors

    surface = serializer.save()

    sk = SurfaceKnowledge.objects.get(surface=surface, collection=graph_collection)
    assert sk.graph_basic_search_config.k == 15
    assert sk.graph_basic_search_config.max_context_tokens == 8000


@pytest.mark.django_db
def test_serializer_create_with_graph_local_config(org, graph_collection):
    serializer = SurfaceWriteSerializer(
        data={
            "name": "graph-local-surface",
            "knowledge": [
                {
                    "collection": graph_collection.pk,
                    "naive_search_config": None,
                    "graph_basic_search_config": None,
                    "graph_local_search_config": {
                        "top_k_entities": 20,
                        "top_k_relationships": 20,
                    },
                }
            ],
        },
        context={"organization": org},
    )
    assert serializer.is_valid(), serializer.errors

    surface = serializer.save()

    sk = SurfaceKnowledge.objects.get(surface=surface, collection=graph_collection)
    assert sk.graph_local_search_config.top_k_entities == 20


# ---------------------------------------------------------------------------
# Round-trip GET returns nested shape
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_round_trip_get_returns_nested_python_tools(org, py_tool_a, py_tool_b):
    from tables.serializers.model_serializers.surface_serializers import (
        SurfaceReadSerializer,
    )

    surface = Surface.objects.create(organization=org, name="rt-py")
    SurfacePythonTool.objects.create(
        surface=surface, python_tool=py_tool_a, mode=ToolMode.ALLOW
    )
    SurfacePythonTool.objects.create(
        surface=surface, python_tool=py_tool_b, mode=ToolMode.DENY
    )

    data = SurfaceReadSerializer(surface).data

    assert data["name"] == "rt-py"
    assert data["owner_agent"] is None
    tools_by_id = {item["python_tool"]: item["mode"] for item in data["python_tools"]}
    assert tools_by_id[py_tool_a.pk] == "allow"
    assert tools_by_id[py_tool_b.pk] == "deny"


@pytest.mark.django_db
def test_round_trip_get_returns_nested_mcp_tools(org, mcp_tool_a):
    from tables.serializers.model_serializers.surface_serializers import (
        SurfaceReadSerializer,
    )

    surface = Surface.objects.create(organization=org, name="rt-mcp")
    SurfaceMcpTool.objects.create(
        surface=surface, mcp_tool=mcp_tool_a, mode=ToolMode.DENY
    )

    data = SurfaceReadSerializer(surface).data

    assert len(data["mcp_tools"]) == 1
    assert data["mcp_tools"][0]["mcp_tool"] == mcp_tool_a.pk
    assert data["mcp_tools"][0]["mode"] == "deny"


@pytest.mark.django_db
def test_round_trip_get_returns_storage_items(org, storage_file_a):
    from tables.serializers.model_serializers.surface_serializers import (
        SurfaceReadSerializer,
    )

    surface = Surface.objects.create(organization=org, name="rt-storage")
    SurfaceStorageItem.objects.create(
        surface=surface,
        storage_file=storage_file_a,
        can_list="allow",
        can_view="allow",
        can_edit="unset",
        can_delete="deny",
    )

    data = SurfaceReadSerializer(surface).data

    assert len(data["storage_items"]) == 1
    item = data["storage_items"][0]
    assert item["storage_file"] == storage_file_a.pk
    assert item["can_list"] == "allow"
    assert item["can_view"] == "allow"
    assert item["can_edit"] == "unset"
    assert item["can_delete"] == "deny"


@pytest.mark.django_db
def test_round_trip_get_returns_knowledge_with_naive_config(org, naive_collection):
    from tables.serializers.model_serializers.surface_serializers import (
        SurfaceReadSerializer,
    )

    surface = Surface.objects.create(organization=org, name="rt-knowledge")
    sk = SurfaceKnowledge.objects.create(surface=surface, collection=naive_collection)
    SurfaceNaiveSearchConfig.objects.create(
        surface_knowledge=sk, search_limit=10, similarity_threshold="0.30"
    )

    data = SurfaceReadSerializer(surface).data

    assert len(data["knowledge"]) == 1
    kn = data["knowledge"][0]
    assert kn["collection"] == naive_collection.pk
    assert kn["naive_search_config"]["search_limit"] == 10
    assert kn["graph_basic_search_config"] is None
    assert kn["graph_local_search_config"] is None


@pytest.mark.django_db
def test_round_trip_read_includes_timestamps_and_id(org):
    from tables.serializers.model_serializers.surface_serializers import (
        SurfaceReadSerializer,
    )

    surface = Surface.objects.create(organization=org, name="rt-meta")

    data = SurfaceReadSerializer(surface).data

    assert "id" in data
    assert "organization" in data
    assert "created_at" in data
    assert "updated_at" in data


# ---------------------------------------------------------------------------
# Reject cases
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_reject_duplicate_python_tool_id_in_payload(org, py_tool_a):
    """Same python_tool appears twice in list → 400, not IntegrityError."""
    serializer = SurfaceWriteSerializer(
        data={
            "name": "dup-py-surface",
            "python_tools": [
                {"python_tool": py_tool_a.pk, "mode": "allow"},
                {"python_tool": py_tool_a.pk, "mode": "deny"},
            ],
        },
        context={"organization": org},
    )

    with pytest.raises(SurfaceValidationError) as exc_info:
        serializer.is_valid(raise_exception=True)

    assert "python_tools" in exc_info.value.detail


@pytest.mark.django_db
def test_reject_duplicate_mcp_tool_id_in_payload(org, mcp_tool_a):
    """Same mcp_tool appears twice → 400."""
    serializer = SurfaceWriteSerializer(
        data={
            "name": "dup-mcp-surface",
            "mcp_tools": [
                {"mcp_tool": mcp_tool_a.pk, "mode": "allow"},
                {"mcp_tool": mcp_tool_a.pk, "mode": "allow"},
            ],
        },
        context={"organization": org},
    )

    with pytest.raises(SurfaceValidationError) as exc_info:
        serializer.is_valid(raise_exception=True)

    assert "mcp_tools" in exc_info.value.detail


@pytest.mark.django_db
def test_reject_duplicate_storage_file_id_in_payload(org, storage_file_a):
    """Same storage_file appears twice → 400."""
    serializer = SurfaceWriteSerializer(
        data={
            "name": "dup-storage-surface",
            "storage_items": [
                {
                    "storage_file": storage_file_a.pk,
                    "can_list": True,
                    "can_view": False,
                    "can_edit": False,
                    "can_delete": False,
                },
                {
                    "storage_file": storage_file_a.pk,
                    "can_list": False,
                    "can_view": True,
                    "can_edit": False,
                    "can_delete": False,
                },
            ],
        },
        context={"organization": org},
    )

    with pytest.raises(SurfaceValidationError) as exc_info:
        serializer.is_valid(raise_exception=True)

    assert "storage_items" in exc_info.value.detail


@pytest.mark.django_db
def test_reject_storage_item_from_other_org(org, storage_file_other_org):
    """StorageFile from a different org → validation error."""
    serializer = SurfaceWriteSerializer(
        data={
            "name": "cross-org-storage",
            "storage_items": [
                {
                    "storage_file": storage_file_other_org.pk,
                    "can_list": True,
                    "can_view": False,
                    "can_edit": False,
                    "can_delete": False,
                }
            ],
        },
        context={"organization": org},
    )

    with pytest.raises(SurfaceValidationError) as exc_info:
        serializer.is_valid(raise_exception=True)

    assert "storage_items" in exc_info.value.detail


@pytest.mark.django_db
def test_reject_naive_config_on_graph_only_collection(org, graph_collection):
    """naive_search_config on a graph-only collection → 400 rag-type mismatch."""
    serializer = SurfaceWriteSerializer(
        data={
            "name": "rag-mismatch-surface",
            "knowledge": [
                {
                    "collection": graph_collection.pk,
                    "naive_search_config": {
                        "search_limit": 5,
                        "similarity_threshold": "0.30",
                    },
                    "graph_basic_search_config": None,
                    "graph_local_search_config": None,
                }
            ],
        },
        context={"organization": org},
    )

    with pytest.raises(SurfaceValidationError) as exc_info:
        serializer.is_valid(raise_exception=True)

    assert "knowledge" in exc_info.value.detail


@pytest.mark.django_db
def test_reject_graph_config_on_naive_only_collection(org, naive_collection):
    """graph_basic_search_config on a naive-only collection → 400 rag-type mismatch."""
    serializer = SurfaceWriteSerializer(
        data={
            "name": "rag-mismatch-graph",
            "knowledge": [
                {
                    "collection": naive_collection.pk,
                    "naive_search_config": None,
                    "graph_basic_search_config": {"k": 5, "max_context_tokens": 4000},
                    "graph_local_search_config": None,
                }
            ],
        },
        context={"organization": org},
    )

    with pytest.raises(SurfaceValidationError) as exc_info:
        serializer.is_valid(raise_exception=True)

    assert "knowledge" in exc_info.value.detail


@pytest.mark.django_db
def test_reject_agent_default_surface_from_other_agent(
    org, agent, agent_b, shared_surface
):
    """Surface owned by agent_b cannot be set as default for agent."""
    from tables.validators.surface_validator import SurfaceValidator

    agent_b_surface = Surface.objects.create(
        organization=org,
        name="agent-b-surf",
        owner_agent=agent_b,
    )

    with pytest.raises(SurfaceValidationError) as exc_info:
        SurfaceValidator.validate_agent_default_surfaces(
            items=[{"surface": agent_b_surface, "place": SurfacePlace.ALL}],
            agent_definition=agent,
            organization=org,
        )

    assert "default_surfaces" in exc_info.value.detail


@pytest.mark.django_db
def test_agent_default_surface_shared_surface_passes_validation(
    org, agent, shared_surface
):
    """Shared surface (owner_agent=None) is valid for any agent's defaults."""
    from tables.validators.surface_validator import SurfaceValidator

    # Must not raise
    SurfaceValidator.validate_agent_default_surfaces(
        items=[{"surface": shared_surface, "place": SurfacePlace.ALL}],
        agent_definition=agent,
        organization=org,
    )


@pytest.mark.django_db
def test_reject_duplicate_knowledge_collection_in_payload(org, naive_collection):
    """Same collection appears twice → 400."""
    serializer = SurfaceWriteSerializer(
        data={
            "name": "dup-kn-surface",
            "knowledge": [
                {
                    "collection": naive_collection.pk,
                    "naive_search_config": None,
                    "graph_basic_search_config": None,
                    "graph_local_search_config": None,
                },
                {
                    "collection": naive_collection.pk,
                    "naive_search_config": None,
                    "graph_basic_search_config": None,
                    "graph_local_search_config": None,
                },
            ],
        },
        context={"organization": org},
    )

    with pytest.raises(SurfaceValidationError) as exc_info:
        serializer.is_valid(raise_exception=True)

    assert "knowledge" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Valid cases pass without error
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_valid_payload_no_tools_passes(org):
    serializer = SurfaceWriteSerializer(
        data={"name": "empty-surface"},
        context={"organization": org},
    )
    assert serializer.is_valid() is True


@pytest.mark.django_db
def test_valid_payload_allow_deny_different_tools_passes(org, py_tool_a, py_tool_b):
    serializer = SurfaceWriteSerializer(
        data={
            "name": "no-conflict",
            "python_tools": [
                {"python_tool": py_tool_a.pk, "mode": "allow"},
                {"python_tool": py_tool_b.pk, "mode": "deny"},
            ],
        },
        context={"organization": org},
    )
    assert serializer.is_valid() is True


# ---------------------------------------------------------------------------
# AgentDefinition.metadata
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_agent_metadata_defaults_to_empty_dict(org):
    agent = AgentDefinition.objects.create(organization=org, name="meta-default")
    assert agent.metadata == {}


@pytest.mark.django_db
def test_agent_write_serializer_accepts_arbitrary_metadata(org):
    from tables.serializers.model_serializers.agent_definition_serializers import (
        AgentDefinitionWriteSerializer,
    )

    payload = {"name": "meta-write", "metadata": {"ui_color": "red", "priority": 3}}
    serializer = AgentDefinitionWriteSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors

    instance = serializer.save(organization=org)

    instance.refresh_from_db()
    assert instance.metadata == {"ui_color": "red", "priority": 3}


@pytest.mark.django_db
def test_agent_read_serializer_returns_stored_metadata(org):
    from tables.serializers.model_serializers.agent_definition_serializers import (
        AgentDefinitionReadSerializer,
    )

    agent = AgentDefinition.objects.create(
        organization=org,
        name="meta-read",
        metadata={"key": "value", "count": 42},
    )

    data = AgentDefinitionReadSerializer(agent).data

    assert data["metadata"] == {"key": "value", "count": 42}
