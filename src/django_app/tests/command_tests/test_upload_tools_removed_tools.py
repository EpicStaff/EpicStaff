"""upload_tools bins built-in tools that left the catalog, and only those."""

from unittest.mock import patch

import pytest

from tables.management.commands.upload_tools import upload_tools
from tables.models import PythonCode
from tables.models.python_models import PythonCodeTool


def _tool(name: str, *, built_in: bool, org=None) -> PythonCodeTool:
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main", libraries="", global_kwargs={})
    return PythonCodeTool.objects.create(
        name=name, description="", variables=[], python_code=code, built_in=built_in, org=org
    )


@pytest.mark.django_db
def test_removed_built_in_tool_is_binned_but_an_org_tool_with_its_name_is_not(default_org):
    removed_built_in = _tool("Retired Tool", built_in=True)
    org_tool = _tool("Retired Tool", built_in=False, org=default_org)

    # An empty catalog: every built-in tool in the database counts as removed.
    with patch("tables.management.commands.upload_tools.get_all_tool_paths", return_value=[]):
        upload_tools()

    assert PythonCodeTool.deleted_objects.filter(id=removed_built_in.id).exists()
    assert PythonCodeTool.objects.filter(id=org_tool.id).exists()
