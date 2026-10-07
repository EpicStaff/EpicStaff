import abc

from foundation.base import AbstractUnitOfWork as _AbstractUnitOfWork

from manager.domain.ports import AbstractVenvRepository


class AbstractUnitOfWork(_AbstractUnitOfWork, abc.ABC):
    @property
    @abc.abstractmethod
    def venv_repo(self) -> AbstractVenvRepository:
        pass
