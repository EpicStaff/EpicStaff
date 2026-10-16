"""
LiteLLMClient + ConcurrencyLimiter: max_rpm caps in-flight calls per deployment config.

litellm.acompletion is the external edge; it is replaced by a fake whose calls
block until the test opens their gate.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import litellm
import pytest
from app.llm.concurrency_limiter import ConcurrencyLimiter
from app.llm.litellm_client import LiteLLMClient
from app.llm.retry import RetryPolicy

MESSAGES = [{"role": "user", "content": "hello"}]
CONFIG_A = {"model": "gpt-4o", "api_key": "sk-a"}
CONFIG_B = {"model": "gpt-4o", "api_key": "sk-b"}


class GatedAcompletion:
    """Fake acompletion: call N records itself in ``started`` and waits for ``gates[N]``."""

    def __init__(self, calls: int) -> None:
        self.started: list[int] = []
        self.gates = [asyncio.Event() for _ in range(calls)]

    async def __call__(self, **kwargs):
        index = len(self.started)
        self.started.append(index)
        await self.gates[index].wait()
        return SimpleNamespace(choices=[], usage=None)


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def _start_calls(model_configs: list[dict], max_rpm: int | None) -> list[asyncio.Task]:
    client = LiteLLMClient(retry=RetryPolicy(max_retries=0), limiter=ConcurrencyLimiter())

    async def call(model_config: dict):
        runtime_config = {"max_rpm": max_rpm}
        return [chunk async for chunk in client.chat(MESSAGES, [], model_config, stream=False, runtime_config=runtime_config)]

    return [asyncio.create_task(call(model_config)) for model_config in model_configs]


@pytest.mark.parametrize(
    ("model_configs", "max_rpm", "expected_in_flight"),
    [
        ([CONFIG_A] * 3, 2, 2),
        ([CONFIG_A] * 3, None, 3),
        ([CONFIG_A] * 3, 0, 3),
        ([CONFIG_A, CONFIG_A, CONFIG_B], 1, 2),
    ],
    ids=["cap-holds-third-call", "no-rpm-no-cap", "zero-rpm-no-cap", "separate-cap-per-api-key"],
)
async def test_max_rpm_caps_concurrent_calls_per_config(monkeypatch, model_configs, max_rpm, expected_in_flight):
    acompletion = GatedAcompletion(len(model_configs))
    monkeypatch.setattr(litellm, "acompletion", acompletion)

    tasks = _start_calls(model_configs, max_rpm)
    await _settle()

    assert len(acompletion.started) == expected_in_flight
    for gate in acompletion.gates:
        gate.set()
    await asyncio.gather(*tasks)
    assert len(acompletion.started) == len(model_configs)


async def test_waiting_call_starts_when_a_slot_frees(monkeypatch):
    acompletion = GatedAcompletion(3)
    monkeypatch.setattr(litellm, "acompletion", acompletion)

    tasks = _start_calls([CONFIG_A] * 3, max_rpm=2)
    await _settle()
    assert acompletion.started == [0, 1]

    acompletion.gates[0].set()
    await _settle()
    assert acompletion.started == [0, 1, 2]

    acompletion.gates[1].set()
    acompletion.gates[2].set()
    await asyncio.gather(*tasks)
