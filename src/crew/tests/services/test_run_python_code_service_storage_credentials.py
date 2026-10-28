"""Storage credentials are minted by django_app and only passed through by crew.

They ride on SessionData, reach run_code() as an argument and must end up in the
POST /executions body: sandbox_new mints nothing of its own and rejects an
execution that asks for storage without credentials.
"""

import pytest

from src.shared.models.storage_scope import StorageCredentials


@pytest.mark.asyncio
async def test_session_credentials_reach_the_submitted_execution(
    run_code, sandbox, make_python_code_data
):
    credentials = StorageCredentials(access_key="AK-SESSION", secret_key="SK-SESSION")

    await run_code(
        python_code_data=make_python_code_data(
            use_storage=True,
            storage_allowed_paths=["org_7/session_42/"],
            storage_org_prefix="org_7",
            org_id=7,
            session_id=42,
        ),
        inputs={},
        storage_credentials=credentials,
    )

    assert sandbox.submitted["storage_credentials"] == {
        "access_key": "AK-SESSION",
        "secret_key": "SK-SESSION",
    }
    assert sandbox.submitted["use_storage"] is True
    assert sandbox.submitted["storage_allowed_paths"] == ["org_7/session_42/"]
    assert sandbox.submitted["storage_org_prefix"] == "org_7"


@pytest.mark.asyncio
async def test_execution_without_storage_submits_null_credentials(
    run_code, sandbox, make_python_code_data
):
    await run_code(python_code_data=make_python_code_data(), inputs={})

    assert sandbox.submitted["storage_credentials"] is None
    assert sandbox.submitted["use_storage"] is False
