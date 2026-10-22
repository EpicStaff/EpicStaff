"""
Integration tests for the InlineSurface model family.

Covers:
- 1:1 InlineSurface-per-TaskNode enforcement (IntegrityError on second create)
- CASCADE behavior: deleting TaskNode removes InlineSurface + content + config rows;
  deleting Graph removes TaskNode (and transitively InlineSurface)
- Duplicate (inline_surface, python_tool) pair rejected by unique constraint
- TaskNode.content_hash unaffected by inline surface create/delete (hash covers
  local fields only — InlineSurface is a reverse relation, not a local field)
- `tasknodes/` API: nested inline_surface with three-way write semantics
  (omitted = untouched, null = delete, object = create-or-full-replace)
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from agents.models import (
    InlineSurface,
    InlineSurfaceKnowledge,
    InlineSurfaceMcpTool,
    InlineSurfaceNaiveSearchConfig,
    InlineSurfacePythonTool,
    InlineSurfaceStorageItem,
    ToolMode,
)
from tables.models.graph_models import Graph, StorageFile, TaskNode
from tables.models.knowledge_models.collection_models import (
    BaseRagType,
    SourceCollection,
)
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from rbac.models import Organization
from agents.serializers.inline_surface_serializers import (
    InlineSurfaceReadSerializer,
)
from agents.serializers.surface_serializers import (
    SurfaceReadSerializer,
)
from agents.services.surface_combine_service import SurfaceCombineService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def org(default_org):
    """Aliased to `default_org` (defined below) rather than a separate
    Organization: the API tests further down mix these model-section
    fixtures (`py_tool`, `mcp_tool`, `naive_collection`, ...) with the
    API-section fixtures (`api_graph`, `api_storage_file`, ...), and both
    must resolve to the same org as `client`'s active-org header for those
    payloads to validate."""
    return default_org


@pytest.fixture
def graph(db, org):
    return Graph.objects.create(name="inline-surface-graph", org=org)


@pytest.fixture
def task_node(db, graph):
    return TaskNode.objects.create(graph=graph, node_name="inline-surface-task")


@pytest.fixture
def py_tool(db, org):
    code = PythonCode.objects.create(code="def main(): pass")
    return PythonCodeTool.objects.create(
        org=org,
        name="inline-surface-py-tool",
        description="test",
        python_code=code,
    )


@pytest.fixture
def mcp_tool(db, org):
    return McpTool.objects.create(
        org=org, name="inline-mcp", transport="http://localhost/sse", tool_name="tool_a"
    )


@pytest.fixture
def storage_file(db, org):
    return StorageFile.objects.create(org=org, name="file-a", path="a/file.txt")


@pytest.fixture
def naive_collection(db, org):
    coll = SourceCollection.objects.create(collection_name="inline-naive-coll", org=org)
    BaseRagType.objects.create(
        rag_type=BaseRagType.RagType.NAIVE,
        source_collection=coll,
    )
    return coll


@pytest.fixture
def graph_collection(db, org):
    coll = SourceCollection.objects.create(collection_name="inline-graph-coll", org=org)
    BaseRagType.objects.create(
        rag_type=BaseRagType.RagType.GRAPH,
        source_collection=coll,
    )
    return coll


@pytest.fixture
def inline_surface(db, task_node):
    return InlineSurface.objects.create(task_node=task_node)


# ---------------------------------------------------------------------------
# API fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(auth_client):
    """`auth_client` (conftest) is authenticated as a member of `default_org`
    and sends its id as the active-org header. `default_org` below overrides
    the conftest fixture of the same name for this module, so `auth_client`'s
    membership resolves against that same org, keeping it consistent with
    `api_graph`/`api_storage_file`."""
    return auth_client


@pytest.fixture
def default_org(db):
    from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME

    return Organization.objects.get_or_create(name=DEFAULT_ORGANIZATION_NAME)[0]


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="inline-surface-other-org")


@pytest.fixture
def api_graph(db, default_org):
    return Graph.objects.create(name="inline-surface-api-graph", org=default_org)


@pytest.fixture
def api_storage_file(db, default_org):
    return StorageFile.objects.create(
        org=default_org, name="api-file-a", path="a/api-file.txt"
    )


@pytest.fixture
def other_org_storage_file(db, other_org):
    return StorageFile.objects.create(
        org=other_org, name="foreign-file", path="c/foreign-file.txt"
    )


# ---------------------------------------------------------------------------
# 1:1 enforcement
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_second_inline_surface_for_same_task_node_raises_integrity_error(
    inline_surface, task_node
):
    with pytest.raises(IntegrityError):
        InlineSurface.objects.create(task_node=task_node)


# ---------------------------------------------------------------------------
# CASCADE behavior
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_deleting_task_node_cascades_inline_surface_and_content_rows(
    task_node, inline_surface, py_tool, naive_collection
):
    InlineSurfacePythonTool.objects.create(
        inline_surface=inline_surface, python_tool=py_tool, mode=ToolMode.ALLOW
    )
    knowledge = InlineSurfaceKnowledge.objects.create(
        inline_surface=inline_surface, collection=naive_collection
    )
    InlineSurfaceNaiveSearchConfig.objects.create(surface_knowledge=knowledge)

    inline_surface_id = inline_surface.pk
    knowledge_id = knowledge.pk

    task_node.delete()

    assert not InlineSurface.objects.filter(pk=inline_surface_id).exists()
    assert not InlineSurfacePythonTool.objects.filter(
        inline_surface_id=inline_surface_id
    ).exists()
    assert not InlineSurfaceKnowledge.objects.filter(pk=knowledge_id).exists()
    assert not InlineSurfaceNaiveSearchConfig.objects.filter(
        surface_knowledge_id=knowledge_id
    ).exists()


@pytest.mark.django_db
def test_deleting_graph_cascades_task_node_and_inline_surface(
    graph, task_node, inline_surface
):
    inline_surface_id = inline_surface.pk
    task_node_id = task_node.pk

    graph.delete()

    assert not TaskNode.objects.filter(pk=task_node_id).exists()
    assert not InlineSurface.objects.filter(pk=inline_surface_id).exists()


# ---------------------------------------------------------------------------
# Unique constraint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_duplicate_python_tool_pair_raises_integrity_error(inline_surface, py_tool):
    InlineSurfacePythonTool.objects.create(
        inline_surface=inline_surface, python_tool=py_tool, mode=ToolMode.ALLOW
    )

    with pytest.raises(IntegrityError):
        InlineSurfacePythonTool.objects.create(
            inline_surface=inline_surface, python_tool=py_tool, mode=ToolMode.DENY
        )


# ---------------------------------------------------------------------------
# tasknodes/ API — nested inline_surface
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_with_full_inline_payload_returns_201_and_creates_rows(
    client, org, api_graph, py_tool, mcp_tool, api_storage_file, naive_collection
):
    py_tool_b_code = PythonCode.objects.create(code="def main(): pass")
    py_tool_b = PythonCodeTool.objects.create(
        org=org,
        name="inline-surface-py-tool-b",
        description="test",
        python_code=py_tool_b_code,
    )

    response = client.post(
        "/api/tasknodes/",
        {
            "graph": api_graph.pk,
            "node_name": "inline-full-payload",
            "inline_surface": {
                "instructions": "be concise",
                "python_tools": [
                    {"python_tool": py_tool.pk, "mode": "allow"},
                    {"python_tool": py_tool_b.pk, "mode": "deny"},
                ],
                "mcp_tools": [{"mcp_tool": mcp_tool.pk, "mode": "allow"}],
                "storage_items": [
                    {"storage_file": api_storage_file.pk, "can_view": "allow"}
                ],
                "knowledge": [
                    {
                        "collection": naive_collection.pk,
                        "naive_search_config": {
                            "search_limit": 7,
                            "similarity_threshold": "0.40",
                        },
                    }
                ],
            },
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    inline_data = response.data["inline_surface"]
    assert inline_data["instructions"] == "be concise"
    assert len(inline_data["python_tools"]) == 2
    assert len(inline_data["mcp_tools"]) == 1
    assert len(inline_data["storage_items"]) == 1
    assert len(inline_data["knowledge"]) == 1
    assert inline_data["knowledge"][0]["naive_search_config"]["search_limit"] == 7

    node = TaskNode.objects.get(node_name="inline-full-payload")
    inline = InlineSurface.objects.get(task_node=node)
    assert inline.python_tools.count() == 2
    assert inline.mcp_tools.count() == 1
    assert inline.storage_items.count() == 1
    assert inline.knowledge.count() == 1


@pytest.mark.django_db
def test_post_without_inline_surface_returns_null(client, api_graph):
    response = client.post(
        "/api/tasknodes/",
        {"graph": api_graph.pk, "node_name": "inline-none"},
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.data["inline_surface"] is None


@pytest.mark.django_db
def test_get_list_and_detail_return_nested_inline_shape(client, api_graph, py_tool):
    node = TaskNode.objects.create(graph=api_graph, node_name="inline-get")
    inline = InlineSurface.objects.create(task_node=node, instructions="hello")
    InlineSurfacePythonTool.objects.create(
        inline_surface=inline, python_tool=py_tool, mode=ToolMode.ALLOW
    )

    detail_response = client.get(f"/api/tasknodes/{node.pk}/")
    assert detail_response.status_code == 200, detail_response.data
    assert detail_response.data["inline_surface"]["instructions"] == "hello"
    assert len(detail_response.data["inline_surface"]["python_tools"]) == 1

    list_response = client.get("/api/tasknodes/")
    assert list_response.status_code == 200, list_response.data
    listed = next(
        item for item in list_response.data["results"] if item["id"] == node.pk
    )
    assert listed["inline_surface"]["instructions"] == "hello"


@pytest.mark.django_db
def test_patch_inline_surface_null_deletes_everything(
    client, api_graph, py_tool, naive_collection
):
    node = TaskNode.objects.create(graph=api_graph, node_name="inline-patch-null")
    inline = InlineSurface.objects.create(task_node=node)
    InlineSurfacePythonTool.objects.create(
        inline_surface=inline, python_tool=py_tool, mode=ToolMode.ALLOW
    )
    knowledge = InlineSurfaceKnowledge.objects.create(
        inline_surface=inline, collection=naive_collection
    )
    InlineSurfaceNaiveSearchConfig.objects.create(surface_knowledge=knowledge)

    response = client.patch(
        f"/api/tasknodes/{node.pk}/",
        {"inline_surface": None},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["inline_surface"] is None
    assert not InlineSurface.objects.filter(task_node=node).exists()
    assert not InlineSurfacePythonTool.objects.filter(
        inline_surface_id=inline.pk
    ).exists()
    assert not InlineSurfaceNaiveSearchConfig.objects.filter(
        surface_knowledge_id=knowledge.pk
    ).exists()


@pytest.mark.django_db
def test_patch_inline_surface_object_fully_replaces(
    client, api_graph, py_tool, mcp_tool
):
    node = TaskNode.objects.create(graph=api_graph, node_name="inline-patch-replace")
    inline = InlineSurface.objects.create(task_node=node, instructions="old")
    old_entry = InlineSurfacePythonTool.objects.create(
        inline_surface=inline, python_tool=py_tool, mode=ToolMode.ALLOW
    )

    response = client.patch(
        f"/api/tasknodes/{node.pk}/",
        {
            "inline_surface": {
                "instructions": "new",
                "mcp_tools": [{"mcp_tool": mcp_tool.pk, "mode": "deny"}],
            }
        },
        format="json",
    )

    assert response.status_code == 200, response.data
    inline.refresh_from_db()
    assert inline.instructions == "new"
    assert not InlineSurfacePythonTool.objects.filter(pk=old_entry.pk).exists()
    assert inline.python_tools.count() == 0
    assert inline.mcp_tools.count() == 1


@pytest.mark.django_db
def test_content_hash_unchanged_across_inline_create_edit_clear_via_api(
    client, api_graph, py_tool
):
    node = TaskNode.objects.create(graph=api_graph, node_name="inline-hash")
    hash_before = node.content_hash

    create_response = client.patch(
        f"/api/tasknodes/{node.pk}/",
        {
            "inline_surface": {
                "python_tools": [{"python_tool": py_tool.pk, "mode": "allow"}]
            }
        },
        format="json",
    )
    assert create_response.status_code == 200, create_response.data
    node.refresh_from_db()
    assert node.content_hash == hash_before

    edit_response = client.patch(
        f"/api/tasknodes/{node.pk}/",
        {"inline_surface": {"instructions": "edited"}},
        format="json",
    )
    assert edit_response.status_code == 200, edit_response.data
    node.refresh_from_db()
    assert node.content_hash == hash_before

    clear_response = client.patch(
        f"/api/tasknodes/{node.pk}/",
        {"inline_surface": None},
        format="json",
    )
    assert clear_response.status_code == 200, clear_response.data
    node.refresh_from_db()
    assert node.content_hash == hash_before


@pytest.mark.django_db
def test_surface_combine_service_accepts_inline_read_serializer_output(
    client,
    api_graph,
    default_org,
    py_tool,
    mcp_tool,
    api_storage_file,
    naive_collection,
):
    """Shape-compat guard: InlineSurfaceReadSerializer output must be usable
    alongside SurfaceReadSerializer output as input to SurfaceCombineService."""
    node = TaskNode.objects.create(graph=api_graph, node_name="inline-combine")
    inline = InlineSurface.objects.create(
        task_node=node, instructions="inline instructions"
    )
    InlineSurfacePythonTool.objects.create(
        inline_surface=inline, python_tool=py_tool, mode=ToolMode.ALLOW
    )
    InlineSurfaceMcpTool.objects.create(
        inline_surface=inline, mcp_tool=mcp_tool, mode=ToolMode.DENY
    )
    InlineSurfaceStorageItem.objects.create(
        inline_surface=inline, storage_file=api_storage_file, can_view="allow"
    )
    knowledge = InlineSurfaceKnowledge.objects.create(
        inline_surface=inline, collection=naive_collection
    )
    InlineSurfaceNaiveSearchConfig.objects.create(surface_knowledge=knowledge)

    from agents.models import Surface

    catalog_surface = Surface.objects.create(
        org=default_org,
        name="inline-combine-catalog-surface",
        instructions="catalog instructions",
    )

    catalog_dict = SurfaceReadSerializer(catalog_surface).data
    inline_dict = InlineSurfaceReadSerializer(inline).data

    combined = SurfaceCombineService.combine([catalog_dict, inline_dict])

    assert "inline instructions" in combined["instructions"]
    assert "catalog instructions" in combined["instructions"]
    assert {t["python_tool"] for t in combined["python_tools"]} == {py_tool.pk}
    assert {t["mcp_tool"] for t in combined["mcp_tools"]} == {mcp_tool.pk}
    assert {s["storage_file"] for s in combined["storage_items"]} == {
        api_storage_file.pk
    }
    assert {k["collection"] for k in combined["knowledge"]} == {naive_collection.pk}


@pytest.mark.parametrize(
    ("inline_surface", "field"),
    [
        (lambda f: {"python_tools": [{"python_tool": f["py_tool"].pk, "mode": "allow"}, {"python_tool": f["py_tool"].pk, "mode": "deny"}]}, "python_tools"),
        (lambda f: {"storage_items": [{"storage_file": f["other_org_storage_file"].pk, "can_view": "allow"}]}, "storage_items"),
        (lambda f: {"knowledge": [{"collection": f["graph_collection"].pk, "naive_search_config": {"search_limit": 5, "similarity_threshold": "0.30"}}]}, "knowledge"),
        *[
            (lambda f, config=config: {"knowledge": [{"collection": f["graph_collection"].pk, "graph_local_search_config": config}]}, "knowledge")
            for config in (
                {"max_context_tokens": 2_000_001},
                {"text_unit_prop": 0.6, "community_prop": 0.5},
                {"prompt": "p" * 10_001},
            )
        ],
    ],
    ids=["python-tool-twice", "other-orgs-storage-file", "naive-config-on-graph-collection", "too-many-tokens", "props-over-one", "prompt-too-long"],
)
@pytest.mark.django_db
def test_invalid_inline_surface_is_refused_under_its_own_key(
    client, api_graph, py_tool, other_org_storage_file, graph_collection, inline_surface, field
):
    """Errors nest under `inline_surface`, apart from the catalog `surface_list` path, and nothing is saved."""
    response = client.post(
        "/api/tasknodes/",
        {"graph": api_graph.pk, "node_name": "inline-invalid", "inline_surface": inline_surface(locals())},
        format="json",
    )

    assert response.status_code == 400, response.data
    message = str(response.data["message"])
    assert "inline_surface" in message
    assert field in message
    assert "surface_list" not in message
    assert not TaskNode.objects.filter(node_name="inline-invalid").exists()


@pytest.mark.parametrize("method", ["patch", "put"])
@pytest.mark.django_db
def test_omitting_inline_surface_leaves_it_untouched(client, api_graph, method):
    """PUT omission is treated like PATCH omission (not an implicit delete), so a
    full update from a client that does not send the key keeps the inline surface."""
    node = TaskNode.objects.create(graph=api_graph, node_name="inline-keep")
    InlineSurface.objects.create(task_node=node, instructions="keep me")

    response = getattr(client, method)(
        f"/api/tasknodes/{node.pk}/",
        {"graph": api_graph.pk, "node_name": "inline-keep", "instructions": "updated task instructions"},
        format="json",
    )

    assert response.status_code == 200, response.data
    node.refresh_from_db()
    assert node.inline_surface.instructions == "keep me"
