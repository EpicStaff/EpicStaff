from abc import ABC, abstractmethod


class TabularProjection(ABC):
    FIELDS: list[str]

    @abstractmethod
    def project(self, row: dict) -> dict:
        """Flatten one exported entity dict into a flat CSV-row dict."""
