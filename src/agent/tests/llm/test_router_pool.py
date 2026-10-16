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

MODEL_CONFIG = {"model": "gpt-4o", "api_key": "sk-test"}


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
