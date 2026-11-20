"""The venv gateway hands libraries to the sandbox untouched and its refusal back unchanged.

What a library may be is the sandbox's rule, not the gateway's. Only the sandbox
client is replaced; the refusal is raised the way the transport raises a 400.
"""

from unittest.mock import patch

import pytest
from proxies.sandbox.models import SandboxVenvBinding
from rest_framework import status

from tests.import_export_tests.venv_fakes import sandbox_refusal
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

VENV_CLIENT = "proxies.sandbox.services.VenvService.client_class"
REFUSAL = (
    "Version specification '>=1\\n-r /etc/passwd' must not contain whitespace other than "
    "plain spaces: no line breaks, tabs or other space characters."
)


@pytest.fixture
def client(client_as, admin_acme, acme):
    api_client = client_as(admin_acme)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return api_client


@pytest.fixture
def venv_sandbox():
    with patch(VENV_CLIENT) as client_class:
        sandbox = client_class.return_value.__enter__.return_value
        sandbox.retrieve.return_value = {"id": 4711, "name": "data", "libs": []}
        yield sandbox


@pytest.mark.parametrize(
    "libs",
    [
        [{"name": "numpy>=1"}],
        [{"name": "pydantic", "specification": ">=1.0, <2"}],
        [{"name": "numpy>=1\n-r /etc/passwd", "specification": ""}],
    ],
    ids=["bound-in-name", "spaced-specification", "injection"],
)
def test_create_forwards_libraries_exactly_as_written(client, venv_sandbox, libs):
    venv_sandbox.create.return_value = {"id": 4711, "name": "data", "libs": [], "status": "declared"}

    response = client.post("/api/venvs/", {"name": "data", "libs": libs}, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    sent = venv_sandbox.create.call_args.args[0]
    assert (sent["name"], sent["libs"]) == ("data", libs)


def test_create_answers_the_sandbox_refusal_unchanged(client, acme, venv_sandbox):
    venv_sandbox.create.side_effect = sandbox_refusal(REFUSAL)

    response = client.post(
        "/api/venvs/",
        {"name": "data", "libs": [{"name": "numpy>=1\n-r /etc/passwd"}]},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["message"] == REFUSAL
    assert not SandboxVenvBinding.objects.filter(org_id=acme.id).exists()


def test_update_answers_the_sandbox_refusal_unchanged(client, acme, venv_sandbox):
    binding = SandboxVenvBinding.objects.create(org_id=acme.id, resource_id="4711")
    venv_sandbox.update.side_effect = sandbox_refusal(REFUSAL)

    response = client.patch(
        f"/api/venvs/{binding.pk}/",
        {"libs": [{"name": "numpy>=1\n-r /etc/passwd"}]},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["message"] == REFUSAL


def test_update_of_another_orgs_venv_is_not_found_and_never_reaches_the_sandbox(
    client, beta, venv_sandbox
):
    binding = SandboxVenvBinding.objects.create(org_id=beta.id, resource_id="4711")

    response = client.patch(
        f"/api/venvs/{binding.pk}/", {"libs": [{"name": "numpy>=1"}]}, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert venv_sandbox.update.call_count == 0
