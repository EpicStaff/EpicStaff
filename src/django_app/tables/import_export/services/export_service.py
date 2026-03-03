from typing import List
from collections import defaultdict

from tables.import_export.registry import EntityRegistry
from tables.import_export.enums import EntityType
from tables.import_export.constants import MAIN_ENTITY_KEY


class ExportService:

    def __init__(self, registry: EntityRegistry):
        self.registry = registry

    def export_entities(self, entity_type: EntityType, entity_ids: List[int]) -> dict:
        """Export multiple entities of the same type with all dependencies"""
        collector = DependencyCollector(self.registry)

        for entity_id in entity_ids:
            collector.collect(entity_type, entity_id)

        data = collector.to_dict()
        data[MAIN_ENTITY_KEY] = entity_type
        return data


class DependencyCollector:
    """Recursively collects all dependencies for export"""

    def __init__(self, registry: EntityRegistry):
        self.registry = registry
        self.collected = defaultdict(dict)

    def collect(self, entity_type: str, entity_id: int):
        """Recursively collect entity and all its dependencies"""

        if entity_id in self.collected[entity_type]:
            return

        strategy = self.registry.get_strategy(entity_type)
        instance = strategy.get_instance(entity_id)

        if not instance:
            return

        self.collected[entity_type][entity_id] = instance

        dependencies = strategy.extract_dependencies_from_instance(instance)

        for dep_type, dep_ids in dependencies.items():
            for dep_id in dep_ids:
                self.collect(dep_type, dep_id)

    def to_dict(self) -> dict:
        """Convert collected entities to exportable dict"""
        result = {}

        for entity_type, instances in self.collected.items():
            strategy = self.registry.get_strategy(entity_type)
            result[entity_type] = [
                strategy.export_entity(instance) for instance in instances.values()
            ]

        return result
