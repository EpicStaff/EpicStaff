"""Venv writes recorded as user actions, through the venv endpoints.

A venv lives in the sandbox and only its binding lives here, so the record takes its
id from the binding (the id the API exposes) and its name from what the sandbox
stored. The sandbox is the external boundary and the only thing replaced.
"""

from unittest.mock import patch

import pytest
from proxies.sandbox.models import SandboxVenvBinding
from rest_framework import status

from tests.import_export_tests.venv_fakes import SANDBOX_CLIENT, FakeSandbox, upstream_venv
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

VENVS_URL = "/api/venvs/"


class EditableSandbox(FakeSandbox):
    """A sandbox that also applies changes and forgets what it removes."""

    def update(self, venv_id: str, data: dict) -> dict:
        venv = self.venvs[int(venv_id)]
        venv.update(data)
        return venv

    def remove(self, venv_id: str) -> None:
        super().remove(venv_id)
        del self.venvs[int(venv_id)]


class SandboxThatCannotDescribe(EditableSandbox):
    """A sandbox whose read fails while its delete still works."""

    def retrieve(self, venv_id: str) -> dict:
        raise ConnectionError("sandbox read failed")


@pytest.fixture
def sandbox():
    fake = EditableSandbox()
    with patch(SANDBOX_CLIENT, fake):
        yield fake


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _recorded(events):
    return [
        (event.action, event.target_type, event.target_id, event.target_name, event.route)
        for event in events
    ]


def test_create_records_the_venv_once_by_binding_id_and_name(
    admin_client, acme, sandbox, sent_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(
            VENVS_URL, {"name": "scraper-venv", "libs": []}, format="json"
        )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    binding = SandboxVenvBinding.objects.get(org=acme)
    assert _recorded(sent_events) == [("created", "venv", str(binding.pk), "scraper-venv", None)]


def test_update_records_the_venv_once_under_its_new_name(
    admin_client, acme, sandbox, sent_events, django_capture_on_commit_callbacks
):
    binding = upstream_venv(sandbox, acme, name="scraper-venv", venv_id=4711)

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.patch(
            f"{VENVS_URL}{binding.pk}/", {"name": "crawler-venv"}, format="json"
        )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _recorded(sent_events) == [("updated", "venv", str(binding.pk), "crawler-venv", None)]


def test_delete_records_the_venv_once_with_the_name_it_had(
    admin_client, acme, sandbox, sent_events, django_capture_on_commit_callbacks
):
    binding = upstream_venv(sandbox, acme, name="scraper-venv", venv_id=4711)
    binding_id = binding.pk

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.delete(f"{VENVS_URL}{binding_id}/")

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    assert not SandboxVenvBinding.objects.filter(pk=binding_id).exists()
    assert _recorded(sent_events) == [("deleted", "venv", str(binding_id), "scraper-venv", None)]


def test_delete_still_deletes_and_records_when_the_name_cannot_be_read(
    admin_client, acme, sent_events, django_capture_on_commit_callbacks
):
    sandbox = SandboxThatCannotDescribe()
    binding = upstream_venv(sandbox, acme, venv_id=4711)
    binding_id = binding.pk

    with patch(SANDBOX_CLIENT, sandbox), django_capture_on_commit_callbacks(execute=True):
        response = admin_client.delete(f"{VENVS_URL}{binding_id}/")

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    assert sandbox.removed == ["4711"]
    assert _recorded(sent_events) == [("deleted", "venv", str(binding_id), None, None)]


def test_delete_of_another_orgs_venv_is_404_and_records_nothing(
    admin_client, beta, sandbox, sent_events, django_capture_on_commit_callbacks
):
    binding = upstream_venv(sandbox, beta, venv_id=4711)

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.delete(f"{VENVS_URL}{binding.pk}/")

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
    assert sandbox.removed == []
    assert sent_events == []


@pytest.mark.parametrize("method", ["post", "delete"])
def test_favorite_is_a_personal_mark_and_records_nothing(
    method, admin_client, acme, sandbox, sent_events, django_capture_on_commit_callbacks
):
    binding = upstream_venv(sandbox, acme, venv_id=4711)

    with django_capture_on_commit_callbacks(execute=True):
        response = getattr(admin_client, method)(f"{VENVS_URL}{binding.pk}/favorite/")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert sent_events == []
