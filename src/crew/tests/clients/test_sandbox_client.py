"""SandboxClient: the POST /executions body crew sends to sandbox_new.

sandbox_new no longer mints storage credentials; it rejects an execution that
asks for storage without them, so the body is the contract that has to carry
the credentials django_app minted for the session.
"""

import json

import httpx
import pytest

from clients.http_client import ClientValidationError
from clients.sandbox import SandboxClient
from src.shared.models.storage_scope import StorageCredentials

BASE_URL = "http://sandbox:8000"


def _submit_kwargs(**overrides) -> dict:
    kwargs = dict(
        execution_id="exec-1",
        venv_id=3,
        session_id=42,
        code="def main(**kw): return kw",
        entrypoint="main",
        func_kwargs={"x": 1},
        global_kwargs={"org_id": 7},
        secrets={"DBPASS": "very-secret"},
        use_storage=True,
        storage_allowed_paths=["org_7/session_42/"],
        storage_org_prefix="org_7",
        storage_credentials=StorageCredentials(access_key="AK-TEMP", secret_key="SK-TEMP"),
        timeout=None,
    )
    kwargs.update(overrides)
    return kwargs


async def _submit(**overrides) -> tuple[dict, bytes]:
    """Submit once; return the decoded body and the raw payload sandbox_new received."""
    payloads: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(request.content)
        return httpx.Response(202, json={"execution_id": "exec-1"})

    client = SandboxClient(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    try:
        await client.submit(**_submit_kwargs(**overrides))
    finally:
        await client.aclose()

    (payload,) = payloads
    return json.loads(payload), payload


@pytest.mark.asyncio
async def test_submit_sends_the_whole_execution_including_storage_credentials():
    body, _ = await _submit()

    assert body == {
        "execution_id": "exec-1",
        "venv_id": 3,
        "session_id": 42,
        "code": "def main(**kw): return kw",
        "entrypoint": "main",
        "func_kwargs": {"x": 1},
        "global_kwargs": {"org_id": 7},
        "secrets": {"DBPASS": "very-secret"},
        "use_storage": True,
        "storage_allowed_paths": ["org_7/session_42/"],
        "storage_org_prefix": "org_7",
        "storage_credentials": {"access_key": "AK-TEMP", "secret_key": "SK-TEMP"},
        "timeout": None,
    }


@pytest.mark.asyncio
async def test_submit_sends_null_credentials_when_the_execution_does_not_use_storage():
    body, payload = await _submit(
        use_storage=False,
        storage_allowed_paths=[],
        storage_org_prefix=None,
        storage_credentials=None,
    )

    assert body["storage_credentials"] is None
    assert b'"storage_credentials":null' in payload


@pytest.mark.asyncio
async def test_submit_raises_when_sandbox_new_rejects_the_execution():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="use_storage requires storage_credentials")

    client = SandboxClient(base_url=BASE_URL, transport=httpx.MockTransport(handler))

    with pytest.raises(ClientValidationError, match="use_storage requires storage_credentials"):
        await client.submit(**_submit_kwargs(storage_credentials=None))

    await client.aclose()
