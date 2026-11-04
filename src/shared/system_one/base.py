from typing import Any, Protocol

from src.shared.models.sessions import TokenUsage
from src.shared.models.system_one import SystemOneConfigData, SystemOneQuestion, SystemOneResult


class SystemOneError(Exception):
    """Message is written by us and safe to show in session messages.

    Never carries provider response text or keys.
    """


class SystemOneAdapter(Protocol):
    async def evaluate(
        self,
        *,
        config: SystemOneConfigData,
        state: dict[str, Any],
        questions: dict[str, SystemOneQuestion],
    ) -> tuple[SystemOneResult, TokenUsage]: ...
