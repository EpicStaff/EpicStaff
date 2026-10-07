from agents.models import AgentDefaultSurface, AgentDefinition, Surface
from django.db.models import Q

from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.serializers.agent_definition import (
    AgentDefinitionImportSerializer,
)
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.utils import (
    create_filters,
    ensure_unique_identifier,
    filter_by_name_or_renamed_copy,
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

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> AgentDefinition:
        owned_surfaces = data.pop("owned_surfaces", [])
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
        self._assign_owned_surfaces(agent_definition, owned_surfaces, id_mapper)
        self._assign_default_surfaces(agent_definition, default_surfaces, id_mapper)

        return agent_definition

    def find_existing(
        self, data: dict, id_mapper: IDMapper, org_id: int | None = None
    ) -> AgentDefinition:
        projected = {field: data.get(field) for field in COMPARED_FIELDS}
        filters, null_filters = create_filters(projected)

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

        # Surface ids the file references but this import did not map are
        # dropped, exactly as create_entity drops them.
        mapped_owned_ids = set()
        created_owned_ids = set()
        for old_surface_id in data.get("owned_surfaces", []):
            new_surface_id = id_mapper.get_or_none(EntityType.SURFACE, old_surface_id)
            if new_surface_id is None:
                continue
            mapped_owned_ids.add(new_surface_id)
            if id_mapper.was_created(EntityType.SURFACE, old_surface_id):
                created_owned_ids.add(new_surface_id)

        # A reused agent is never modified, so a surface this import created
        # that is still unowned can only go to a new agent.
        if Surface.objects.filter(id__in=created_owned_ids, owner_agent__isnull=True).exists():
            return None

        expected_default_rows = {
            (new_surface_id, row["place"])
            for row in data.get("default_surfaces", [])
            if (new_surface_id := id_mapper.get_or_none(EntityType.SURFACE, row["surface_id"]))
            is not None
        }
        candidates = [
            candidate
            for candidate in filter_by_name_or_renamed_copy(
                AgentDefinition.objects.filter(**filters, **null_filters).filter(
                    self.get_org_scope_q(org_id)
                ),
                data.get("name"),
            ).prefetch_related("owned_surfaces", "default_surfaces")
            if {(row.surface_id, row.place) for row in candidate.default_surfaces.all()}
            == expected_default_rows
        ]
        owned_ids_by_candidate = [
            (candidate, {surface.id for surface in candidate.owned_surfaces.all()})
            for candidate in candidates
        ]

        # An agent owning exactly the file's surfaces beats any subset match, in
        # candidate order -- so when the file owns nothing, the exact name wins
        # over a renamed copy.
        for candidate, owned_ids in owned_ids_by_candidate:
            if owned_ids == mapped_owned_ids:
                return candidate
        # A surface owned by another agent cannot be claimed, so an agent created
        # without it must still be found. Newest wins: every copy an import mints
        # is newer than the rows it shadows, so re-imports of the same file keep
        # the first binding. Trade-off: on a first import with several
        # pre-existing subset matches, the newest wins even if an older one owns
        # more. Known limitation: importing a different file in between can mint
        # a newer matching row; fixing that needs persisted import provenance.
        subset_matches = [
            candidate
            for candidate, owned_ids in owned_ids_by_candidate
            if owned_ids <= mapped_owned_ids
        ]
        if not subset_matches:
            return None
        return max(subset_matches, key=lambda candidate: candidate.id)

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

    def _assign_owned_surfaces(
        self, agent_definition: AgentDefinition, owned_surfaces, id_mapper: IDMapper
    ):
        new_surface_ids = []

        for old_surface_id in owned_surfaces:
            new_surface_id = id_mapper.get_or_none(EntityType.SURFACE, old_surface_id)
            # A reused surface is never modified, so only surfaces this import
            # created are claimed; the isnull guard keeps another agent created
            # earlier in the same import from losing one.
            if new_surface_id is None or not id_mapper.was_created(
                EntityType.SURFACE, old_surface_id
            ):
                continue

            new_surface_ids.append(new_surface_id)

        Surface.objects.filter(id__in=new_surface_ids, owner_agent__isnull=True).update(
            owner_agent=agent_definition
        )

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
