"""Combining surfaces: the merge rules (pure, on SurfaceReadSerializer-shaped dicts)
and the POST /surfaces/combine/ contract."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from agents.exceptions import SurfaceValidationError
from agents.models.surface_models import (
    Surface,
    SurfaceKnowledge,
    SurfaceNaiveSearchConfig,
    SurfacePythonTool,
    ToolMode,
)
from agents.services.surface_combine_service import SurfaceCombineService
from tables.models.knowledge_models.collection_models import BaseRagType, SourceCollection
from tables.models.python_models import PythonCode, PythonCodeTool
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole


def surface(instructions="", python_tools=(), mcp_tools=(), storage_items=(), knowledge=()):
    return {
        "instructions": instructions,
        "python_tools": [{"python_tool": tool_id, "mode": mode} for tool_id, mode in python_tools],
        "mcp_tools": [{"mcp_tool": tool_id, "mode": mode} for tool_id, mode in mcp_tools],
        "storage_items": [
            {"storage_file": file_id, "can_list": "unset", "can_view": "unset", "can_edit": "unset", "can_delete": "unset", **flags}
            for file_id, flags in storage_items
        ],
        "knowledge": [
            {
                "collection": collection_id,
                "naive_search_config": None,
                "graph_basic_search_config": None,
                "graph_local_search_config": None,
                **configs,
            }
            for collection_id, configs in knowledge
        ],
    }


# ---------------------------------------------------------------------------
# Merge rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("instructions", "expected"),
    [
        (["be concise", "use bullet points"], "be concise\n\nuse bullet points"),
        (["", "be helpful", ""], "be helpful"),
        (["", ""], ""),
        (["single"], "single"),
    ],
)
def test_instructions_are_joined_skipping_empty_ones(instructions, expected):
    combined = SurfaceCombineService.combine([surface(instructions=text) for text in instructions])

    assert combined["instructions"] == expected


@pytest.mark.parametrize("kind", ["python_tools", "mcp_tools"])
@pytest.mark.parametrize(
    ("per_surface", "expected"),
    [
        ([[(1, "allow")], [(1, "deny")]], {1: "deny"}),
        ([[(1, "deny")], [(1, "allow")]], {1: "deny"}),
        ([[(1, "allow")], [(2, "allow")]], {1: "allow", 2: "allow"}),
        ([[(5, "allow")], []], {5: "allow"}),
        ([[], []], {}),
    ],
    ids=["deny-beats-allow", "deny-beats-allow-in-either-order", "union", "one-surface-only", "none"],
)
def test_tools_are_unioned_and_deny_wins(kind, per_surface, expected):
    combined = SurfaceCombineService.combine([surface(**{kind: tools}) for tools in per_surface])

    key = "python_tool" if kind == "python_tools" else "mcp_tool"
    assert {tool[key]: tool["mode"] for tool in combined[kind]} == expected


@pytest.mark.parametrize(
    ("per_surface", "expected"),
    [
        (
            [
                {"can_list": "allow", "can_view": "deny", "can_edit": "unset", "can_delete": "allow"},
                {"can_list": "unset", "can_view": "allow", "can_edit": "allow", "can_delete": "deny"},
            ],
            {"can_list": "allow", "can_view": "deny", "can_edit": "allow", "can_delete": "deny"},
        ),
        # A surface that does not mention the file counts as unset for every flag.
        ([{"can_edit": "allow"}, None], {"can_list": "unset", "can_view": "unset", "can_edit": "allow", "can_delete": "unset"}),
        ([{"can_delete": "deny"}, None], {"can_list": "unset", "can_view": "unset", "can_edit": "unset", "can_delete": "deny"}),
    ],
    ids=["each-flag-deny-then-allow-then-unset", "allow-beats-absent", "deny-beats-absent"],
)
def test_storage_flags_combine_per_flag_deny_then_allow_then_unset(per_surface, expected):
    surfaces = [surface(storage_items=[(1, flags)] if flags is not None else []) for flags in per_surface]

    (item,) = SurfaceCombineService.combine(surfaces)["storage_items"]

    assert {flag: item[flag] for flag in expected} == expected


NAIVE_A = {"naive_search_config": {"search_limit": 5, "similarity_threshold": "0.30"}}
NAIVE_B = {"naive_search_config": {"search_limit": 10, "similarity_threshold": "0.50"}}
GRAPH_A = {"graph_basic_search_config": {"prompt": None, "k": 10, "max_context_tokens": 12000}}
GRAPH_B = {"graph_basic_search_config": {"prompt": None, "k": 5, "max_context_tokens": 8000}}


@pytest.mark.parametrize(
    ("per_surface", "expected_collections"),
    [
        ([[(1, {})], [(2, {})]], [1, 2]),
        ([[(1, NAIVE_A)], [(1, NAIVE_A)]], [1]),
        ([[(1, {})], []], [1]),
    ],
    ids=["union", "identical-config-once", "one-surface-only"],
)
def test_knowledge_is_unioned_by_collection(per_surface, expected_collections):
    combined = SurfaceCombineService.combine([surface(knowledge=items) for items in per_surface])

    assert sorted(item["collection"] for item in combined["knowledge"]) == expected_collections


@pytest.mark.parametrize(("first", "second"), [(NAIVE_A, NAIVE_B), (GRAPH_A, GRAPH_B)], ids=["naive", "graph-basic"])
def test_one_collection_with_two_different_search_configs_cannot_be_combined(first, second):
    with pytest.raises(SurfaceValidationError):
        SurfaceCombineService.combine([surface(knowledge=[(1, first)]), surface(knowledge=[(1, second)])])


def test_combined_result_is_settings_only():
    assert set(SurfaceCombineService.combine([surface()])) == {
        "instructions",
        "python_tools",
        "mcp_tools",
        "storage_items",
        "knowledge",
    }


# ---------------------------------------------------------------------------
# POST /surfaces/combine/
# ---------------------------------------------------------------------------


@pytest.fixture
def org(db):
    return Organization.objects.create(name="combine-test-org")


@pytest.fixture
def client(django_user_model, org):
    role = Role.objects.get(name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True)
    user = django_user_model.objects.create_user(email="combine-test@example.com", password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    api_client = APIClient()
    api_client.force_authenticate(user=user)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return api_client


def _combine(client, surface_ids):
    return client.post("/api/surfaces/combine/", {"surface_ids": surface_ids}, format="json")


@pytest.mark.django_db
def test_combine_returns_the_merged_settings(client, org):
    s_a = Surface.objects.create(org=org, name="api-combine-a", instructions="be concise")
    s_b = Surface.objects.create(org=org, name="api-combine-b", instructions="use bullets")
    tool = PythonCodeTool.objects.create(
        org=org, name="api-combine-tool", description="t", python_code=PythonCode.objects.create(code="def main(): pass")
    )
    SurfacePythonTool.objects.create(surface=s_a, python_tool=tool, mode=ToolMode.ALLOW)
    SurfacePythonTool.objects.create(surface=s_b, python_tool=tool, mode=ToolMode.DENY)

    response = _combine(client, [s_a.pk, s_b.pk])

    assert response.status_code == 200
    data = response.json()
    assert data["instructions"] == "be concise\n\nuse bullets"
    assert data["python_tools"] == [{"python_tool": tool.pk, "mode": "deny"}]
    assert "id" not in data and "name" not in data


def _conflicting_surfaces(org):
    collection = SourceCollection.objects.create(collection_name="api-conflict-coll", org=org)
    BaseRagType.objects.create(rag_type=BaseRagType.RagType.NAIVE, source_collection=collection)
    surface_ids = []
    for name, limit, threshold in (("api-conflict-a", 5, "0.30"), ("api-conflict-b", 10, "0.50")):
        conflicting = Surface.objects.create(org=org, name=name)
        knowledge = SurfaceKnowledge.objects.create(surface=conflicting, collection=collection)
        SurfaceNaiveSearchConfig.objects.create(
            surface_knowledge=knowledge, search_limit=limit, similarity_threshold=threshold
        )
        surface_ids.append(conflicting.pk)
    return surface_ids


@pytest.mark.parametrize(
    "surface_ids",
    [
        lambda org: [],
        lambda org: [99999],
        lambda org: [Surface.objects.create(org=Organization.objects.create(name="other-org"), name="foreign").pk],
        lambda org: [Surface.objects.create(org=org, name="twice").pk] * 2,
        _conflicting_surfaces,
    ],
    ids=["none", "unknown", "another-orgs-surface", "same-surface-twice", "conflicting-knowledge"],
)
@pytest.mark.django_db
def test_combine_refuses_an_invalid_selection_with_400(client, org, surface_ids):
    assert _combine(client, surface_ids(org)).status_code == 400
