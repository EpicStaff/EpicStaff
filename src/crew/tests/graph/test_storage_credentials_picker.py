import pytest
from services.graph.storage_credentials_picker import pick_storage_credentials
from src.shared.models.storage_scope import StorageCredentials, StorageGrant, storage_account_key

DEFAULT = StorageCredentials(access_key="default", secret_key="d")
READ_ACCOUNT = StorageCredentials(access_key="read", secret_key="r")
READ = StorageGrant(read=True)
READ_IN_FLOW_7 = {storage_account_key(READ, 7): READ_ACCOUNT}


@pytest.mark.parametrize(
    ("grant", "graph_id", "by_grant", "expected"),
    [
        pytest.param(READ, 7, READ_IN_FLOW_7, READ_ACCOUNT, id="grant-with-an-account"),
        pytest.param(None, 7, READ_IN_FLOW_7, DEFAULT, id="no-grant-takes-the-default"),
        pytest.param(StorageGrant(write=True), 7, READ_IN_FLOW_7, None, id="grant-without-account"),
        pytest.param(READ, 8, READ_IN_FLOW_7, None, id="same-grant-in-another-flow"),
        pytest.param(READ, None, {storage_account_key(READ, None): READ_ACCOUNT}, READ_ACCOUNT, id="flow-without-id"),
    ],
)
def test_code_runs_with_its_grants_account_in_its_own_flow(grant, graph_id, by_grant, expected):
    assert pick_storage_credentials(grant, graph_id, DEFAULT, by_grant) == expected


def test_picker_uses_grant_and_graph_key():
    parent_account = StorageCredentials(access_key="parent", secret_key="p")
    child_account = StorageCredentials(access_key="child", secret_key="c")
    by_grant = {
        storage_account_key(READ, 1): parent_account,
        storage_account_key(READ, 2): child_account,
    }

    assert pick_storage_credentials(READ, 1, DEFAULT, by_grant) is parent_account
    assert pick_storage_credentials(READ, 2, DEFAULT, by_grant) is child_account


def test_nothing_is_picked_when_no_account_was_minted_at_all():
    assert pick_storage_credentials(READ, 7, None, {}) is None
