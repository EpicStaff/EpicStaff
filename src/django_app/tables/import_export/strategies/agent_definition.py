from tables.models import LLMConfig
from agents.models import AgentDefinition, AgentDefaultSurface, Surface
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.agent_definition import (
    AgentDefinitionImportSerializer,
)
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.utils import (
    ensure_unique_identifier,
    resolve_import_organization,
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
        default_surface_ids = set(
            instance.default_surface_list.values_list("id", flat=True)
        )
        deps[EntityType.SURFACE] = list(owned_surface_ids | default_surface_ids)

        return deps

    def export_entity(self, instance: AgentDefinition) -> dict:
        return self.serializer_class(instance).data

    def create_entity(
        self, data: dict, id_mapper: IDMapper, **kwargs
    ) -> AgentDefinition:
        owned_surfaces = data.pop("owned_surfaces", [])
        default_surfaces = data.pop("default_surfaces", [])
        old_llm_config_id = data.pop("llm_config", None)
        old_fcm_llm_config_id = data.pop("fcm_llm_config", None)
        data.pop("id", None)

        organization = resolve_import_organization(kwargs.get("org_id"))

        if "name" in data:
            existing_names = AgentDefinition.objects.filter(
                organization=organization
            ).values_list("name", flat=True)
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

    def _assign_llm_configs(
        self,
        agent_definition: AgentDefinition,
        old_llm_config_id,
        old_fcm_llm_config_id,
        id_mapper: IDMapper,
    ):
        new_llm_config_id = id_mapper.get_or_none(
            EntityType.LLM_CONFIG, old_llm_config_id
        )
        new_fcm_llm_config_id = id_mapper.get_or_none(
            EntityType.LLM_CONFIG, old_fcm_llm_config_id
        )

        agent_definition.llm_config = LLMConfig.objects.filter(
            id=new_llm_config_id
        ).first()
        agent_definition.fcm_llm_config = LLMConfig.objects.filter(
            id=new_fcm_llm_config_id
        ).first()
        agent_definition.save()

    def _assign_owned_surfaces(
        self, agent_definition: AgentDefinition, owned_surfaces, id_mapper: IDMapper
    ):
        new_surface_ids = []

        for old_surface_id in owned_surfaces:
            new_surface_id = id_mapper.get_or_none(EntityType.SURFACE, old_surface_id)
            if new_surface_id is None:
                continue

            new_surface_ids.append(new_surface_id)

        Surface.objects.filter(id__in=new_surface_ids).update(
            owner_agent=agent_definition
        )

    def _assign_default_surfaces(
        self, agent_definition: AgentDefinition, default_surfaces, id_mapper: IDMapper
    ):
        default_surface_rows = []

        for row in default_surfaces:
            new_surface_id = id_mapper.get_or_none(
                EntityType.SURFACE, row["surface_id"]
            )
            if new_surface_id is None:
                continue

            default_surface_rows.append(
                AgentDefaultSurface(
                    agent_definition=agent_definition,
                    surface_id=new_surface_id,
                    place=row["place"],
                )
            )

        AgentDefaultSurface.objects.bulk_create(
            default_surface_rows, ignore_conflicts=True
        )
