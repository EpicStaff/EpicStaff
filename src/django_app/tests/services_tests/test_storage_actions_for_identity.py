"""What a run's code may do to the files attached to it, from the identity that runs it.

Domain rule: FILES permissions -> storage actions (READ needs READ; WRITE needs READ plus
CREATE and UPDATE; DELETE needs READ plus DELETE). Resolved for a real user, API key owner
or inherited sub-flow root through `ActingIdentity`, against the real database.
"""

import pytest
from rbac.access.effective import EffectivePermissions
from rbac.models import ApiKey, OrganizationUser
from rbac.models.enums import Permission, ResourceType
from src.shared.models.storage_scope import StorageAction
from storage_credentials.services.acting_identity import ActingIdentity
from storage_credentials.storage_actions import storage_actions_for
from tables.models import Graph, Session
from tables.models.session_models import SessionPrincipal

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

READ, WRITE, DELETE = StorageAction.READ, StorageAction.WRITE, StorageAction.DELETE
CREATE_P, READ_P, UPDATE_P, DELETE_P = (
    Permission.CREATE,
    Permission.READ,
    Permission.UPDATE,
    Permission.DELETE,
)


def _effective(files_bits: int) -> EffectivePermissions:
    return EffectivePermissions(
        is_superadmin=False, role=None, by_resource={ResourceType.FILES.value: files_bits}
    )


@pytest.mark.parametrize(
    ("files_bits", "expected"),
    [
        (0, set()),
        (READ_P, {READ}),
        (READ_P | CREATE_P, {READ}),
        (READ_P | UPDATE_P, {READ}),
        (READ_P | CREATE_P | UPDATE_P, {READ, WRITE}),
        (READ_P | DELETE_P, {READ, DELETE}),
        (READ_P | CREATE_P | UPDATE_P | DELETE_P, {READ, WRITE, DELETE}),
        # Nothing is allowed without READ, whatever else is held.
        (CREATE_P | UPDATE_P | DELETE_P, set()),
        (CREATE_P, set()),
        (UPDATE_P, set()),
        (DELETE_P, set()),
    ],
    ids=[
        "no-permissions",
        "read",
        "read-create-only",
        "read-update-only",
        "read-create-update",
        "read-delete-without-update",
        "everything",
        "no-read-everything-else",
        "create-only",
        "update-only",
        "delete-only",
    ],
)
def test_storage_actions_follow_the_files_permissions(files_bits, expected):
    assert storage_actions_for(_effective(int(files_bits))) == expected


def test_superadmin_may_do_everything():
    superadmin = EffectivePermissions(is_superadmin=True, role=None)

    assert storage_actions_for(superadmin) == {READ, WRITE, DELETE}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("role_fixture", "expected"),
    [
        ("role_org_admin", {READ, WRITE, DELETE}),
        # A Member holds FILES create/read/update but not delete: the bug this guards.
        ("role_member", {READ, WRITE}),
        ("role_viewer", {READ}),
    ],
)
def test_builtin_roles_resolve_to_their_actions(request, acme, django_user_model, role_fixture, expected):
    user = django_user_model.objects.create_user(email=f"{role_fixture}@example.com", password="x")
    OrganizationUser.objects.create(user=user, org=acme, role=request.getfixturevalue(role_fixture))

    assert ActingIdentity.for_request(user, None).shared_actions(acme.id) == expected


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("files_bits", "expected"),
    [
        (CREATE_P, set()),
        (UPDATE_P, set()),
        (DELETE_P | READ_P, {READ, DELETE}),
        (READ_P | CREATE_P, {READ}),
    ],
    ids=["create-only", "update-only", "delete-without-update", "read-and-create"],
)
def test_custom_roles_resolve_to_their_actions(acme, custom_role_user, files_bits, expected):
    user = custom_role_user(acme, "custom@example.com", {ResourceType.FILES: files_bits})

    assert ActingIdentity.for_request(user, None).shared_actions(acme.id) == expected


@pytest.mark.django_db
def test_a_superadmin_resolves_to_everything_without_a_membership(superadmin, acme):
    assert ActingIdentity.for_request(superadmin, None).shared_actions(acme.id) == {READ, WRITE, DELETE}


@pytest.mark.django_db
def test_a_user_outside_the_org_resolves_to_nothing(member_only, beta):
    assert ActingIdentity.for_request(member_only, None).shared_actions(beta.id) == frozenset()


@pytest.mark.django_db
def test_an_inactive_user_resolves_to_nothing(admin_acme, acme):
    admin_acme.is_active = False
    admin_acme.save()

    assert ActingIdentity.for_request(admin_acme, None).shared_actions(acme.id) == frozenset()


@pytest.mark.django_db
def test_a_run_without_a_user_or_key_keeps_every_action():
    assert ActingIdentity.for_request(None, None).shared_actions(1) == {READ, WRITE, DELETE}


@pytest.mark.django_db
def test_a_user_key_acts_with_its_owners_permissions(member_only, acme, issue_api_key):
    _, key = issue_api_key(user=member_only, org=acme)

    identity = ActingIdentity.for_request(member_only, key)

    assert identity.shared_actions(acme.id) == {READ, WRITE}
    assert identity.api_key == key
    assert identity.recorded_user is None


@pytest.mark.django_db
def test_a_user_run_records_the_user(member_only):
    assert ActingIdentity.for_request(member_only, None).recorded_user == member_only


# ---- the identity of the root session ----


def _session(org, parent=None) -> Session:
    graph = Graph.objects.create(org=org, name=f"g-{Graph.objects.count()}")
    return Session.objects.create(
        graph=graph, status=Session.SessionStatus.PENDING, parent_session=parent
    )


def _principal(session, kind, **fields) -> None:
    SessionPrincipal.objects.create(session=session, kind=kind, **fields)


@pytest.mark.django_db
def test_a_sub_flow_acts_as_whoever_started_the_root_session(acme, member_only, admin_acme):
    root = _session(acme)
    _principal(root, SessionPrincipal.ActionKind.USER, user=member_only)
    child = _session(acme, parent=root)
    # The tool that started the sub-flow used a more privileged key; it must not matter.
    _principal(child, SessionPrincipal.ActionKind.USER, user=admin_acme)
    grandchild = _session(acme, parent=child)

    identity = ActingIdentity.of_root_session(grandchild.pk)

    assert identity.shared_actions(acme.id) == {READ, WRITE}
    assert identity.recorded_user == member_only


@pytest.mark.django_db
def test_a_sub_flow_of_a_user_key_run_inherits_the_key(acme, member_only, issue_api_key):
    _, key = issue_api_key(user=member_only, org=acme)
    root = _session(acme)
    _principal(root, SessionPrincipal.ActionKind.API_KEY_USER, user=member_only, api_key=key)

    identity = ActingIdentity.of_root_session(root.pk)

    assert identity.api_key == key
    assert identity.shared_actions(acme.id) == {READ, WRITE}


@pytest.mark.django_db
def test_a_sub_flow_of_a_system_key_run_may_do_everything(acme, issue_api_key):
    _, system_key = issue_api_key()
    root = _session(acme)
    _principal(root, SessionPrincipal.ActionKind.API_KEY_SYSTEM, api_key=system_key)

    assert ActingIdentity.of_root_session(root.pk).shared_actions(acme.id) == {
        READ,
        WRITE,
        DELETE,
    }


@pytest.mark.django_db
def test_a_sub_flow_of_a_trigger_run_keeps_every_action(acme):
    root = _session(acme)
    _principal(root, SessionPrincipal.ActionKind.TRIGGER)

    assert ActingIdentity.of_root_session(root.pk).shared_actions(acme.id) == {
        READ,
        WRITE,
        DELETE,
    }


@pytest.mark.django_db
@pytest.mark.parametrize("key_state", ["revoked", "deleted"])
def test_a_sub_flow_cannot_inherit_a_key_that_no_longer_works(
    acme, member_only, issue_api_key, key_state
):
    _, key = issue_api_key(user=member_only, org=acme)
    root = _session(acme)
    _principal(root, SessionPrincipal.ActionKind.API_KEY_USER, user=member_only, api_key=key)
    if key_state == "revoked":
        ApiKey.objects.filter(pk=key.pk).update(revoked_at=key.created_at)
    else:
        key.delete()

    assert ActingIdentity.of_root_session(root.pk).shared_actions(acme.id) == frozenset()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "kind", [SessionPrincipal.ActionKind.PLUGIN, SessionPrincipal.ActionKind.UNKNOWN]
)
def test_a_sub_flow_of_an_identity_it_cannot_rebuild_gets_nothing(acme, kind):
    root = _session(acme)
    _principal(root, kind)

    assert ActingIdentity.of_root_session(root.pk).shared_actions(acme.id) == frozenset()


@pytest.mark.django_db
def test_a_sub_flow_whose_root_has_no_principal_gets_nothing(acme):
    root = _session(acme)

    assert ActingIdentity.of_root_session(root.pk).shared_actions(acme.id) == frozenset()


# ---- a sub-flow may do only what both the caller and the root session's starter may do ----


def _started_by(session_org, user, api_key=None):
    root = _session(session_org)
    if api_key is None:
        _principal(root, SessionPrincipal.ActionKind.USER, user=user)
    else:
        _principal(root, SessionPrincipal.ActionKind.API_KEY_USER, user=user, api_key=api_key)
    return root


@pytest.mark.django_db
def test_a_member_naming_an_admins_session_as_parent_gets_the_members_actions(
    acme, admin_acme, member_only
):
    admins_root = _started_by(acme, admin_acme)

    identity = ActingIdentity.for_sub_flow(member_only, None, admins_root.pk)

    assert identity.shared_actions(acme.id) == {READ, WRITE}


@pytest.mark.django_db
def test_an_admin_tool_key_under_a_members_root_gets_the_members_actions(
    acme, admin_acme, member_only, issue_api_key
):
    _, admin_key = issue_api_key(user=admin_acme, org=acme)
    members_root = _started_by(acme, member_only)

    identity = ActingIdentity.for_sub_flow(admin_acme, admin_key, members_root.pk)

    assert identity.shared_actions(acme.id) == {READ, WRITE}


@pytest.mark.django_db
def test_an_admin_tool_key_under_a_viewers_root_may_only_read(
    acme, admin_acme, django_user_model, role_viewer, issue_api_key
):
    viewer = django_user_model.objects.create_user(email="viewer-root@example.com", password="x")
    OrganizationUser.objects.create(user=viewer, org=acme, role=role_viewer)
    _, admin_key = issue_api_key(user=admin_acme, org=acme)
    viewers_root = _started_by(acme, viewer)

    identity = ActingIdentity.for_sub_flow(admin_acme, admin_key, viewers_root.pk)

    assert identity.shared_actions(acme.id) == {READ}


@pytest.mark.django_db
def test_an_admin_under_an_admins_root_may_do_everything(acme, admin_acme):
    admins_root = _started_by(acme, admin_acme)

    identity = ActingIdentity.for_sub_flow(admin_acme, None, admins_root.pk)

    assert identity.shared_actions(acme.id) == {READ, WRITE, DELETE}


@pytest.mark.django_db
def test_under_a_trigger_root_the_callers_own_actions_decide(acme, member_only, issue_api_key):
    _, member_key = issue_api_key(user=member_only, org=acme)
    trigger_root = _session(acme)
    _principal(trigger_root, SessionPrincipal.ActionKind.TRIGGER)

    identity = ActingIdentity.for_sub_flow(member_only, member_key, trigger_root.pk)

    assert identity.shared_actions(acme.id) == {READ, WRITE}


@pytest.mark.django_db
def test_an_admin_under_a_root_that_cannot_be_resolved_gets_nothing(acme, admin_acme):
    root_without_principal = _session(acme)

    identity = ActingIdentity.for_sub_flow(admin_acme, None, root_without_principal.pk)

    assert identity.shared_actions(acme.id) == frozenset()


@pytest.mark.django_db
def test_the_request_identity_is_the_one_recorded(acme, admin_acme, member_only, issue_api_key):
    _, admin_key = issue_api_key(user=admin_acme, org=acme)
    members_root = _started_by(acme, member_only)

    identity = ActingIdentity.for_sub_flow(admin_acme, admin_key, members_root.pk)

    assert identity.api_key == admin_key
    assert identity.recorded_user is None
    assert identity.bounded_by.recorded_user == member_only


# ---- a plugin run is revocable through the person it is made for ----


class _PluginPrincipal:
    """A pinned-org principal as a plugin service account presents itself."""

    is_plugin_credential = True
    plugin_identifier = "weather"
    display_name = "Weather (plugin)"
    rate_limit_key = "plugin-service-account:1"

    def __init__(self, org_id, files_bits, person=None):
        self.pinned_org_id = org_id
        self.person = person
        self._files_bits = files_bits

    def resolve_effective_permissions(self, org_id):
        return _effective(int(self._files_bits))

    def may_reference_secrets(self, secret_ids):
        return False


@pytest.mark.django_db
def test_a_plugin_run_acts_with_the_plugins_access_and_records_its_person(acme, member_only):
    plugin = _PluginPrincipal(acme.id, READ_P, person=member_only)

    identity = ActingIdentity.for_request(plugin, None)

    # Its own declared access decides, not the person's (the Member could also write).
    assert identity.shared_actions(acme.id) == {READ}
    assert identity.recorded_user == member_only


@pytest.mark.django_db
def test_a_plugin_run_without_a_person_records_nobody(acme):
    identity = ActingIdentity.for_request(_PluginPrincipal(acme.id, READ_P), None)

    assert identity.recorded_user is None
