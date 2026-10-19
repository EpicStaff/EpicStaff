import abc


class AbstractRateLimiter(abc.ABC):
    @abc.abstractmethod
    async def hit(self, key: str, limit: int, window_seconds: int) -> int | None:
        """Count one hit; return the seconds to wait when the window's count exceeds `limit`, else None."""

    @abc.abstractmethod
    async def acquire_slot(self, key: str, limit: int, holder: str, lease_seconds: int) -> bool:
        """Take one of `limit` concurrent slots for `holder`, leased for `lease_seconds`.

        Returns False (nothing taken) when `limit` unexpired leases already exist. A lease the holder
        neither renews nor releases expires and frees its slot.
        """

    @abc.abstractmethod
    async def renew_slot(self, key: str, holder: str, lease_seconds: int) -> None:
        """Extend the holder's lease to `lease_seconds` from now; a lease that already expired stays gone."""

    @abc.abstractmethod
    async def release_slot(self, key: str, holder: str) -> None:
        """Give back the holder's slot; releasing one not held does nothing."""
