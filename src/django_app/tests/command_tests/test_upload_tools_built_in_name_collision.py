"""upload_tools writes only built-in tools, even when an org tool shares a catalog tool's name."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tables.management.commands.upload_tools import upload_tools
from tables.models import PythonCode
from tables.models.python_models import PythonCodeTool
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

CATALOG_TOOL_NAME = "Catalog Tool"
CATALOG_CODE = "def main(query):\n    return query\n"


@pytest.fixture
def catalog_tool_path(tmp_path_factory) -> Path:
    tool_path = tmp_path_factory.mktemp("catalog_tool")
    (tool_path / "tool_data.yaml").write_text(
        "tool-data:\n"
        f'  name: "{CATALOG_TOOL_NAME}"\n'
        '  description: "Catalog description."\n'
        '  args-schema: "args_schema.json"\n'
        '  code-file: "main.py"\n'
        '  entrypoint: "main"\n'
        '  requirements: "requirements.txt"\n',
        encoding="utf-8",
    )
    (tool_path / "args_schema.json").write_text(
        json.dumps(
            {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Text."}},
                "required": ["query"],
            }
        ),
        encoding="utf-8",
    )
    (tool_path / "main.py").write_text(CATALOG_CODE, encoding="utf-8")
    return tool_path


def _tool(name: str, *, built_in: bool, org=None, code: str = "def run(): return 1") -> PythonCodeTool:
    python_code = PythonCode.objects.create(code=code, entrypoint="run", global_kwargs={})
    return PythonCodeTool.objects.create(
        name=name,
        description="Own description.",
        variables=[],
        python_code=python_code,
        built_in=built_in,
        org=org,
    )


def _upload(catalog_tool_path: Path) -> None:
    with patch(
        "tables.management.commands.upload_tools.get_all_tool_paths",
        return_value=[catalog_tool_path],
    ):
        upload_tools()


@pytest.mark.django_db
def test_org_tools_named_like_a_new_catalog_tool_keep_their_content_and_a_built_in_is_created(
    acme, beta, catalog_tool_path
):
    org_tools = [
        _tool(CATALOG_TOOL_NAME, built_in=False, org=org, code=f"def run(): return '{org.name}'")
        for org in (acme, beta)
    ]

    _upload(catalog_tool_path)

    for org_tool in org_tools:
        stored = PythonCodeTool.objects.select_related("python_code").get(id=org_tool.id)
        assert stored.built_in is False
        assert stored.org_id == org_tool.org_id
        assert stored.description == "Own description."
        assert stored.variables == []
        assert stored.use_storage is False
        assert stored.python_code.code == org_tool.python_code.code
        assert stored.python_code.entrypoint == "run"

    built_in = PythonCodeTool.objects.select_related("python_code").get(
        name=CATALOG_TOOL_NAME, built_in=True
    )
    assert built_in.org_id is None
    assert built_in.description == "Catalog description."
    assert built_in.python_code.code == CATALOG_CODE
    assert built_in.python_code.entrypoint == "main"


@pytest.mark.django_db
def test_existing_built_in_tool_is_updated_in_place(acme, catalog_tool_path):
    built_in = _tool(CATALOG_TOOL_NAME, built_in=True)
    _tool(CATALOG_TOOL_NAME, built_in=False, org=acme)

    _upload(catalog_tool_path)

    stored = PythonCodeTool.objects.select_related("python_code").get(
        name=CATALOG_TOOL_NAME, built_in=True
    )
    assert stored.id == built_in.id
    assert stored.description == "Catalog description."
    assert stored.python_code.code == CATALOG_CODE
    assert [variable["name"] for variable in stored.variables] == ["query"]
