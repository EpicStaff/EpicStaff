"""
Tests for the surface combine feature.

Unit tests operate on plain dicts matching SurfaceReadSerializer output — no DB needed.
Integration tests use APIClient to test POST /surfaces/combine/.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from tables.exceptions import SurfaceValidationError
from tables.models.agent_models.surface_models import (
    Surface,
    SurfaceKnowledge,
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
from tables.services.surface_combine_service import SurfaceCombineService


# ---------------------------------------------------------------------------
# Helpers to build surface dicts (mirror SurfaceReadSerializer output shape)
# ---------------------------------------------------------------------------


def make_surface_dict(
    instructions="",
    allow_creation=False,
    python_tools=None,
    mcp_tools=None,
    storage_items=None,
    knowledge=None,
):
    return {
        "instructions": instructions,
        "allow_creation": allow_creation,
        "python_tools": python_tools or [],
        "mcp_tools": mcp_tools or [],
        "storage_items": storage_items or [],
        "knowledge": knowledge or [],
    }


def make_python_tool(tool_id, mode):
    return {"python_tool": tool_id, "mode": mode}


def make_mcp_tool(tool_id, mode):
    return {"mcp_tool": tool_id, "mode": mode}


def make_storage_item(
    file_id, can_list="unset", can_view="unset", can_edit="unset", can_delete="unset"
):
    return {
        "storage_file": file_id,
        "can_list": can_list,
        "can_view": can_view,
        "can_edit": can_edit,
        "can_delete": can_delete,
    }


def make_knowledge_item(
    collection_id,
    naive_search_config=None,
    graph_basic_search_config=None,
    graph_local_search_config=None,
):
    return {
        "collection": collection_id,
        "naive_search_config": naive_search_config,
        "graph_basic_search_config": graph_basic_search_config,
        "graph_local_search_config": graph_local_search_config,
    }


# ---------------------------------------------------------------------------
# Unit tests — pure combiner (no DB)
# ---------------------------------------------------------------------------


class TestCombineInstructions:
    def test_two_non_empty_instructions_joined_with_double_newline(self):
        s1 = make_surface_dict(instructions="be concise")
        s2 = make_surface_dict(instructions="use bullet points")
        result = SurfaceCombineService.combine([s1, s2])
        assert result["instructions"] == "be concise\n\nuse bullet points"

    def test_empty_instructions_skipped(self):
        s1 = make_surface_dict(instructions="")
        s2 = make_surface_dict(instructions="be helpful")
        s3 = make_surface_dict(instructions="")
        result = SurfaceCombineService.combine([s1, s2, s3])
        assert result["instructions"] == "be helpful"

    def test_all_empty_instructions_produces_empty_string(self):
        s1 = make_surface_dict(instructions="")
        s2 = make_surface_dict(instructions="")
        result = SurfaceCombineService.combine([s1, s2])
        assert result["instructions"] == ""

    def test_single_surface_instructions_unchanged(self):
        s1 = make_surface_dict(instructions="single")
        result = SurfaceCombineService.combine([s1])
        assert result["instructions"] == "single"


class TestCombinePythonTools:
    def test_deny_beats_allow_for_same_tool(self):
        s1 = make_surface_dict(python_tools=[make_python_tool(1, "allow")])
        s2 = make_surface_dict(python_tools=[make_python_tool(1, "deny")])
        result = SurfaceCombineService.combine([s1, s2])
        tools_by_id = {t["python_tool"]: t["mode"] for t in result["python_tools"]}
        assert tools_by_id[1] == "deny"

    def test_allow_union_when_no_deny(self):
        s1 = make_surface_dict(python_tools=[make_python_tool(1, "allow")])
        s2 = make_surface_dict(python_tools=[make_python_tool(2, "allow")])
        result = SurfaceCombineService.combine([s1, s2])
        tools_by_id = {t["python_tool"]: t["mode"] for t in result["python_tools"]}
        assert tools_by_id[1] == "allow"
        assert tools_by_id[2] == "allow"

    def test_tool_from_single_surface_preserved(self):
        s1 = make_surface_dict(python_tools=[make_python_tool(5, "allow")])
        s2 = make_surface_dict(python_tools=[])
        result = SurfaceCombineService.combine([s1, s2])
        assert len(result["python_tools"]) == 1
        assert result["python_tools"][0]["python_tool"] == 5

    def test_no_tools_produces_empty_list(self):
        s1 = make_surface_dict()
        s2 = make_surface_dict()
        result = SurfaceCombineService.combine([s1, s2])
        assert result["python_tools"] == []


class TestCombineMcpTools:
    def test_deny_beats_allow_for_same_mcp_tool(self):
        s1 = make_surface_dict(mcp_tools=[make_mcp_tool(10, "allow")])
        s2 = make_surface_dict(mcp_tools=[make_mcp_tool(10, "deny")])
        result = SurfaceCombineService.combine([s1, s2])
        tools_by_id = {t["mcp_tool"]: t["mode"] for t in result["mcp_tools"]}
        assert tools_by_id[10] == "deny"

    def test_allow_union_across_surfaces(self):
        s1 = make_surface_dict(mcp_tools=[make_mcp_tool(10, "allow")])
        s2 = make_surface_dict(mcp_tools=[make_mcp_tool(20, "allow")])
        result = SurfaceCombineService.combine([s1, s2])
        assert len(result["mcp_tools"]) == 2


class TestCombineStorage:
    def test_deny_beats_allow_per_flag(self):
        s1 = make_surface_dict(storage_items=[make_storage_item(1, can_list="allow")])
        s2 = make_surface_dict(storage_items=[make_storage_item(1, can_list="deny")])
        result = SurfaceCombineService.combine([s1, s2])
        item = result["storage_items"][0]
        assert item["can_list"] == "deny"

    def test_allow_beats_unset(self):
        s1 = make_surface_dict(storage_items=[make_storage_item(1, can_view="allow")])
        s2 = make_surface_dict(storage_items=[make_storage_item(1, can_view="unset")])
        result = SurfaceCombineService.combine([s1, s2])
        item = result["storage_items"][0]
        assert item["can_view"] == "allow"

    def test_file_present_in_subset_absent_counts_as_unset(self):
        # file 2 only in s1; s2 does not reference it.
        # absent = unset, so allow from s1 should win.
        s1 = make_surface_dict(storage_items=[make_storage_item(2, can_edit="allow")])
        s2 = make_surface_dict(storage_items=[])
        result = SurfaceCombineService.combine([s1, s2])
        items_by_id = {i["storage_file"]: i for i in result["storage_items"]}
        assert items_by_id[2]["can_edit"] == "allow"

    def test_deny_from_one_surface_overrides_absent_in_other(self):
        # file 3 only in s1 with deny; s2 absent (=unset). deny wins.
        s1 = make_surface_dict(storage_items=[make_storage_item(3, can_delete="deny")])
        s2 = make_surface_dict(storage_items=[])
        result = SurfaceCombineService.combine([s1, s2])
        items_by_id = {i["storage_file"]: i for i in result["storage_items"]}
        assert items_by_id[3]["can_delete"] == "deny"

    def test_all_flags_combined_independently(self):
        s1 = make_surface_dict(
            storage_items=[
                make_storage_item(
                    1,
                    can_list="allow",
                    can_view="deny",
                    can_edit="unset",
                    can_delete="allow",
                )
            ]
        )
        s2 = make_surface_dict(
            storage_items=[
                make_storage_item(
                    1,
                    can_list="unset",
                    can_view="allow",
                    can_edit="allow",
                    can_delete="deny",
                )
            ]
        )
        result = SurfaceCombineService.combine([s1, s2])
        item = result["storage_items"][0]
        # deny beats all
        assert item["can_list"] == "allow"  # allow vs unset -> allow
        assert item["can_view"] == "deny"  # deny beats allow
        assert item["can_edit"] == "allow"  # allow beats unset
        assert item["can_delete"] == "deny"  # deny beats allow


class TestCombineAllowCreation:
    def test_all_true_returns_true(self):
        s1 = make_surface_dict(allow_creation=True)
        s2 = make_surface_dict(allow_creation=True)
        result = SurfaceCombineService.combine([s1, s2])
        assert result["allow_creation"] is True

    def test_any_false_returns_false(self):
        s1 = make_surface_dict(allow_creation=True)
        s2 = make_surface_dict(allow_creation=False)
        result = SurfaceCombineService.combine([s1, s2])
        assert result["allow_creation"] is False

    def test_single_false_returns_false(self):
        s1 = make_surface_dict(allow_creation=False)
        result = SurfaceCombineService.combine([s1])
        assert result["allow_creation"] is False


class TestCombineKnowledge:
    def test_knowledge_union_different_collections(self):
        s1 = make_surface_dict(knowledge=[make_knowledge_item(1)])
        s2 = make_surface_dict(knowledge=[make_knowledge_item(2)])
        result = SurfaceCombineService.combine([s1, s2])
        collection_ids = {k["collection"] for k in result["knowledge"]}
        assert collection_ids == {1, 2}

    def test_identical_config_deduped_to_one(self):
        config = {"search_limit": 5, "similarity_threshold": "0.30"}
        s1 = make_surface_dict(
            knowledge=[make_knowledge_item(1, naive_search_config=config)]
        )
        s2 = make_surface_dict(
            knowledge=[make_knowledge_item(1, naive_search_config=config)]
        )
        result = SurfaceCombineService.combine([s1, s2])
        assert len(result["knowledge"]) == 1
        assert result["knowledge"][0]["naive_search_config"] == config

    def test_conflicting_naive_search_config_raises_surface_validation_error(self):
        config_a = {"search_limit": 5, "similarity_threshold": "0.30"}
        config_b = {"search_limit": 10, "similarity_threshold": "0.50"}
        s1 = make_surface_dict(
            knowledge=[make_knowledge_item(1, naive_search_config=config_a)]
        )
        s2 = make_surface_dict(
            knowledge=[make_knowledge_item(1, naive_search_config=config_b)]
        )
        with pytest.raises(SurfaceValidationError):
            SurfaceCombineService.combine([s1, s2])

    def test_conflicting_graph_basic_config_raises_surface_validation_error(self):
        config_a = {"prompt": None, "k": 10, "max_context_tokens": 12000}
        config_b = {"prompt": None, "k": 5, "max_context_tokens": 8000}
        s1 = make_surface_dict(
            knowledge=[make_knowledge_item(1, graph_basic_search_config=config_a)]
        )
        s2 = make_surface_dict(
            knowledge=[make_knowledge_item(1, graph_basic_search_config=config_b)]
        )
        with pytest.raises(SurfaceValidationError):
            SurfaceCombineService.combine([s1, s2])

    def test_collection_in_one_surface_only_passes(self):
        s1 = make_surface_dict(knowledge=[make_knowledge_item(1)])
        s2 = make_surface_dict(knowledge=[])
        result = SurfaceCombineService.combine([s1, s2])
        assert len(result["knowledge"]) == 1


class TestCombineOutputShape:
    def test_output_omits_metadata_fields(self):
        s1 = make_surface_dict()
        result = SurfaceCombineService.combine([s1])
        assert "id" not in result
        assert "name" not in result
        assert "owner_agent" not in result
        assert "description" not in result
        assert "organization" not in result
        assert "created_at" not in result
        assert "updated_at" not in result

    def test_output_contains_expected_keys(self):
        s1 = make_surface_dict()
        result = SurfaceCombineService.combine([s1])
        assert set(result.keys()) == {
            "instructions",
            "allow_creation",
            "python_tools",
            "mcp_tools",
            "storage_items",
            "knowledge",
        }


# ---------------------------------------------------------------------------
# Fixtures for API integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
def org(db):
    return Organization.objects.create(name="combine-test-org")


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def py_tool_a(db):
    code = PythonCode.objects.create(code="def main(): pass")
    return PythonCodeTool.objects.create(
        name="combine-py-tool-a", description="test", python_code=code
    )


@pytest.fixture
def py_tool_b(db):
    code = PythonCode.objects.create(code="def main(): pass")
    return PythonCodeTool.objects.create(
        name="combine-py-tool-b", description="test", python_code=code
    )


@pytest.fixture
def mcp_tool_a(db):
    return McpTool.objects.create(
        name="combine-mcp-a", transport="http://localhost/sse", tool_name="tool_a"
    )


@pytest.fixture
def storage_file_a(db, org):
    return StorageFile.objects.create(
        org=org, name="combine-file-a", path="combine/a.txt"
    )


@pytest.fixture
def naive_collection(db):
    coll = SourceCollection.objects.create(collection_name="combine-naive-coll")
    BaseRagType.objects.create(
        rag_type=BaseRagType.RagType.NAIVE, source_collection=coll
    )
    return coll


@pytest.fixture
def surface_a(db, org, py_tool_a, storage_file_a):
    surface = Surface.objects.create(
        organization=org,
        name="combine-surface-a",
        instructions="be concise",
        allow_creation=True,
    )
    SurfacePythonTool.objects.create(
        surface=surface, python_tool=py_tool_a, mode=ToolMode.ALLOW
    )
    SurfaceStorageItem.objects.create(
        surface=surface, storage_file=storage_file_a, can_view="allow"
    )
    return surface


@pytest.fixture
def surface_b(db, org, py_tool_a, py_tool_b):
    surface = Surface.objects.create(
        organization=org,
        name="combine-surface-b",
        instructions="use bullet points",
        allow_creation=False,
    )
    SurfacePythonTool.objects.create(
        surface=surface, python_tool=py_tool_a, mode=ToolMode.DENY
    )
    SurfacePythonTool.objects.create(
        surface=surface, python_tool=py_tool_b, mode=ToolMode.ALLOW
    )
    return surface


@pytest.fixture
def surface_c(db, org):
    return Surface.objects.create(
        organization=org,
        name="combine-surface-c",
        instructions="",
        allow_creation=True,
    )


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_combine_happy_path_returns_merged_result(
    client, org, surface_a, surface_b, py_tool_a, py_tool_b, storage_file_a
):
    from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME
    from tables.models.rbac_models import Organization as Org

    # The view uses _get_organization() which fetches by DEFAULT_ORGANIZATION_NAME.
    # We need a surface scoped to that org, so create a default-named org.
    default_org = Org.objects.get_or_create(name=DEFAULT_ORGANIZATION_NAME)[0]
    s_a = Surface.objects.create(
        organization=default_org,
        name="api-combine-a",
        instructions="be concise",
        allow_creation=True,
    )
    s_b = Surface.objects.create(
        organization=default_org,
        name="api-combine-b",
        instructions="use bullets",
        allow_creation=False,
    )

    code = PythonCode.objects.create(code="def main(): pass")
    tool = PythonCodeTool.objects.create(
        name="api-combine-tool", description="t", python_code=code
    )
    SurfacePythonTool.objects.create(surface=s_a, python_tool=tool, mode=ToolMode.ALLOW)
    SurfacePythonTool.objects.create(surface=s_b, python_tool=tool, mode=ToolMode.DENY)

    response = client.post(
        "/api/surfaces/combine/",
        {"surface_ids": [s_a.pk, s_b.pk]},
        format="json",
    )

    assert response.status_code == 200
    data = response.json()
    # Instructions joined
    assert "be concise" in data["instructions"]
    assert "use bullets" in data["instructions"]
    # allow_creation AND
    assert data["allow_creation"] is False
    # deny beats allow for py_tool
    tools_by_id = {t["python_tool"]: t["mode"] for t in data["python_tools"]}
    assert tools_by_id[tool.pk] == "deny"
    # Metadata fields absent
    assert "id" not in data
    assert "name" not in data


@pytest.mark.django_db
def test_combine_empty_surface_ids_returns_400(client, db):
    from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME
    from tables.models.rbac_models import Organization as Org

    Org.objects.get_or_create(name=DEFAULT_ORGANIZATION_NAME)
    response = client.post("/api/surfaces/combine/", {"surface_ids": []}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_combine_unknown_surface_id_returns_400(client, db):
    from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME
    from tables.models.rbac_models import Organization as Org

    Org.objects.get_or_create(name=DEFAULT_ORGANIZATION_NAME)
    response = client.post(
        "/api/surfaces/combine/", {"surface_ids": [99999]}, format="json"
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_combine_conflicting_knowledge_returns_400(client):
    from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME
    from tables.models.rbac_models import Organization as Org

    default_org = Org.objects.get_or_create(name=DEFAULT_ORGANIZATION_NAME)[0]
    coll = SourceCollection.objects.create(collection_name="api-conflict-coll")
    BaseRagType.objects.create(
        rag_type=BaseRagType.RagType.NAIVE, source_collection=coll
    )

    s_a = Surface.objects.create(organization=default_org, name="api-conflict-a")
    s_b = Surface.objects.create(organization=default_org, name="api-conflict-b")

    sk_a = SurfaceKnowledge.objects.create(surface=s_a, collection=coll)
    SurfaceNaiveSearchConfig.objects.create(
        surface_knowledge=sk_a, search_limit=5, similarity_threshold="0.30"
    )
    sk_b = SurfaceKnowledge.objects.create(surface=s_b, collection=coll)
    SurfaceNaiveSearchConfig.objects.create(
        surface_knowledge=sk_b, search_limit=10, similarity_threshold="0.50"
    )

    response = client.post(
        "/api/surfaces/combine/",
        {"surface_ids": [s_a.pk, s_b.pk]},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_combine_duplicate_surface_ids_returns_400(client, db):
    from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME
    from tables.models.rbac_models import Organization as Org

    default_org = Org.objects.get_or_create(name=DEFAULT_ORGANIZATION_NAME)[0]
    surface = Surface.objects.create(
        organization=default_org,
        name="api-duplicate-combine",
    )

    response = client.post(
        "/api/surfaces/combine/",
        {"surface_ids": [surface.pk, surface.pk]},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_combine_single_surface_returns_its_effective_data(client):
    from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME
    from tables.models.rbac_models import Organization as Org

    default_org = Org.objects.get_or_create(name=DEFAULT_ORGANIZATION_NAME)[0]
    surface = Surface.objects.create(
        organization=default_org,
        name="api-single-combine",
        instructions="solo instructions",
        allow_creation=True,
    )

    response = client.post(
        "/api/surfaces/combine/",
        {"surface_ids": [surface.pk]},
        format="json",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["instructions"] == "solo instructions"
    assert data["allow_creation"] is True
