from typing import List
from collections import defaultdict

from tables.import_export.registry import EntityRegistry
from tables.import_export.enums import EntityType
from tables.import_export.constants import MAIN_ENTITY_KEY, IMPORT_VERSION


class ExportService:
    def __init__(self, registry: EntityRegistry):
        self.registry = registry

    def export_entities(
        self,
        entity_type: EntityType,
        entity_ids: List[int],
        org_id: int | None = None,
    ) -> dict:
        collector = DependencyCollector(self.registry, org_id=org_id)

        for entity_id in entity_ids:
            collector.collect(entity_type, entity_id)

        data = collector.to_dict()
        data[MAIN_ENTITY_KEY] = entity_type
        data["version"] = IMPORT_VERSION
        return data


class DependencyCollector:
    """Recursively collects all dependencies for export"""

    def __init__(self, registry: EntityRegistry, org_id: int | None = None):
        self.registry = registry
        self.org_id = org_id
        self.collected = defaultdict(dict)

    def collect(self, entity_type: str, entity_id: int):
        """Recursively collect entity and all its dependencies"""

        if entity_id in self.collected[entity_type]:
            return

        strategy = self.registry.get_strategy(entity_type)
        instance = strategy.get_instance(entity_id)

        if not instance:
            return

        dependencies = self._extract_dependencies(strategy, instance)

        for dep_type, dep_ids in dependencies.items():
            for dep_id in dep_ids:
                self.collect(dep_type, dep_id)

        self.collected[entity_type][entity_id] = instance

    def _extract_dependencies(self, strategy, instance) -> dict[str, list[int]]:
        extractor = getattr(strategy, "extract_org_scoped_dependencies", None)
        if extractor is not None and self.org_id is not None:
            return extractor(instance, self.org_id)
        return strategy.extract_dependencies_from_instance(instance)

    def to_dict(self) -> dict:
        """Convert collected entities to exportable dict"""
        result = {}

        for entity_type, instances in self.collected.items():
            strategy = self.registry.get_strategy(entity_type)
            result[entity_type] = [
                self._export_entity(strategy, instance)
                for instance in instances.values()
            ]

        return result

    def _export_entity(self, strategy, instance) -> dict:
        exporter = getattr(strategy, "export_entity_org_scoped", None)
        if exporter is not None and self.org_id is not None:
            return exporter(instance, self.org_id)
        return strategy.export_entity(instance)
