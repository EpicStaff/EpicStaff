import math
from collections import Counter, defaultdict
from copy import deepcopy

from agents.models import AgentDefaultSurface, AgentDefinition
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db.models import Q

from tables.import_export.constants import MAX_REUSE_CANDIDATES, OWNED_SURFACE_ENTRIES_KEY
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.schemas import ImportSettings
from tables.import_export.serializers.agent_definition import (
    AgentDefinitionImportSerializer,
)
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.strategies.surface import SurfaceStrategy
from tables.import_export.utils import (
    compared_values,
    create_filters,
    ensure_unique_identifier,
    filter_by_name_or_renamed_copy,
    import_values,
    resolve_import_organization,
)
from tables.models import LLMConfig

# Scalar fields compared for reuse, next to the rename-aware name match, the
# llm configs and the owned/default surfaces. Explicit allowlist (not
# create_filters over the whole dict) so the comparison stays self-documenting
# and immune to serializer/field additions.
COMPARED_FIELDS = (
    "description",
    "instruction_list",
    "metadata",
    "max_iter",
    "max_rpm",
    "max_execution_time",
    "cache",
    "max_retry_limit",
    "default_temperature",
    "max_tool_calls",
    "tool_timeout",
    "max_consecutive_failures",
    "schema_max_retries",
)

LEGACY_INSTRUCTION_NAME = "Instruction_1.md"


def convert_legacy_instructions(data: dict) -> None:
    """Replace a released-version `instructions` string with `instruction_list` in place.

    Export files written before AgentDefinition switched to named instructions carry a
    single `instructions` text; it becomes the agent's only instruction. Their obsolete
    `metadata["instructions_format"]` flag is dropped, as the migration does for stored
    rows, so reuse matching in `find_existing` still finds migrated agents.
    """
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("instructions_format", None)
    legacy_instructions = data.pop("instructions", None)
    if data.get("instruction_list") is not None:
        return
    if isinstance(legacy_instructions, str) and legacy_instructions.strip():
        data["instruction_list"] = [
            {"name": LEGACY_INSTRUCTION_NAME, "content": legacy_instructions}
        ]
    else:
        data["instruction_list"] = []


# Frozen copy of the singleton values that migration 0010 backfilled NULLs with, so an
# old export keeps the limits it ran with and matches rows migrated from the same data.
_LEGACY_NULL_REPLACEMENTS = {
    "max_iter": 25,
    "max_rpm": 10,
    "max_execution_time": 60,
    "cache": False,
    "max_retry_limit": 3,
    "max_tool_calls": 15,
    "tool_timeout": 300,
    "max_consecutive_failures": 3,
    "schema_max_retries": 2,
}
_CLAMPED_FIELDS = (*_LEGACY_NULL_REPLACEMENTS, "default_temperature")


def _clamp_to_field_validators(field_name: str, value):
    for validator in AgentDefinition._meta.get_field(field_name).validators:
        if isinstance(validator, MinValueValidator):
            value = max(value, validator.limit_value)
        elif isinstance(validator, MaxValueValidator):
            value = min(value, validator.limit_value)
    return value


def _normalize_execution_fields(data: dict) -> None:
    """Make older export files importable under the current field rules, in place.

    Older exports carry null for the execution fields and values outside today's
    bounds; nulls take the legacy singleton values and numbers are clamped into range.
    A non-finite default_temperature becomes null, as in agents migration 0010.
    Non-numeric values are left for the serializer to reject.
    """
    for field_name, replacement in _LEGACY_NULL_REPLACEMENTS.items():
        if data.get(field_name) is None:
            data[field_name] = replacement

    temperature = data.get("default_temperature")
    if isinstance(temperature, float) and not math.isfinite(temperature):
        data["default_temperature"] = None

    for field_name in _CLAMPED_FIELDS:
        value = data.get(field_name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            data[field_name] = _clamp_to_field_validators(field_name, value)


def normalize_legacy_agent_entry(data: dict) -> None:
    """Bring an AgentDefinition entry from an older export to today's fields, in place.

    Applied before validation, lookup and create alike, so all three see the
    same values.
    """
    convert_legacy_instructions(data)
    _normalize_execution_fields(data)


class AgentDefinitionStrategy(EntityImportExportStrategy):
    entity_type = EntityType.AGENT_DEFINITION
    serializer_class = AgentDefinitionImportSerializer

    def __init__(self):
        self.surface_strategy = SurfaceStrategy()

    def get_instance(self, entity_id: int) -> AgentDefinition:
        return AgentDefinition.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: AgentDefinition) -> dict:
        return {"id": instance.id, "name": instance.name}

    def extract_dependencies_from_instance(self, instance: AgentDefinition) -> dict:
        deps = {}

        llm_config_ids = set()
        if instance.llm_config_id:
            llm_config_ids.add(instance.llm_config_id)
        if instance.fcm_llm_config_id:
            llm_config_ids.add(instance.fcm_llm_config_id)
        deps[EntityType.LLM_CONFIG] = list(llm_config_ids)

        owned_surface_ids = set(instance.owned_surfaces.values_list("id", flat=True))
        default_surface_ids = set(instance.default_surface_list.values_list("id", flat=True))
        deps[EntityType.SURFACE] = list(owned_surface_ids | default_surface_ids)

        return deps

    def export_entity(self, instance: AgentDefinition) -> dict:
        return self.serializer_class(instance).data

    def import_entity(
        self,
        data: dict,
        id_mapper: IDMapper,
        is_main: bool = False,
        settings: ImportSettings = None,
        **kwargs,
    ) -> AgentDefinition:
        """Import the agent and map its owned surfaces to the rows it owns.

        create_entity maps the surfaces it creates. On reuse, find_existing
        matched them by content only, so the exported ids are mapped here to the
        reused agent's equivalent surfaces -- by the same function, over the
        rows find_existing loaded, so the two cannot disagree.
        """
        agent_definition = super().import_entity(
            data, id_mapper, is_main, settings=settings, **kwargs
        )
        owned_surface_entries = data.get(OWNED_SURFACE_ENTRIES_KEY, [])
        # An unmapped owned entry means the agent was reused: create_entity maps
        # every entry it creates.
        if any(
            not id_mapper.has_mapping(EntityType.SURFACE, entry["id"])
            for entry in owned_surface_entries
        ):
            pairing = self._match_surfaces(agent_definition, *self._entry_surfaces(data, id_mapper))
            for old_surface_id, surface_id in pairing.items():
                id_mapper.map(EntityType.SURFACE, old_surface_id, surface_id, was_created=False)
        return agent_definition

    def nested_entity_types(self, data: dict) -> tuple[EntityType, ...]:
        return (EntityType.SURFACE,) if data.get(OWNED_SURFACE_ENTRIES_KEY) else ()

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> AgentDefinition:
        owned_surface_entries = data.pop(OWNED_SURFACE_ENTRIES_KEY, [])
        data.pop("owned_surfaces", None)
        default_surfaces = data.pop("default_surfaces", [])
        old_llm_config_id = data.pop("llm_config", None)
        old_fcm_llm_config_id = data.pop("fcm_llm_config", None)
        data.pop("id", None)
        normalize_legacy_agent_entry(data)

        organization = resolve_import_organization(kwargs.get("org_id"))

        if "name" in data:
            existing_names = AgentDefinition.objects.filter(organization=organization).values_list(
                "name", flat=True
            )
            data["name"] = ensure_unique_identifier(
                base_name=data["name"],
                existing_names=existing_names,
            )

        serializer = self.serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        agent_definition = serializer.save(organization=organization)

        self._assign_llm_configs(
            agent_definition, old_llm_config_id, old_fcm_llm_config_id, id_mapper
        )
        # Owned surfaces are always created fresh for a new agent: a reused row
        # is never re-owned, and each agent's owned surfaces are its own.
        for entry in owned_surface_entries:
            surface = self.surface_strategy.create_entity(
                dict(entry),
                id_mapper,
                org_id=kwargs.get("org_id"),
                owner_agent=agent_definition,
            )
            id_mapper.map(EntityType.SURFACE, entry["id"], surface.id, was_created=True)
        self._assign_default_surfaces(agent_definition, default_surfaces, id_mapper)

        return agent_definition

    def find_existing(
        self, data: dict, id_mapper: IDMapper, org_id: int | None = None
    ) -> AgentDefinition | None:
        normalized_data = deepcopy(data)
        normalize_legacy_agent_entry(normalized_data)
        filters, null_filters = create_filters(
            compared_values(
                AgentDefinition, self.serializer_class, normalized_data, COMPARED_FIELDS
            )
        )

        new_llm_config_id = id_mapper.get_or_none(EntityType.LLM_CONFIG, data.get("llm_config"))
        new_fcm_llm_config_id = id_mapper.get_or_none(
            EntityType.LLM_CONFIG, data.get("fcm_llm_config")
        )

        if new_llm_config_id is None:
            null_filters["llm_config_id__isnull"] = True
        else:
            filters["llm_config_id"] = new_llm_config_id

        if new_fcm_llm_config_id is None:
            null_filters["fcm_llm_config_id__isnull"] = True
        else:
            filters["fcm_llm_config_id"] = new_fcm_llm_config_id

        # SQL narrows on stored columns; whether the owned and default surfaces
        # match is decided in Python.
        content_key_by_old_surface_id, entry_default_rows = self._entry_surfaces(data, id_mapper)
        candidates = filter_by_name_or_renamed_copy(
            AgentDefinition.objects.filter(**filters, **null_filters)
            .filter(self.get_org_scope_q(org_id))
            .prefetch_related(
                "owned_surfaces__python_tools", "owned_surfaces__mcp_tools", "default_surfaces"
            ),
            import_values(self.serializer_class, data, ("name",)).get("name"),
        )[:MAX_REUSE_CANDIDATES]
        return next(
            (
                candidate
                for candidate in candidates
                if self._match_surfaces(
                    candidate, content_key_by_old_surface_id, entry_default_rows
                )
                is not None
            ),
            None,
        )

    def _entry_surfaces(self, data: dict, id_mapper: IDMapper) -> tuple[dict, tuple]:
        """Return the entry's owned surface content keys and its default rows.

        Computed once per lookup or mapping and shared by every candidate.
        """
        content_key_by_old_surface_id = {
            entry["id"]: self.surface_strategy.entry_content_key(entry, id_mapper)
            for entry in data.get(OWNED_SURFACE_ENTRIES_KEY, [])
        }
        return content_key_by_old_surface_id, self._entry_default_rows(
            data, id_mapper, content_key_by_old_surface_id
        )

    def _match_surfaces(
        self,
        agent_definition: AgentDefinition,
        content_key_by_old_surface_id: dict,
        entry_default_rows: tuple,
    ) -> dict[int, int] | None:
        """Pair the entry's owned surfaces with the agent's, if the agent matches.

        A reused agent is never modified, so it must already hold what the file
        says: owned surfaces equal by content only (instructions plus remapped
        tool sets with modes; names ignored), as a multiset, and the same default
        rows -- shared ones by surface and place, owned ones by content and
        place. Unmapped ids are dropped, as create_entity drops them. Takes the
        entry's side from `_entry_surfaces`. Returns {exported surface id:
        agent's surface id}, pairing within one content in ascending id order,
        or None when the agent does not match.
        """
        old_surface_ids_by_content = defaultdict(list)
        for old_surface_id, content_key in content_key_by_old_surface_id.items():
            old_surface_ids_by_content[content_key].append(old_surface_id)

        surface_ids_by_content = defaultdict(list)
        content_key_by_surface_id = {}
        for surface in sorted(agent_definition.owned_surfaces.all(), key=lambda row: row.id):
            content_key = self.surface_strategy.surface_content_key(surface)
            surface_ids_by_content[content_key].append(surface.id)
            content_key_by_surface_id[surface.id] = content_key

        if Counter(content_key_by_old_surface_id.values()) != Counter(
            content_key_by_surface_id.values()
        ):
            return None
        if entry_default_rows != self._agent_default_rows(
            agent_definition, content_key_by_surface_id
        ):
            return None

        pairing = {}
        for content_key, old_surface_ids in old_surface_ids_by_content.items():
            pairing.update(
                zip(sorted(old_surface_ids), surface_ids_by_content[content_key], strict=True)
            )
        return pairing

    @staticmethod
    def _entry_default_rows(
        data: dict, id_mapper: IDMapper, content_key_by_old_surface_id: dict
    ) -> tuple[set, Counter]:
        """Return (shared rows by mapped surface id, owned rows by content) of the entry."""
        shared_rows = set()
        owned_rows = set()
        for row in data.get("default_surfaces", []):
            if row["surface_id"] in content_key_by_old_surface_id:
                owned_rows.add((row["surface_id"], row["place"]))
                continue
            new_surface_id = id_mapper.get_or_none(EntityType.SURFACE, row["surface_id"])
            if new_surface_id is not None:
                shared_rows.add((new_surface_id, row["place"]))
        owned_rows_by_content = Counter(
            (content_key_by_old_surface_id[old_surface_id], place)
            for old_surface_id, place in owned_rows
        )
        return shared_rows, owned_rows_by_content

    @staticmethod
    def _agent_default_rows(
        agent_definition: AgentDefinition, content_key_by_surface_id: dict
    ) -> tuple[set, Counter]:
        """Return the agent's default rows in the shape of `_entry_default_rows`."""
        shared_rows = set()
        owned_rows_by_content = Counter()
        for row in agent_definition.default_surfaces.all():
            if row.surface_id in content_key_by_surface_id:
                owned_rows_by_content[(content_key_by_surface_id[row.surface_id], row.place)] += 1
            else:
                shared_rows.add((row.surface_id, row.place))
        return shared_rows, owned_rows_by_content

    def get_org_scope_q(self, org_id: int) -> Q:
        organization = resolve_import_organization(org_id)
        if organization is None:
            return Q()
        return Q(organization=organization)

    def _assign_llm_configs(
        self,
        agent_definition: AgentDefinition,
        old_llm_config_id,
        old_fcm_llm_config_id,
        id_mapper: IDMapper,
    ):
        new_llm_config_id = id_mapper.get_or_none(EntityType.LLM_CONFIG, old_llm_config_id)
        new_fcm_llm_config_id = id_mapper.get_or_none(EntityType.LLM_CONFIG, old_fcm_llm_config_id)

        agent_definition.llm_config = LLMConfig.objects.filter(id=new_llm_config_id).first()
        agent_definition.fcm_llm_config = LLMConfig.objects.filter(id=new_fcm_llm_config_id).first()
        agent_definition.save()

    def _assign_default_surfaces(
        self, agent_definition: AgentDefinition, default_surfaces, id_mapper: IDMapper
    ):
        default_surface_rows = []

        for row in default_surfaces:
            new_surface_id = id_mapper.get_or_none(EntityType.SURFACE, row["surface_id"])
            if new_surface_id is None:
                continue

            default_surface_rows.append(
                AgentDefaultSurface(
                    agent_definition=agent_definition,
                    surface_id=new_surface_id,
                    place=row["place"],
                )
            )

        AgentDefaultSurface.objects.bulk_create(default_surface_rows, ignore_conflicts=True)
