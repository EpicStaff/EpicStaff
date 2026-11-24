"""A built-in tool runs in the sandbox's `builtin_tools` venv, on every path that runs it.

Built-in tools are owned by no organization, so they have no venv of their own; without
the system venv they land in the sandbox's default venv, which has none of the libraries
they import, and fail with "No module named ...".
"""

import pytest

from tables.models import PythonCode, PythonCodeTool, PythonCodeToolConfig
from tables.services.converter_service import ConverterService
from tables.services.run_python_code_service import RunPythonCodeService


def _tool(*, built_in: bool, org=None) -> PythonCodeTool:
    return PythonCodeTool.objects.create(
        name="built-in-venv-tool",
        description="tool",
        python_code=PythonCode.objects.create(code="def main(): return 1", entrypoint="main"),
        built_in=built_in,
        org=org,
    )


@pytest.mark.django_db
def test_a_built_in_tool_runs_in_the_builtin_tools_venv():
    tool_data = ConverterService().convert_python_code_tool_to_pydantic(_tool(built_in=True))

    assert tool_data.python_code.system_venv == "builtin_tools"
    assert tool_data.python_code.venv_id is None


@pytest.mark.django_db
def test_a_custom_tool_names_no_system_venv(default_org):
    tool_data = ConverterService().convert_python_code_tool_to_pydantic(
        _tool(built_in=False, org=default_org)
    )

    assert tool_data.python_code.system_venv is None


@pytest.mark.django_db
def test_a_configured_built_in_tool_runs_in_the_builtin_tools_venv(default_org):
    tool_config = PythonCodeToolConfig.objects.create(
        name="built-in-venv-config",
        tool=_tool(built_in=True),
        org=default_org,
        configuration={},
    )

    tool_data = ConverterService().convert_python_code_tool_config_to_pydantic(tool_config)

    assert tool_data.python_code.system_venv == "builtin_tools"


@pytest.mark.django_db
@pytest.mark.parametrize(("built_in", "expected"), [(True, "builtin_tools"), (False, None)])
def test_a_test_run_sends_the_tools_system_venv(
    built_in, expected, default_org, regular_user, sandbox_intake
):
    tool = _tool(built_in=built_in, org=None if built_in else default_org)

    RunPythonCodeService().run_code(
        python_code_id=tool.python_code_id,
        varaibles={},
        organization_id=default_org.id,
        user=regular_user,
    )

    (body,) = sandbox_intake.bodies
    assert body["system_venv"] == expected
    assert body["venv_id"] is None
