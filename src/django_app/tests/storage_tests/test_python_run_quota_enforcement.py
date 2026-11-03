"""After python code writes past the org's quota, django purges the bin or cuts the run off.

Python writes cannot be refused; django hears of them afterwards through the mutation event.
Once a reported write is confirmed in storage and the org is over its quota: a run acting for
a user holding FILES:DELETE gets the oldest storage bin entries purged, exactly like a UI
upload; if that is not possible or not enough, the run's own temporary account is revoked.
A user's objects are never deleted, and a forged report can neither purge nor revoke.

Real handler, services, quota arithmetic, recycle bin and database; the storage backend is
in memory and the storage admin API is a fake.
"""

import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import fakeredis
import pytest
from django.utils import timezone
from loguru import logger
from rbac.models import ApiKey, OrganizationUser, RolePermission
from rbac.models.enums import Permission, ResourceType
from storage_credentials.models import TemporaryStorageAccount
from storage_credentials.services import run_bin_purge as run_bin_purge_module
from storage_credentials.services import session_credential_service as service_module
from storage_credentials.services.acting_identity import ActingIdentity
from storage_credentials.services.session_credential_service import session_credential_service
from tables.models import Graph, PythonCodeResult, Session, StorageFile
from tables.services import redis_pubsub, storage_service
from tables.services.storage_service.manager import StorageManager
from tables.services.storage_service.quota import org_used_bytes

from storage_credentials.tests.test_revoke_for_owner import realtime_chat  # noqa: F401
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.services_tests.test_run_code_storage_credentials import (
    GATEWAY_PATH,
    ORG_CREDENTIALS_PATH,
    FakeStorageGateway,
)
from tests.services_tests.test_storage_credentials_follow_acting_identity import _session_data
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, seed_file

pytestmark = pytest.mark.django_db

RUN_FOLDER = "test-runs/function-1/"


@pytest.fixture(autouse=True)
def _bucket(settings):
    settings.STORAGE_BUCKET_NAME = "bucket"
    # Minting happens under a quota nobody is near; a test lowers it once the run exists.
    settings.ORG_STORAGE_QUOTA = 10**9


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
def backend():
    return InMemoryStorageBackend(organization_prefix="")


@pytest.fixture
def manager(backend):
    return StorageManager(backend)


@pytest.fixture
def pubsub(monkeypatch, backend):
    monkeypatch.setattr(
        redis_pubsub.RedisPubSub,
        "_create_redis_client",
        lambda self: fakeredis.FakeRedis(decode_responses=True),
    )
    # close_old_connections would drop the test's transactional connection.
    monkeypatch.setattr(redis_pubsub, "close_old_connections", lambda: None)
    shared_manager = StorageManager(backend)
    monkeypatch.setattr(storage_service, "get_storage_manager", lambda: shared_manager)
    monkeypatch.setattr(run_bin_purge_module, "get_storage_manager", lambda: shared_manager)
    monkeypatch.setattr(
        service_module, "get_storage_backend", lambda organization_prefix="": backend
    )
    return redis_pubsub.RedisPubSub()


@pytest.fixture
def log_lines():
    lines: list[str] = []
    sink_id = logger.add(lambda message: lines.append(str(message)), level="INFO")
    yield lines
    logger.remove(sink_id)


def _start_test_run(org, user, execution_id: str) -> str:
    """Mint a test run's account for `user`; returns its access key."""
    result = PythonCodeResult.objects.create(
        execution_id=execution_id, org_id=org.id, status=PythonCodeResult.Status.COMPLETED
    )
    credentials = session_credential_service.issue_for_test_run(
        result,
        [RUN_FOLDER],
        org.id,
        own_paths=[RUN_FOLDER],
        acting_identity=ActingIdentity.for_request(user, None),
    )
    return credentials.access_key


def _start_session_run(org, user) -> tuple[Session, str]:
    session = Session.objects.create(
        graph=Graph.objects.create(org=org, name=f"flow-{Graph.objects.count()}"), status=Session.SessionStatus.PENDING
    )
    credentials = session_credential_service.issue_for_session(
        session_data=_session_data(session.pk, org.id, [f"sessions/{session.pk}/"]),
        session_orm=session,
        org=org,
        acting_identity=ActingIdentity.for_request(user, None),
    )
    return session, credentials.access_key


def _bin_file(manager, org, path: str, size: int, days_ago: int) -> None:
    seed_file(manager._backend, org.id, path, b"x" * size)
    batch = manager.delete(org.id, path, user=None)
    StorageFile.deleted_objects.filter(org=org, soft_delete_batch=batch).update(
        soft_deleted_at=timezone.now() - timedelta(days=days_ago)
    )


def _binned_paths(org) -> set[str]:
    return set(StorageFile.deleted_objects.filter(org=org).values_list("path", flat=True))


def _report_write(
    pubsub,
    org,
    path: str,
    *,
    execution_id: str,
    session_id: int | None = None,
    store: int | None,
    access_key: str | None = None,
) -> None:
    """The mutation event the sandbox publishes for a write; `store` bytes are really stored."""
    if store is not None:
        storage_service.get_storage_manager()._backend.put_bytes(
            f"org_{org.id}/{path}", b"x" * store
        )
    pubsub.storage_mutations_handler(
        {
            "data": json.dumps(
                {
                    "execution_id": execution_id,
                    "org_prefix": f"org_{org.id}",
                    "session_id": session_id,
                    "access_key": access_key,
                    "mutations": [{"op": "write", "path": f"org_{org.id}/{path}"}],
                }
            )
        }
    )


def _account_exists(access_key: str) -> bool:
    return TemporaryStorageAccount.objects.filter(access_key=access_key).exists()


def test_a_user_with_files_delete_gets_the_oldest_bin_entries_purged_and_keeps_the_account(
    pubsub, gateway, manager, acme, admin_acme, settings, log_lines
):
    _bin_file(manager, acme, "oldest.bin", 10, days_ago=3)
    _bin_file(manager, acme, "newer.bin", 10, days_ago=2)
    access_key = _start_test_run(acme, admin_acme, "exec-admin")
    settings.ORG_STORAGE_QUOTA = 30

    # 20 binned + 15 written is 5 over: the oldest entry alone covers that.
    _report_write(pubsub, acme, f"{RUN_FOLDER}out.bin", execution_id="exec-admin", store=15)

    assert _binned_paths(acme) == {"newer.bin"}
    assert StorageFile.objects.filter(org=acme, path=f"{RUN_FOLDER}out.bin", size=15).exists()
    assert org_used_bytes(acme.id) == 25
    assert _account_exists(access_key)
    assert gateway.deleted == []
    purge_logs = [line for line in log_lines if "Purged 1 recycle-bin entries" in line]
    assert purge_logs
    assert "oldest.bin" in purge_logs[0]
    assert "exec-admin" in purge_logs[0]


def test_when_the_whole_bin_is_not_enough_nothing_is_purged_and_the_run_is_revoked(
    pubsub, gateway, manager, acme, admin_acme, settings
):
    _bin_file(manager, acme, "old.bin", 10, days_ago=3)
    access_key = _start_test_run(acme, admin_acme, "exec-big")
    settings.ORG_STORAGE_QUOTA = 30

    _report_write(pubsub, acme, f"{RUN_FOLDER}huge.bin", execution_id="exec-big", store=50)

    assert _binned_paths(acme) == {"old.bin"}
    assert StorageFile.objects.filter(org=acme, path=f"{RUN_FOLDER}huge.bin").exists()
    assert gateway.deleted == [access_key]
    assert not _account_exists(access_key)


def test_a_user_without_files_delete_never_has_the_bin_purged_and_the_run_is_revoked(
    pubsub, gateway, manager, acme, member_only, settings
):
    _bin_file(manager, acme, "old.bin", 100, days_ago=3)
    access_key = _start_test_run(acme, member_only, "exec-member")
    settings.ORG_STORAGE_QUOTA = 110

    _report_write(pubsub, acme, f"{RUN_FOLDER}out.bin", execution_id="exec-member", store=20)

    assert _binned_paths(acme) == {"old.bin"}
    assert gateway.deleted == [access_key]
    assert not _account_exists(access_key)


def test_a_run_with_no_acting_user_is_revoked_without_purging(
    pubsub, gateway, manager, acme, settings
):
    _bin_file(manager, acme, "old.bin", 100, days_ago=3)
    result = PythonCodeResult.objects.create(
        execution_id="exec-trigger", org_id=acme.id, status=PythonCodeResult.Status.COMPLETED
    )
    access_key = session_credential_service.issue_for_test_run(
        result,
        [RUN_FOLDER],
        acme.id,
        own_paths=[RUN_FOLDER],
        acting_identity=ActingIdentity.unattributed(),
    ).access_key
    settings.ORG_STORAGE_QUOTA = 110

    _report_write(pubsub, acme, f"{RUN_FOLDER}out.bin", execution_id="exec-trigger", store=20)

    assert _binned_paths(acme) == {"old.bin"}
    assert not _account_exists(access_key)


def test_a_run_whose_user_lost_files_delete_since_it_began_is_judged_by_the_live_role(
    pubsub, gateway, manager, acme, custom_role_user, settings
):
    user = custom_role_user(
        acme,
        "was-admin@example.com",
        {ResourceType.FILES: Permission.READ | Permission.CREATE | Permission.UPDATE | Permission.DELETE},
    )
    _bin_file(manager, acme, "old.bin", 100, days_ago=3)
    access_key = _start_test_run(acme, user, "exec-demoted")
    settings.ORG_STORAGE_QUOTA = 110
    RolePermission.objects.filter(
        role=OrganizationUser.objects.get(user=user, org=acme).role,
        resource_type=ResourceType.FILES.value,
    ).update(permissions=int(Permission.READ | Permission.CREATE | Permission.UPDATE))

    _report_write(pubsub, acme, f"{RUN_FOLDER}out.bin", execution_id="exec-demoted", store=20)

    assert _binned_paths(acme) == {"old.bin"}
    assert not _account_exists(access_key)


def test_a_forged_report_of_an_object_that_is_not_stored_neither_purges_nor_revokes(
    pubsub, gateway, manager, acme, admin_acme, settings
):
    _bin_file(manager, acme, "old.bin", 10, days_ago=3)
    seed_file(manager._backend, acme.id, "live.bin", b"x" * 40)
    access_key = _start_test_run(acme, admin_acme, "exec-forger")
    settings.ORG_STORAGE_QUOTA = 30

    _report_write(pubsub, acme, f"{RUN_FOLDER}ghost.bin", execution_id="exec-forger", store=None)

    assert _binned_paths(acme) == {"old.bin"}
    assert _account_exists(access_key)
    assert gateway.deleted == []


def test_a_run_inside_the_quota_is_left_alone(pubsub, gateway, manager, acme, member_only, settings):
    _bin_file(manager, acme, "old.bin", 10, days_ago=3)
    access_key = _start_test_run(acme, member_only, "exec-small")
    settings.ORG_STORAGE_QUOTA = 100

    _report_write(pubsub, acme, f"{RUN_FOLDER}out.bin", execution_id="exec-small", store=20)

    assert _binned_paths(acme) == {"old.bin"}
    assert _account_exists(access_key)


def test_a_report_for_one_run_never_revokes_another_runs_account(
    pubsub, gateway, manager, acme, member_only, settings
):
    key_a = _start_test_run(acme, member_only, "exec-a")
    key_b = _start_test_run(acme, member_only, "exec-b")
    settings.ORG_STORAGE_QUOTA = 10

    _report_write(pubsub, acme, f"{RUN_FOLDER}out.bin", execution_id="exec-a", store=20)

    assert gateway.deleted == [key_a]
    assert not _account_exists(key_a)
    assert _account_exists(key_b)


def test_a_report_naming_a_session_revokes_only_that_sessions_account(
    pubsub, gateway, manager, acme, member_only, settings
):
    session_a, key_a = _start_session_run(acme, member_only)
    session_b, key_b = _start_session_run(acme, member_only)
    settings.ORG_STORAGE_QUOTA = 10

    _report_write(
        pubsub,
        acme,
        f"sessions/{session_a.pk}/out.bin",
        execution_id="node-run-1",
        session_id=session_a.pk,
        store=20,
    )

    assert gateway.deleted == [key_a]
    assert _account_exists(key_b)


def test_an_event_of_one_org_never_revokes_the_account_of_a_run_in_another_org(
    pubsub, gateway, manager, acme, beta, member_only, custom_role_user, settings
):
    beta_user = custom_role_user(
        beta,
        "beta-member@example.com",
        {ResourceType.FILES: Permission.READ | Permission.CREATE | Permission.UPDATE},
    )
    beta_key = _start_test_run(beta, beta_user, "exec-beta")
    settings.ORG_STORAGE_QUOTA = 10

    # Acme's write is over quota, and its event names beta's execution id.
    _report_write(pubsub, acme, "stray/out.bin", execution_id="exec-beta", store=20)

    assert gateway.deleted == []
    assert _account_exists(beta_key)


def test_an_event_for_a_run_whose_account_is_already_gone_is_ignored(
    pubsub, gateway, manager, acme, settings
):
    _bin_file(manager, acme, "old.bin", 10, days_ago=3)
    settings.ORG_STORAGE_QUOTA = 5

    _report_write(pubsub, acme, "stray/out.bin", execution_id="exec-finished", store=20)

    assert StorageFile.objects.filter(org=acme, path="stray/out.bin").exists()
    assert _binned_paths(acme) == {"old.bin"}
    assert gateway.deleted == []


def test_a_run_started_by_an_api_key_is_never_purged_for(pubsub, gateway, manager, acme, admin_acme, settings):
    api_key = ApiKey.objects.create(
        name="ci", key_type=ApiKey.KeyType.USER, prefix="es_ci", key_hash="h" * 64, org=acme, created_by=admin_acme
    )
    _bin_file(manager, acme, "old.bin", 100, days_ago=3)
    result = PythonCodeResult.objects.create(
        execution_id="exec-key", org_id=acme.id, status=PythonCodeResult.Status.COMPLETED
    )
    access_key = session_credential_service.issue_for_test_run(
        result,
        [RUN_FOLDER],
        acme.id,
        own_paths=[RUN_FOLDER],
        acting_identity=ActingIdentity.for_request(admin_acme, api_key),
    ).access_key
    settings.ORG_STORAGE_QUOTA = 110

    _report_write(pubsub, acme, f"{RUN_FOLDER}out.bin", execution_id="exec-key", store=20)

    assert _binned_paths(acme) == {"old.bin"}
    assert not _account_exists(access_key)


class _PluginPrincipal:
    """A plugin credential acting for a person: it carries its own permissions."""

    is_plugin_credential = True
    plugin_identifier = "plugin"
    display_name = "plugin"
    rate_limit_key = "plugin"

    def __init__(self, org, person):
        self.pinned_org_id = org.id
        self.person = person

    def resolve_effective_permissions(self, org_id):
        from rbac.access.effective import EffectivePermissions

        return EffectivePermissions(is_superadmin=True, role=None, by_resource={})

    def may_reference_secrets(self, secret_ids):
        return False


def test_a_plugin_run_for_an_admin_is_never_purged_for_though_the_person_is_recorded(
    pubsub, gateway, manager, acme, admin_acme, settings
):
    _bin_file(manager, acme, "old.bin", 100, days_ago=3)
    result = PythonCodeResult.objects.create(
        execution_id="exec-plugin", org_id=acme.id, status=PythonCodeResult.Status.COMPLETED
    )
    credentials = session_credential_service.issue_for_test_run(
        result,
        [RUN_FOLDER],
        acme.id,
        own_paths=[RUN_FOLDER],
        acting_identity=ActingIdentity.for_request(_PluginPrincipal(acme, admin_acme), None),
    )
    account = TemporaryStorageAccount.objects.get(access_key=credentials.access_key)
    assert account.issued_for_user == admin_acme
    assert account.may_purge_storage_bin is False
    settings.ORG_STORAGE_QUOTA = 110

    _report_write(
        pubsub,
        acme,
        f"{RUN_FOLDER}out.bin",
        execution_id="exec-plugin",
        access_key=credentials.access_key,
        store=20,
    )

    assert _binned_paths(acme) == {"old.bin"}
    assert not _account_exists(credentials.access_key)


def _start_realtime_run(org, user, chat) -> str:
    credentials = session_credential_service.issue_for_realtime_chat(
        chat,
        ["docs/"],
        org.id,
        acting_identity=ActingIdentity.for_request(user, None),
    )
    return credentials.access_key


@pytest.fixture
def org(acme):
    """The organization the imported `realtime_chat` fixture builds its agent in."""
    return acme


def test_a_realtime_run_of_an_admin_is_purged_for_by_its_access_key(
    pubsub, gateway, manager, acme, admin_acme, realtime_chat, settings
):
    _bin_file(manager, acme, "old.bin", 10, days_ago=3)
    access_key = _start_realtime_run(acme, admin_acme, realtime_chat)
    settings.ORG_STORAGE_QUOTA = 20

    # The event of a realtime tool call has a random execution id and no session.
    _report_write(
        pubsub,
        acme,
        "docs/out.bin",
        execution_id="random-uuid",
        access_key=access_key,
        store=15,
    )

    assert _binned_paths(acme) == set()
    assert _account_exists(access_key)


def test_a_realtime_run_of_a_member_is_revoked_by_its_access_key(
    pubsub, gateway, manager, acme, member_only, realtime_chat, settings
):
    access_key = _start_realtime_run(acme, member_only, realtime_chat)
    settings.ORG_STORAGE_QUOTA = 10

    _report_write(
        pubsub,
        acme,
        "docs/out.bin",
        execution_id="random-uuid",
        access_key=access_key,
        store=15,
    )

    assert gateway.deleted == [access_key]
    assert not _account_exists(access_key)


def test_an_event_naming_the_access_key_of_another_orgs_account_does_nothing(
    pubsub, gateway, manager, acme, beta, custom_role_user, settings
):
    beta_user = custom_role_user(
        beta,
        "beta-member2@example.com",
        {ResourceType.FILES: Permission.READ | Permission.CREATE | Permission.UPDATE},
    )
    beta_key = _start_test_run(beta, beta_user, "exec-beta-key")
    settings.ORG_STORAGE_QUOTA = 10

    _report_write(
        pubsub,
        acme,
        "stray/out.bin",
        execution_id="exec-beta-key",
        access_key=beta_key,
        store=20,
    )

    assert gateway.deleted == []
    assert _account_exists(beta_key)


def test_a_run_revoked_mid_run_has_its_unreported_writes_indexed_first(
    pubsub, gateway, manager, acme, member_only, settings
):
    access_key = _start_test_run(acme, member_only, "exec-midrun")
    settings.ORG_STORAGE_QUOTA = 10
    # Written with no report at all, as direct boto3 code would.
    storage_service.get_storage_manager()._backend.put_bytes(
        f"org_{acme.id}/{RUN_FOLDER}silent.bin", b"x" * 30
    )

    _report_write(
        pubsub,
        acme,
        f"{RUN_FOLDER}reported.bin",
        execution_id="exec-midrun",
        access_key=access_key,
        store=20,
    )

    assert not _account_exists(access_key)
    indexed = StorageFile.objects.filter(org=acme, item_type="file").values_list("path", flat=True)
    assert set(indexed) == {f"{RUN_FOLDER}reported.bin", f"{RUN_FOLDER}silent.bin"}
