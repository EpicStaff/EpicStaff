"""Temporary storage accounts are narrowed to what the acting identity may do to files.

User code holds the raw keys and can call S3 directly, so the minted policy is the
enforcement point. Exercised through the real services and database; only the storage
backend's admin API is replaced (FakeStorageGateway).
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rbac.models.enums import Permission, ResourceType
from src.shared.models.graph_nodes import EndNodeData, GraphData, PythonNodeData
from src.shared.models.sessions import SessionData
from src.shared.models.storage_scope import StorageAction
from src.shared.models.tools import PythonCodeData
from storage_credentials.exceptions import CredentialScopeValidationError
from storage_credentials.models import TemporaryStorageAccount
from storage_credentials.services.acting_identity import ActingIdentity
from storage_credentials.services.session_credential_service import session_credential_service
from tables.models import Graph, PythonCodeResult, RealtimeAgentChat, Session
from tables.models.session_models import SessionPrincipal

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

from .test_run_code_storage_credentials import GATEWAY_PATH, ORG_CREDENTIALS_PATH, FakeStorageGateway

GET, PUT, DELETE = "s3:GetObject", "s3:PutObject", "s3:DeleteObject"


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


def _session_data(session_id: int, org_id: int, allowed_paths: list[str]) -> SessionData:
    node = PythonNodeData(
        node_name="storage_node",
        python_code=PythonCodeData(
            venv_name="test",
            code="x = 1",
            entrypoint="main",
            libraries=[],
            use_storage=True,
            storage_allowed_paths=allowed_paths,
            storage_org_prefix=f"org_{org_id}",
            org_id=org_id,
        ),
        input_map={},
    )
    graph_data = GraphData(
        graph_id=1,
        name="g",
        entrypoint="start",
        end_node=EndNodeData(node_name="end", output_map={}),
        python_node_list=[node],
    )
    return SessionData(
        id=session_id, org_id=org_id, audit_retention_days=0, graph=graph_data, unique_subgraph_list=[]
    )


def _actions_by_resource(policy: dict) -> dict[str, list[str]]:
    """Object actions the policy allows on each bucket resource."""
    granted: dict[str, list[str]] = {}
    for statement in policy["Statement"]:
        if statement["Effect"] != "Allow" or "Condition" in statement:
            continue
        if not all(action in (GET, PUT, DELETE) for action in statement["Action"]):
            continue
        for resource in statement["Resource"]:
            granted[resource.removeprefix("arn:aws:s3:::bucket/").split("/", 1)[1]] = statement["Action"]
    return granted


@pytest.fixture(autouse=True)
def _bucket(settings):
    settings.STORAGE_BUCKET_NAME = "bucket"


def _issue_for_session(session, org, identity, allowed_paths=("reports/",)):
    return session_credential_service.issue_for_session(
        session_data=_session_data(session.pk, org.id, [*allowed_paths, f"sessions/{session.pk}/"]),
        session_orm=session,
        org=org,
        acting_identity=identity,
    )


# ---- session ----


@pytest.mark.django_db
def test_a_member_cannot_delete_attached_files_but_owns_the_session_folder(
    gateway, acme, session, member_only
):
    credentials = _issue_for_session(session, acme, ActingIdentity.for_request(member_only, None))

    granted = _actions_by_resource(gateway.created[0]["policy"])
    assert granted["reports/*"] == [GET, PUT]
    assert granted[f"sessions/{session.pk}/*"] == [GET, PUT, DELETE]
    assert credentials.shared_actions == [StorageAction.READ, StorageAction.WRITE]
    assert credentials.own_paths == [f"sessions/{session.pk}/"]
    account = TemporaryStorageAccount.objects.get(session=session)
    assert (account.issued_for_user, account.issued_for_api_key) == (member_only, None)


@pytest.mark.django_db
def test_a_viewer_may_only_read_attached_files(gateway, acme, session, django_user_model, role_viewer):
    viewer = django_user_model.objects.create_user(email="viewer@example.com", password="x")
    OrganizationUser.objects.create(user=viewer, org=acme, role=role_viewer)

    credentials = _issue_for_session(session, acme, ActingIdentity.for_request(viewer, None))

    assert _actions_by_resource(gateway.created[0]["policy"])["reports/*"] == [GET]
    assert credentials.shared_actions == [StorageAction.READ]


@pytest.mark.django_db
def test_an_org_admin_may_do_everything(gateway, acme, session, admin_acme):
    credentials = _issue_for_session(session, acme, ActingIdentity.for_request(admin_acme, None))

    assert _actions_by_resource(gateway.created[0]["policy"])["reports/*"] == [GET, PUT, DELETE]
    assert credentials.shared_actions == [StorageAction.READ, StorageAction.WRITE, StorageAction.DELETE]


@pytest.mark.django_db
def test_a_run_started_with_an_api_key_records_the_key_and_uses_its_owners_permissions(
    gateway, acme, session, member_only, issue_api_key
):
    _, key = issue_api_key(user=member_only, org=acme)

    _issue_for_session(session, acme, ActingIdentity.for_request(member_only, key))

    assert _actions_by_resource(gateway.created[0]["policy"])["reports/*"] == [GET, PUT]
    account = TemporaryStorageAccount.objects.get(session=session)
    assert (account.issued_for_user, account.issued_for_api_key) == (None, key)


@pytest.mark.django_db
def test_a_run_with_no_identity_keeps_every_action_and_records_nobody(gateway, acme, session):
    credentials = _issue_for_session(session, acme, ActingIdentity.unattributed())

    assert _actions_by_resource(gateway.created[0]["policy"])["reports/*"] == [GET, PUT, DELETE]
    assert credentials.shared_actions == [StorageAction.READ, StorageAction.WRITE, StorageAction.DELETE]
    account = TemporaryStorageAccount.objects.get(session=session)
    assert (account.issued_for_user, account.issued_for_api_key) == (None, None)


@pytest.mark.django_db
def test_a_user_without_read_loses_the_attached_files_but_the_run_still_starts(
    gateway, acme, session, custom_role_user
):
    user = custom_role_user(acme, "noread@example.com", {ResourceType.FILES: Permission.CREATE})

    credentials = _issue_for_session(session, acme, ActingIdentity.for_request(user, None))

    policy_text = json.dumps(gateway.created[0]["policy"])
    assert "reports" not in policy_text
    assert _actions_by_resource(gateway.created[0]["policy"]) == {
        f"sessions/{session.pk}/*": [GET, PUT, DELETE]
    }
    assert credentials.shared_actions == []
    assert credentials.own_paths == [f"sessions/{session.pk}/"]


@pytest.mark.django_db
def test_a_sub_flow_is_narrowed_to_the_identity_of_the_root_session(
    gateway, acme, session, member_only, admin_acme, issue_api_key
):
    SessionPrincipal.objects.create(
        session=session, kind=SessionPrincipal.ActionKind.USER, user=member_only
    )
    child = Session.objects.create(
        graph=session.graph, status=Session.SessionStatus.PENDING, parent_session=session
    )

    _, admin_key = issue_api_key(user=admin_acme, org=acme)

    credentials = _issue_for_session(
        child, acme, ActingIdentity.for_sub_flow(admin_acme, admin_key, child.parent_session_id)
    )

    # The tool's admin key is bounded by the member who started the root session.
    assert credentials.shared_actions == [StorageAction.READ, StorageAction.WRITE]
    assert credentials.own_paths == [f"sessions/{child.pk}/"]
    account = TemporaryStorageAccount.objects.get(session=child)
    assert (account.issued_for_user, account.issued_for_api_key) == (None, admin_key)
    assert (account.issued_for_root_user, account.issued_for_root_api_key) == (member_only, None)


# ---- test run ----


@pytest.mark.django_db
def test_a_test_run_owns_its_folder_whatever_the_identity_may_do(gateway, acme, member_only):
    result = PythonCodeResult.objects.create(execution_id="exec-1", org=acme)

    credentials = session_credential_service.issue_for_test_run(
        python_code_result=result,
        storage_allowed_paths=["test-runs/exec-1/", "reports/"],
        org_id=acme.id,
        own_paths=["test-runs/exec-1/"],
        acting_identity=ActingIdentity.for_request(member_only, None),
    )

    granted = _actions_by_resource(gateway.created[0]["policy"])
    assert granted["test-runs/exec-1/*"] == [GET, PUT, DELETE]
    assert granted["reports/*"] == [GET, PUT]
    assert credentials.own_paths == ["test-runs/exec-1/"]
    assert TemporaryStorageAccount.objects.get(python_code_result=result).issued_for_user == member_only


# ---- realtime chat ----


@pytest.mark.django_db
def test_a_realtime_chat_gets_only_what_the_identity_may_do(gateway, acme, member_only):
    chat = RealtimeAgentChat.objects.create(connection_key="conn-1")

    credentials = session_credential_service.issue_for_realtime_chat(
        realtime_agent_chat=chat,
        storage_allowed_paths=["reports/"],
        org_id=acme.id,
        acting_identity=ActingIdentity.for_request(member_only, None),
    )

    assert _actions_by_resource(gateway.created[0]["policy"])["reports/*"] == [GET, PUT]
    assert credentials.own_paths == []
    assert TemporaryStorageAccount.objects.get(realtime_agent_chat=chat).issued_for_user == member_only


@pytest.mark.django_db
def test_a_realtime_chat_with_nothing_readable_is_refused_with_a_clear_message(
    gateway, acme, custom_role_user
):
    user = custom_role_user(acme, "norread@example.com", {ResourceType.FILES: Permission.CREATE})
    chat = RealtimeAgentChat.objects.create(connection_key="conn-2")

    with pytest.raises(CredentialScopeValidationError, match="don't have access to the files"):
        session_credential_service.issue_for_realtime_chat(
            realtime_agent_chat=chat,
            storage_allowed_paths=["reports/"],
            org_id=acme.id,
            acting_identity=ActingIdentity.for_request(user, None),
        )

    assert gateway.created == []
    assert not TemporaryStorageAccount.objects.filter(realtime_agent_chat=chat).exists()


# ---- policy size ----


@pytest.mark.django_db
def test_too_many_attached_files_is_refused_before_the_backend_is_called(gateway, acme, session):
    files = [f"attachments/a-long-enough-file-name-{index}.pdf" for index in range(80)]

    with pytest.raises(CredentialScopeValidationError, match="Attach a folder"):
        _issue_for_session(session, acme, ActingIdentity.unattributed(), allowed_paths=files)

    assert gateway.created == []
    assert not TemporaryStorageAccount.objects.filter(session=session).exists()


@pytest.mark.django_db
def test_a_plugin_runs_account_is_recorded_for_its_person(gateway, acme, session, member_only):
    from .test_storage_actions_for_identity import READ_P, _PluginPrincipal

    plugin = _PluginPrincipal(acme.id, READ_P, person=member_only)

    credentials = _issue_for_session(session, acme, ActingIdentity.for_request(plugin, None))

    assert credentials.shared_actions == [StorageAction.READ]
    account = TemporaryStorageAccount.objects.get(session=session)
    assert (account.issued_for_user, account.issued_for_api_key) == (member_only, None)
