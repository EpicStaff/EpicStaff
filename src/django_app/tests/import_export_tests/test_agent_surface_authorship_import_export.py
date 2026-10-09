import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from rest_framework import status

from agents.models import AgentDefinition
from agents.models.surface_models import Surface
from rbac.models import OrganizationUser, ResourceLastEdit
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.models import Graph
from tables.models.graph_models import AgentNode
from tests.helpers import data_to_json_file
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

AUTHOR_KEY = "created_by"
ORG_KEYS = ("org", "organization")


@pytest.fixture
def admin_beta(db, django_user_model, beta, role_org_admin):
    user = django_user_model.objects.create_user(
        email="admin-beta-authorship@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=beta, role=role_org_admin)
    return user


@pytest.fixture
def source_flow(acme, member_only):
    """An acme flow whose AgentNode references an AgentDefinition and a Surface authored by `member_only`."""
    agent_definition = AgentDefinition.objects.create(
        org=acme, name="authored-agent", created_by=member_only
    )
    Surface.objects.create(
        org=acme, name="owned-surface", owner_agent=agent_definition, created_by=member_only
    )
    shared_surface = Surface.objects.create(
        org=acme, name="shared-surface", created_by=member_only
    )
    graph = Graph.objects.create(
        name="agent-flow", org=acme, metadata={"nodes": [], "edges": []}, created_by=member_only
    )
    agent_node = AgentNode.objects.create(
        graph=graph, node_name="agent", agent_definition=agent_definition, created_by=member_only
    )
    agent_node.surface_list.set([shared_surface])
    return graph


def _export(graph: Graph) -> dict:
    return ExportService(entity_registry).export_entities(EntityType.GRAPH, [graph.id])


def _keys_named(value, key: str) -> list[str]:
    """Return the path of every dict key equal to `key`, at any depth of `value`."""
    found = []

    def walk(item, path):
        if isinstance(item, dict):
            for item_key, child in item.items():
                child_path = f"{path}.{item_key}"
                if item_key == key:
                    found.append(child_path)
                walk(child, child_path)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{path}[{index}]")

    walk(value, "$")
    return found


def _import_flow(client, org, export_data):
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client.post(
        reverse("graphs-import-entity"),
        {"file": data_to_json_file(data=export_data, filename="flow.json")},
        format="multipart",
    )


@pytest.mark.django_db
def test_export_carries_no_author_or_org_for_agent_definition_and_surface(source_flow):
    export_data = _export(source_flow)

    assert len(export_data[EntityType.AGENT_DEFINITION]) == 1
    assert len(export_data[EntityType.SURFACE]) == 2
    assert _keys_named(export_data, AUTHOR_KEY) == []
    for entity_type in (EntityType.AGENT_DEFINITION, EntityType.SURFACE):
        for entity_data in export_data[entity_type]:
            assert not set(ORG_KEYS) & set(entity_data), entity_data


@pytest.mark.django_db
def test_import_authors_new_agent_definition_and_surfaces_with_importer(
    client_as, admin_beta, beta, source_flow
):
    response = _import_flow(client_as(admin_beta), beta, _export(source_flow))

    assert response.status_code == status.HTTP_200_OK, response.content
    imported_definition = AgentDefinition.objects.get(org=beta)
    imported_surfaces = Surface.objects.filter(org=beta)
    assert imported_definition.created_by_id == admin_beta.id
    assert imported_surfaces.count() == 2
    assert set(imported_surfaces.values_list("created_by_id", flat=True)) == {admin_beta.id}


@pytest.mark.django_db
def test_import_file_cannot_choose_agent_definition_or_surface_author(
    client_as, admin_beta, member_only, beta, source_flow
):
    export_data = _export(source_flow)
    for entity_type in (EntityType.AGENT_DEFINITION, EntityType.SURFACE):
        for entity_data in export_data[entity_type]:
            entity_data[AUTHOR_KEY] = member_only.id
            entity_data["org"] = source_flow.org_id

    response = _import_flow(client_as(admin_beta), beta, export_data)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert AgentDefinition.objects.get(org=beta).created_by_id == admin_beta.id
    assert set(Surface.objects.filter(org=beta).values_list("created_by_id", flat=True)) == {
        admin_beta.id
    }


@pytest.mark.django_db
def test_import_records_importer_as_last_editor_of_agent_definition_and_surfaces(
    client_as, admin_beta, beta, source_flow
):
    response = _import_flow(client_as(admin_beta), beta, _export(source_flow))

    assert response.status_code == status.HTTP_200_OK, response.content
    owned_surface = Surface.objects.get(org=beta, owner_agent__isnull=False)
    shared_surface = Surface.objects.get(org=beta, owner_agent__isnull=True)
    for resource in (AgentDefinition.objects.get(org=beta), owned_surface, shared_surface):
        last_edit = ResourceLastEdit.objects.get(
            content_type=ContentType.objects.get_for_model(resource), object_id=resource.pk
        )
        assert last_edit.edited_by_id == admin_beta.id, resource
