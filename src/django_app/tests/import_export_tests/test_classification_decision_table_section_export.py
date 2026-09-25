"""Regression tests: `section` in exported condition_groups must serialize as
a string UUID (or null), not a raw uuid.UUID object."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework_simplejwt.tokens import RefreshToken

from tables.models.graph_models import ClassificationConditionGroup
from tables.models.rbac_models import Organization, OrganizationUser
from tables.import_export.enums import EntityType


def _condition_groups_of(export_data, cdt_node):
    """Locate the exported condition_groups for a CDT node inside a
    CLASSIFICATION_DECISION_TABLE_NODE-scoped export payload."""
    cdt_nodes = export_data[EntityType.CLASSIFICATION_DECISION_TABLE_NODE]
    exported_cdt = next(n for n in cdt_nodes if n["id"] == cdt_node.id)
    return exported_cdt["condition_groups"]


@pytest.mark.django_db
class TestCDTSectionExportJsonSerializability:
    """CDT exports return valid JSON (section field is serializable)."""

    def test_graph_export_with_cdt_sections_returns_valid_json(
        self, auth_client, default_org, cdt_condition_group_factory
    ):
        graph, *_ = cdt_condition_group_factory(default_org)

        url = reverse("graphs-export", kwargs={"pk": graph.id})
        response = auth_client.get(url)

        assert response.status_code == 200
        # json.loads/dumps throws if a raw UUID object made it into the payload.
        export_data = json.loads(response.content)
        assert json.dumps(export_data) is not None

    def test_partial_export_with_cdt_node_returns_valid_json(
        self, auth_client, default_org, cdt_condition_group_factory
    ):
        graph, cdt_node, *_ = cdt_condition_group_factory(default_org)

        url = reverse("graphs-partial-export", kwargs={"pk": graph.id})
        payload = {"classification_decision_table_node_list": [str(cdt_node.id)]}
        response = auth_client.post(url, payload, format="json")

        assert response.status_code == 200
        export_data = json.loads(response.content)
        assert json.dumps(export_data) is not None

    def test_cdt_node_direct_export_returns_valid_json(
        self, default_org, export_service, cdt_condition_group_factory
    ):
        _, cdt_node, *_ = cdt_condition_group_factory(default_org)

        export_data = export_service.export_entities(
            EntityType.CLASSIFICATION_DECISION_TABLE_NODE, [cdt_node.id]
        )

        assert json.dumps(export_data) is not None


@pytest.mark.django_db
class TestCDTSectionFieldFormatValidation:
    """The section field serializes as string, not a UUID object."""

    def test_section_field_serializes_as_string(
        self, default_org, export_service, cdt_condition_group_factory
    ):
        _, cdt_node, section, _ = cdt_condition_group_factory(default_org)

        export_data = export_service.export_entities(
            EntityType.CLASSIFICATION_DECISION_TABLE_NODE, [cdt_node.id]
        )
        parsed = json.loads(json.dumps(export_data))
        section_value = _condition_groups_of(parsed, cdt_node)[0]["section"]

        assert section_value == str(section.id)

    def test_section_field_null_when_no_section(
        self, default_org, export_service, cdt_condition_group_factory
    ):
        _, cdt_node, *_ = cdt_condition_group_factory(default_org, with_section=False)

        export_data = export_service.export_entities(
            EntityType.CLASSIFICATION_DECISION_TABLE_NODE, [cdt_node.id]
        )
        parsed = json.loads(json.dumps(export_data))

        assert _condition_groups_of(parsed, cdt_node)[0]["section"] is None

    def test_all_condition_group_fields_json_serializable(
        self, default_org, export_service, cdt_condition_group_factory
    ):
        _, cdt_node, *_ = cdt_condition_group_factory(
            default_org,
            expression="field == 'test'",
            manipulation="set_output('test_output')",
            field_expressions={"field": "value"},
            field_manipulations={"field": "manipulated"},
        )

        export_data = export_service.export_entities(
            EntityType.CLASSIFICATION_DECISION_TABLE_NODE, [cdt_node.id]
        )
        parsed = json.loads(json.dumps(export_data))
        exported_group = _condition_groups_of(parsed, cdt_node)[0]

        for key, value in exported_group.items():
            if isinstance(value, (dict, list)):
                json.dumps(value)
            elif value is not None and not isinstance(value, (str, int, float, bool)):
                pytest.fail(f"Field {key} is not JSON-serializable: {value!r}")


@pytest.mark.django_db
class TestCDTSectionExportRoundTrip:
    def test_export_cdt_with_sections_is_json_roundtrippable(
        self, default_org, export_service, cdt_condition_group_factory
    ):
        graph, cdt_node, *_ = cdt_condition_group_factory(default_org)

        export_data = export_service.export_entities(EntityType.GRAPH, [graph.id])
        parsed = json.loads(json.dumps(export_data))

        # The CDT node is nested inside the exported Flow entry's flat "nodes"
        # list, tagged with its node_type, not a separate top-level entity key.
        exported_flow = parsed[EntityType.GRAPH][0]
        exported_cdt = next(
            n
            for n in exported_flow["nodes"]
            if n["node_type"] == EntityType.CLASSIFICATION_DECISION_TABLE_NODE
        )
        assert exported_cdt["condition_groups"][0]["section"] is not None

    def test_export_import_roundtrip_with_cdt_sections(
        self, default_org, export_service, import_service, cdt_condition_group_factory
    ):
        original_graph, _, section, _ = cdt_condition_group_factory(
            default_org, graph_name="cdt-roundtrip-original"
        )

        export_data = export_service.export_entities(
            EntityType.GRAPH, [original_graph.id]
        )
        assert json.dumps(export_data) is not None

        id_mapper, _ = import_service.import_data(export_data, EntityType.GRAPH)
        new_graph_id = id_mapper.get_created_ids(EntityType.GRAPH)[0]
        assert new_graph_id != original_graph.id

        new_group = ClassificationConditionGroup.objects.get(
            classification_decision_table_node__graph_id=new_graph_id
        )
        assert new_group.section is not None
        assert new_group.section.name == section.name
        assert new_group.section.metadata == section.metadata


@pytest.mark.django_db
class TestCDTSectionExportCrossOrgAccess:
    def test_accessing_other_org_cdt_export_returns_404(
        self, org_admin_role, api_client, cdt_condition_group_factory
    ):
        """A user scoped to their own org gets 404 (not 403) for another org's
        graph — row-level scoping, not an org-membership permission gate."""
        org1 = Organization.objects.create(name="Org 1")
        org2 = Organization.objects.create(name="Org 2")

        user = get_user_model().objects.create_user(
            email="user@org1.example.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(user=user, org=org1, role=org_admin_role)

        graph, *_ = cdt_condition_group_factory(org2, graph_name="org2-graph")

        refresh = RefreshToken.for_user(user)
        api_client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}",
            HTTP_X_ORGANIZATION_ID=str(org1.id),
        )

        url = reverse("graphs-export", kwargs={"pk": graph.id})
        response = api_client.get(url)

        assert response.status_code == 404
