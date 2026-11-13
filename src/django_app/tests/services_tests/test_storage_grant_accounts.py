"""A run's temporary storage accounts follow the storage grants of its nodes.

Exercised through the real services and database; only the storage backend's admin API
is replaced (FakeStorageGateway). The policy is what enforces a grant, so it is what is
asserted.
"""

import itertools
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from src.shared.models.graph_nodes import (
    EndNodeData,
    GraphData,
    PythonNodeData,
    SubGraphData,
)
from src.shared.models.sessions import SessionData
from src.shared.models.storage_scope import StorageAction, StorageGrant, storage_account_key
from src.shared.models.tools import PythonCodeData
from storage_credentials.models import TemporaryStorageAccount
from storage_credentials.services.session_credential_service import session_credential_service
from tables.models import Graph, Session

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


def _issue(session, org, grants, **graph_fields):
    return session_credential_service.issue_session_accounts(
        session_data=_session_data(session, org, grants, **graph_fields),
        session_orm=session,
        org=org,
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
def test_a_run_gives_a_node_exactly_its_grants_actions(
    gateway, acme, session, grant, expected
):
    accounts = _issue(session, acme, [grant])

    assert accounts.default is None
    credentials = accounts.by_grant[storage_account_key(grant, 1)]
    policy = _policy_of(gateway, credentials)
    assert _shared_actions_of(policy, session) == expected
    assert _own_actions_of(policy, session) == [GET, PUT, DELETE]
    assert credentials.shared_actions == [a for a in StorageAction if a in grant.actions]


@pytest.mark.django_db
def test_a_node_granted_nothing_gets_its_own_folder_only(gateway, acme, session):
    accounts = _issue(session, acme, [StorageGrant()])

    policy = _policy_of(gateway, accounts.by_grant["---@1"])
    assert _shared_actions_of(policy, session) is None
    assert _own_actions_of(policy, session) == [GET, PUT, DELETE]


@pytest.mark.django_db
def test_a_node_with_no_grant_keeps_the_legacy_full_access_in_the_default_account(
    gateway, acme, session
):
    accounts = _issue(session, acme, [None])

    assert accounts.by_grant == {}
    assert _shared_actions_of(_policy_of(gateway, accounts.default), session) == [GET, PUT, DELETE]


@pytest.mark.django_db
def test_ninety_nodes_over_all_combinations_and_no_grant_mint_one_account_per_distinct_action_set(
    gateway, acme, session
):
    grants = [*ALL_GRANTS, None]
    nodes = [grants[index % 9] for index in range(90)]

    accounts = _issue(session, acme, nodes)

    # Eight distinct action sets. The nodes with no grant run with everything, which is
    # exactly what rwd allows, so both share the default account.
    assert len(gateway.created) == 8
    assert TemporaryStorageAccount.objects.filter(session=session).count() == 8
    assert set(accounts.by_grant) == {storage_account_key(grant, 1) for grant in ALL_GRANTS}
    assert accounts.by_grant["rwd@1"] == accounts.default
    for grant in ALL_GRANTS:
        policy = _policy_of(gateway, accounts.by_grant[storage_account_key(grant, 1)])
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
    assert stored[accounts.by_grant["r-d@1"].access_key] == ["read", "delete"]
    assert stored[accounts.default.access_key] == ["read", "write", "delete"]


@pytest.mark.django_db
def test_ninety_nodes_with_one_combination_mint_one_account(gateway, acme, session):
    grant = StorageGrant(read=True, write=True)

    accounts = _issue(session, acme, [grant] * 90)

    assert len(gateway.created) == 1
    assert TemporaryStorageAccount.objects.filter(session=session).count() == 1
    assert list(accounts.by_grant) == [storage_account_key(grant, 1)]


@pytest.mark.django_db
def test_every_account_of_a_session_is_revoked_when_it_ends(gateway, acme, session):
    accounts = _issue(session, acme, [*ALL_GRANTS, None]
    )
    keys = {a.access_key for a in accounts.by_grant.values()} | {accounts.default.access_key}

    session_credential_service.revoke_for_session(session.pk)

    assert set(gateway.deleted) == keys
    assert len(keys) == 8
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
        _issue(session, acme, [StorageGrant(read=True), StorageGrant(write=True)])

    assert gateway.deleted == ["temp-access-1"]
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
            _issue(session, acme, [StorageGrant(read=True), StorageGrant(write=True), StorageGrant(delete=True)],
            )

    # The first has its row (the session's end revokes it); the other two have none.
    assert sorted(gateway.deleted) == ["temp-access-2", "temp-access-3"]
    assert list(TemporaryStorageAccount.objects.values_list("access_key", flat=True)) == [
        "temp-access-1"
    ]


@pytest.mark.django_db
def test_a_session_end_reconciles_the_folders_of_all_its_accounts_once(gateway, acme, session):
    from unittest.mock import MagicMock

    _issue(session, acme, [StorageGrant(), StorageGrant(write=True)],
    )
    reconciler = MagicMock()
    with (
        patch(
            "storage_credentials.services.session_credential_service.StorageReconciler",
            return_value=reconciler,
        ),
        patch("storage_credentials.services.session_credential_service.get_storage_backend"),
    ):
        session_credential_service.revoke_for_session(session.pk)

    # The "---" account was created first and holds only the session's own folder; the
    # attached folder only the "-w-" account could write to must be reconciled as well.
    reconciled = sorted(call.kwargs["prefix"] for call in reconciler.reconcile_tree.call_args_list)
    assert reconciled == ["reports/", f"sessions/{session.pk}/"]
    assert len(gateway.deleted) == 2


def _tool_node_data(org_id: int, session_id: int):
    from src.shared.models.graph_nodes import AgentNodeData
    from src.shared.models.tools import BaseToolData, PythonCodeToolData

    return AgentNodeData(
        node_name="agent",
        input_map={},
        tools=[
            BaseToolData(
                unique_name="python-code-tool:1",
                data=PythonCodeToolData(
                    id=1,
                    name="tool",
                    description="",
                    python_code=PythonCodeData(
                        code="x = 1",
                        entrypoint="main",
                        use_storage=True,
                        storage_allowed_paths=["tool-files/", f"sessions/{session_id}/"],
                        storage_org_prefix=f"org_{org_id}",
                        org_id=org_id,
                    ),
                ),
            )
        ],
    )


def _file_resources(policy: dict) -> set[str]:
    """Every resource an unconditional Allow statement of the policy names."""
    return {
        resource
        for statement in policy["Statement"]
        if statement["Effect"] == "Allow" and "Condition" not in statement
        for resource in statement["Resource"]
    }


@pytest.mark.django_db
def test_the_same_grant_in_two_flows_gets_two_accounts_each_over_its_own_files(
    gateway, acme, session
):
    grant = StorageGrant(read=True, delete=True)
    parent = _session_data(session, acme, [grant])
    child_node = _node("child_node", acme.id, session.pk, grant)
    child_node.python_code.storage_allowed_paths = ["child-files/", f"sessions/{session.pk}/"]
    child = GraphData(
        graph_id=2,
        name="child",
        entrypoint="start",
        end_node=EndNodeData(node_name="end", output_map={}),
        python_node_list=[child_node],
    )
    parent.unique_subgraph_list = [SubGraphData(id=2, data=child)]

    accounts = session_credential_service.issue_session_accounts(
        session_data=parent, session_orm=session, org=acme
    )

    assert set(accounts.by_grant) == {"r-d@1", "r-d@2"}
    parent_files = _file_resources(_policy_of(gateway, accounts.by_grant["r-d@1"]))
    child_files = _file_resources(_policy_of(gateway, accounts.by_grant["r-d@2"]))
    assert any("reports" in resource for resource in parent_files)
    assert not any("child-files" in resource for resource in parent_files)
    assert any("child-files" in resource for resource in child_files)
    assert not any("reports" in resource for resource in child_files)


@pytest.mark.django_db
def test_flows_attaching_the_same_files_with_the_same_grant_share_one_account(
    gateway, acme, session
):
    grant = StorageGrant(read=True)
    parent = _session_data(session, acme, [grant])
    child_node = _node("child_node", acme.id, session.pk, grant)
    child = GraphData(
        graph_id=2,
        name="child",
        entrypoint="start",
        end_node=EndNodeData(node_name="end", output_map={}),
        python_node_list=[child_node],
    )
    parent.unique_subgraph_list = [SubGraphData(id=2, data=child)]

    accounts = session_credential_service.issue_session_accounts(
        session_data=parent, session_orm=session, org=acme
    )

    assert len(gateway.created) == 1
    assert accounts.by_grant["r--@1"] == accounts.by_grant["r--@2"]


@pytest.mark.django_db
def test_the_default_account_covers_only_the_files_of_the_code_without_a_grant(
    gateway, acme, session
):
    session_data = _session_data(
        session, acme, [StorageGrant(read=True)], agent_node_list=[_tool_node_data(acme.id, session.pk)]
    )

    accounts = session_credential_service.issue_session_accounts(
        session_data=session_data, session_orm=session, org=acme
    )

    default_files = _file_resources(_policy_of(gateway, accounts.default))
    granted_files = _file_resources(_policy_of(gateway, accounts.by_grant["r--@1"]))
    assert any("tool-files" in resource for resource in default_files)
    assert not any("reports" in resource for resource in default_files)
    assert any("reports" in resource for resource in granted_files)
    assert not any("tool-files" in resource for resource in granted_files)
    assert accounts.default.shared_actions == list(StorageAction)
