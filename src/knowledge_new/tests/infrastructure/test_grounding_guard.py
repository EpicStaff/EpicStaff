"""Tests for the post-generation grounding guard.

Seam: `create_completion` — the only external boundary (the judge's LLM call).
"""

import logging
from types import SimpleNamespace

import pandas
import pytest
from domain.enums import GraphSearchMethodEnum
from graphrag.config.models.graph_rag_config import GraphRagConfig
from graphrag.prompts.query.global_search_reduce_system_prompt import NO_DATA_ANSWER
from infrastructure import grounding_guard

QUERY = "what is the secret project codename?"
CONTEXT = {"reports": pandas.DataFrame({"content": ["the retrieved context"]})}
GUARD_LOGGER = "infrastructure.grounding_guard"


def _config() -> GraphRagConfig:
    from graphrag_llm.config import ModelConfig

    config = GraphRagConfig()
    config.completion_models["default_completion_model"] = ModelConfig(
        model_provider="openai", model="gpt-4o", api_key="stub-key"
    )
    return config


@pytest.fixture
def judge(monkeypatch):
    """Install a judge verdict; returns the list of prompts it was asked to judge."""

    def install(verdict: str) -> list[str]:
        prompts: list[str] = []

        class FakeModel:
            async def completion_async(self, messages, stream=False):
                prompts.append(messages)
                return SimpleNamespace(content=verdict)

        monkeypatch.setattr(grounding_guard, "create_completion", lambda _config: FakeModel())
        return prompts

    return install


async def _apply(response, config=None):
    return await grounding_guard.apply_grounding_guard(
        query=QUERY,
        response=response,
        context=CONTEXT,
        config=config or _config(),
        method=GraphSearchMethodEnum.LOCAL,
        rag_id=77,
    )


async def test_grounded_answer_is_returned_unchanged(judge):
    judge("GROUNDED")

    assert await _apply("the draft answer") == "the draft answer"


@pytest.mark.parametrize(
    "verdict", ["NOT_GROUNDED", "maybe?"], ids=["not-grounded", "unparseable"]
)
async def test_answer_the_judge_does_not_confirm_is_dropped(judge, verdict):
    judge(verdict)

    assert await _apply("fabricated answer") == ""


@pytest.mark.parametrize(
    "response", ["", None, NO_DATA_ANSWER], ids=["empty", "none", "no-data"]
)
async def test_non_answers_are_dropped_without_consulting_the_judge(judge, response):
    prompts = judge("GROUNDED")

    assert await _apply(response) == ""
    assert prompts == []


async def test_rejection_is_logged_by_rag_id_and_never_quotes_the_user_query(judge, caplog):
    judge("NOT_GROUNDED")

    with caplog.at_level(logging.WARNING, logger=GUARD_LOGGER):
        await _apply("fabricated answer")

    rejection_logs = [
        record.getMessage()
        for record in caplog.records
        if "Grounding guard rejected" in record.getMessage()
    ]
    (rejection,) = rejection_logs
    assert "rag_id: [77]" in rejection
    assert "local" in rejection
    assert all(QUERY not in record.getMessage() for record in caplog.records)
