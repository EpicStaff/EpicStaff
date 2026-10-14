"""Rules carried by the storage-scoped models; plain fields and defaults are not retested."""

import pytest
from shared.models.storage_scope import StorageCredentials
from shared.models.tools import CodeTaskData

CODE_TASK = {
    "venv_name": "test-venv",
    "libraries": ["lib1", "lib2"],
    "code": "print('hello')",
    "execution_id": "exec-123",
    "entrypoint": "main",
}


@pytest.mark.parametrize(
    ("credentials", "credentials_shown"),
    [(StorageCredentials(access_key="secret-access-key", secret_key="secret-key-value"), "present"), (None, "none")],
)
def test_log_summary_names_what_a_task_carries_but_never_a_secret(credentials, credentials_shown):
    task = CodeTaskData(**CODE_TASK, storage_credentials=credentials, secrets={"DBPASS": "very-secret-password"})

    summary = task.log_summary()

    assert "secret-key-value" not in summary
    assert "very-secret-password" not in summary
    for shown in ("exec-123", "test-venv", "main", "libraries=2", "secrets=1", f"storage_credentials={credentials_shown}"):
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
