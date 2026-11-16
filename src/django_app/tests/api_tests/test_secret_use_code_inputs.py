"""What secret-declaring code runs with needs secrets:USE to change, like the code itself.

A venv's libraries run inside the code's process, and a tool's variable defaults and
its configs' values are merged into the code's globals, so changing any of them for
code that declares a secret is refused without secrets:USE: a 400 naming the field,
as a code edit is. Code that declares nothing changes freely, a resend of the same
value is free, and a binned declared secret still counts. A refused venv change never
reaches the sandbox's update.
"""

from unittest.mock import patch

import pytest
from proxies.sandbox.models import SandboxVenvBinding
from rest_framework import status

from rbac.models.enums import Permission, ResourceType
from tables.models import PythonCode, PythonCodeTool, PythonCodeToolConfig
from tables.services.secrets import secret_service
from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

CLIENT_PATH = "proxies.sandbox.services.VenvService.client_class"
WRITE = Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE
DENIED = '"Use" permission on Secrets'
CODE = 'def main(**kwargs):\n    return get_secret("INPUT_KEY")\n'
PLAIN_CODE = "def main(**kwargs):\n    return 1\n"
STORED_LIBS = [{"name": "requests", "description": "HTTP", "specification": "", "version": "2.32.3"}]
VARIABLES = [{"name": "region", "input_type": "user_input", "type": "string", "default_value": "eu"}]


def _grants(secrets):
    return {
        ResourceType.SECRETS: secrets,
        ResourceType.VENVS: WRITE,
        ResourceType.TOOLS: WRITE,
    }


@pytest.fixture
def no_use_client(custom_role_client, acme):
    return custom_role_client(acme, _grants(Permission.READ), "inputs-no-use")


@pytest.fixture
def use_client(custom_role_client, acme):
    return custom_role_client(acme, _grants(Permission.READ | Permission.USE), "inputs-use")


@pytest.fixture
def secret(acme):
    return secret_service.create(text="sk-inputs", org=acme, name="INPUT_KEY")


@pytest.fixture
def sandbox_client():
    """The upstream sandbox, replaced so no request leaves this process."""
    with patch(CLIENT_PATH) as client_class:
        upstream = client_class.return_value.__enter__.return_value
        upstream.retrieve.return_value = {"id": 4711, "name": "env", "libs": STORED_LIBS}
        upstream.update.side_effect = lambda venv_id, data: {"id": int(venv_id), **data}
        yield upstream


@pytest.fixture
def binding(acme):
    return SandboxVenvBinding.objects.create(org_id=acme.id, resource_id="4711")


def _code(secret=None, **fields):
    python_code = PythonCode.objects.create(code=CODE if secret else PLAIN_CODE, **fields)
    if secret is not None:
        python_code.secrets.set([secret])
    return python_code


def _tool(acme, secret=None, **fields):
    return PythonCodeTool.objects.create(
        name="Inputs tool",
        description="reads a secret",
        python_code=_code(secret),
        variables=VARIABLES,
        org=acme,
        **fields,
    )


def _patch_venv(client, binding, data):
    return client.patch(f"/api/venvs/{binding.pk}/", data, format="json")


def _assert_denied(response, field):
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    message = response.json()["message"]
    assert message.startswith(f"{field}: ") and DENIED in message, message


NEW_LIBS = [{"name": "requests", "specification": "", "version": "2.32.3"}, {"name": "evil-pth"}]


@pytest.mark.django_db
class TestVenvLibraries:
    def test_adding_a_library_without_use_is_refused_before_the_sandbox_update(
        self, no_use_client, binding, secret, sandbox_client
    ):
        _code(secret, venv=binding)

        response = _patch_venv(no_use_client, binding, {"libs": NEW_LIBS})

        _assert_denied(response, "libs")
        sandbox_client.update.assert_not_called()

    def test_with_use_the_libraries_change(self, use_client, binding, secret, sandbox_client):
        _code(secret, venv=binding)

        response = _patch_venv(use_client, binding, {"libs": NEW_LIBS})

        assert response.status_code == status.HTTP_200_OK, response.content
        sandbox_client.update.assert_called_once_with("4711", {"libs": NEW_LIBS})

    def test_a_venv_whose_code_declares_nothing_changes_without_use(
        self, no_use_client, binding, sandbox_client
    ):
        _code(venv=binding)

        response = _patch_venv(no_use_client, binding, {"libs": NEW_LIBS})

        assert response.status_code == status.HTTP_200_OK, response.content
        sandbox_client.retrieve.assert_not_called()

    def test_resending_the_same_libraries_in_another_order_is_free(
        self, no_use_client, binding, secret, sandbox_client
    ):
        """The editor saves name and libraries together: a rename must not need USE."""
        _code(secret, venv=binding)
        sandbox_client.retrieve.return_value["libs"] = [*STORED_LIBS, {"name": "httpx", "specification": "", "version": None}]

        response = _patch_venv(
            no_use_client,
            binding,
            {
                "name": "renamed",
                "libs": [{"name": "httpx"}, {"name": "requests", "version": "2.32.3", "description": "edited"}],
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.content

    def test_renaming_alone_is_free(self, no_use_client, binding, secret, sandbox_client):
        _code(secret, venv=binding)

        response = _patch_venv(no_use_client, binding, {"name": "renamed"})

        assert response.status_code == status.HTTP_200_OK, response.content
        sandbox_client.retrieve.assert_not_called()

    def test_a_binned_secret_and_binned_code_still_count(
        self, no_use_client, binding, secret, sandbox_client
    ):
        """A binned tool's code runs here again once the tool is restored."""
        tool = PythonCodeTool.objects.create(
            name="Binned tool", description="d", python_code=_code(secret, venv=binding), org=binding.org
        )
        tool.delete()
        secret.delete()

        response = _patch_venv(no_use_client, binding, {"libs": NEW_LIBS})

        _assert_denied(response, "libs")
        sandbox_client.update.assert_not_called()

    def test_an_unreadable_libs_payload_is_a_change(self, no_use_client, binding, secret, sandbox_client):
        _code(secret, venv=binding)

        response = _patch_venv(no_use_client, binding, {"libs": "requests"})

        _assert_denied(response, "libs")


def _patch_tool(client, tool, data):
    return client.patch(f"/api/python-code-tool/{tool.pk}/", data, format="json")


CHANGED_VARIABLES = [{**VARIABLES[0], "default_value": "https://attacker.example"}]


@pytest.mark.django_db
class TestToolVariables:
    def test_changing_the_variables_without_use_is_refused(self, no_use_client, acme, secret):
        tool = _tool(acme, secret)

        response = _patch_tool(no_use_client, tool, {"variables": CHANGED_VARIABLES})

        _assert_denied(response, "variables")
        tool.refresh_from_db()
        assert tool.variables == VARIABLES

    def test_with_use_the_variables_change(self, use_client, acme, secret):
        tool = _tool(acme, secret)

        response = _patch_tool(use_client, tool, {"variables": CHANGED_VARIABLES})

        assert response.status_code == status.HTTP_200_OK, response.content
        tool.refresh_from_db()
        assert tool.variables == CHANGED_VARIABLES

    def test_resending_the_same_variables_with_a_rename_is_free(self, no_use_client, acme, secret):
        tool = _tool(acme, secret)

        response = _patch_tool(no_use_client, tool, {"name": "Renamed tool", "variables": VARIABLES})

        assert response.status_code == status.HTTP_200_OK, response.content

    def test_a_tool_whose_code_declares_nothing_changes_without_use(self, no_use_client, acme):
        tool = _tool(acme)

        response = _patch_tool(no_use_client, tool, {"variables": CHANGED_VARIABLES})

        assert response.status_code == status.HTTP_200_OK, response.content

    def test_a_binned_declared_secret_still_counts(self, no_use_client, acme, secret):
        tool = _tool(acme, secret)
        secret.delete()

        response = _patch_tool(no_use_client, tool, {"variables": CHANGED_VARIABLES})

        _assert_denied(response, "variables")


CONFIGS_URL = "/api/python-code-tool-configs/"


def _config(tool, configuration=None):
    return PythonCodeToolConfig.objects.create(
        name="Prod", tool=tool, configuration=configuration or {"region": "eu"}, org=tool.org
    )


@pytest.mark.django_db
class TestToolConfigs:
    def test_creating_a_config_without_use_is_refused(self, no_use_client, acme, secret):
        tool = _tool(acme, secret)

        response = no_use_client.post(
            CONFIGS_URL,
            {"name": "Prod", "tool": tool.pk, "configuration": {"region": "us"}},
            format="json",
        )

        _assert_denied(response, "configuration")
        assert not PythonCodeToolConfig.objects.filter(tool=tool).exists()

    def test_changing_a_config_without_use_is_refused(self, no_use_client, acme, secret):
        config = _config(_tool(acme, secret))

        response = no_use_client.patch(
            f"{CONFIGS_URL}{config.pk}/",
            {"name": "Prod", "tool": config.tool_id, "configuration": {"region": "attacker"}},
            format="json",
        )

        _assert_denied(response, "configuration")
        config.refresh_from_db()
        assert config.configuration == {"region": "eu"}

    def test_with_use_a_config_is_created_and_changed(self, use_client, acme, secret):
        tool = _tool(acme, secret)

        created = use_client.post(
            CONFIGS_URL,
            {"name": "Prod", "tool": tool.pk, "configuration": {"region": "us"}},
            format="json",
        )
        changed = use_client.patch(
            f"{CONFIGS_URL}{created.json()['id']}/",
            {"name": "Prod", "tool": tool.pk, "configuration": {"region": "ap"}},
            format="json",
        )

        assert created.status_code == status.HTTP_201_CREATED, created.content
        assert changed.status_code == status.HTTP_200_OK, changed.content
        assert PythonCodeToolConfig.objects.get(tool=tool).configuration == {"region": "ap"}

    def test_resending_the_same_configuration_with_a_rename_is_free(self, no_use_client, acme, secret):
        config = _config(_tool(acme, secret))

        response = no_use_client.patch(
            f"{CONFIGS_URL}{config.pk}/",
            {"name": "Renamed", "tool": config.tool_id, "configuration": {"region": "eu"}},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.content

    def test_a_tool_whose_code_declares_nothing_is_configured_without_use(self, no_use_client, acme):
        tool = _tool(acme)

        response = no_use_client.post(
            CONFIGS_URL,
            {"name": "Prod", "tool": tool.pk, "configuration": {"region": "us"}},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content

    def test_moving_a_config_to_a_declaring_tool_without_use_is_refused(self, no_use_client, acme, secret):
        config = _config(_tool(acme))
        declaring = PythonCodeTool.objects.create(
            name="Declaring tool", description="d", python_code=_code(secret), variables=VARIABLES, org=acme
        )

        response = no_use_client.patch(
            f"{CONFIGS_URL}{config.pk}/",
            {"name": "Prod", "tool": declaring.pk, "configuration": {"region": "eu"}},
            format="json",
        )

        _assert_denied(response, "configuration")

    def test_a_binned_declared_secret_still_counts(self, no_use_client, acme, secret):
        config = _config(_tool(acme, secret))
        secret.delete()

        response = no_use_client.patch(
            f"{CONFIGS_URL}{config.pk}/",
            {"name": "Prod", "tool": config.tool_id, "configuration": {"region": "attacker"}},
            format="json",
        )

        _assert_denied(response, "configuration")

    def test_deleting_a_config_is_free(self, no_use_client, acme, secret):
        config = _config(_tool(acme, secret))

        response = no_use_client.delete(f"{CONFIGS_URL}{config.pk}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
