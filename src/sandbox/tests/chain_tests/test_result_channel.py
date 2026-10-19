"""The sandbox publishes every execution result to the channel its caller listens on.

Crew asks for its own channel with `reply_to_crew_channel`; every other caller
gets the shared `code_results` channel. That holds for a normal result, an
uncaught chain failure and a cancelled execution alike.
"""

import asyncio
import importlib

import pytest

pytest.importorskip(
    "pwd",
    reason="POSIX-only: sandbox isolation requires pwd/landlock; runs in the Linux image",
)

import settings
from src.shared.models import CodeResultData, CodeTaskData


class RecordingRedisService:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    async def async_publish(self, channel: str, message: dict) -> None:
        self.published.append((channel, message))


class FakeExecutorChain:
    def __init__(self, outcome: str):
        self.outcome = outcome

    async def run(self, **kwargs) -> CodeResultData:
        if self.outcome == "error":
            raise RuntimeError("chain blew up")
        if self.outcome == "cancelled":
            raise asyncio.CancelledError
        return CodeResultData(execution_id=kwargs["execution_id"], result_data="42")


@pytest.fixture
def sandbox_main(tmp_path, monkeypatch):
    # main.py changes into ./savefiles on first import; monkeypatch restores the cwd.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "savefiles").mkdir()
    sandbox_main = importlib.import_module("main")
    monkeypatch.setattr(settings, "OUTPUT_PATH", tmp_path / "out")
    monkeypatch.setattr(settings, "CODE_RESULT_CHANNEL", "code_results")
    redis_service = RecordingRedisService()
    monkeypatch.setattr(sandbox_main, "redis_service", redis_service)
    return sandbox_main, redis_service


def make_task(reply_to_crew_channel: bool) -> CodeTaskData:
    return CodeTaskData(
        venv_name="default",
        libraries=[],
        code="def main():\n    return 42",
        execution_id="exec-1",
        entrypoint="main",
        reply_to_crew_channel=reply_to_crew_channel,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply_to_crew_channel", "expected_channel"),
    [(True, "code_results:crew"), (False, "code_results")],
)
@pytest.mark.parametrize(
    ("outcome", "expected_returncode"),
    [("result", 0), ("error", 1), ("cancelled", 1)],
)
async def test_result_is_published_once_to_the_callers_channel(
    sandbox_main, monkeypatch, reply_to_crew_channel, expected_channel, outcome, expected_returncode
):
    main, redis_service = sandbox_main
    monkeypatch.setattr(main, "executor_chain", FakeExecutorChain(outcome))

    if outcome == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await main.run(make_task(reply_to_crew_channel))
    else:
        await main.run(make_task(reply_to_crew_channel))

    [(channel, message)] = redis_service.published
    assert channel == expected_channel
    assert message["execution_id"] == "exec-1"
    assert message["returncode"] == expected_returncode
