"""
Integration tests for the InlineSurface model family.

Covers:
- Create InlineSurface with content rows (python tool, mcp tool, storage item,
  knowledge + naive config) — rows exist, reverse accessors work
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
from rest_framework.test import APIClient

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
from tables.models.rbac_models import Organization
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
def org(db):
    return Organization.objects.create(name="inline-surface-org")


@pytest.fixture
def graph(db):
    return Graph.objects.create(name="inline-surface-graph")


@pytest.fixture
def task_node(db, graph):
    return TaskNode.objects.create(graph=graph, node_name="inline-surface-task")


@pytest.fixture
def py_tool(db):
    code = PythonCode.objects.create(code="def main(): pass")
    return PythonCodeTool.objects.create(
        name="inline-surface-py-tool",
        description="test",
        python_code=code,
    )


@pytest.fixture
def mcp_tool(db):
    return McpTool.objects.create(
        name="inline-mcp", transport="http://localhost/sse", tool_name="tool_a"
    )


@pytest.fixture
def storage_file(db, org):
    return StorageFile.objects.create(org=org, name="file-a", path="a/file.txt")


@pytest.fixture
def naive_collection(db):
    coll = SourceCollection.objects.create(collection_name="inline-naive-coll")
    BaseRagType.objects.create(
        rag_type=BaseRagType.RagType.NAIVE,
        source_collection=coll,
    )
    return coll


@pytest.fixture
def graph_collection(db):
    coll = SourceCollection.objects.create(collection_name="inline-graph-coll")
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
def client():
    return APIClient()


@pytest.fixture
def default_org(db):
    from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME

    return Organization.objects.get_or_create(name=DEFAULT_ORGANIZATION_NAME)[0]


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="inline-surface-other-org")


@pytest.fixture
def api_graph(db, default_org):
    return Graph.objects.create(name="inline-surface-api-graph")


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
# Create with content rows — rows exist, reverse accessors work
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_inline_surface(task_node):
    inline = InlineSurface.objects.create(
        task_node=task_node,
        instructions="be concise",
    )

    assert inline.pk is not None
    assert inline.task_node == task_node
    assert inline.instructions == "be concise"


@pytest.mark.django_db
def test_inline_surface_python_tool_reverse_accessor(inline_surface, py_tool):
    InlineSurfacePythonTool.objects.create(
        inline_surface=inline_surface,
        python_tool=py_tool,
        mode=ToolMode.ALLOW,
    )

    entries = list(inline_surface.python_tools.all())
    assert len(entries) == 1
    assert entries[0].python_tool == py_tool
    assert entries[0].mode == ToolMode.ALLOW


@pytest.mark.django_db
def test_inline_surface_mcp_tool_reverse_accessor(inline_surface, mcp_tool):
    InlineSurfaceMcpTool.objects.create(
        inline_surface=inline_surface,
        mcp_tool=mcp_tool,
        mode=ToolMode.DENY,
    )

    entries = list(inline_surface.mcp_tools.all())
    assert len(entries) == 1
    assert entries[0].mcp_tool == mcp_tool
    assert entries[0].mode == ToolMode.DENY


@pytest.mark.django_db
def test_inline_surface_storage_item_reverse_accessor(inline_surface, storage_file):
    InlineSurfaceStorageItem.objects.create(
        inline_surface=inline_surface,
        storage_file=storage_file,
        can_view="allow",
    )

    entries = list(inline_surface.storage_items.all())
    assert len(entries) == 1
    assert entries[0].storage_file == storage_file
    assert entries[0].can_view == "allow"


@pytest.mark.django_db
def test_inline_surface_knowledge_with_naive_config_reverse_accessor(
    inline_surface, naive_collection
):
    knowledge = InlineSurfaceKnowledge.objects.create(
        inline_surface=inline_surface,
        collection=naive_collection,
    )
    InlineSurfaceNaiveSearchConfig.objects.create(
        surface_knowledge=knowledge,
        search_limit=7,
        similarity_threshold="0.40",
    )

    entries = list(inline_surface.knowledge.all())
    assert len(entries) == 1
    assert entries[0].collection == naive_collection
    assert entries[0].naive_search_config.search_limit == 7


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
# content_hash unaffected
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_content_hash_unchanged_by_inline_surface_create_and_delete(task_node):
    """ContentHashMixin.generate_hash iterates _meta.fields only — the reverse
    OneToOne accessor to InlineSurface is not a local field and is excluded."""
    hash_before = task_node.content_hash

    inline = InlineSurface.objects.create(task_node=task_node)
    task_node.refresh_from_db()
    assert task_node.content_hash == hash_before

    inline.delete()
    task_node.refresh_from_db()
    assert task_node.content_hash == hash_before


# ---------------------------------------------------------------------------
# tasknodes/ API — nested inline_surface
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_with_full_inline_payload_returns_201_and_creates_rows(
    client, api_graph, py_tool, mcp_tool, api_storage_file, naive_collection
):
    py_tool_b_code = PythonCode.objects.create(code="def main(): pass")
    py_tool_b = PythonCodeTool.objects.create(
        name="inline-surface-py-tool-b", description="test", python_code=py_tool_b_code
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
def test_patch_other_field_only_leaves_inline_untouched(client, api_graph):
    node = TaskNode.objects.create(graph=api_graph, node_name="inline-patch-keep")
    InlineSurface.objects.create(task_node=node, instructions="keep me")

    response = client.patch(
        f"/api/tasknodes/{node.pk}/",
        {"instructions": "updated task instructions"},
        format="json",
    )

    assert response.status_code == 200, response.data
    node.refresh_from_db()
    assert node.inline_surface.instructions == "keep me"


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
def test_put_without_inline_key_leaves_inline_untouched(client, api_graph):
    """Documented deviation: PUT omitting `inline_surface` is treated the same
    as PATCH omission (untouched), not as an implicit delete. This protects
    IdempotentNodeCreateMixin retry payloads that lack the key."""
    node = TaskNode.objects.create(graph=api_graph, node_name="inline-put-keep")
    InlineSurface.objects.create(task_node=node, instructions="keep me")

    response = client.put(
        f"/api/tasknodes/{node.pk}/",
        {
            "graph": api_graph.pk,
            "node_name": "inline-put-keep",
            "instructions": "put updated",
        },
        format="json",
    )

    assert response.status_code == 200, response.data
    node.refresh_from_db()
    assert node.inline_surface.instructions == "keep me"


@pytest.mark.django_db
def test_reject_duplicate_python_tool_ids(client, api_graph, py_tool):
    response = client.post(
        "/api/tasknodes/",
        {
            "graph": api_graph.pk,
            "node_name": "inline-dup-python-tools",
            "inline_surface": {
                "python_tools": [
                    {"python_tool": py_tool.pk, "mode": "allow"},
                    {"python_tool": py_tool.pk, "mode": "deny"},
                ]
            },
        },
        format="json",
    )

    assert response.status_code == 400, response.data
    assert "inline_surface" in response.data["message"]
    assert "python_tools" in response.data["message"]


@pytest.mark.django_db
def test_reject_cross_org_storage_file(client, api_graph, other_org_storage_file):
    response = client.post(
        "/api/tasknodes/",
        {
            "graph": api_graph.pk,
            "node_name": "inline-cross-org-storage",
            "inline_surface": {
                "storage_items": [
                    {"storage_file": other_org_storage_file.pk, "can_view": "allow"}
                ]
            },
        },
        format="json",
    )

    assert response.status_code == 400, response.data
    assert "inline_surface" in response.data["message"]
    assert "storage_items" in response.data["message"]


@pytest.mark.django_db
def test_reject_naive_config_on_graph_only_collection(
    client, api_graph, graph_collection
):
    response = client.post(
        "/api/tasknodes/",
        {
            "graph": api_graph.pk,
            "node_name": "inline-rag-mismatch",
            "inline_surface": {
                "knowledge": [
                    {
                        "collection": graph_collection.pk,
                        "naive_search_config": {
                            "search_limit": 5,
                            "similarity_threshold": "0.30",
                        },
                    }
                ]
            },
        },
        format="json",
    )

    assert response.status_code == 400, response.data
    assert "inline_surface" in response.data["message"]
    assert "knowledge" in response.data["message"]


@pytest.mark.django_db
def test_reject_duplicate_python_tool_ids_nests_error_under_inline_surface_key(
    client, api_graph, py_tool
):
    """Regression: SurfaceValidator errors raised from InlineSurfaceWriteSerializer
    must be nested under `inline_surface`, distinct from top-level `surface_list`
    errors raised by TaskNodeSerializer for the catalog-surface path."""
    response = client.post(
        "/api/tasknodes/",
        {
            "graph": api_graph.pk,
            "node_name": "inline-dup-error-shape",
            "inline_surface": {
                "python_tools": [
                    {"python_tool": py_tool.pk, "mode": "allow"},
                    {"python_tool": py_tool.pk, "mode": "deny"},
                ]
            },
        },
        format="json",
    )

    assert response.status_code == 400, response.data
    assert "inline_surface" in response.data["message"]
    assert "surface_list" not in response.data["message"]


@pytest.mark.django_db
def test_idempotent_create_replaces_inline_content(
    client, api_graph, py_tool, mcp_tool
):
    """Same (graph, node_name) POSTed again updates instead of creating —
    exercises IdempotentNodeCreateMixin with an inline_surface payload change."""

    first = client.post(
        "/api/tasknodes/",
        {
            "graph": api_graph.pk,
            "node_name": "inline-idempotent",
            "inline_surface": {
                "python_tools": [{"python_tool": py_tool.pk, "mode": "allow"}]
            },
        },
        format="json",
    )
    assert first.status_code == 201, first.data

    second = client.post(
        "/api/tasknodes/",
        {
            "graph": api_graph.pk,
            "node_name": "inline-idempotent",
            "inline_surface": {
                "mcp_tools": [{"mcp_tool": mcp_tool.pk, "mode": "deny"}]
            },
        },
        format="json",
    )

    assert second.status_code == 200, second.data
    assert (
        TaskNode.objects.filter(graph=api_graph, node_name="inline-idempotent").count()
        == 1
    )
    node = TaskNode.objects.get(graph=api_graph, node_name="inline-idempotent")
    inline = InlineSurface.objects.get(task_node=node)
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
        organization=default_org,
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
