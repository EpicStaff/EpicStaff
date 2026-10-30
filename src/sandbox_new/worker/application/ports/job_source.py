"""The worker's inbound port: where ready jobs come from.

The counterpart of the manager's ``AbstractJobDispatcher``. The manager dispatches
only jobs whose venv is COMPLETED, so by the time one arrives here it is runnable. The
adapter behind this port owns the transport (an in-process queue now, a network
source later) and hands back a domain ``Job`` -- the wire ``ExecutionJobMessage``
is decoded at the boundary and never reaches the application.
"""

import abc

from worker.domain.models import Job

__all__ = ["AbstractJobSource", "UndecodableJobError"]


class UndecodableJobError(Exception):
    """A job arrived that could not be decoded into a ``Job``.

    Carries only what is needed to answer its producer with a failed result. Never the
    decode error itself: its text would quote the job's fields, secrets included.
    """

    def __init__(
        self, execution_id: str, *, reply_to_crew_channel: bool, session_id: int | None = None
    ) -> None:
        super().__init__(f"Job {execution_id} could not be decoded.")
        self.execution_id = execution_id
        self.reply_to_crew_channel = reply_to_crew_channel
        self.session_id = session_id


class AbstractJobSource(abc.ABC):
    @abc.abstractmethod
    async def get(self) -> Job:
        """Block until a ready job is available, then return it.

        Raises:
            UndecodableJobError: The next job could not be decoded; it is consumed, and
                the caller is expected to fail it so its producer is not left waiting.
        """
