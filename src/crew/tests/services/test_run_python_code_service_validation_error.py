"""An execution sandbox_new rejects must fail the node without leaking its secrets.

The storage scope is validated by sandbox_new now, which answers 400 when an
execution asks for storage it may not have. run_code() turns that rejection into
a returncode-1 result; the stderr it returns and the line it logs both reach
places the execution's `secrets` plaintext and `storage_credentials.secret_key`
must never appear in.
"""

import asyncio

import pytest
from loguru import logger

from src.shared.models.storage_scope import StorageCredentials

SECRET_VALUE = "sk-live-SUPERSECRET-0123456789"
STORAGE_SECRET_KEY = "SK-MINIO-SUPERSECRET-9876543210"
REJECTION = "use_storage requires storage_credentials"


@pytest.fixture
def captured_logs():
    lines: list[str] = []
    sink_id = logger.add(lines.append, level="DEBUG")
    yield lines
    logger.remove(sink_id)


@pytest.mark.asyncio
async def test_rejected_submit_fails_the_execution_without_waiting_for_a_result(
    run_python_code_service, sandbox, make_python_code_data
):
    sandbox.rejects_with = REJECTION

    # No result will ever arrive for a rejected submit, so the call must return
    # now rather than sit out settings.CODE_RESULT_TIMEOUT.
    result = await asyncio.wait_for(
        run_python_code_service.run_code(
            python_code_data=make_python_code_data(use_storage=True, org_id=7),
            inputs={},
            storage_credentials=None,
        ),
        timeout=5,
    )

    assert result["returncode"] == 1
    assert result["result_data"] is None
    assert REJECTION in result["stderr"]
    assert result["execution_id"] == sandbox.submitted["execution_id"]
    assert run_python_code_service._pending_results == {}


@pytest.mark.asyncio
async def test_rejected_submit_keeps_secrets_out_of_stderr_and_logs(
    captured_logs, run_python_code_service, sandbox, make_python_code_data
):
    sandbox.rejects_with = REJECTION

    result = await run_python_code_service.run_code(
        python_code_data=make_python_code_data(
            use_storage=True,
            org_id=7,
            secrets={"MY_SECRET": SECRET_VALUE},
        ),
        inputs={"input_name": "input_value"},
        storage_credentials=StorageCredentials(
            access_key="AK-PUBLIC", secret_key=STORAGE_SECRET_KEY
        ),
    )

    logged = "\n".join(captured_logs)
    for forbidden in (SECRET_VALUE, STORAGE_SECRET_KEY, "MY_SECRET", "input_value"):
        assert forbidden not in result["stderr"]
        assert forbidden not in logged
