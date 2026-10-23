"""upload_tools bins built-in tools that left the catalog, and only those."""

from unittest.mock import patch

import pytest

from agents.models import Surface, SurfacePythonTool, ToolMode
from tables.management.commands.upload_tools import upload_tools
from tables.models import PythonCode
from tables.models.python_models import PythonCodeTool, PythonCodeToolConfig
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _tool(name: str, *, built_in: bool, org=None) -> PythonCodeTool:
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main", global_kwargs={})
    return PythonCodeTool.objects.create(
        name=name, description="", variables=[], python_code=code, built_in=built_in, org=org
    )


@pytest.mark.django_db
def test_removed_built_in_tool_is_unlinked_in_every_org_but_an_org_tool_with_its_name_stays(acme, beta):
    removed_built_in = _tool("Retired Tool", built_in=True)
    acme_tool = _tool("Retired Tool", built_in=False, org=acme)
    for org in (acme, beta):
        surface = Surface.objects.create(org=org, name=f"{org.name} surface")
        SurfacePythonTool.objects.create(surface=surface, python_tool=removed_built_in, mode=ToolMode.ALLOW)
    PythonCodeToolConfig.objects.create(org=acme, name="acme config", tool=removed_built_in, configuration={})

    # An empty catalog: every built-in tool in the database counts as removed.
    with patch("tables.management.commands.upload_tools.get_all_tool_paths", return_value=[]):
        upload_tools()

    assert PythonCodeTool.deleted_objects.filter(id=removed_built_in.id).exists()
    # A surface only references the tool, so its link is removed for good; the
    # config belongs to the tool and goes to the bin with it.
    assert not SurfacePythonTool.all_objects.filter(python_tool=removed_built_in).exists()
    assert not PythonCodeToolConfig.objects.filter(tool=removed_built_in).exists()
    assert PythonCodeToolConfig.deleted_objects.filter(tool=removed_built_in).count() == 1
    assert PythonCodeTool.objects.filter(id=acme_tool.id).exists()
