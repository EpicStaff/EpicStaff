from abc import ABC, abstractmethod


class TabularProjection(ABC):
    FIELDS: list[str]

    def expand(self, item) -> list[dict]:
        """Turn one exported-entity dict into a list of flat CSV-row source dicts.
        Default: item is already a flat list of rows (legacy shape)."""
        return item if isinstance(item, list) else [item]

    def expand_all(self, items: list) -> list[dict]:
        """Expand every exported entity; override when one item's rows depend on the others."""
        return [row for item in items for row in self.expand(item)]

    @abstractmethod
    def project(self, row: dict) -> dict:
        """Flatten one exported entity dict into a flat CSV-row dict."""
