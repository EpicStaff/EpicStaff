"""Importing an LLM config whose extra_headers or connection carry a new
`epicstaff_secret(<name>)` marker needs secrets:USE, through the real import endpoints. A denied import rolls
back everything it had already created; a config reused as-is needs no USE."""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from rbac.models.enums import Permission, ResourceType
from tables.import_export.enums import EntityType, NodeType
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.import_export.strategies.nodes.node_maps import NODE_TYPE_TO_ENTITY_TYPE
from tables.models import Graph
from ai_models.models import LLMConfig, LLMModel, Provider
from tables.services.secrets import secret_service
from tests.helpers import UNRESTRICTED_EXPORT_POLICY, data_to_json_file
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

MARKER_HEADERS = {"Authorization": "Bearer epicstaff_secret(GATEWAY_TOKEN)"}
MARKER_CONNECTION = {
    "aws_access_key_id": "epicstaff_secret(GATEWAY_TOKEN)",
    "aws_region_name": "eu-west-1",
}
MARKED_FIELDS = pytest.mark.parametrize("marked_field", ["extra_headers", "connection"])
CRUD = Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE


@pytest.fixture
def importer_without_use(custom_role_user, default_org):
    """Can create flows and LLM configs and read secrets, but not use them."""
    user = custom_role_user(
        default_org,
        "marker-importer@example.com",
        {
            ResourceType.FLOWS: CRUD,
            ResourceType.LLM_CONFIGS: CRUD,
            ResourceType.SECRETS: Permission.READ,
        },
    )
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return client


def _with_new_model_and_marked_config(export_data: dict, marked_field: str = "extra_headers") -> dict:
    # Renaming the model and the config makes find_existing miss both, so the import
    # creates the LLM model first and then reaches the config carrying the new marker.
    model = export_data[EntityType.LLM_MODEL][0]
    model["name"] = "marker-import-model"
    config = export_data[EntityType.LLM_CONFIG][0]
    config["custom_name"] = "marker-import-config"
    if marked_field == "extra_headers":
        config["extra_headers"] = MARKER_HEADERS
    else:
        # A connection marker sits in a secret field, which Bedrock has; the secret
        # exists, so only the missing secrets:USE refuses the import.
        Provider.objects.get_or_create(name="bedrock")
        model["provider_name"] = "bedrock"
        config["connection"] = MARKER_CONNECTION
    return export_data


@pytest.fixture
def gateway_token(default_org):
    return secret_service.create(text="token", org=default_org, name="GATEWAY_TOKEN")


@pytest.mark.django_db
class TestGraphImportEndpoint:
    @MARKED_FIELDS
    def test_new_marker_without_use_is_rejected_and_rolled_back(
        self, importer_without_use, exportable_graph_with_agent_node, gateway_token, marked_field
    ):
        export_data = _with_new_model_and_marked_config(
            ExportService(entity_registry)
            .export_entities(
                EntityType.GRAPH,
                [exportable_graph_with_agent_node.id],
                policy=UNRESTRICTED_EXPORT_POLICY,
            )
            .data,
            marked_field,
        )
        graphs_before = Graph.objects.count()
        configs_before = LLMConfig.objects.count()

        response = importer_without_use.post(
            reverse("graphs-import-entity"),
            {"file": data_to_json_file(data=export_data, filename="flow.json")},
            format="multipart",
        )

        assert response.status_code == 400, response.json()
        assert marked_field in response.json()["message"]
        # The LLM model was created earlier in this import; it must be rolled back too.
        assert not LLMModel.objects.filter(name="marker-import-model").exists()
        assert LLMConfig.objects.count() == configs_before
        assert Graph.objects.count() == graphs_before

    def test_reused_config_with_existing_markers_needs_no_use(
        self, importer_without_use, exportable_graph_with_agent_node
    ):
        agent_node = exportable_graph_with_agent_node.agent_node_list.get()
        source_config = agent_node.agent_definition.llm_config
        source_config.extra_headers = MARKER_HEADERS
        source_config.save(update_fields=["extra_headers"])
        export_data = (
            ExportService(entity_registry)
            .export_entities(
                EntityType.GRAPH,
                [exportable_graph_with_agent_node.id],
                policy=UNRESTRICTED_EXPORT_POLICY,
            )
            .data
        )
        graphs_before = Graph.objects.count()
        configs_before = LLMConfig.objects.count()

        response = importer_without_use.post(
            reverse("graphs-import-entity"),
            {"file": data_to_json_file(data=export_data, filename="flow.json")},
            format="multipart",
        )

        assert response.status_code == 200, response.json()
        assert Graph.objects.count() == graphs_before + 1
        assert LLMConfig.objects.count() == configs_before


@pytest.mark.django_db
@MARKED_FIELDS
def test_partial_import_of_a_new_marker_without_use_is_rejected_and_rolled_back(
    importer_without_use, exportable_graph_with_agent_node, default_org, gateway_token, marked_field
):
    agent_node = exportable_graph_with_agent_node.agent_node_list.get()
    export_data = _with_new_model_and_marked_config(
        GraphPartialExportService(entity_registry)
        .export(
            [
                NodeRef(
                    entity_type=NODE_TYPE_TO_ENTITY_TYPE[NodeType.AGENT_NODE],
                    node_id=agent_node.id,
                )
            ],
            org_id=default_org.id,
            policy=UNRESTRICTED_EXPORT_POLICY,
        )
        .data,
        marked_field,
    )
    target = Graph.objects.create(name="partial-target", org=default_org)
    nodes_before = target.agent_node_list.count()
    configs_before = LLMConfig.objects.count()

    response = importer_without_use.post(
        reverse("graphs-partial-import", args=[target.id]),
        {"file": data_to_json_file(data=export_data, filename="nodes.json")},
        format="multipart",
    )

    assert response.status_code == 400, response.json()
    assert marked_field in response.json()["message"]
    assert not LLMModel.objects.filter(name="marker-import-model").exists()
    assert LLMConfig.objects.count() == configs_before
    assert target.agent_node_list.count() == nodes_before
