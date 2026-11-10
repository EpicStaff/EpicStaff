"""An unattended run's temporary storage accounts follow the storage grants of its nodes.

Exercised through the real services and database; only the storage backend's admin API
is replaced (FakeStorageGateway). The policy is what enforces a grant, so it is what is
asserted.
"""

import itertools
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from src.shared.models.graph_nodes import (
    AgentNodeData,
    EndNodeData,
    FileExtractorNodeData,
    GraphData,
    PythonNodeData,
)
from src.shared.models.sessions import SessionData
from src.shared.models.storage_scope import StorageAction, StorageGrant
from src.shared.models.tools import PythonCodeData
from storage_credentials.models import TemporaryStorageAccount
from storage_credentials.services.acting_identity import ActingIdentity
from storage_credentials.services.session_credential_service import session_credential_service
from tables.models import Graph, Session
from tables.models.session_models import SessionPrincipal

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

from .test_run_code_storage_credentials import GATEWAY_PATH, ORG_CREDENTIALS_PATH, FakeStorageGateway

GET, PUT, DELETE = "s3:GetObject", "s3:PutObject", "s3:DeleteObject"
ALL_GRANTS = [
    StorageGrant(read=read, write=write, delete=delete)
    for read, write, delete in itertools.product((False, True), repeat=3)
]


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
def session(acme):
    graph = Graph.objects.create(org=acme, name="flow")
    return Session.objects.create(graph=graph, status=Session.SessionStatus.PENDING)


def _node(name: str, org_id: int, session_id: int, grant: StorageGrant | None) -> PythonNodeData:
    return PythonNodeData(
        node_name=name,
        python_code=PythonCodeData(
            code="x = 1",
            entrypoint="main",
            use_storage=True,
            storage_allowed_paths=["reports/", f"sessions/{session_id}/"],
            storage_org_prefix=f"org_{org_id}",
            org_id=org_id,
            storage_grant=grant,
        ),
        input_map={},
    )


def _session_data(session, org, grants: list[StorageGrant | None], **graph_fields) -> SessionData:
    graph_data = GraphData(
        graph_id=1,
        name="g",
        entrypoint="start",
        end_node=EndNodeData(node_name="end", output_map={}),
        python_node_list=[
            _node(f"node_{index}", org.id, session.pk, grant) for index, grant in enumerate(grants)
        ],
        **graph_fields,
    )
    return SessionData(
        id=session.pk, org_id=org.id, audit_retention_days=0, graph=graph_data
    )


def _issue(session, org, identity, grants, **graph_fields):
    return session_credential_service.issue_session_accounts(
        session_data=_session_data(session, org, grants, **graph_fields),
        session_orm=session,
        org=org,
        acting_identity=identity,
    )


def _shared_actions_of(policy: dict, session) -> list[str] | None:
    """Object actions the policy allows on the attached `reports/` folder, None when it has none."""
    for statement in policy["Statement"]:
        if statement["Effect"] != "Allow" or "Condition" in statement:
            continue
        if any(resource.endswith("/reports/*") for resource in statement["Resource"]):
            return statement["Action"]
    return None


def _own_actions_of(policy: dict, session) -> list[str]:
    for statement in policy["Statement"]:
        if statement["Effect"] == "Allow" and any(
            resource.endswith(f"/sessions/{session.pk}/*") for resource in statement["Resource"]
        ):
            return statement["Action"]
    raise AssertionError("no own-folder statement")


def _policy_of(gateway, credentials) -> dict:
    index = int(credentials.access_key.rsplit("-", 1)[1]) - 1
    return gateway.created[index]["policy"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("grant", "expected"),
    [
        (StorageGrant(read=True), [GET]),
        (StorageGrant(read=True, write=True, delete=True), [GET, PUT, DELETE]),
        (StorageGrant(write=True), [PUT]),
        (StorageGrant(read=True, delete=True), [GET, DELETE]),
    ],
)
def test_a_trigger_run_gives_a_node_exactly_its_grants_actions(
    gateway, acme, session, grant, expected
):
    accounts = _issue(session, acme, ActingIdentity.unattributed(), [grant])

    assert accounts.default is None
    credentials = accounts.by_grant[grant.key]
    policy = _policy_of(gateway, credentials)
    assert _shared_actions_of(policy, session) == expected
    assert _own_actions_of(policy, session) == [GET, PUT, DELETE]
    assert credentials.shared_actions == [a for a in StorageAction if a in grant.actions]


@pytest.mark.django_db
def test_a_node_granted_nothing_gets_its_own_folder_only(gateway, acme, session):
    accounts = _issue(session, acme, ActingIdentity.unattributed(), [StorageGrant()])

    policy = _policy_of(gateway, accounts.by_grant["---"])
    assert _shared_actions_of(policy, session) is None
    assert _own_actions_of(policy, session) == [GET, PUT, DELETE]


@pytest.mark.django_db
def test_a_node_with_no_grant_keeps_the_legacy_full_access_in_the_default_account(
    gateway, acme, session
):
    accounts = _issue(session, acme, ActingIdentity.unattributed(), [None])

    assert accounts.by_grant == {}
    assert _shared_actions_of(_policy_of(gateway, accounts.default), session) == [GET, PUT, DELETE]


@pytest.mark.django_db
def test_an_attended_run_ignores_grants_and_mints_one_account_for_the_identity(
    gateway, acme, session, member_only
):
    accounts = _issue(
        session,
        acme,
        ActingIdentity.for_request(member_only, None),
        [StorageGrant(delete=True), StorageGrant(read=True)],
    )

    assert accounts.by_grant == {}
    assert len(gateway.created) == 1
    assert _shared_actions_of(_policy_of(gateway, accounts.default), session) == [GET, PUT]


@pytest.mark.django_db
def test_a_sub_flow_of_a_trigger_run_gets_its_grant_cut_down_to_the_callers_permissions(
    gateway, acme, session, member_only
):
    root = Session.objects.create(graph=session.graph, status=Session.SessionStatus.PENDING)
    SessionPrincipal.objects.create(session=root, kind=SessionPrincipal.ActionKind.TRIGGER)
    session.parent_session = root
    session.save()
    identity = ActingIdentity.for_sub_flow(member_only, None, root.pk)
    assert identity.trigger_rooted

    accounts = _issue(
        session,
        acme,
        identity,
        [StorageGrant(read=True, write=True, delete=True), StorageGrant(delete=True), None],
    )

    # A member may read and write but not delete: rwd -> rw-, --d -> nothing, and the
    # node with no grant follows the caller alone.
    assert _shared_actions_of(_policy_of(gateway, accounts.by_grant["rwd"]), session) == [GET, PUT]
    assert _shared_actions_of(_policy_of(gateway, accounts.by_grant["--d"]), session) is None
    assert _shared_actions_of(_policy_of(gateway, accounts.default), session) == [GET, PUT]


@pytest.mark.django_db
def test_an_attended_chain_ignores_grants(gateway, acme, session, member_only, admin_acme):
    root = Session.objects.create(graph=session.graph, status=Session.SessionStatus.PENDING)
    SessionPrincipal.objects.create(
        session=root, kind=SessionPrincipal.ActionKind.USER, user=admin_acme
    )
    identity = ActingIdentity.for_sub_flow(member_only, None, root.pk)
    assert not identity.trigger_rooted

    accounts = _issue(session, acme, identity, [StorageGrant(read=True)])

    assert accounts.by_grant == {}
    assert _shared_actions_of(_policy_of(gateway, accounts.default), session) == [GET, PUT]


@pytest.mark.django_db
def test_ninety_nodes_over_all_combinations_and_no_grant_mint_one_account_per_distinct_action_set(
    gateway, acme, session
):
    grants = [*ALL_GRANTS, None]
    nodes = [grants[index % 9] for index in range(90)]

    accounts = _issue(session, acme, ActingIdentity.unattributed(), nodes)

    # Eight distinct action sets. The nodes with no grant run with everything, which is
    # exactly what rwd allows, so both share the default account.
    assert len(gateway.created) == 8
    assert TemporaryStorageAccount.objects.filter(session=session).count() == 8
    assert set(accounts.by_grant) == {grant.key for grant in ALL_GRANTS}
    assert accounts.by_grant["rwd"] == accounts.default
    for grant in ALL_GRANTS:
        policy = _policy_of(gateway, accounts.by_grant[grant.key])
        expected = [
            action
            for action, wanted in zip((GET, PUT, DELETE), (grant.read, grant.write, grant.delete))
            if wanted
        ]
        assert _shared_actions_of(policy, session) == (expected or None)
    assert _shared_actions_of(_policy_of(gateway, accounts.default), session) == [GET, PUT, DELETE]
    stored = {
        account.access_key: account.shared_actions
        for account in TemporaryStorageAccount.objects.filter(session=session)
    }
    assert stored[accounts.by_grant["r-d"].access_key] == ["read", "delete"]
    assert stored[accounts.default.access_key] == ["read", "write", "delete"]


@pytest.mark.django_db
def test_a_default_account_that_cannot_delete_is_shared_with_the_grants_that_end_up_equal(
    gateway, acme, session, member_only
):
    root = Session.objects.create(graph=session.graph, status=Session.SessionStatus.PENDING)
    SessionPrincipal.objects.create(session=root, kind=SessionPrincipal.ActionKind.TRIGGER)
    identity = ActingIdentity.for_sub_flow(member_only, None, root.pk)

    accounts = _issue(
        session, acme, identity, [None, StorageGrant(read=True, write=True), StorageGrant(write=True)]
    )

    # A member may read and write: that is the default account, and rw- equals it.
    assert len(gateway.created) == 2
    assert accounts.by_grant["rw-"] == accounts.default
    assert accounts.by_grant["-w-"] != accounts.default


@pytest.mark.django_db
def test_ninety_nodes_with_one_combination_mint_one_account(gateway, acme, session):
    grant = StorageGrant(read=True, write=True)

    accounts = _issue(session, acme, ActingIdentity.unattributed(), [grant] * 90)

    assert len(gateway.created) == 1
    assert TemporaryStorageAccount.objects.filter(session=session).count() == 1
    assert list(accounts.by_grant) == [grant.key]


@pytest.mark.django_db
def test_grants_the_callers_permissions_make_equal_share_one_account(
    gateway, acme, session, member_only
):
    root = Session.objects.create(graph=session.graph, status=Session.SessionStatus.PENDING)
    SessionPrincipal.objects.create(session=root, kind=SessionPrincipal.ActionKind.TRIGGER)
    identity = ActingIdentity.for_sub_flow(member_only, None, root.pk)

    accounts = _issue(
        session, acme, identity, [StorageGrant(read=True, delete=True), StorageGrant(read=True)]
    )

    assert len(gateway.created) == 1
    assert accounts.by_grant["r-d"] == accounts.by_grant["r--"]


@pytest.mark.django_db
def test_agent_and_file_nodes_count_through_their_own_grants(gateway, acme, session):
    tool_code = PythonCodeData(
        code="x = 1",
        entrypoint="main",
        use_storage=True,
        storage_allowed_paths=["reports/", f"sessions/{session.pk}/"],
        storage_org_prefix=f"org_{acme.id}",
        org_id=acme.id,
    )
    from src.shared.models.tools import BaseToolData, PythonCodeToolData

    agent = AgentNodeData(
        node_name="agent",
        storage_grant=StorageGrant(read=True),
        tools=[
            BaseToolData(
                unique_name="python-code-tool:1",
                data=PythonCodeToolData(
                    id=1, name="t", description="d", python_code=tool_code
                ),
            )
        ],
    )
    extractor = FileExtractorNodeData(
        node_name="extractor",
        input_map={},
        storage_allowed_paths=["reports/", f"sessions/{session.pk}/"],
        storage_org_prefix=f"org_{acme.id}",
        org_id=acme.id,
        storage_grant=StorageGrant(delete=True),
    )
    session_data = _session_data(
        session, acme, [], agent_node_list=[agent], file_extractor_node_list=[extractor]
    )

    accounts = session_credential_service.issue_session_accounts(
        session_data=session_data,
        session_orm=session,
        org=acme,
        acting_identity=ActingIdentity.unattributed(),
    )

    assert set(accounts.by_grant) == {"r--", "--d"}
    assert accounts.default is None


@pytest.mark.django_db
def test_every_account_of_a_session_is_revoked_when_it_ends(gateway, acme, session):
    accounts = _issue(
        session, acme, ActingIdentity.unattributed(), [*ALL_GRANTS, None]
    )
    keys = {a.access_key for a in accounts.by_grant.values()} | {accounts.default.access_key}

    session_credential_service.revoke_for_session(session.pk)

    assert set(gateway.deleted) == keys
    assert len(keys) == 8
    assert not TemporaryStorageAccount.objects.filter(session=session).exists()


@pytest.mark.django_db
def test_unattended_accounts_never_purge_the_storage_bin(gateway, acme, session, admin_acme):
    root = Session.objects.create(graph=session.graph, status=Session.SessionStatus.PENDING)
    SessionPrincipal.objects.create(session=root, kind=SessionPrincipal.ActionKind.TRIGGER)

    _issue(session, acme, ActingIdentity.for_sub_flow(admin_acme, None, root.pk), [StorageGrant(read=True)])

    assert not TemporaryStorageAccount.objects.get(session=session).may_purge_storage_bin


@pytest.mark.django_db
def test_revoking_by_identity_reaches_every_account_of_a_sub_flow_session(
    gateway, acme, session, member_only
):
    root = Session.objects.create(graph=session.graph, status=Session.SessionStatus.PENDING)
    SessionPrincipal.objects.create(session=root, kind=SessionPrincipal.ActionKind.TRIGGER)
    _issue(
        session,
        acme,
        ActingIdentity.for_sub_flow(member_only, None, root.pk),
        [StorageGrant(read=True), StorageGrant(write=True), None],
    )
    assert TemporaryStorageAccount.objects.filter(session=session).count() == 3

    session_credential_service.revoke_for_identity(org_id=acme.id, user_ids=[member_only.pk])

    assert len(gateway.deleted) == 3
    assert not TemporaryStorageAccount.objects.filter(session=session).exists()


@pytest.mark.django_db
def test_a_failed_mint_among_several_revokes_the_ones_that_succeeded(gateway, acme, session):
    from storage_credentials.exceptions import TemporaryCredentialIssueError

    original = gateway.create_service_account

    async def second_mint_fails(**kwargs):
        if len(gateway.created) == 1:
            raise RuntimeError("backend down")
        return await original(**kwargs)

    gateway.create_service_account = second_mint_fails

    with pytest.raises(TemporaryCredentialIssueError):
        _issue(session, acme, ActingIdentity.unattributed(), [StorageGrant(read=True), StorageGrant(write=True)])

    assert gateway.deleted == ["temp-access-1"]
    assert not TemporaryStorageAccount.objects.filter(session=session).exists()


@pytest.mark.django_db
def test_going_over_quota_cuts_off_every_account_of_the_run(gateway, acme, session):
    from storage_credentials.services.run_quota_enforcer import run_quota_enforcer

    accounts = _issue(
        session,
        acme,
        ActingIdentity.unattributed(),
        [StorageGrant(read=True), StorageGrant(write=True), StorageGrant(delete=True)],
    )

    with patch(
        "storage_credentials.services.run_quota_enforcer.is_over_quota", return_value=True
    ):
        run_quota_enforcer.enforce_after_write(
            org_id=acme.id,
            access_key=accounts.by_grant["-w-"].access_key,
            session_id=session.pk,
            execution_id="exec",
        )

    assert set(gateway.deleted) == {a.access_key for a in accounts.by_grant.values()}
    assert not TemporaryStorageAccount.objects.filter(session=session).exists()


@pytest.mark.django_db
def test_every_minted_key_without_a_row_is_revoked_when_persisting_fails(gateway, acme, session):
    from storage_credentials.exceptions import TemporaryCredentialIssueError

    real_create = TemporaryStorageAccount.objects.create
    calls = []

    def second_row_fails(**kwargs):
        calls.append(kwargs["access_key"])
        if len(calls) == 2:
            raise RuntimeError("database down")
        return real_create(**kwargs)

    with patch.object(TemporaryStorageAccount.objects, "create", side_effect=second_row_fails):
        with pytest.raises(TemporaryCredentialIssueError):
            _issue(
                session,
                acme,
                ActingIdentity.unattributed(),
                [StorageGrant(read=True), StorageGrant(write=True), StorageGrant(delete=True)],
            )

    # The first has its row (the session's end revokes it); the other two have none.
    assert sorted(gateway.deleted) == ["temp-access-2", "temp-access-3"]
    assert list(TemporaryStorageAccount.objects.values_list("access_key", flat=True)) == [
        "temp-access-1"
    ]


@pytest.mark.django_db
def test_a_session_end_reconciles_the_folders_of_all_its_accounts_once(gateway, acme, session):
    from unittest.mock import MagicMock

    _issue(
        session,
        acme,
        ActingIdentity.unattributed(),
        [StorageGrant(), StorageGrant(write=True)],
    )
    reconciler = MagicMock()
    with (
        patch(
            "storage_credentials.services.session_credential_service.StorageReconciler",
            return_value=reconciler,
        ),
        patch("storage_credentials.services.session_credential_service.get_storage_backend"),
        patch(
            "storage_credentials.services.session_credential_service.is_over_quota",
            return_value=False,
        ),
    ):
        session_credential_service.revoke_for_session(session.pk)

    # The "---" account was created first and holds only the session's own folder; the
    # attached folder only the "-w-" account could write to must be reconciled as well.
    reconciled = sorted(call.kwargs["prefix"] for call in reconciler.reconcile_tree.call_args_list)
    assert reconciled == ["reports/", f"sessions/{session.pk}/"]
    assert len(gateway.deleted) == 2


@pytest.mark.django_db
def test_revoking_by_identity_reconciles_the_session_union_once(
    gateway, acme, session, member_only
):
    from unittest.mock import MagicMock

    root = Session.objects.create(graph=session.graph, status=Session.SessionStatus.PENDING)
    SessionPrincipal.objects.create(session=root, kind=SessionPrincipal.ActionKind.TRIGGER)
    _issue(
        session,
        acme,
        ActingIdentity.for_sub_flow(member_only, None, root.pk),
        [StorageGrant(), StorageGrant(write=True)],
    )
    reconciler = MagicMock()
    with (
        patch(
            "storage_credentials.services.session_credential_service.StorageReconciler",
            return_value=reconciler,
        ),
        patch("storage_credentials.services.session_credential_service.get_storage_backend"),
        patch(
            "storage_credentials.services.session_credential_service.is_over_quota",
            return_value=False,
        ),
    ):
        session_credential_service.revoke_for_identity(org_id=acme.id, user_ids=[member_only.pk])

    reconciled = sorted(call.kwargs["prefix"] for call in reconciler.reconcile_tree.call_args_list)
    assert reconciled == ["reports/", f"sessions/{session.pk}/"]
