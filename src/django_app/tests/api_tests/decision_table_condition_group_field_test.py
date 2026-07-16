"""
Regression tests for MCP-audit bugs B (DecisionTableNode) and F
(ClassificationDecisionTableNode): a `condition_groups` entry containing a
field the target model doesn't have (e.g. a read-only `next_node` name
round-tripped from a GET response, or DT's `group_type` sent for a CDT group)
must return a clean 400, never an unhandled 500 / dropped connection.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    ConditionGroup,
    DecisionTableNode,
)
from tests.fixtures import *  # noqa: F401,F403


@pytest.fixture
def decision_table_node(graph):
    return DecisionTableNode.objects.create(graph=graph, node_name="dt_node")


@pytest.fixture
def classification_decision_table_node(graph):
    return ClassificationDecisionTableNode.objects.create(
        graph=graph, node_name="cdt_node"
    )


@pytest.mark.django_db
class TestDecisionTableNodeConditionGroupFieldValidation:
    def test_patch_with_stray_next_node_field_returns_400_not_500(
        self, auth_client, decision_table_node
    ):
        """A `next_node` name (read-only, round-tripped from a GET response) must
        not be splatted into ConditionGroup(**kwargs) — that field doesn't exist
        on the model (only `next_node_id` does)."""
        url = reverse("decisiontablenode-detail", args=[decision_table_node.id])
        data = {
            "condition_groups": [
                {
                    "group_name": "group_1",
                    "group_type": "simple",
                    "order": 0,
                    "expression": "1 == 1",
                    "next_node": "some_downstream_node",
                }
            ]
        }

        response = auth_client.patch(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "next_node" in str(response.json())
        # No partial state left behind — group not created outside a transaction.
        assert not ConditionGroup.objects.filter(
            decision_table_node=decision_table_node
        ).exists()

    def test_patch_with_valid_fields_still_succeeds(
        self, auth_client, decision_table_node
    ):
        url = reverse("decisiontablenode-detail", args=[decision_table_node.id])
        data = {
            "condition_groups": [
                {
                    "group_name": "group_1",
                    "group_type": "simple",
                    "order": 0,
                    "expression": "1 == 1",
                    "next_node_id": None,
                }
            ]
        }

        response = auth_client.patch(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert ConditionGroup.objects.filter(
            decision_table_node=decision_table_node, group_name="group_1"
        ).exists()


@pytest.mark.django_db
class TestClassificationDecisionTableNodeConditionGroupFieldValidation:
    def test_patch_with_stray_group_type_field_returns_400_not_500(
        self, auth_client, classification_decision_table_node
    ):
        """DT's `group_type` has no equivalent on ClassificationConditionGroup —
        splatting it into the model constructor raises an unhandled TypeError."""
        url = reverse(
            "classificationdecisiontablenode-detail",
            args=[classification_decision_table_node.id],
        )
        data = {
            "condition_groups": [
                {
                    "group_name": "route_1",
                    "order": 0,
                    "expression": "variables.category == 'billing'",
                    "group_type": "simple",
                }
            ]
        }

        response = auth_client.patch(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "group_type" in str(response.json())

    def test_patch_with_valid_fields_still_succeeds(
        self, auth_client, classification_decision_table_node
    ):
        url = reverse(
            "classificationdecisiontablenode-detail",
            args=[classification_decision_table_node.id],
        )
        data = {
            "condition_groups": [
                {
                    "group_name": "route_1",
                    "order": 0,
                    "expression": "variables.category == 'billing'",
                }
            ]
        }

        response = auth_client.patch(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert classification_decision_table_node.condition_groups.filter(
            group_name="route_1"
        ).exists()
