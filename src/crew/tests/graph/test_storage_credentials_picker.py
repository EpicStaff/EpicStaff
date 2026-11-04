import pytest
from services.graph.storage_credentials_picker import pick_storage_credentials
from src.shared.models.storage_scope import StorageCredentials, StorageGrant

DEFAULT = StorageCredentials(access_key="default", secret_key="d")
READ_ACCOUNT = StorageCredentials(access_key="read", secret_key="r")


@pytest.mark.parametrize(
    ("grant", "by_grant", "expected"),
    [
        pytest.param(
            StorageGrant(read=True), {"r--": READ_ACCOUNT}, READ_ACCOUNT, id="grant-with-an-account"
        ),
        pytest.param(None, {"r--": READ_ACCOUNT}, DEFAULT, id="no-grant-takes-the-default"),
        pytest.param(
            StorageGrant(write=True),
            {"r--": READ_ACCOUNT},
            DEFAULT,
            id="grant-nothing-was-minted-for",
        ),
        pytest.param(
            StorageGrant(read=True), {}, DEFAULT, id="attended-run-has-no-accounts-by-grant"
        ),
    ],
)
def test_code_runs_with_its_grants_account_else_the_default(grant, by_grant, expected):
    assert pick_storage_credentials(grant, DEFAULT, by_grant) == expected


def test_nothing_is_picked_when_no_account_was_minted_at_all():
    assert pick_storage_credentials(StorageGrant(read=True), None, {}) is None
