"""Rules carried by the storage-scoped models; plain fields and defaults are not retested."""

import pytest
from shared.models.graph_nodes import GraphData, PythonNodeData
from shared.models.sessions import SessionData
from shared.models.storage_scope import (
    StorageAction,
    StorageCredentials,
    StorageGrant,
    storage_account_key,
)
from shared.models.tools import PythonCodeData
from shared.models.tools import CodeTaskData

CODE_TASK = {
    "code": "print('hello')",
    "execution_id": "exec-123",
    "entrypoint": "main",
}


@pytest.mark.parametrize(
    ("credentials", "credentials_shown"),
    [(StorageCredentials(access_key="secret-access-key", secret_key="secret-key-value"), "present"), (None, "none")],
)
def test_log_summary_names_what_a_task_carries_but_never_a_secret(credentials, credentials_shown):
    task = CodeTaskData(
        **CODE_TASK,
        storage_credentials=credentials,
        secrets={"DBPASS": "very-secret-password"},
        execution_timeout=42,
        venv_id=7,
    )

    summary = task.log_summary()

    assert "secret-key-value" not in summary
    assert "very-secret-password" not in summary
    for shown in (
        "exec-123",
        "venv_id=7",
        "main",
        "execution_timeout=42",
        "secrets=1",
        f"storage_credentials={credentials_shown}",
    ):
        assert shown in summary


@pytest.mark.parametrize(
    "scope",
    [{}, {"org_id": 5}, {"storage_org_prefix": "org_42"}],
    ids=["neither", "no-prefix", "no-org"],
)
def test_a_storage_task_must_name_its_org_and_prefix(scope):
    with pytest.raises(ValueError, match="org_id and storage_org_prefix"):
        CodeTaskData(**CODE_TASK, use_storage=True, storage_allowed_paths=["/data"], **scope)


def test_a_complete_storage_scope_is_accepted():
    task = CodeTaskData(
        **CODE_TASK,
        use_storage=True,
        storage_allowed_paths=["/data"],
        storage_org_prefix="org_42",
        org_id=5,
        storage_credentials=StorageCredentials(access_key="access", secret_key="secret"),
    )

    assert task.use_storage is True


@pytest.mark.parametrize(
    ("grant", "expected_key"),
    [
        (StorageGrant(), "---"),
        (StorageGrant(read=True), "r--"),
        (StorageGrant(write=True), "-w-"),
        (StorageGrant(delete=True), "--d"),
        (StorageGrant(read=True, delete=True), "r-d"),
        (StorageGrant(read=True, write=True, delete=True), "rwd"),
    ],
)
def test_grant_key_names_the_combination(grant, expected_key):
    assert grant.key == expected_key


def test_grant_key_does_not_depend_on_the_order_the_flags_were_given():
    assert (
        StorageGrant(delete=True, read=True).key
        == StorageGrant(read=True, delete=True).key
        == StorageGrant.model_validate({"delete": True, "write": False, "read": True}).key
    )


def test_every_combination_has_its_own_key_and_survives_the_key_round_trip():
    grants = [
        StorageGrant(read=read, write=write, delete=delete)
        for read in (False, True)
        for write in (False, True)
        for delete in (False, True)
    ]

    assert len({grant.key for grant in grants}) == 8
    assert all(StorageGrant.from_key(grant.key) == grant for grant in grants)


def test_account_key_names_the_grant_and_the_flow():
    grant = StorageGrant(read=True, delete=True)

    assert storage_account_key(grant, 7) == "r-d@7"
    assert storage_account_key(grant, 8) != storage_account_key(grant, 7)
    assert storage_account_key(grant, None) == "r-d@None"


def test_grant_actions_are_the_flags_that_are_on():
    assert StorageGrant(read=True, delete=True).actions == {
        StorageAction.READ,
        StorageAction.DELETE,
    }
    assert StorageGrant().actions == frozenset()


def test_grant_round_trips_through_json_inside_the_session_payload():
    session = SessionData(
        id=1,
        org_id=1,
        audit_retention_days=0,
        graph=GraphData(
            name="g",
            python_node_list=[
                PythonNodeData(
                    node_name="n",
                    python_code=PythonCodeData(
                        code="x", entrypoint="main", storage_grant=StorageGrant(write=True)
                    ),
                    input_map={},
                )
            ],
            entrypoint="n",
            end_node=None,
        ),
        storage_credentials_by_grant={
            "-w-": StorageCredentials(access_key="ak", secret_key="sk"),
        },
    )

    restored = SessionData.model_validate_json(session.model_dump_json())

    assert restored.graph.python_node_list[0].python_code.storage_grant == StorageGrant(write=True)
    assert restored.storage_credentials_by_grant["-w-"].access_key == "ak"


def test_a_payload_published_before_grants_existed_is_still_valid():
    old_payload = {
        "id": 1,
        "org_id": 1,
        "audit_retention_days": 0,
        "graph": {
            "name": "g",
            "python_node_list": [
                {
                    "node_name": "n",
                    "python_code": {"code": "x", "entrypoint": "main"},
                    "input_map": {},
                }
            ],
            "agent_node_list": [{"node_name": "agent"}],
            "task_node_list": [{"node_name": "task"}],
            "entrypoint": "n",
            "end_node": None,
        },
    }

    session = SessionData.model_validate(old_payload)

    assert session.storage_credentials_by_grant == {}
    assert session.graph.python_node_list[0].python_code.storage_grant is None
