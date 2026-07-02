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
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from tables.models.agent_models import (
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
def inline_surface(db, task_node):
    return InlineSurface.objects.create(task_node=task_node)


# ---------------------------------------------------------------------------
# Create with content rows — rows exist, reverse accessors work
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_inline_surface(task_node):
    inline = InlineSurface.objects.create(
        task_node=task_node,
        instructions="be concise",
        allow_creation=True,
    )

    assert inline.pk is not None
    assert inline.task_node == task_node
    assert inline.instructions == "be concise"
    assert inline.allow_creation is True


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
