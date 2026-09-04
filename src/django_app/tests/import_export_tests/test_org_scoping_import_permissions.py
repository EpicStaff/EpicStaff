import json
import pytest

from django.urls import reverse
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from tables.models import Graph, LLMConfig
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.import_service import ImportService
from tables.import_export.services.export_service import ExportService
from tables.import_export.schemas import ImportSettings
from tables.services.rbac.effective_permissions import EffectivePermissions
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.models.rbac_models import OrganizationUser, Role
from tables.models.rbac_models.role import RolePermission
from tests.helpers import data_to_json_file


def _ep(by_resource, is_superadmin=False):
    return EffectivePermissions(
        is_superadmin=is_superadmin, role=None, by_resource=by_resource
    )


def _graph_export_forcing_config_create(export_service, graph):
    # Tweaking the embedded LLM config's custom_name makes find_existing miss,
    # so the import must CREATE a new LLMConfig (find_existing is global, not
    # org-scoped, so an untouched config would otherwise be reused).
    export_data = export_service.export_entities(EntityType.GRAPH, [graph.id])
    export_data[EntityType.LLM_CONFIG][0]["custom_name"] = "Unique Import Config ZZZ"
    return export_data


@pytest.mark.django_db
class TestImportPermissionEnforcement:
    def test_denies_when_dependency_create_permission_missing(
        self, exportable_graph_with_agent_node, export_service, default_org
    ):
        export_data = _graph_export_forcing_config_create(
            export_service, exportable_graph_with_agent_node
        )
        ep = _ep({ResourceType.FLOWS: int(Permission.CREATE | Permission.READ)})

        graphs_before = Graph.objects.count()
        configs_before = LLMConfig.objects.count()

        with pytest.raises(PermissionDenied) as exc:
            ImportService(entity_registry).import_data(
                export_data,
                export_data["main_entity"],
                settings=ImportSettings(),
                org_id=default_org.id,
                effective_permissions=ep,
            )

        assert "llm_configs" in str(exc.value)
        # collect-all rollback: nothing persisted, not even the permitted flow
        assert Graph.objects.count() == graphs_before
        assert LLMConfig.objects.count() == configs_before

    def test_allows_when_all_create_permissions_present(
        self, exportable_graph_with_agent_node, export_service, default_org
    ):
        export_data = _graph_export_forcing_config_create(
            export_service, exportable_graph_with_agent_node
        )
        ep = _ep(
            {
                ResourceType.FLOWS: int(Permission.CREATE | Permission.READ),
                ResourceType.LLM_CONFIGS: int(Permission.CREATE | Permission.READ),
            }
        )

        graphs_before = Graph.objects.count()
        ImportService(entity_registry).import_data(
            export_data,
            export_data["main_entity"],
            settings=ImportSettings(),
            org_id=default_org.id,
            effective_permissions=ep,
        )
        assert Graph.objects.count() == graphs_before + 1

    def test_reuse_needs_no_create_permission(
        self, exportable_graph_with_agent_node, export_service, default_org
    ):
        # No tweak: the embedded LLM config is reused (found globally), so only
        # the main flow is created. Caller has FLOWS create but not LLM_CONFIGS.
        export_data = export_service.export_entities(
            EntityType.GRAPH, [exportable_graph_with_agent_node.id]
        )
        ep = _ep({ResourceType.FLOWS: int(Permission.CREATE | Permission.READ)})

        graphs_before = Graph.objects.count()
        ImportService(entity_registry).import_data(
            export_data,
            export_data["main_entity"],
            settings=ImportSettings(),
            org_id=default_org.id,
            effective_permissions=ep,
        )
        assert Graph.objects.count() == graphs_before + 1

    def test_superadmin_bypasses_enforcement(
        self, exportable_graph_with_agent_node, export_service, default_org
    ):
        export_data = _graph_export_forcing_config_create(
            export_service, exportable_graph_with_agent_node
        )
        ep = _ep({}, is_superadmin=True)

        graphs_before = Graph.objects.count()
        ImportService(entity_registry).import_data(
            export_data,
            export_data["main_entity"],
            settings=ImportSettings(),
            org_id=default_org.id,
            effective_permissions=ep,
        )
        assert Graph.objects.count() == graphs_before + 1


def _import_client(user, org):
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return c


@pytest.mark.django_db
class TestImportPermissionEndpoint:
    def test_member_with_flows_only_role_is_denied(
        self, exportable_graph_with_agent_node, default_org, django_user_model
    ):
        # Custom role: can create FLOWS (passes the main-entity gate) but has no
        # LLM_CONFIGS permission (fails on the dependency create).
        role = Role.objects.create(
            name="ImporterFlowsOnly", org=default_org, is_built_in=False
        )
        RolePermission.objects.create(
            role=role,
            resource_type=ResourceType.FLOWS,
            permissions=int(Permission.CREATE | Permission.READ),
        )
        user = django_user_model.objects.create_user(
            email="importer@example.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(user=user, org=default_org, role=role)

        export_data = ExportService(entity_registry).export_entities(
            EntityType.GRAPH, [exportable_graph_with_agent_node.id]
        )
        export_data[EntityType.LLM_CONFIG][0]["custom_name"] = "Unique Import ZZZ"
        file = data_to_json_file(data=export_data, filename="flow.json")

        graphs_before = Graph.objects.count()
        client = _import_client(user, default_org)
        resp = client.post(
            reverse("graphs-import-entity"), {"file": file}, format="multipart"
        )

        assert resp.status_code == 403
        assert "llm_configs" in json.dumps(resp.json())
        assert Graph.objects.count() == graphs_before  # rolled back

    def test_superadmin_import_succeeds(
        self, exportable_graph_with_agent_node, default_org, superadmin_user
    ):
        export_data = ExportService(entity_registry).export_entities(
            EntityType.GRAPH, [exportable_graph_with_agent_node.id]
        )
        export_data[EntityType.LLM_CONFIG][0]["custom_name"] = "Unique Import SU"
        file = data_to_json_file(data=export_data, filename="flow.json")

        graphs_before = Graph.objects.count()
        client = _import_client(superadmin_user, default_org)
        resp = client.post(
            reverse("graphs-import-entity"), {"file": file}, format="multipart"
        )

        assert resp.status_code == 200
        assert Graph.objects.count() == graphs_before + 1
