"""ImportSettings.force_create_types: listed types are always created, never matched."""

import pytest
from agents.models import Surface

from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.schemas import ImportSettings
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.import_service import ImportService
from tables.models import Graph, LLMConfig, LLMModel, TaskNode


@pytest.fixture
def exported_flow(default_org, llm_config):
    """A Flow export whose task node's agent owns a surface, all in `default_org`."""
    from agents.models import AgentDefinition

    agent = AgentDefinition.objects.create(
        organization=default_org, name="Agent", llm_config=llm_config
    )
    Surface.objects.create(organization=default_org, name="Agent surface", owner_agent=agent)
    graph = Graph.objects.create(org=default_org, name="Flow", metadata={})
    TaskNode.objects.create(graph=graph, agent_definition=agent)
    yield ExportService(entity_registry).export_entities(
        EntityType.GRAPH, [graph.id], org_id=default_org.id
    )


def _import(data, default_org, **settings):
    id_mapper, _ = ImportService(entity_registry).import_data(
        data, EntityType.GRAPH, settings=ImportSettings(**settings), org_id=default_org.id
    )
    return id_mapper


@pytest.mark.django_db
def test_without_force_create_the_org_rows_are_reused(exported_flow, default_org, llm_config):
    id_mapper = _import(exported_flow, default_org)

    assert id_mapper.get_reused_ids(EntityType.LLM_CONFIG) == [llm_config.pk]
    assert id_mapper.get_created_ids(EntityType.LLM_CONFIG) == []
    assert len(id_mapper.get_reused_ids(EntityType.SURFACE)) == 1


@pytest.mark.django_db
def test_force_created_types_get_new_rows(exported_flow, default_org, llm_config):
    id_mapper = _import(
        exported_flow,
        default_org,
        force_create_types=frozenset({EntityType.LLM_CONFIG, EntityType.SURFACE}),
    )

    [new_config_id] = id_mapper.get_created_ids(EntityType.LLM_CONFIG)
    assert new_config_id != llm_config.pk
    assert id_mapper.get_reused_ids(EntityType.LLM_CONFIG) == []
    assert LLMConfig.objects.filter(org=default_org).count() == 2
    assert len(id_mapper.get_created_ids(EntityType.SURFACE)) == 1
    assert id_mapper.get_reused_ids(EntityType.SURFACE) == []


@pytest.mark.django_db
def test_types_not_listed_are_still_reused(exported_flow, default_org, llm_config):
    id_mapper = _import(
        exported_flow, default_org, force_create_types=frozenset({EntityType.SURFACE})
    )

    assert id_mapper.get_reused_ids(EntityType.LLM_CONFIG) == [llm_config.pk]
    assert id_mapper.get_reused_ids(EntityType.LLM_MODEL) == [llm_config.model_id]
    assert LLMModel.objects.count() == 1


@pytest.mark.django_db
def test_force_created_rows_still_need_create_permission(exported_flow, default_org, llm_config):
    from rbac.access.effective import EffectivePermissions
    from rbac.models.enums import Permission, ResourceType
    from rest_framework.exceptions import PermissionDenied

    everything_but_llm_configs = EffectivePermissions(
        is_superadmin=False,
        role=None,
        by_resource={
            resource.value: int(Permission.CREATE | Permission.READ)
            for resource in ResourceType
            if resource != ResourceType.LLM_CONFIGS
        },
    )

    with pytest.raises(PermissionDenied, match="llm_configs"):
        ImportService(entity_registry).import_data(
            exported_flow,
            EntityType.GRAPH,
            settings=ImportSettings(force_create_types=frozenset({EntityType.LLM_CONFIG})),
            org_id=default_org.id,
            effective_permissions=everything_but_llm_configs,
        )
