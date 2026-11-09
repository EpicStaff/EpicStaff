"""Bookkeeping for dependencies an export left out because the caller may not export them."""

from dataclasses import dataclass

from agents.models import Surface
from rbac.scoping.fields import org_visible_q

from tables.import_export.enums import EntityType
from tables.import_export.permissions import ExportAccessPolicy
from tables.import_export.registry import EntityRegistry

# Excluded entities named per type; the rest are counted without a name, so a large
# export does not look up every name.
MAX_EXCLUDED_NAMES_PER_TYPE = 5


@dataclass(frozen=True)
class ExcludedEntity:
    entity_type: EntityType
    entity_id: int
    # None when the caller may not read this type, or the name was not looked up.
    name: str | None = None


class ExcludedEntityRecorder:
    """Applies an ExportAccessPolicy to dependency edges and remembers what it refused."""

    def __init__(self, registry: EntityRegistry, policy: ExportAccessPolicy, org_id: int | None):
        self._registry = registry
        self._policy = policy
        self._org_id = org_id
        self._excluded: dict[tuple[EntityType, int], ExcludedEntity] = {}
        self._named_count: dict[EntityType, int] = {}
        self._surface_owner_ids: dict[int, int | None] = {}

    @property
    def excluded(self) -> list[ExcludedEntity]:
        return list(self._excluded.values())

    def admits(self, entity_type: str, entity_id: int | None) -> bool:
        """Return True when the dependency may be bundled; otherwise record it and return False.

        An unset reference (`None` id) points at nothing, so it is neither bundled nor recorded.
        A surface owned by an agent follows that agent: it is refused, without a record of its
        own, whenever the agent is (the agent's exclusion already accounts for it).
        """
        if entity_id is None:
            return False
        if entity_type == EntityType.SURFACE and not self._admits_owned_surface(entity_id):
            return False
        if self._policy.allows(entity_type):
            return True

        entity_type = EntityType(entity_type)
        key = (entity_type, entity_id)
        if key not in self._excluded:
            self._excluded[key] = ExcludedEntity(
                entity_type, entity_id, self._lookup_name(entity_type, entity_id)
            )
        return False

    def _admits_owned_surface(self, surface_id: int) -> bool:
        if surface_id not in self._surface_owner_ids:
            self._surface_owner_ids[surface_id] = (
                Surface.objects.filter(id=surface_id)
                .values_list("owner_agent_id", flat=True)
                .first()
            )
        owner_id = self._surface_owner_ids[surface_id]
        return owner_id is None or self._policy.allows(EntityType.AGENT_DEFINITION)

    def _lookup_name(self, entity_type: EntityType, entity_id: int) -> str | None:
        if not self._policy.can_reveal_names(entity_type):
            return None
        if self._named_count.get(entity_type, 0) >= MAX_EXCLUDED_NAMES_PER_TYPE:
            return None
        strategy = self._registry.get_strategy(entity_type)
        instance = strategy.get_instance(entity_id)
        if instance is None:
            return None
        # A row of another organization still counts as excluded, but its name stays hidden.
        model = type(instance)
        if not model.objects.filter(org_visible_q(model, self._org_id), pk=entity_id).exists():
            return None
        self._named_count[entity_type] = self._named_count.get(entity_type, 0) + 1
        return strategy.get_preview_data(instance).get("name")
