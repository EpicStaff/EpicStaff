from importlib import import_module

import pytest
from django.apps import apps

from agents.models.surface_models import Surface, SurfaceGraphLocalSearchConfig, SurfaceKnowledge
from rbac.models import Organization
from tables.models.graph_models import Graph, KnowledgeNode
from tables.models.knowledge_models import (
    KnowledgeNodeGraphRagDriftSearchConfig,
    SourceCollection,
)

tables_migration = import_module("tables.migrations.0260_search_config_non_finite_floats")
agents_migration = import_module("agents.migrations.0012_surface_search_config_non_finite_floats")


@pytest.mark.django_db
def test_non_finite_search_config_values_are_reset_to_defaults():
    organization = Organization.objects.create(name="Non-finite Org")
    node = KnowledgeNode.objects.create(graph=Graph.objects.create(org=organization, name="flow"))
    drift = KnowledgeNodeGraphRagDriftSearchConfig.objects.create(knowledge_node=node)
    surface_knowledge = SurfaceKnowledge.objects.create(
        surface=Surface.objects.create(organization=organization, name="surface"),
        collection=SourceCollection.objects.create(org=organization, collection_name="kb"),
    )
    surface_local = SurfaceGraphLocalSearchConfig.objects.create(
        surface_knowledge=surface_knowledge
    )
    KnowledgeNodeGraphRagDriftSearchConfig.objects.filter(pk=drift.pk).update(
        local_search_top_p=float("nan"),
        reduce_temperature=float("inf"),
        local_search_temperature=1.5,
    )
    SurfaceGraphLocalSearchConfig.objects.filter(pk=surface_local.pk).update(
        text_unit_prop=float("-inf"), community_prop=float("nan")
    )

    tables_migration.reset_non_finite_values(apps)
    agents_migration.reset_non_finite_values(apps)

    drift.refresh_from_db()
    surface_local.refresh_from_db()
    assert drift.local_search_top_p == 1.0
    assert drift.reduce_temperature == 0.0
    assert drift.local_search_temperature == 1.5
    assert (surface_local.text_unit_prop, surface_local.community_prop) == (0.5, 0.15)
