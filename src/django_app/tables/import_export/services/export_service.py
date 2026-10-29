from collections import defaultdict
from dataclasses import dataclass, field

from tables.import_export.constants import IMPORT_VERSION, MAIN_ENTITY_KEY
from tables.import_export.enums import EntityType
from tables.import_export.export_exclusions import ExcludedEntity, ExcludedEntityRecorder
from tables.import_export.permissions import ExportAccessPolicy
from tables.import_export.registry import EntityRegistry


@dataclass
class ExportResult:
    data: dict = field(default_factory=dict)
    excluded: list[ExcludedEntity] = field(default_factory=list)


class ExportService:
    def __init__(self, registry: EntityRegistry):
        self.registry = registry

    def export_entities(
        self,
        entity_type: EntityType,
        entity_ids: list[int],
        org_id: int | None = None,
        *,
        policy: ExportAccessPolicy,
    ) -> ExportResult:
        """Export entities with their dependencies, leaving out those `policy` denies.

        The requested entities themselves are never filtered; only dependencies
        reached from them are, and anything reachable only through a denied
        dependency is dropped with it.
        """
        collector = DependencyCollector(self.registry, org_id=org_id, policy=policy)

        for entity_id in entity_ids:
            collector.collect(entity_type, entity_id)

        data = collector.to_dict()
        data[MAIN_ENTITY_KEY] = entity_type
        data["version"] = IMPORT_VERSION
        return ExportResult(data=data, excluded=collector.excluded)


class DependencyCollector:
    """Recursively collects all dependencies for export"""

    def __init__(
        self,
        registry: EntityRegistry,
        org_id: int | None = None,
        *,
        policy: ExportAccessPolicy,
    ):
        self.registry = registry
        self.org_id = org_id
        self.collected = defaultdict(dict)
        self._exclusions = ExcludedEntityRecorder(registry, policy, org_id)

    @property
    def excluded(self) -> list[ExcludedEntity]:
        return self._exclusions.excluded

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
                if not self._exclusions.admits(dep_type, dep_id):
                    continue
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
                self._export_entity(strategy, instance) for instance in instances.values()
            ]

        return result

    def _export_entity(self, strategy, instance) -> dict:
        exporter = getattr(strategy, "export_entity_org_scoped", None)
        if exporter is not None and self.org_id is not None:
            return exporter(instance, self.org_id)
        return strategy.export_entity(instance)
