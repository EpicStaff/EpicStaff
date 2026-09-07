import pytest
from dynamic_venv_executor_chain import DynamicVenvExecutorChain, AbstractHandler
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


class FakeManager:
    def __init__(self, create_result=("scoped-ak", "scoped-sk"), create_exc=None):
        self.create_result = create_result
        self.create_exc = create_exc
        self.build_policy_calls = []
        self.created = 0
        self.revoked = []

    def build_policy(self, allowed_bucket, allowed_folders):
        self.build_policy_calls.append((allowed_bucket, allowed_folders))
        return {"Version": "2012-10-17", "Statement": []}

    async def create(self, policy):
        self.created += 1
        if self.create_exc:
            raise self.create_exc
        return self.create_result

    async def revoke(self, access_key):
        self.revoked.append(access_key)


def make_chain(tmp_path, manager):
    chain = DynamicVenvExecutorChain(
        output_path=tmp_path / "out",
        base_venv_path=tmp_path / "venvs",
        storage_credential_manager=manager,
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
async def test_use_storage_true_happy_path(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BUCKET_NAME", "epicstaff")
    manager = FakeManager()
    chain, fake = make_chain(tmp_path, manager)

    result = await chain.run(
        **COMMON_RUN_KWARGS,
        use_storage=True,
        storage_org_prefix="org_1",
        storage_allowed_paths=["flowA"],
    )

    assert manager.created == 1
    assert fake.seen_context["temp_storage_access_key"] == "scoped-ak"
    assert fake.seen_context["temp_storage_secret_key"] == "scoped-sk"
    assert result.returncode == 0
    assert manager.revoked == ["scoped-ak"]

    assert len(manager.build_policy_calls) == 1
    called_bucket, called_folders = manager.build_policy_calls[0]
    assert called_bucket == "epicstaff"
    assert called_folders == {"org_1/flowA"}


@pytest.mark.asyncio
async def test_use_storage_false_skips_credentials(tmp_path):
    manager = FakeManager()
    chain, fake = make_chain(tmp_path, manager)

    await chain.run(**COMMON_RUN_KWARGS, use_storage=False)

    assert manager.created == 0
    assert manager.revoked == []
    assert "temp_storage_access_key" not in (fake.seen_context or {})


@pytest.mark.asyncio
async def test_create_failure_returns_error_result(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BUCKET_NAME", "epicstaff")
    manager = FakeManager(create_exc=RuntimeError("boom"))
    chain, fake = make_chain(tmp_path, manager)

    result = await chain.run(
        **COMMON_RUN_KWARGS,
        use_storage=True,
        storage_org_prefix="org_1",
    )

    assert result.returncode == 1
    assert "boom" in result.stderr
    assert fake.seen_context is None
    assert manager.revoked == []


@pytest.mark.asyncio
async def test_revoke_runs_on_chain_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BUCKET_NAME", "epicstaff")
    manager = FakeManager()
    chain, fake = make_chain(tmp_path, manager)
    fake.raise_exc = RuntimeError("chain-fail")

    with pytest.raises(RuntimeError, match="chain-fail"):
        await chain.run(
            **COMMON_RUN_KWARGS,
            use_storage=True,
            storage_org_prefix="org_1",
        )

    assert manager.revoked == ["scoped-ak"]


@pytest.mark.asyncio
async def test_missing_org_prefix_returns_error_result(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BUCKET_NAME", "epicstaff")
    manager = FakeManager()
    chain, fake = make_chain(tmp_path, manager)

    result = await chain.run(
        **COMMON_RUN_KWARGS,
        use_storage=True,
        storage_org_prefix=None,
    )

    assert result.returncode == 1
    assert fake.seen_context is None
    assert manager.created == 0
