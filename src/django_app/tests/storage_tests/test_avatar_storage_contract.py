"""The avatar storage keeps every avatar under `system/` in the bucket and never hands out a URL.

`system/` sits outside every `org_<id>/` prefix, so no organization's scoped storage
credentials reach an avatar, and no avatar name can climb out of it. One suite runs
against the configured AvatarStorage -- its S3 calls answered by botocore's Stubber,
so nothing reaches the network -- and against the in-memory double every other test
uses, so the double cannot drift from the adapter it stands in for.
"""

import pytest
from botocore.stub import Stubber
from django.core.exceptions import SuspiciousOperation
from django.core.files.base import ContentFile
from django.utils.module_loading import import_string

from django_app.settings.storage import STORAGES as CONFIGURED_STORAGES
from rbac.profile.avatar_storage import AvatarStorage
from tables.models.user import User
from tests.avatar_storage_double import InMemoryAvatarStorage

AVATAR_NAME = "avatars/7/0f1e2d3c4b5a69788796a5b4c3d2e1f0.png"


def _configured_avatar_storage():
    """AvatarStorage built from the real settings, with dummy credentials and an unroutable endpoint."""
    config = CONFIGURED_STORAGES["avatars"]
    options = {
        **config["OPTIONS"],
        "access_key": "test-access-key",
        "secret_key": "test-secret-key",
        "endpoint_url": "http://avatar-storage.invalid",
    }
    return import_string(config["BACKEND"])(**options)


class _StubbedS3:
    def __init__(self):
        self.storage = _configured_avatar_storage()
        self.stubber = Stubber(self.storage.connection.meta.client)
        self.stubber.activate()

    def _params(self, name):
        return {"Bucket": self.storage.bucket_name, "Key": f"system/{name}"}

    def expect_missing_object(self, name):
        self.stubber.add_client_error(
            "head_object", service_error_code="404", http_status_code=404, expected_params=self._params(name)
        )

    def expect_existing_object(self, name):
        self.stubber.add_response("head_object", {"ContentLength": 3}, self._params(name))

    def expect_delete(self, name):
        self.stubber.add_response("delete_object", {}, self._params(name))

    def verify(self):
        self.stubber.assert_no_pending_responses()
        self.stubber.deactivate()


class _InMemory:
    def __init__(self):
        self.storage = InMemoryAvatarStorage()

    def expect_missing_object(self, name):
        pass

    def expect_existing_object(self, name):
        self.storage.save(name, ContentFile(b"abc"))

    def expect_delete(self, name):
        pass

    def verify(self):
        pass


@pytest.fixture(params=[_StubbedS3, _InMemory], ids=["avatar-storage-s3", "in-memory-double"])
def backend(request):
    backend = request.param()
    yield backend
    backend.verify()


def test_url_is_refused(backend):
    with pytest.raises(NotImplementedError):
        backend.storage.url(AVATAR_NAME)


def test_opening_a_missing_object_raises_file_not_found(backend):
    backend.expect_missing_object(AVATAR_NAME)

    with pytest.raises(FileNotFoundError):
        backend.storage.open(AVATAR_NAME, "rb")


def test_an_existing_object_is_found(backend):
    backend.expect_existing_object(AVATAR_NAME)

    assert backend.storage.exists(AVATAR_NAME) is True


def test_deleting_a_missing_object_is_not_an_error(backend):
    backend.expect_delete(AVATAR_NAME)

    backend.storage.delete(AVATAR_NAME)


# ---- the adapter only ----


def test_the_test_suite_writes_avatars_to_the_double_not_the_bucket():
    assert isinstance(User._meta.get_field("avatar").storage, InMemoryAvatarStorage)


def test_the_configured_storage_is_the_avatar_storage_under_system():
    storage = _configured_avatar_storage()

    assert isinstance(storage, AvatarStorage)
    assert storage.location == "system"


@pytest.mark.parametrize(
    "escaping_name",
    ["../org_1/secret.txt", "avatars/../../org_1/secret.txt"],
    ids=["parent", "nested-parent"],
)
def test_a_name_cannot_climb_out_of_system(escaping_name):
    storage = _configured_avatar_storage()

    with pytest.raises(SuspiciousOperation):
        storage.exists(escaping_name)
