from abc import ABC, abstractmethod

__all__ = ["AbstractCryptographer", "AbstractRotatedCryptographer"]


class AbstractCryptographer(ABC):
    @abstractmethod
    def encrypt(self, data: str) -> str:
        pass

    @abstractmethod
    def decrypt(self, data: str) -> str:
        pass


class AbstractRotatedCryptographer(AbstractCryptographer):
    @abstractmethod
    def rotate(self, data: str) -> str:
        pass

    @abstractmethod
    def is_rotated(self, data: str) -> bool:
        pass
