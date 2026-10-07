import abc

from manager.domain.models import Job

__all__ = ["AbstractJobDispatcher"]


class AbstractJobDispatcher(abc.ABC):
    @abc.abstractmethod
    async def dispatch(self, job: Job):
        """Hand a ready job to the worker.

        Takes the domain ``Job``; the adapter behind this port is the only place
        that knows the wire shape and maps it to an ``ExecutionJobMessage``.
        """
