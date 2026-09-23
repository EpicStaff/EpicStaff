from abc import ABC, abstractmethod


class TabularProjection(ABC):
    FIELDS: list[str]

    def expand(self, item) -> list[dict]:
        """Turn one exported-entity dict into a list of flat CSV-row source dicts.
        Default: item is already a flat list of rows (legacy shape)."""
        return item if isinstance(item, list) else [item]

    @abstractmethod
    def project(self, row: dict) -> dict:
        """Flatten one exported entity dict into a flat CSV-row dict."""
