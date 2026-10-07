"""The worker's inbound port: where ready jobs come from.

The counterpart of the manager's ``AbstractJobDispatcher``. The manager dispatches
only jobs whose venv is COMPLETED, so by the time one arrives here it is runnable. The
adapter behind this port owns the transport (an in-process queue now, a network
source later) and hands back a domain ``Job`` -- the wire ``ExecutionJobMessage``
is decoded at the boundary and never reaches the application.
"""

import abc

from worker.domain.models import Job

__all__ = ["AbstractJobSource"]


class AbstractJobSource(abc.ABC):
    @abc.abstractmethod
    async def get(self) -> Job:
        """Block until a ready job is available, then return it."""
