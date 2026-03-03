from tables.import_export.strategies.base import EntityImportExportStrategy


class EntityRegistry:
    def __init__(self):
        self._strategies = {}

    def register(self, strategy: EntityImportExportStrategy):
        self._strategies[strategy.entity_type] = strategy

    def get_strategy(self, entity_type: str) -> EntityImportExportStrategy:
        return self._strategies[entity_type]


entity_registry = EntityRegistry()
