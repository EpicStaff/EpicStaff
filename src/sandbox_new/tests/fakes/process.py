"""A subprocess stand-in for the one branch a real process cannot reproduce.

``LaunchStep`` is otherwise exercised with real children. This covers the case where
both ``os.killpg`` and ``Process.kill`` fail, which makes the step report that the
execution may still be running.
"""

import asyncio

__all__ = ["FakeProcess"]


class FakeProcess:
    def __init__(
        self,
        *,
        pid: int = 424242,
        returncode: int | None = None,
        stdout: bytes = b"",
        stderr: bytes = b"",
        hang: bool = False,
        kill_error: Exception | None = None,
    ) -> None:
        self.pid = pid
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._hang = hang
        self._kill_error = kill_error
        self.kill_calls = 0

    async def communicate(self, input=None) -> tuple[bytes, bytes]:
        if self._hang:
            await asyncio.Event().wait()
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.kill_calls += 1
        if self._kill_error is not None:
            raise self._kill_error
