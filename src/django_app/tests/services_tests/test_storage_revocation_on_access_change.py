"""A temporary storage account carries the FILES permissions of the identity it was minted
for, so changing that identity's access must revoke it. Covers `revoke_for_identity` and
each governance operation that changes access. Real database and services; the storage
backend's admin API is replaced (FakeStorageGateway).
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rbac.governance.api_keys import ApiKeyManagementService
from rbac.governance.memberships import MembershipManagementService
from rbac.governance.roles import RoleManagementService
from rbac.governance.users import UserManagementService
from rbac.identity.api_keys.service import ApiKeyService
from rbac.models import OrganizationUser, Role
from rbac.models.enums import Permission, ResourceType
from storage_credentials.models import TemporaryStorageAccount
from storage_credentials.services.session_credential_service import session_credential_service
from tables.models import Graph, Session

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

from .test_run_code_storage_credentials import GATEWAY_PATH, ORG_CREDENTIALS_PATH, FakeStorageGateway


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
def make_account():
    """Factory -> an account for a session of `org`, issued for a user and/or API key."""

    def _make(
        org, access_key, *, user=None, api_key=None, root_user=None, root_api_key=None
    ) -> TemporaryStorageAccount:
        graph = Graph.objects.create(org=org, name=f"flow-{access_key}")
        session = Session.objects.create(graph=graph, status=Session.SessionStatus.PENDING)
        return TemporaryStorageAccount.objects.create(
            session=session,
            access_key=access_key,
            issued_for_user=user,
            issued_for_api_key=api_key,
            issued_for_root_user=root_user,
            issued_for_root_api_key=root_api_key,
        )

    return _make


def _remaining() -> set[str]:
    return set(TemporaryStorageAccount.objects.values_list("access_key", flat=True))


@pytest.fixture
def run_on_commit(django_capture_on_commit_callbacks):
    """Runs what the governance operation scheduled for after its transaction."""
    return lambda operation: _run(django_capture_on_commit_callbacks, operation)


def _run(capture, operation):
    with capture(execute=True):
        return operation()


# ---- revoke_for_identity ----


@pytest.mark.django_db
def test_revokes_only_the_accounts_of_the_named_identity_in_the_named_org(
    gateway, acme, beta, member_only, admin_acme, make_account, issue_api_key
):
    _, key = issue_api_key(user=member_only, org=acme)
    make_account(acme, "member-acme", user=member_only)
    make_account(acme, "member-key", api_key=key)
    make_account(beta, "member-beta", user=member_only)
    make_account(acme, "admin-acme", user=admin_acme)
    make_account(acme, "nobody")

    session_credential_service.revoke_for_identity(
        org_id=acme.id, user_ids=[member_only.id], api_key_ids=[key.pk]
    )

    assert sorted(gateway.deleted) == ["member-acme", "member-key"]
    assert _remaining() == {"member-beta", "admin-acme", "nobody"}


@pytest.mark.django_db
def test_without_an_org_every_org_of_the_identity_is_revoked(
    gateway, acme, beta, member_only, admin_acme, make_account
):
    make_account(acme, "member-acme", user=member_only)
    make_account(beta, "member-beta", user=member_only)
    make_account(acme, "admin-acme", user=admin_acme)

    session_credential_service.revoke_for_identity(org_id=None, user_ids=[member_only.id])

    assert sorted(gateway.deleted) == ["member-acme", "member-beta"]
    assert _remaining() == {"admin-acme"}


@pytest.mark.django_db
def test_a_failed_revocation_keeps_the_row_for_the_cleanup_job(
    gateway, acme, member_only, make_account
):
    gateway.delete_error = RuntimeError("storage backend down")
    make_account(acme, "member-acme", user=member_only)

    session_credential_service.revoke_for_identity(org_id=acme.id, user_ids=[member_only.id])

    assert _remaining() == {"member-acme"}


@pytest.mark.django_db
def test_no_identity_revokes_nothing(gateway, acme, make_account):
    make_account(acme, "nobody")

    session_credential_service.revoke_for_identity(org_id=acme.id)

    assert _remaining() == {"nobody"}
    assert gateway.deleted == []


# ---- governance operations ----


@pytest.mark.django_db
def test_changing_a_members_role_revokes_their_accounts_and_their_keys_accounts(
    gateway, run_on_commit, acme, admin_acme, member_only, role_viewer, make_account, issue_api_key
):
    _, key = issue_api_key(user=member_only, org=acme)
    make_account(acme, "member-user", user=member_only)
    make_account(acme, "member-key", api_key=key)
    make_account(acme, "admin-user", user=admin_acme)
    membership = OrganizationUser.objects.get(user=member_only, org=acme)

    run_on_commit(
        lambda: MembershipManagementService().change_role(
            actor=admin_acme, membership_id=membership.pk, role_id=role_viewer.pk
        )
    )

    assert sorted(gateway.deleted) == ["member-key", "member-user"]
    assert _remaining() == {"admin-user"}


@pytest.mark.django_db
def test_assigning_the_role_a_member_already_has_revokes_nothing(
    gateway, run_on_commit, acme, admin_acme, member_only, role_member, make_account
):
    make_account(acme, "member-user", user=member_only)
    membership = OrganizationUser.objects.get(user=member_only, org=acme)

    run_on_commit(
        lambda: MembershipManagementService().change_role(
            actor=admin_acme, membership_id=membership.pk, role_id=role_member.pk
        )
    )

    assert _remaining() == {"member-user"}


@pytest.mark.django_db
def test_removing_a_member_revokes_the_accounts_of_the_user_and_of_the_keys_it_deletes(
    gateway, run_on_commit, acme, beta, admin_acme, member_only, make_account, issue_api_key
):
    _, key = issue_api_key(user=member_only, org=acme)
    make_account(acme, "member-user", user=member_only)
    make_account(acme, "member-key", api_key=key)
    # The same user's account in another org is not touched.
    make_account(beta, "member-beta", user=member_only)
    membership = OrganizationUser.objects.get(user=member_only, org=acme)

    run_on_commit(
        lambda: MembershipManagementService().remove_member(
            actor=admin_acme, membership_id=membership.pk
        )
    )

    assert sorted(gateway.deleted) == ["member-key", "member-user"]
    assert _remaining() == {"member-beta"}


@pytest.mark.django_db
def test_editing_a_roles_permissions_revokes_the_accounts_of_its_members_only(
    gateway, run_on_commit, acme, admin_acme, custom_role_user, make_account
):
    holder = custom_role_user(acme, "holder@example.com", {ResourceType.FILES: Permission.READ})
    other = custom_role_user(acme, "other@example.com", {ResourceType.FILES: Permission.READ})
    role = OrganizationUser.objects.get(user=holder, org=acme).role
    make_account(acme, "holder", user=holder)
    make_account(acme, "other", user=other)

    run_on_commit(
        lambda: RoleManagementService().update_role(
            actor=admin_acme,
            role_id=role.pk,
            changes={"permissions": [{"resource_type": "files", "bitmask": int(Permission.CREATE)}]},
        )
    )

    assert gateway.deleted == ["holder"]
    assert _remaining() == {"other"}


@pytest.mark.django_db
def test_renaming_a_role_revokes_nothing(
    gateway, run_on_commit, acme, admin_acme, custom_role_user, make_account
):
    holder = custom_role_user(acme, "holder@example.com", {ResourceType.FILES: Permission.READ})
    role = OrganizationUser.objects.get(user=holder, org=acme).role
    make_account(acme, "holder", user=holder)

    run_on_commit(
        lambda: RoleManagementService().update_role(
            actor=admin_acme, role_id=role.pk, changes={"name": "renamed"}
        )
    )

    assert _remaining() == {"holder"}


@pytest.mark.django_db
def test_deleting_a_role_revokes_the_accounts_of_everyone_who_held_it(
    gateway, run_on_commit, acme, admin_acme, custom_role_user, make_account
):
    holder = custom_role_user(acme, "holder@example.com", {ResourceType.FILES: Permission.READ})
    role = OrganizationUser.objects.get(user=holder, org=acme).role
    make_account(acme, "holder", user=holder)
    make_account(acme, "admin-user", user=admin_acme)

    run_on_commit(lambda: RoleManagementService().delete_role(actor=admin_acme, role_id=role.pk))

    assert gateway.deleted == ["holder"]
    assert _remaining() == {"admin-user"}
    assert not Role.objects.filter(pk=role.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("operation", ["revoke_key", "delete_key"])
def test_an_admin_revoking_or_deleting_a_key_revokes_the_accounts_issued_for_it(
    gateway, run_on_commit, acme, admin_acme, member_only, make_account, issue_api_key, operation
):
    _, key = issue_api_key(user=member_only, org=acme)
    _, other_key = issue_api_key(user=member_only, org=acme, name="other")
    make_account(acme, "by-key", api_key=key)
    make_account(acme, "by-other-key", api_key=other_key)

    run_on_commit(
        lambda: getattr(ApiKeyManagementService(), operation)(actor=admin_acme, key_id=key.pk)
    )

    assert gateway.deleted == ["by-key"]
    assert _remaining() == {"by-other-key"}


@pytest.mark.django_db
@pytest.mark.parametrize("operation", ["revoke_key", "delete_key"])
def test_an_owner_revoking_or_deleting_their_own_key_revokes_the_accounts_issued_for_it(
    gateway, run_on_commit, acme, member_only, make_account, issue_api_key, operation
):
    _, key = issue_api_key(user=member_only, org=acme)
    make_account(acme, "by-key", api_key=key)

    run_on_commit(lambda: getattr(ApiKeyService(), operation)(member_only, key.pk))

    assert gateway.deleted == ["by-key"]
    assert _remaining() == set()


@pytest.mark.django_db
def test_deactivating_a_user_revokes_their_accounts_in_every_org(
    gateway, run_on_commit, acme, beta, superadmin, member_only, admin_acme, make_account, issue_api_key
):
    _, key = issue_api_key(user=member_only, org=acme)
    make_account(acme, "member-acme", user=member_only)
    make_account(beta, "member-beta", user=member_only)
    make_account(acme, "member-key", api_key=key)
    make_account(acme, "admin-user", user=admin_acme)

    run_on_commit(
        lambda: UserManagementService().set_user_active(
            actor=superadmin, target_user_id=member_only.pk, value=False
        )
    )

    assert sorted(gateway.deleted) == ["member-acme", "member-beta", "member-key"]
    assert _remaining() == {"admin-user"}


@pytest.mark.django_db
def test_reactivating_a_user_revokes_nothing(
    gateway, run_on_commit, acme, superadmin, member_only, make_account
):
    make_account(acme, "member-acme", user=member_only)

    run_on_commit(
        lambda: UserManagementService().set_user_active(
            actor=superadmin, target_user_id=member_only.pk, value=True
        )
    )

    assert _remaining() == {"member-acme"}


@pytest.mark.django_db
def test_a_sub_flow_account_is_revoked_with_either_the_caller_or_the_root_starter(
    gateway, acme, admin_acme, member_only, make_account, issue_api_key
):
    _, tool_key = issue_api_key(user=admin_acme, org=acme)
    _, member_key = issue_api_key(user=member_only, org=acme)
    make_account(acme, "by-root-user", api_key=tool_key, root_user=member_only)
    make_account(acme, "by-root-key", api_key=tool_key, root_api_key=member_key)
    make_account(acme, "unrelated", api_key=tool_key, root_user=admin_acme)

    session_credential_service.revoke_for_identity(org_id=acme.id, user_ids=[member_only.id])
    session_credential_service.revoke_for_identity(org_id=acme.id, api_key_ids=[member_key.pk])

    assert sorted(gateway.deleted) == ["by-root-key", "by-root-user"]
    assert _remaining() == {"unrelated"}


@pytest.mark.django_db
def test_setting_a_password_revokes_the_users_accounts_in_every_org(
    gateway, run_on_commit, acme, beta, member_only, admin_acme, make_account, issue_api_key
):
    from rbac.identity.credential_revocation import CredentialRevocationService

    _, key = issue_api_key(user=member_only, org=acme)
    make_account(acme, "member-acme", user=member_only)
    make_account(beta, "member-beta", user=member_only)
    make_account(acme, "member-key", api_key=key)
    make_account(acme, "admin-user", user=admin_acme)

    run_on_commit(lambda: CredentialRevocationService().revoke_all_credentials_for_user(member_only))

    assert sorted(gateway.deleted) == ["member-acme", "member-beta", "member-key"]
    assert _remaining() == {"admin-user"}


@pytest.mark.django_db
def test_revoking_superadmin_revokes_the_accounts_issued_for_that_user(
    gateway, run_on_commit, acme, superadmin, django_user_model, member_only, make_account
):
    demoted = django_user_model.objects.create_user(
        email="demoted@example.com", password="StrongPass123!", is_superadmin=True
    )
    make_account(acme, "demoted", user=demoted)
    make_account(acme, "member", user=member_only)

    run_on_commit(
        lambda: UserManagementService().revoke_superadmin(
            actor=superadmin, target_user_id=demoted.pk
        )
    )

    assert gateway.deleted == ["demoted"]
    assert _remaining() == {"member"}


@pytest.mark.django_db
def test_deleting_a_user_revokes_the_accounts_issued_for_them_and_their_keys(
    gateway, run_on_commit, acme, superadmin, member_only, admin_acme, make_account, issue_api_key
):
    _, key = issue_api_key(user=member_only, org=acme)
    make_account(acme, "member-user", user=member_only)
    make_account(acme, "member-key", api_key=key)
    make_account(acme, "admin-user", user=admin_acme)

    run_on_commit(
        lambda: UserManagementService().delete_user(
            actor=superadmin,
            target_user_id=member_only.pk,
            verification_phrase=f"delete-{member_only.email}",
        )
    )

    assert sorted(gateway.deleted) == ["member-key", "member-user"]
    assert _remaining() == {"admin-user"}


class _CountingGateway(FakeStorageGateway):
    """A FakeStorageGateway that counts how often a connection is opened and fails chosen keys."""

    def __init__(self, failing_keys=()):
        super().__init__()
        self.connections = 0
        self.failing_keys = set(failing_keys)

    def __call__(self, *args, **kwargs):
        self.connections += 1
        return self

    async def delete_service_account(self, access_key):
        if access_key in self.failing_keys:
            raise RuntimeError("storage backend rejected the delete")
        await super().delete_service_account(access_key)


@pytest.fixture
def counting_gateway():
    def _install(failing_keys=()):
        fake = _CountingGateway(failing_keys)
        patchers = (
            patch(GATEWAY_PATH, fake),
            patch(
                ORG_CREDENTIALS_PATH,
                return_value=SimpleNamespace(access_key="org-access", secret_key="org-secret"),
            ),
        )
        for patcher in patchers:
            patcher.start()
        return fake, patchers

    installed = []

    def install(failing_keys=()):
        fake, patchers = _install(failing_keys)
        installed.append(patchers)
        return fake

    yield install
    for patchers in installed:
        for patcher in patchers:
            patcher.stop()


@pytest.mark.django_db
def test_many_accounts_across_two_orgs_are_revoked_over_one_connection_per_org(
    counting_gateway, acme, beta, member_only, make_account
):
    gateway = counting_gateway()
    for index in range(4):
        make_account(acme, f"acme-{index}", user=member_only)
    for index in range(3):
        make_account(beta, f"beta-{index}", user=member_only)

    session_credential_service.revoke_for_identity(org_id=None, user_ids=[member_only.id])

    assert gateway.connections == 2
    assert len(gateway.deleted) == 7
    assert _remaining() == set()


@pytest.mark.django_db
def test_one_failed_revocation_keeps_only_its_own_row(
    counting_gateway, acme, beta, member_only, make_account
):
    gateway = counting_gateway(failing_keys={"acme-1"})
    make_account(acme, "acme-0", user=member_only)
    make_account(acme, "acme-1", user=member_only)
    make_account(acme, "acme-2", user=member_only)
    make_account(beta, "beta-0", user=member_only)

    session_credential_service.revoke_for_identity(org_id=None, user_ids=[member_only.id])

    assert _remaining() == {"acme-1"}
    assert sorted(gateway.deleted) == ["acme-0", "acme-2", "beta-0"]
