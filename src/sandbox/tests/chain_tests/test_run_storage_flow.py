import pytest
from dynamic_venv_executor_chain import DynamicVenvExecutorChain, AbstractHandler
from services.storage_credential_client import StorageCredentialRequestError
from src.shared.models import CodeResultData


class FakeChain(AbstractHandler):
    def __init__(self):
        self.seen_context = None
        self.raise_exc = None

    async def handle(self, context):
        self.seen_context = context
        if self.raise_exc:
            raise self.raise_exc
        return CodeResultData(execution_id=context["execution_id"], returncode=0)


class FakeStorageCredentialClient:
    """sandbox no longer mints/revokes anything itself; it only asks the
    issuer (django_app) for credentials by execution_id and never sees --
    let alone chooses -- org_id/storage_org_prefix/storage_allowed_paths."""

    def __init__(self, response=None, error=None):
        self.response = response or {
            "access_key": "scoped-ak",
            "secret_key": "scoped-sk",
        }
        self.error = error
        self.requested_execution_ids: list[str] = []

    async def request(self, execution_id: str) -> dict:
        self.requested_execution_ids.append(execution_id)
        if self.error:
            raise self.error
        return self.response


def make_chain(tmp_path, client):
    chain = DynamicVenvExecutorChain(
        output_path=tmp_path / "out",
        base_venv_path=tmp_path / "venvs",
        storage_credential_client=client,
    )
    fake = FakeChain()
    chain.chain = fake
    return chain, fake


COMMON_RUN_KWARGS = dict(
    libraries=[],
    venv_name="v",
    execution_id="exec1",
    code="def main():\n    return 1",
    entrypoint="main",
    func_kwargs={},
)


@pytest.mark.asyncio
async def test_use_storage_true_happy_path(tmp_path):
    client = FakeStorageCredentialClient()
    chain, fake = make_chain(tmp_path, client)

    result = await chain.run(
        **COMMON_RUN_KWARGS,
        use_storage=True,
        storage_org_prefix="org_1",
        storage_allowed_paths=["flowA"],
    )

    assert client.requested_execution_ids == ["exec1"]
    assert fake.seen_context["temp_storage_access_key"] == "scoped-ak"
    assert fake.seen_context["temp_storage_secret_key"] == "scoped-sk"
    assert result.returncode == 0


@pytest.mark.asyncio
async def test_use_storage_false_skips_credentials(tmp_path):
    client = FakeStorageCredentialClient()
    chain, fake = make_chain(tmp_path, client)

    await chain.run(**COMMON_RUN_KWARGS, use_storage=False)

    assert client.requested_execution_ids == []
    assert "temp_storage_access_key" not in (fake.seen_context or {})


@pytest.mark.asyncio
async def test_issue_failure_returns_error_result_fail_closed(tmp_path):
    client = FakeStorageCredentialClient(error=StorageCredentialRequestError("boom"))
    chain, fake = make_chain(tmp_path, client)

    result = await chain.run(
        **COMMON_RUN_KWARGS,
        use_storage=True,
        storage_org_prefix="org_1",
    )

    assert result.returncode == 1
    assert "boom" in result.stderr
    assert fake.seen_context is None


@pytest.mark.asyncio
async def test_issuer_timeout_fails_closed_without_starting_execution(tmp_path):
    """Mirrors the exact message `StorageCredentialClient.request()` raises
    on `asyncio.TimeoutError` (services/storage_credential_client.py) -- the
    issuer never responding within STORAGE_CREDENTIAL_WAIT_TIMEOUT_S must
    fail closed the same way any other StorageCredentialRequestError does."""
    client = FakeStorageCredentialClient(
        error=StorageCredentialRequestError(
            "Timed out waiting for storage credentials (execution_id=exec1)"
        )
    )
    chain, fake = make_chain(tmp_path, client)

    result = await chain.run(
        **COMMON_RUN_KWARGS,
        use_storage=True,
        storage_org_prefix="org_1",
    )

    assert result.returncode == 1
    assert "Timed out waiting for storage credentials" in result.stderr
    assert fake.seen_context is None


@pytest.mark.asyncio
async def test_issuer_reported_error_fails_closed_without_starting_execution(tmp_path):
    """Mirrors the response `{"error": ...}` path in
    `StorageCredentialClient.request()`: the issuer answering with an error
    (e.g. scope_not_published, CredentialScopeValidationError) must fail
    closed exactly like a timeout does -- code execution must not begin."""
    client = FakeStorageCredentialClient(
        error=StorageCredentialRequestError("scope_not_published")
    )
    chain, fake = make_chain(tmp_path, client)

    result = await chain.run(
        **COMMON_RUN_KWARGS,
        use_storage=True,
        storage_org_prefix="org_1",
    )

    assert result.returncode == 1
    assert "scope_not_published" in result.stderr
    assert fake.seen_context is None
