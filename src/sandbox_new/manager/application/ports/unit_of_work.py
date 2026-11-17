import abc

from foundation.base import AbstractUnitOfWork as _AbstractUnitOfWork

from manager.domain.ports import (
    AbstractCustomLibraryRepository,
    AbstractVenvRepository,
    AbstractWheelRepository,
)


class AbstractUnitOfWork(_AbstractUnitOfWork, abc.ABC):
    @property
    @abc.abstractmethod
    def venv_repo(self) -> AbstractVenvRepository:
        pass

    @property
    @abc.abstractmethod
    def custom_library_repo(self) -> AbstractCustomLibraryRepository:
        pass

    @property
    @abc.abstractmethod
    def wheel_repo(self) -> AbstractWheelRepository:
        pass
