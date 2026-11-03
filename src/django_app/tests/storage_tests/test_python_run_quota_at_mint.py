"""An organization with no storage left gets python-run accounts that cannot write.

Python code writes straight to storage, so the quota can only be enforced by what the
account is allowed to do. Minting looks at the org's free bytes and, when the acting
identity may purge the storage bin, at the bytes that purge would free too. With nothing
to add the policy has no PutObject anywhere, the run's own folders included, but the run
still starts. The credentials also carry the byte counts for the library's friendly limit.

Real services, quota arithmetic and database; only the storage admin API is replaced.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from src.shared.models.storage_scope import StorageAction
from storage_credentials.models import TemporaryStorageAccount
from storage_credentials.services.acting_identity import ActingIdentity
from storage_credentials.services.session_credential_service import session_credential_service
from tables.models import PythonCodeResult
from tables.services.storage_service.manager import StorageManager

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.services_tests.test_run_code_storage_credentials import (
    GATEWAY_PATH,
    ORG_CREDENTIALS_PATH,
    FakeStorageGateway,
)
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, seed_file

pytestmark = pytest.mark.django_db

GET, PUT, DELETE = "s3:GetObject", "s3:PutObject", "s3:DeleteObject"
OWN_FOLDER = "test-runs/function-1/"
SHARED_FOLDER = "reports/"


@pytest.fixture(autouse=True)
def _bucket(settings):
    settings.STORAGE_BUCKET_NAME = "bucket"


@pytest.fixture
def gateway():
    fake = FakeStorageGateway()
    with (
        patch(GATEWAY_PATH, fake),
        patch(
            ORG_CREDENTIALS_PATH,
            return_value=SimpleNamespace(access_key="org-access", secret_key="org-secret"),
        ),
    ):
        yield fake


@pytest.fixture
def manager():
    return StorageManager(InMemoryStorageBackend(organization_prefix=""))


def _binned(manager, org, path: str, size: int) -> None:
    seed_file(manager._backend, org.id, path, b"x" * size)
    manager.delete(org.id, path, user=None)


def _mint(org, identity):
    result = PythonCodeResult.objects.create(
        execution_id="exec-mint", org_id=org.id, status=PythonCodeResult.Status.COMPLETED
    )
    return session_credential_service.issue_for_test_run(
        result,
        [SHARED_FOLDER, OWN_FOLDER],
        org.id,
        own_paths=[OWN_FOLDER],
        acting_identity=identity,
    )


def _allow_actions(policy: dict) -> dict[str, set[str]]:
    """Object actions the policy allows, by folder (org prefix and wildcard stripped)."""
    granted: dict[str, set[str]] = {}
    for statement in policy["Statement"]:
        if statement["Effect"] != "Allow" or "Condition" in statement:
            continue
        if not all(action in (GET, PUT, DELETE) for action in statement["Action"]):
            continue
        for resource in statement["Resource"]:
            folder = resource.removeprefix("arn:aws:s3:::bucket/").split("/", 1)[1]
            granted[folder.removesuffix("*")] = set(statement["Action"])
    return granted


def test_an_org_over_its_quota_gets_no_put_object_on_shared_or_own_folders(
    gateway, acme, admin_acme, manager, settings
):
    seed_file(manager._backend, acme.id, "big.bin", b"x" * 50)
    settings.ORG_STORAGE_QUOTA = 40

    credentials = _mint(acme, ActingIdentity.for_request(admin_acme, None))

    policy = gateway.created[0]["policy"]
    granted = _allow_actions(policy)
    assert granted[SHARED_FOLDER] == {GET, DELETE}
    assert granted[OWN_FOLDER] == {GET, DELETE}
    assert PUT not in {action for actions in granted.values() for action in actions}
    # Same actions on both, so the policy keeps one statement for them and stays compact.
    assert len([s for s in policy["Statement"] if s["Effect"] == "Allow" and GET in s["Action"]]) == 1
    assert (credentials.free_bytes, credentials.purgeable_bytes) == (0, 0)


def test_the_run_still_starts_and_the_library_is_told_why_it_cannot_write(
    gateway, acme, member_only, manager, settings
):
    seed_file(manager._backend, acme.id, "big.bin", b"x" * 50)
    settings.ORG_STORAGE_QUOTA = 40

    credentials = _mint(acme, ActingIdentity.for_request(member_only, None))

    assert TemporaryStorageAccount.objects.filter(access_key=credentials.access_key).exists()
    # The identity's own permissions are untouched, so a refused write reads as a full
    # quota in the library rather than as a missing permission.
    assert StorageAction.WRITE in credentials.shared_actions
    assert (credentials.free_bytes, credentials.purgeable_bytes) == (0, 0)


def test_an_org_exactly_at_its_quota_gets_no_write_access_either(
    gateway, acme, member_only, manager, settings
):
    seed_file(manager._backend, acme.id, "full.bin", b"x" * 40)
    settings.ORG_STORAGE_QUOTA = 40

    _mint(acme, ActingIdentity.for_request(member_only, None))

    assert PUT not in {a for actions in _allow_actions(gateway.created[0]["policy"]).values() for a in actions}


def test_an_identity_that_may_purge_the_bin_keeps_write_access_while_the_bin_has_room(
    gateway, acme, admin_acme, manager, settings
):
    seed_file(manager._backend, acme.id, "live.bin", b"x" * 30)
    _binned(manager, acme, "old.bin", 20)
    settings.ORG_STORAGE_QUOTA = 40

    credentials = _mint(acme, ActingIdentity.for_request(admin_acme, None))

    granted = _allow_actions(gateway.created[0]["policy"])
    assert PUT in granted[SHARED_FOLDER]
    assert PUT in granted[OWN_FOLDER]
    # 50 stored against 40: 10 of the 20 binned bytes only cover the overage.
    assert (credentials.free_bytes, credentials.purgeable_bytes) == (0, 10)


def test_a_bin_that_only_covers_the_overage_leaves_nothing_to_write(
    gateway, acme, admin_acme, manager, settings
):
    seed_file(manager._backend, acme.id, "live.bin", b"x" * 30)
    _binned(manager, acme, "old.bin", 20)
    settings.ORG_STORAGE_QUOTA = 30

    credentials = _mint(acme, ActingIdentity.for_request(admin_acme, None))

    assert PUT not in {a for actions in _allow_actions(gateway.created[0]["policy"]).values() for a in actions}
    assert (credentials.free_bytes, credentials.purgeable_bytes) == (0, 0)


def test_an_identity_without_files_delete_cannot_count_on_the_bin(
    gateway, acme, member_only, manager, settings
):
    seed_file(manager._backend, acme.id, "live.bin", b"x" * 30)
    _binned(manager, acme, "old.bin", 20)
    settings.ORG_STORAGE_QUOTA = 40

    credentials = _mint(acme, ActingIdentity.for_request(member_only, None))

    assert PUT not in {a for actions in _allow_actions(gateway.created[0]["policy"]).values() for a in actions}
    assert (credentials.free_bytes, credentials.purgeable_bytes) == (0, 0)


@pytest.mark.parametrize(
    ("identity_name", "expected_purgeable"), [("admin", 20), ("member", 0), ("unattributed", 0)]
)
def test_free_and_purgeable_bytes_are_filled_for_an_org_with_room(
    gateway, acme, admin_acme, member_only, manager, settings, identity_name, expected_purgeable
):
    seed_file(manager._backend, acme.id, "live.bin", b"x" * 10)
    _binned(manager, acme, "old.bin", 20)
    settings.ORG_STORAGE_QUOTA = 100
    identity = {
        "admin": ActingIdentity.for_request(admin_acme, None),
        "member": ActingIdentity.for_request(member_only, None),
        "unattributed": ActingIdentity.unattributed(),
    }[identity_name]

    credentials = _mint(acme, identity)

    assert credentials.free_bytes == 70
    assert credentials.purgeable_bytes == expected_purgeable
    assert PUT in _allow_actions(gateway.created[0]["policy"])[OWN_FOLDER]


def test_the_account_records_the_granted_paths_without_the_org_prefix(
    gateway, acme, member_only, settings
):
    settings.ORG_STORAGE_QUOTA = 100

    credentials = _mint(acme, ActingIdentity.for_request(member_only, None))

    account = TemporaryStorageAccount.objects.get(access_key=credentials.access_key)
    assert account.granted_folders == [SHARED_FOLDER, OWN_FOLDER]


def test_a_shared_folder_the_identity_cannot_read_is_not_recorded_as_granted(
    gateway, acme, custom_role_user, settings
):
    from rbac.models.enums import Permission, ResourceType

    nothing_on_files = custom_role_user(acme, "no-files@example.com", {ResourceType.FLOWS: Permission.READ})
    settings.ORG_STORAGE_QUOTA = 100

    credentials = _mint(acme, ActingIdentity.for_request(nothing_on_files, None))

    account = TemporaryStorageAccount.objects.get(access_key=credentials.access_key)
    assert account.granted_folders == [OWN_FOLDER]


class TestMayPurgeStorageBin:
    """Who may have the storage bin purged for a run's writes (domain rule)."""

    def test_a_user_with_files_delete_may(self, acme, admin_acme):
        assert ActingIdentity.for_request(admin_acme, None).may_purge_storage_bin(acme.id)

    def test_a_user_without_files_delete_may_not(self, acme, member_only):
        assert not ActingIdentity.for_request(member_only, None).may_purge_storage_bin(acme.id)

    def test_a_run_with_no_identity_may_not(self, acme):
        assert not ActingIdentity.unattributed().may_purge_storage_bin(acme.id)

    def test_a_run_started_with_an_api_key_may_not_even_for_an_admin(self, acme, admin_acme):
        identity = ActingIdentity(principal=admin_acme, api_key=object())

        assert not identity.may_purge_storage_bin(acme.id)

    def test_a_user_in_another_org_may_not(self, beta, admin_acme):
        assert not ActingIdentity.for_request(admin_acme, None).may_purge_storage_bin(beta.id)

    def test_a_sub_flow_is_bounded_by_the_user_who_started_the_root_session(
        self, acme, admin_acme, member_only
    ):
        identity = ActingIdentity(principal=admin_acme, bounded_by=ActingIdentity(principal=member_only))

        assert not identity.may_purge_storage_bin(acme.id)


@pytest.mark.parametrize(("who", "expected"), [("admin", True), ("member", False), ("unattributed", False)])
def test_the_mint_time_purge_decision_is_stored_on_the_account(
    gateway, acme, admin_acme, member_only, settings, who, expected
):
    settings.ORG_STORAGE_QUOTA = 100
    identity = {
        "admin": ActingIdentity.for_request(admin_acme, None),
        "member": ActingIdentity.for_request(member_only, None),
        "unattributed": ActingIdentity.unattributed(),
    }[who]

    credentials = _mint(acme, identity)

    account = TemporaryStorageAccount.objects.get(access_key=credentials.access_key)
    assert account.may_purge_storage_bin is expected


def test_a_plugin_credential_acting_for_an_admin_may_not_purge_the_bin(acme, admin_acme):
    class Plugin:
        is_plugin_credential = True
        pinned_org_id = acme.id
        plugin_identifier = "plugin"
        display_name = "plugin"
        rate_limit_key = "plugin"
        person = admin_acme

        def resolve_effective_permissions(self, org_id):
            from rbac.access.effective import EffectivePermissions

            return EffectivePermissions(is_superadmin=True, role=None, by_resource={})

        def may_reference_secrets(self, secret_ids):
            return False

    identity = ActingIdentity.for_request(Plugin(), None)

    assert identity.recorded_user == admin_acme
    assert not identity.may_purge_storage_bin(acme.id)
