from collections import Counter, defaultdict

from agents.models import AgentDefaultSurface, AgentDefinition, Surface
from django.db.models import Exists, OuterRef, Q
from django.db.models.lookups import Exact

from tables.exceptions import ImportedAgentSurfacesChangedError
from tables.import_export.constants import OWNED_SURFACE_ENTRIES_KEY
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
    related_row_count,
    resolve_import_organization,
)
from tables.models import LLMConfig

# Scalar fields compared for reuse, next to the rename-aware name match, the
# llm configs and the owned/default surfaces. Explicit allowlist (not
# create_filters over the whole dict) so the comparison stays self-documenting
# and immune to serializer/field additions.
COMPARED_FIELDS = (
    "description",
    "instructions",
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
        reused agent's equivalent surfaces.
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
            pairing = self._pair_owned_surfaces(data, id_mapper, agent_definition.id)
            # find_existing matched on the same content, so a failure here means
            # the agent's surfaces changed in between (a concurrent edit).
            if pairing is None:
                raise ImportedAgentSurfacesChangedError()
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
        filters, null_filters = create_filters(
            compared_values(AgentDefinition, data, COMPARED_FIELDS)
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

        candidates = (
            AgentDefinition.objects.filter(**filters, **null_filters)
            .filter(self.get_org_scope_q(org_id))
            .filter(self._owned_and_default_surfaces_q(data, id_mapper))
        )
        # A reused agent is never modified, so it must already own an equivalent
        # of every surface the file says it owns (and nothing else) and hold the
        # same default surfaces. The whole comparison runs in SQL; candidate
        # order: exact name first, then id.
        return filter_by_name_or_renamed_copy(candidates, data.get("name")).first()

    def _owned_and_default_surfaces_q(self, data: dict, id_mapper: IDMapper) -> Q:
        """Return a Q for agents whose owned and default surfaces match the entry.

        Owned surfaces compare by content only (instructions plus remapped tool
        sets with modes), names ignored: per content, the agent owns as many
        surfaces as the file lists, and no others. Default rows compare per
        shared surface, and per (content, place) for owned ones. Every subquery
        is correlated to the candidate agent. Unmapped ids are dropped, as
        create_entity drops them.
        """
        content_key_by_old_surface_id = {}
        for entry in data.get(OWNED_SURFACE_ENTRIES_KEY, []):
            content_key_by_old_surface_id[entry["id"]] = self.surface_strategy.entry_content_key(
                entry, id_mapper
            )

        conditions = Q(
            Exact(
                related_row_count(Surface.objects.all(), "owner_agent"),
                len(content_key_by_old_surface_id),
            )
        )
        for content_key, entry_count in Counter(content_key_by_old_surface_id.values()).items():
            owned_surfaces_with_content = self.surface_strategy.filter_equivalent_content(
                Surface.objects.all(), content_key
            )
            conditions &= Q(
                Exact(related_row_count(owned_surfaces_with_content, "owner_agent"), entry_count)
            )

        shared_default_rows = set()
        owned_default_rows = set()
        for row in data.get("default_surfaces", []):
            if row["surface_id"] in content_key_by_old_surface_id:
                owned_default_rows.add((row["surface_id"], row["place"]))
                continue
            new_surface_id = id_mapper.get_or_none(EntityType.SURFACE, row["surface_id"])
            if new_surface_id is not None:
                shared_default_rows.add((new_surface_id, row["place"]))

        conditions &= Q(
            Exact(
                related_row_count(AgentDefaultSurface.objects.all(), "agent_definition"),
                len(shared_default_rows) + len(owned_default_rows),
            )
        )
        for surface_id, place in shared_default_rows:
            conditions &= Q(
                Exists(
                    AgentDefaultSurface.objects.filter(
                        agent_definition=OuterRef("pk"), surface_id=surface_id, place=place
                    )
                )
            )
        owned_default_counts = Counter(
            (content_key_by_old_surface_id[old_surface_id], place)
            for old_surface_id, place in owned_default_rows
        )
        for (content_key, place), row_count in owned_default_counts.items():
            own_surface_with_content = self.surface_strategy.filter_equivalent_content(
                Surface.objects.filter(
                    pk=OuterRef("surface_id"), owner_agent=OuterRef("agent_definition_id")
                ),
                content_key,
            )
            default_rows_on_own_surface = AgentDefaultSurface.objects.filter(
                Exists(own_surface_with_content), place=place
            )
            conditions &= Q(
                Exact(related_row_count(default_rows_on_own_surface, "agent_definition"), row_count)
            )
        return conditions

    def _pair_owned_surfaces(
        self, data: dict, id_mapper: IDMapper, agent_definition_id: int
    ) -> dict[int, int] | None:
        """Map exported owned surface ids to the surfaces the agent owns.

        Returns {exported surface id: agent's surface id}, or None when the
        agent's owned surfaces are not, content for content, the entry's. Within
        one content, exported and stored surfaces pair in ascending id order.
        Only called for the agent find_existing matched, so it loads as many
        surfaces as the file lists.
        """
        old_surface_ids_by_content = defaultdict(list)
        for entry in data.get(OWNED_SURFACE_ENTRIES_KEY, []):
            content_key = self.surface_strategy.entry_content_key(entry, id_mapper)
            old_surface_ids_by_content[content_key].append(entry["id"])

        surface_ids_by_content = defaultdict(list)
        for surface in (
            Surface.objects.filter(owner_agent_id=agent_definition_id)
            .order_by("id")
            .prefetch_related("python_tools", "mcp_tools")
        ):
            surface_ids_by_content[self.surface_strategy.surface_content_key(surface)].append(
                surface.id
            )

        if {key: len(ids) for key, ids in old_surface_ids_by_content.items()} != {
            key: len(ids) for key, ids in surface_ids_by_content.items()
        }:
            return None
        pairing = {}
        for content_key, old_surface_ids in old_surface_ids_by_content.items():
            pairing.update(
                zip(sorted(old_surface_ids), surface_ids_by_content[content_key], strict=True)
            )
        return pairing

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
