from typing import Protocol

__all__ = ["Runner"]


class Runner(Protocol):
    """A background loop the composition root starts as a supervised task."""

    async def run(self) -> None: ...
