"""Custom library writes recorded as user actions, through the custom library endpoints.

A library lives in the sandbox and only its binding lives here, so, as for a venv, the
record takes its id from the binding (the id the API exposes) and its name from what the
sandbox stored. A wheel has no row here at all: uploading or deleting one is recorded as
an update of its library. The sandbox is the external boundary and the only thing replaced.
"""

from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from proxies.sandbox.models import SandboxCustomLibraryBinding
from rest_framework import status

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

SANDBOX_CLIENT = "proxies.sandbox.services.CustomLibraryService.client_class"
LIBRARIES_URL = "/api/custom-libraries/"


class FakeLibrarySandbox:
    """Holds the libraries it was told about and records every removal."""

    def __init__(self):
        self.libraries: dict[int, dict] = {}
        self.removed: list[str] = []
        self.removed_wheels: list[tuple[str, str]] = []
        self._next_id = 9000

    def __call__(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def create(self, file) -> dict:
        self._next_id += 1
        library = {"id": self._next_id, "name": file.name.split("-", 1)[0]}
        self.libraries[self._next_id] = library
        return library

    def retrieve(self, library_id: str) -> dict:
        return self.libraries[int(library_id)]

    def remove(self, library_id: str) -> None:
        self.removed.append(library_id)
        del self.libraries[int(library_id)]

    def upload_wheel(self, library_id: str, file) -> dict:
        return {"id": 9, "wheel_filename": file.name}

    def remove_wheel(self, library_id: str, wheel_id: str) -> None:
        self.removed_wheels.append((library_id, wheel_id))


class SandboxThatCannotDescribe(FakeLibrarySandbox):
    """A sandbox whose read fails while its writes still work."""

    def retrieve(self, library_id: str) -> dict:
        raise ConnectionError("sandbox read failed")


@pytest.fixture
def sandbox():
    fake = FakeLibrarySandbox()
    with patch(SANDBOX_CLIENT, fake):
        yield fake


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _upstream_library(sandbox, org, *, name="mylib", library_id=4711):
    """A library the sandbox already has, bound to `org` under an id that is not the binding's."""
    sandbox.libraries[library_id] = {"id": library_id, "name": name}
    return SandboxCustomLibraryBinding.objects.create(org_id=org.id, resource_id=str(library_id))


def _wheel() -> SimpleUploadedFile:
    return SimpleUploadedFile(
        "mylib-1.0-py3-none-any.whl", b"PK\x03\x04zip", content_type="application/octet-stream"
    )


def _recorded(events):
    return [
        (event.action, event.target_type, event.target_id, event.target_name, event.route)
        for event in events
    ]


def test_create_records_the_library_once_by_binding_id_and_name(
    admin_client, acme, sandbox, sent_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(LIBRARIES_URL, {"file": _wheel()}, format="multipart")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    binding = SandboxCustomLibraryBinding.objects.get(org=acme)
    assert _recorded(sent_events) == [
        ("created", "custom library", str(binding.pk), "mylib", None)
    ]


def test_delete_records_the_library_once_with_the_name_it_had(
    admin_client, acme, sandbox, sent_events, django_capture_on_commit_callbacks
):
    binding = _upstream_library(sandbox, acme)
    binding_id = binding.pk

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.delete(f"{LIBRARIES_URL}{binding_id}/")

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    assert not SandboxCustomLibraryBinding.objects.filter(pk=binding_id).exists()
    assert _recorded(sent_events) == [
        ("deleted", "custom library", str(binding_id), "mylib", None)
    ]


@pytest.mark.parametrize(
    ("method", "suffix", "expected_status"),
    [
        ("post", "wheels/", status.HTTP_201_CREATED),
        ("delete", "wheels/9/", status.HTTP_204_NO_CONTENT),
    ],
    ids=["upload", "delete"],
)
def test_a_wheel_change_records_its_library_once_as_updated(
    method, suffix, expected_status, admin_client, acme, sandbox, sent_events,
    django_capture_on_commit_callbacks,
):
    binding = _upstream_library(sandbox, acme)

    with django_capture_on_commit_callbacks(execute=True):
        response = getattr(admin_client, method)(
            f"{LIBRARIES_URL}{binding.pk}/{suffix}", {"file": _wheel()}, format="multipart"
        )

    assert response.status_code == expected_status, response.content
    assert _recorded(sent_events) == [
        ("updated", "custom library", str(binding.pk), "mylib", None)
    ]


@pytest.mark.parametrize(
    ("suffix", "removed", "removed_wheels", "action"),
    [("", ["4711"], [], "deleted"), ("wheels/9/", [], [("4711", "9")], "updated")],
    ids=["library delete", "wheel delete"],
)
def test_a_delete_still_happens_and_is_recorded_when_the_name_cannot_be_read(
    suffix, removed, removed_wheels, action, admin_client, acme, sent_events,
    django_capture_on_commit_callbacks,
):
    sandbox = SandboxThatCannotDescribe()
    binding = _upstream_library(sandbox, acme)
    binding_id = binding.pk

    with patch(SANDBOX_CLIENT, sandbox), django_capture_on_commit_callbacks(execute=True):
        response = admin_client.delete(f"{LIBRARIES_URL}{binding_id}/{suffix}")

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    assert (sandbox.removed, sandbox.removed_wheels) == (removed, removed_wheels)
    assert _recorded(sent_events) == [(action, "custom library", str(binding_id), None, None)]


@pytest.mark.parametrize(
    ("method", "suffix"),
    [("delete", ""), ("post", "wheels/"), ("delete", "wheels/9/")],
    ids=["library delete", "wheel upload", "wheel delete"],
)
def test_a_write_to_another_orgs_library_is_404_and_records_nothing(
    method, suffix, admin_client, beta, sandbox, sent_events, django_capture_on_commit_callbacks
):
    binding = _upstream_library(sandbox, beta)

    with django_capture_on_commit_callbacks(execute=True):
        response = getattr(admin_client, method)(
            f"{LIBRARIES_URL}{binding.pk}/{suffix}", {"file": _wheel()}, format="multipart"
        )

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
    assert (sandbox.removed, sandbox.removed_wheels) == ([], [])
    assert sent_events == []
