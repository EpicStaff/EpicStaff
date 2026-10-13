import pytest

pytest.importorskip(
    "pwd",
    reason="POSIX-only: sandbox isolation requires pwd/landlock; runs in the Linux image",
)

import settings
from dynamic_venv_executor_chain import DynamicVenvExecutorChain, AbstractHandler
from src.shared.models import CodeResultData
from src.shared.models.storage_scope import StorageCredentials
from utils.logger import logger

CREDENTIAL_FAILURE_STDERR = "Storage access requested but no credentials provided."


@pytest.fixture
def error_log_messages():
    """`DynamicVenvExecutorChain` logs through loguru, which never reaches
    pytest's `caplog` (that only sees stdlib `logging`). Attach a sink instead."""
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="ERROR")
    try:
        yield messages
    finally:
        logger.remove(sink_id)


class FakeChain(AbstractHandler):
    def __init__(self):
        self.seen_context = None
        self.raise_exc = None

    async def handle(self, context):
        self.seen_context = context
        if self.raise_exc:
            raise self.raise_exc
        return CodeResultData(execution_id=context["execution_id"], returncode=0)


def make_chain(tmp_path):
    chain = DynamicVenvExecutorChain(
        output_path=tmp_path / "out",
        base_venv_path=tmp_path / "venvs",
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
    chain, fake = make_chain(tmp_path)
    credentials = StorageCredentials(access_key="scoped-ak", secret_key="scoped-sk")

    result = await chain.run(
        **COMMON_RUN_KWARGS,
        use_storage=True,
        storage_org_prefix="org_1",
        storage_allowed_paths=["flowA"],
        storage_credentials=credentials,
    )

    assert fake.seen_context["temp_storage_access_key"] == "scoped-ak"
    assert fake.seen_context["temp_storage_secret_key"] == "scoped-sk"
    assert result.returncode == 0


@pytest.mark.asyncio
async def test_use_storage_false_skips_credentials(tmp_path):
    chain, fake = make_chain(tmp_path)

    await chain.run(**COMMON_RUN_KWARGS, use_storage=False)

    assert "temp_storage_access_key" not in (fake.seen_context or {})


@pytest.mark.asyncio
async def test_missing_credentials_fails_closed_without_starting_execution(
    tmp_path, error_log_messages
):
    """Fail-closed: a task that asks for storage access but was not handed
    `storage_credentials` (crew/agent are responsible for injecting it at
    publication time) must never reach code execution."""
    chain, fake = make_chain(tmp_path)

    result = await chain.run(
        **COMMON_RUN_KWARGS,
        use_storage=True,
        storage_org_prefix="org_1",
        storage_credentials=None,
    )

    assert result.returncode == 1
    assert result.stderr == CREDENTIAL_FAILURE_STDERR
    assert any("exec1" in message for message in error_log_messages)
    assert fake.seen_context is None


@pytest.mark.asyncio
async def test_chain_failure_keeps_the_exception_text_out_of_stderr(
    tmp_path, error_log_messages
):
    """A handler blowing up (venv creation, library install) must fail
    closed with fixed text so host paths and connection strings never reach
    the SSE stream or the LLM tool observation."""
    chain, fake = make_chain(tmp_path)
    fake.raise_exc = RuntimeError("/srv/internal/venvs/v/bin/python is missing")

    result = await chain.run(**COMMON_RUN_KWARGS, use_storage=False)

    assert result.returncode == 1
    assert result.stderr == "Execution chain failed."
    assert "/srv/internal/venvs" not in result.stderr
    assert any("/srv/internal/venvs" in message for message in error_log_messages)
