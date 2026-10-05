"""MCP tools go to the recycle bin on delete, and come back on restore."""

import pytest

from agents.models import Surface, SurfaceMcpTool, ToolMode
from tables.models.favorite_models import McpToolFavorite
from tables.models.mcp_models import McpTool
from tables.services.recycle_bin.restore_service import RestoreService


def _results(response):
    body = response.data
    return body["results"] if isinstance(body, dict) and "results" in body else body


def _mcp_tool(org, name="Search") -> McpTool:
    return McpTool.objects.create(name=name, transport="http://mcp", tool_name="search", org=org)


@pytest.mark.django_db
class TestMcpToolGoesToTheRecycleBin:
    def test_delete_bins_the_tool_and_hides_it_from_the_list(self, auth_client, default_org):
        tool = _mcp_tool(default_org)

        response = auth_client.delete(f"/api/mcp-tools/{tool.id}/")

        assert response.status_code == 204, response.data
        assert McpTool.deleted_objects.filter(pk=tool.pk).exists()
        assert tool.id not in {item["id"] for item in _results(auth_client.get("/api/mcp-tools/"))}

    def test_bulk_delete_bins_every_tool(self, auth_client, default_org):
        first, second = _mcp_tool(default_org, "First"), _mcp_tool(default_org, "Second")

        response = auth_client.post("/api/mcp-tools/bulk-delete/", {"ids": [first.id, second.id]}, format="json")

        assert response.status_code == 200, response.data
        assert McpTool.deleted_objects.filter(pk__in=[first.pk, second.pk]).count() == 2

    def test_a_binned_tool_frees_its_name(self, auth_client, default_org):
        _mcp_tool(default_org, "Search").delete()

        response = auth_client.post(
            "/api/mcp-tools/", {"name": "Search", "transport": "http://mcp", "tool_name": "search"}, format="json"
        )

        assert response.status_code == 201, response.data

    def test_full_replace_update_keeps_the_tool_live(self, auth_client, default_org):
        tool = _mcp_tool(default_org)

        response = auth_client.put(
            f"/api/mcp-tools/{tool.id}/",
            {"name": "Renamed", "transport": "http://mcp", "tool_name": "search"},
            format="json",
        )

        assert response.status_code == 200, response.data
        assert McpTool.objects.get(pk=tool.pk).name == "Renamed"
        assert not set(response.data) & {"active", "soft_deleted_at", "soft_delete_batch"}

    def test_delete_removes_surface_links_and_bins_favorites(self, default_org, regular_user):
        tool = _mcp_tool(default_org)
        surface = Surface.objects.create(organization=default_org, name="S")
        link = SurfaceMcpTool.objects.create(surface=surface, mcp_tool=tool, mode=ToolMode.ALLOW)
        favorite = McpToolFavorite.objects.create(user=regular_user, tool=tool)

        batch = tool.delete()

        assert not SurfaceMcpTool.all_objects.filter(pk=link.pk).exists()
        assert McpToolFavorite.all_objects.get(pk=favorite.pk).soft_delete_batch == batch


@pytest.mark.django_db
class TestMcpToolRestore:
    def test_restore_brings_the_tool_and_its_favorite_back(self, default_org, regular_user):
        tool = _mcp_tool(default_org)
        favorite = McpToolFavorite.objects.create(user=regular_user, tool=tool)
        tool.delete()

        result = RestoreService.restore(McpTool.all_objects.get(pk=tool.pk))

        assert result.renamed_from is None
        assert McpTool.objects.filter(pk=tool.pk).exists()
        assert McpToolFavorite.objects.filter(pk=favorite.pk).exists()

    def test_restore_renames_when_the_name_is_taken(self, default_org):
        tool = _mcp_tool(default_org, "Search")
        tool.delete()
        _mcp_tool(default_org, "Search")

        result = RestoreService.restore(McpTool.all_objects.get(pk=tool.pk))

        assert result.renamed_from == "Search"
        assert result.object.name == "Search #2"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "method, path",
    [
        ("get", ""),
        ("put", ""),
        ("patch", ""),
        ("delete", ""),
        ("post", "favorite/"),
        ("post", "copy/"),
        ("get", "usage-detail/"),
        ("get", "export/"),
        ("delete", "favorite/"),
    ],
)
def test_a_binned_tool_is_not_reachable_by_id(auth_client, default_org, method, path):
    # Pins the live-only viewset queryset: a binned tool can't be read, edited,
    # deleted again, favorited or copied until it's restored.
    tool = _mcp_tool(default_org)
    tool.delete()

    response = getattr(auth_client, method)(
        f"/api/mcp-tools/{tool.id}/{path}",
        {"name": "x", "transport": "http://mcp", "tool_name": "search"},
        format="json",
    )

    assert response.status_code == 404, (method, path, response.status_code)


@pytest.mark.django_db
def test_bulk_export_rejects_a_binned_tool(auth_client, default_org):
    tool = _mcp_tool(default_org)
    tool.delete()

    response = auth_client.post("/api/mcp-tools/bulk-export/", {"ids": [tool.id]}, format="json")

    assert response.status_code == 400, response.status_code


@pytest.mark.django_db
def test_bulk_delete_skips_a_tool_already_in_the_bin(auth_client, default_org):
    tool = _mcp_tool(default_org)
    tool.delete()
    binned_at = McpTool.all_objects.get(pk=tool.pk).soft_deleted_at

    response = auth_client.post("/api/mcp-tools/bulk-delete/", {"ids": [tool.id]}, format="json")

    assert response.status_code == 200, response.data
    assert response.data["deleted"] == 0
    assert McpTool.all_objects.get(pk=tool.pk).soft_deleted_at == binned_at
