"""Importing an LLM config whose headers carry secret markers requires secrets:USE; an imported model name cannot carry a URL.

Secret FKs never travel in an export, but `epicstaff_secret(<name>)` markers in
`extra_headers` do, and they resolve by name against the importing org's secrets.
"""

import pytest
from rbac.access.resolver import PermissionResolver
from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from rest_framework.exceptions import ValidationError

from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.schemas import ImportSettings
from tables.import_export.services.import_service import ImportService
from tables.models import Graph, LLMConfig, LLMModel

MARKER = {"X-K": "epicstaff_secret(OPENAI_KEY)"}
IMPORTED_NAME = "Imported Header Config"
CREATE_READ = int(Permission.CREATE | Permission.READ)


def _user_with(django_user_model, org, *, email, secrets_bitmask):
    role = Role.objects.create(name=f"role-{email}", org=org, is_built_in=False)
    grants = {
        ResourceType.SECRETS.value: secrets_bitmask,
        ResourceType.FLOWS.value: CREATE_READ,
        ResourceType.LLM_CONFIGS.value: CREATE_READ,
        ResourceType.AGENTS.value: CREATE_READ,
        ResourceType.SURFACES.value: CREATE_READ,
    }
    for resource_type, bitmask in grants.items():
        RolePermission.objects.create(role=role, resource_type=resource_type, permissions=bitmask)
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


@pytest.fixture
def user_without_use(db, django_user_model, default_org):
    return _user_with(
        django_user_model,
        default_org,
        email="import_markers_nouse@example.com",
        secrets_bitmask=int(Permission.READ),
    )


@pytest.fixture
def user_with_use(db, django_user_model, default_org):
    return _user_with(
        django_user_model,
        default_org,
        email="import_markers_use@example.com",
        secrets_bitmask=int(Permission.READ | Permission.USE),
    )


def _export_with_headers(export_service, graph, headers):
    # A new custom_name makes find_existing miss, so the import creates the config.
    export_data = export_service.export_entities(EntityType.GRAPH, [graph.id])
    exported_config = export_data[EntityType.LLM_CONFIG][0]
    exported_config["custom_name"] = IMPORTED_NAME
    exported_config["extra_headers"] = headers
    return export_data


def _import(export_data, *, user, org):
    ImportService(entity_registry).import_data(
        export_data,
        export_data["main_entity"],
        settings=ImportSettings(),
        org_id=org.id,
        user=user,
        effective_permissions=PermissionResolver().resolve(user=user, org_id=org.id),
    )


@pytest.mark.django_db
class TestImportedHeaderMarkers:
    def test_markers_without_use_are_rejected_and_nothing_is_imported(
        self, exportable_graph_with_agent_node, export_service, default_org, user_without_use
    ):
        export_data = _export_with_headers(
            export_service, exportable_graph_with_agent_node, MARKER
        )
        graphs_before = Graph.objects.count()

        with pytest.raises(ValidationError) as exc:
            _import(export_data, user=user_without_use, org=default_org)

        assert "extra_headers" in exc.value.detail
        assert not LLMConfig.objects.filter(custom_name__startswith=IMPORTED_NAME).exists()
        assert Graph.objects.count() == graphs_before

    def test_markers_with_use_are_imported(
        self, exportable_graph_with_agent_node, export_service, default_org, user_with_use
    ):
        export_data = _export_with_headers(
            export_service, exportable_graph_with_agent_node, MARKER
        )

        _import(export_data, user=user_with_use, org=default_org)

        imported = LLMConfig.objects.get(custom_name__startswith=IMPORTED_NAME)
        assert imported.extra_headers == MARKER

    def test_plain_headers_without_use_are_imported(
        self, exportable_graph_with_agent_node, export_service, default_org, user_without_use
    ):
        export_data = _export_with_headers(
            export_service, exportable_graph_with_agent_node, {"X-Trace": "1"}
        )

        _import(export_data, user=user_without_use, org=default_org)

        assert LLMConfig.objects.filter(custom_name__startswith=IMPORTED_NAME).exists()

    def test_reusing_an_equivalent_config_with_markers_needs_no_use(
        self, exportable_graph_with_agent_node, export_service, default_org, user_without_use
    ):
        # The org already holds a config with these markers, so the import reuses it
        # and attaches nothing new.
        config = LLMConfig.objects.get(
            pk=exportable_graph_with_agent_node.agent_node_list.get().agent_definition.llm_config_id
        )
        config.extra_headers = MARKER
        config.save(update_fields=["extra_headers"])
        export_data = export_service.export_entities(
            EntityType.GRAPH, [exportable_graph_with_agent_node.id]
        )
        configs_before = LLMConfig.objects.count()

        _import(export_data, user=user_without_use, org=default_org)

        assert LLMConfig.objects.count() == configs_before

    @pytest.mark.parametrize("malformed_headers", [["X-K"], "X-K: value"])
    def test_malformed_headers_are_a_validation_error_not_a_crash(
        self,
        exportable_graph_with_agent_node,
        export_service,
        default_org,
        user_without_use,
        malformed_headers,
    ):
        export_data = _export_with_headers(
            export_service, exportable_graph_with_agent_node, malformed_headers
        )

        with pytest.raises(ValidationError) as exc:
            _import(export_data, user=user_without_use, org=default_org)

        assert "extra_headers" in exc.value.detail
        assert not LLMConfig.objects.filter(custom_name__startswith=IMPORTED_NAME).exists()


@pytest.mark.django_db
def test_importing_an_llm_model_whose_name_carries_a_url_is_rejected(
    exportable_graph_with_agent_node, export_service, default_org, user_with_use
):
    """A model name can never carry a URL, whatever the importer's permissions."""
    export_data = export_service.export_entities(
        EntityType.GRAPH, [exportable_graph_with_agent_node.id]
    )
    url_name = "huggingface/https://attacker.example"
    export_data[EntityType.LLM_MODEL][0]["name"] = url_name

    with pytest.raises(ValidationError) as exc:
        _import(export_data, user=user_with_use, org=default_org)

    assert "name" in exc.value.detail
    assert not LLMModel.objects.filter(name__startswith=url_name).exists()
