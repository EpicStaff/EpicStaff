import threading


class CancellationToken:
    """
    Thread-safe cancellation token using threading.Event.

    Usage:
        token = CancellationToken("job-123")

        # In worker thread:
        if token.is_cancelled:
            raise asyncio.CancelledError("Job cancelled")

        # To cancel:
        token.cancel()
    """

    __slots__ = ('_event', '_job_id')

    def __init__(self, job_id: str):
        """
        Initialize cancellation token.

        Args:
            job_id: Unique identifier for the job this token belongs to
        """
        self._event = threading.Event()
        self._job_id = job_id

    def cancel(self) -> None:
        """
        Mark the token as cancelled.
        can be called from any thread.
        """
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        """
        Check if cancellation was requested.
        can be called from any thread.

        Returns:
            True if cancel() was called, False otherwise
        """
        return self._event.is_set()

    @property
    def job_id(self) -> str:
        """Get the job ID associated with this token."""
        return self._job_id

    def __repr__(self) -> str:
        status = "cancelled" if self.is_cancelled else "active"
        return f"CancellationToken(job_id={self._job_id!r}, status={status})"
