"""
Unit tests for RouterPool and get_router_pool.

litellm.Router is patched with a factory that returns distinct instances so
identity checks can verify the caching / deduplication logic.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

import app.llm.router_pool as router_pool_module
from app.llm.router_pool import RouterPool, get_router_pool


MODEL_CONFIG = {"model": "gpt-4o", "api_key": "sk-test"}


@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    """Reset the process singleton between tests."""
    monkeypatch.setattr(router_pool_module, "_POOL", None)


def make_router_factory():
    """Return a side_effect function that creates a fresh MagicMock per call."""
    instances = []

    def factory(model_list, **kwargs):
        instance = MagicMock()
        instance.model_list = model_list
        instances.append(instance)
        return instance

    return factory, instances


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_same_key_returns_same_instance():
    """Two get() calls with identical config return the exact same Router."""
    factory, instances = make_router_factory()

    with patch("app.llm.router_pool.Router", side_effect=factory):
        pool = RouterPool()
        router1 = await pool.get("gpt-4o", MODEL_CONFIG, rpm=None)
        router2 = await pool.get("gpt-4o", MODEL_CONFIG, rpm=None)

    assert router1 is router2
    assert len(instances) == 1


async def test_different_rpm_produces_different_router():
    """rpm=60 and rpm=120 for the same model produce separate Router instances."""
    factory, instances = make_router_factory()

    with patch("app.llm.router_pool.Router", side_effect=factory):
        pool = RouterPool()
        router_60 = await pool.get("gpt-4o", MODEL_CONFIG, rpm=60)
        router_120 = await pool.get("gpt-4o", MODEL_CONFIG, rpm=120)

    assert router_60 is not router_120
    assert len(instances) == 2


async def test_rpm_none_shared_across_callers():
    """rpm=None calls sharing the same model+auth get the same Router."""
    factory, instances = make_router_factory()

    with patch("app.llm.router_pool.Router", side_effect=factory):
        pool = RouterPool()
        r1 = await pool.get("gpt-4o", MODEL_CONFIG, rpm=None)
        r2 = await pool.get("gpt-4o", MODEL_CONFIG, rpm=None)

    assert r1 is r2
    assert len(instances) == 1


async def test_get_router_pool_returns_singleton():
    """get_router_pool() returns the same RouterPool across calls."""
    pool1 = get_router_pool()
    pool2 = get_router_pool()
    assert pool1 is pool2


async def test_concurrent_get_constructs_only_one_router():
    """Concurrent get() calls under the lock construct exactly one Router."""
    created = []

    def sync_factory(model_list, **kwargs):
        instance = MagicMock()
        instance.model_list = model_list
        created.append(instance)
        return instance

    with patch("app.llm.router_pool.Router", side_effect=sync_factory):
        pool = RouterPool()
        results = await asyncio.gather(
            pool.get("gpt-4o", MODEL_CONFIG, rpm=None),
            pool.get("gpt-4o", MODEL_CONFIG, rpm=None),
            pool.get("gpt-4o", MODEL_CONFIG, rpm=None),
        )

    assert len(created) == 1
    assert results[0] is results[1] is results[2]


async def test_rpm_embedded_in_litellm_params():
    """rpm appears inside litellm_params when building the deployment."""
    captured = []

    def capturing_factory(model_list, **kwargs):
        captured.append(model_list)
        instance = MagicMock()
        instance.model_list = model_list
        return instance

    with patch("app.llm.router_pool.Router", side_effect=capturing_factory):
        pool = RouterPool()
        await pool.get("gpt-4o", MODEL_CONFIG, rpm=42)

    deployment = captured[0][0]
    assert deployment["litellm_params"]["rpm"] == 42


async def test_rpm_none_not_in_litellm_params():
    """When rpm is None, the key is absent from litellm_params."""
    captured = []

    def capturing_factory(model_list, **kwargs):
        captured.append(model_list)
        instance = MagicMock()
        instance.model_list = model_list
        return instance

    with patch("app.llm.router_pool.Router", side_effect=capturing_factory):
        pool = RouterPool()
        await pool.get("gpt-4o", MODEL_CONFIG, rpm=None)

    deployment = captured[0][0]
    assert "rpm" not in deployment["litellm_params"]


async def test_router_constructed_with_disable_cooldowns():
    """Router is constructed with disable_cooldowns=True so single-deployment
    transient failures don't trigger a ~60 s cooldown blackout."""
    captured_kwargs: list[dict] = []

    def capturing_factory(*args, **kwargs):
        captured_kwargs.append(kwargs)
        instance = MagicMock()
        instance.disable_cooldowns = kwargs.get("disable_cooldowns")
        return instance

    with patch("app.llm.router_pool.Router", side_effect=capturing_factory):
        pool = RouterPool()
        await pool.get("gpt-4o", MODEL_CONFIG, rpm=None)

    assert captured_kwargs[0]["disable_cooldowns"] is True
