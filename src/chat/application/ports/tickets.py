import abc


class AbstractTickets(abc.ABC):
    @abc.abstractmethod
    async def issue(self, payload: dict) -> tuple[str, int]:
        """Return (ticket, expires_in_seconds)."""

    @abc.abstractmethod
    async def consume(self, ticket: str) -> dict | None:
        """Single use: the payload once, None afterwards or for an unknown ticket."""
