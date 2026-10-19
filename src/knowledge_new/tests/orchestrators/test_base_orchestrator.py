import asyncio
import io
import sys

import pytest
from application.commands import RunIndex, RunSearch
from application.orchestrators.base import AbstractOrchestrator
from bootstrap.lifespans import configure_logging
from domain.models import NaiveSearchConfig
from loguru import logger

EMBEDDING_API_KEY = "sk-embedding-provider-key"
LLM_API_KEY = "sk-llm-provider-key"
RAG_ID = 42


class CancelledOrchestrator(AbstractOrchestrator):
    async def on_execute(self, command):
        raise asyncio.CancelledError()


@pytest.fixture
def log_messages():
    messages: list[str] = []
    sink_id = logger.add(messages.append, level="INFO", format="{message}")
    yield messages
    logger.remove(sink_id)


@pytest.mark.parametrize(
    "command",
    [
        RunIndex(
            rag_id=RAG_ID,
            document_ids=frozenset({1}),
            embedding_api_key=EMBEDDING_API_KEY,
            llm_api_key=LLM_API_KEY,
        ),
        RunSearch(
            rag_id=RAG_ID,
            query="query",
            search_config=NaiveSearchConfig(search_limit=5, similarity_threshold=0.3),
            embedding_api_key=EMBEDDING_API_KEY,
            llm_api_key=LLM_API_KEY,
        ),
    ],
    ids=["index", "search"],
)
async def test_cancel_log_names_the_rag_without_provider_keys(command, log_messages):
    await CancelledOrchestrator(uow=None).execute(command)

    cancel_log = "".join(log_messages)
    assert f"rag_id={RAG_ID}" in cancel_log
    assert EMBEDDING_API_KEY not in cancel_log
    assert LLM_API_KEY not in cancel_log


def build_embedder(rag_id: int, api_key: str):
    raise RuntimeError("provider rejected the key")


class FailingOrchestrator(AbstractOrchestrator):
    async def on_execute(self, command):
        build_embedder(command.rag_id, command.embedding_api_key)


@pytest.fixture
def service_stderr(monkeypatch):
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr)
    configure_logging()
    yield stderr
    logger.configure(handlers=[{"sink": sys.__stderr__}])


async def test_failure_traceback_keeps_provider_keys_out_of_the_log(service_stderr):
    command = RunIndex(
        rag_id=RAG_ID,
        document_ids=frozenset({1}),
        embedding_api_key=EMBEDDING_API_KEY,
        llm_api_key=LLM_API_KEY,
    )

    with pytest.raises(RuntimeError):
        await FailingOrchestrator(uow=None).execute(command)

    error_log = service_stderr.getvalue()
    assert "provider rejected the key" in error_log
    assert "build_embedder" in error_log
    assert EMBEDDING_API_KEY not in error_log
    assert LLM_API_KEY not in error_log
