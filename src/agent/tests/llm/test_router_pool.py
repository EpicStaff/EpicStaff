"""
RouterPool: one litellm Router per (model, auth, rpm), shared by concurrent runs.

litellm.Router is external; it is replaced by a recorder of the routers built.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import app.llm.router_pool as router_pool_module
import pytest
from app.llm.router_pool import RouterPool
from app.loop.agent_loop import _build_model_config
from app.loop.context import AgentContext
from shared.models.agent_service import AgentSpec
from shared.models.ai_providers import LLMConfigData, LLMData

MODEL_CONFIG = {"model": "gpt-4o", "connection": {"api_key": "sk-test"}}


@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    """Reset the process singleton between tests."""
    monkeypatch.setattr(router_pool_module, "_POOL", None)


@pytest.fixture
def built_routers():
    """Every Router the pool constructs, as (model_list, constructor kwargs)."""
    built = []

    def build(model_list, **kwargs):
        built.append((model_list, kwargs))
        return MagicMock()

    with patch("app.llm.router_pool.Router", side_effect=build):
        yield built


@pytest.mark.parametrize(
    ("rpms", "concurrent", "expected_routers"),
    [
        ([None, None], False, 1),
        ([60, 120], False, 2),
        ([None, None, None], True, 1),
    ],
    ids=["same-config-reused", "different-rpm-separate", "concurrent-first-use-builds-one"],
)
async def test_routers_are_shared_per_model_and_rpm(built_routers, rpms, concurrent, expected_routers):
    pool = RouterPool()
    calls = [pool.get("gpt-4o", MODEL_CONFIG, rpm=rpm) for rpm in rpms]

    routers = await asyncio.gather(*calls) if concurrent else [await call for call in calls]

    assert len(built_routers) == expected_routers
    assert len({id(router) for router in routers}) == expected_routers


@pytest.mark.parametrize("rpm", [42, None])
async def test_router_is_built_with_the_rate_limit_and_without_cooldowns_or_retries(built_routers, rpm):
    await RouterPool().get("gpt-4o", MODEL_CONFIG, rpm=rpm)

    ((model_list, kwargs),) = built_routers
    assert model_list[0]["litellm_params"].get("rpm") == rpm
    # A single deployment must not be put on a ~60 s cooldown after one transient failure.
    assert kwargs["disable_cooldowns"] is True
    # RetryPolicy owns retries; Router retries would multiply the attempts.
    assert kwargs["num_retries"] == 0


async def _never_cancelled() -> bool:
    return False


def _model_config(provider: str, llm_config: LLMConfigData) -> dict:
    agent = AgentSpec(id=1, name="a", instructions="i", llm=LLMData(provider=provider, config=llm_config))
    context = AgentContext(agent=agent, attachments=[], correlation_id="c", is_cancelled=_never_cancelled)
    return _build_model_config(context)


async def _deployment_params(built_routers, provider: str, llm_config: LLMConfigData) -> dict:
    model_config = _model_config(provider, llm_config)
    await RouterPool().get(model_config["model"], model_config, rpm=None)
    ((model_list, _),) = built_routers
    return model_list[0]["litellm_params"]


async def test_a_bedrock_configs_connection_reaches_the_router_deployment(built_routers):
    llm_config = LLMConfigData(
        model="anthropic.claude-v2",
        api_key="bedrock-key",
        connection={"aws_region_name": "eu-west-1", "aws_access_key_id": "AKIA-resolved"},
    )

    assert await _deployment_params(built_routers, "bedrock", llm_config) == {
        "model": "bedrock/anthropic.claude-v2",
        "aws_region_name": "eu-west-1",
        "aws_access_key_id": "AKIA-resolved",
        "api_key": "bedrock-key",
    }


@pytest.mark.parametrize(
    ("provider", "expected_model"),
    [("openai", "gpt-4o"), ("azure", "azure/my-deployment")],
)
async def test_deployment_id_reaches_litellm_only_as_the_azure_model(built_routers, provider, expected_model):
    # litellm sends any call that carries a deployment_id to Azure.
    llm_config = LLMConfigData(
        model="gpt-4o",
        api_key="sk-test",
        connection={"api_base": "https://example.test", "deployment_id": "my-deployment"},
    )

    assert await _deployment_params(built_routers, provider, llm_config) == {
        "model": expected_model,
        "api_base": "https://example.test",
        "api_key": "sk-test",
    }


async def test_configs_differing_only_in_a_connection_value_get_separate_routers(built_routers):
    pool = RouterPool()
    for region in ("eu-west-1", "us-east-1"):
        model_config = _model_config(
            "bedrock", LLMConfigData(model="anthropic.claude-v2", connection={"aws_region_name": region})
        )
        await pool.get(model_config["model"], model_config, rpm=None)

    assert [model_list[0]["litellm_params"]["aws_region_name"] for model_list, _ in built_routers] == [
        "eu-west-1",
        "us-east-1",
    ]
