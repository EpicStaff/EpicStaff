"""The sandbox scope of a venv is always the active organization's.

The sandbox knows no organizations, so the gateway sets `scope` from the active
organization, whatever the caller sent. The sandbox is the only thing replaced.
"""

from unittest.mock import patch

import pytest
from proxies.sandbox.models import SandboxVenvBinding
from rbac.models import Organization
from rest_framework import status

from tests.import_export_tests.venv_fakes import SANDBOX_CLIENT, FakeSandbox, upstream_venv


@pytest.fixture
def sandbox():
    fake = FakeSandbox()
    with patch(SANDBOX_CLIENT, fake):
        yield fake


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Org venv names other")


@pytest.mark.django_db
def test_a_new_venv_is_put_in_the_active_orgs_scope(auth_client, default_org, sandbox):
    response = auth_client.post("/api/venvs/", {"name": "data", "libs": []}, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    [venv] = sandbox.venvs.values()
    assert venv["scope"] == str(default_org.id)


@pytest.mark.django_db
def test_a_scope_sent_by_the_caller_is_ignored(auth_client, default_org, other_org, sandbox):
    """Otherwise a caller could file its venv under another org and build that org's
    stored libraries into it."""
    response = auth_client.post(
        "/api/venvs/", {"name": "data", "libs": [], "scope": str(other_org.id)}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED
    [venv] = sandbox.venvs.values()
    assert venv["scope"] == str(default_org.id)


@pytest.mark.django_db
def test_a_rename_cannot_move_a_venv_to_another_scope(
    auth_client, default_org, other_org, sandbox
):
    binding = upstream_venv(sandbox, default_org, name="data", venv_id=4711)

    response = auth_client.patch(
        f"/api/venvs/{binding.pk}/", {"scope": str(other_org.id)}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert "scope" not in sandbox.venvs[4711]
