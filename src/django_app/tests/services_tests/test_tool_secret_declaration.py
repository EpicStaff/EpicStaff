"""Custom tools abort a session too.

A PythonCodeTool is org-owned rather than graph-owned, so the graph walk cannot
reach it — the converter gates it instead. Both attachment paths are covered
because a configured tool goes through a different converter method.
"""

import pytest

from tables.models import PythonCode, PythonCodeTool, PythonCodeToolConfig
from tables.models.rbac_models import Organization
from tables.services.converter_service import ConverterService
from tables.services.secrets import UndeclaredSecretError, secret_service

DECLARING_CODE = 'def main(**kwargs):\n    return get_secret("TOOL_KEY")\n'


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org ToolDecl")


@pytest.fixture
def secret(org):
    return secret_service.create(text="sk-tool", org=org, name="TOOL_KEY")


def _tool(*, org, declared=None, name="decl tool"):
    python_code = PythonCode.objects.create(code=DECLARING_CODE, entrypoint="main")
    if declared:
        python_code.secrets.set(declared)
    return PythonCodeTool.objects.create(
        name=name,
        description="declares a secret",
        org=org,
        built_in=False,
        python_code=python_code,
    )


@pytest.mark.django_db
class TestDirectlyAttachedTool:
    def test_undeclared_secret_aborts(self, org):
        tool = _tool(org=org)

        with pytest.raises(UndeclaredSecretError) as excinfo:
            ConverterService().convert_python_code_tool_to_pydantic(tool)

        message = str(excinfo.value)
        assert "decl tool" in message
        assert "TOOL_KEY" in message

    def test_a_declared_tool_converts(self, org, secret):
        tool = _tool(org=org, declared=[secret])

        data = ConverterService().convert_python_code_tool_to_pydantic(tool)

        assert data.python_code.secret_names == ["TOOL_KEY"]


@pytest.mark.django_db
class TestConfiguredTool:
    def test_undeclared_secret_aborts_through_a_config_too(self, org):
        """The path that would have been missed: a configured tool goes through a
        different converter method, so gating only the direct one leaves a hole."""
        tool = _tool(org=org, name="configured tool")
        config = PythonCodeToolConfig.objects.create(
            name="cfg", tool=tool, org=org, configuration={}
        )

        with pytest.raises(UndeclaredSecretError) as excinfo:
            ConverterService().convert_python_code_tool_config_to_pydantic(config)

        assert "configured tool" in str(excinfo.value)

    def test_a_declared_configured_tool_converts(self, org, secret):
        tool = _tool(org=org, declared=[secret], name="ok configured tool")
        config = PythonCodeToolConfig.objects.create(
            name="cfg-ok", tool=tool, org=org, configuration={}
        )

        data = ConverterService().convert_python_code_tool_config_to_pydantic(config)

        assert data.python_code.secret_names == ["TOOL_KEY"]
