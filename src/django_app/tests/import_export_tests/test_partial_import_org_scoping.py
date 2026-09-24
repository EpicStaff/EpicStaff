import json

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from tables.models import Graph, LLMConfig, LLMModel, Provider
from tables.models.graph_models import ClassificationDecisionTableNode
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole, Permission, ResourceType
from rbac.models.role import RolePermission
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tests.helpers import data_to_json_file


def _partial_client(user, org):
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return c


def _cdt_node_export(cdt_node):
    """Partial-export a single ClassificationDecisionTableNode (pulls its default_llm_config as a dep)."""
    result = GraphPartialExportService(entity_registry).export(
        [
            NodeRef(
                entity_type=EntityType.CLASSIFICATION_DECISION_TABLE_NODE,
                node_id=cdt_node.id,
            )
        ]
    )
    assert not result.has_errors, result.errors
    return result.data


def _custom_role(org, resource_perms: dict):
    role = Role.objects.create(name="PartialImporter", org=org, is_built_in=False)
    for resource_type, mask in resource_perms.items():
        RolePermission.objects.create(
            role=role, resource_type=resource_type, permissions=int(mask)
        )
    return role


def _member(django_user_model, org, role, email):
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


@pytest.fixture
def org_owning_the_llm_config(db):
    """A different org than the one importing, so `LLMConfigStrategy.find_existing`
    (org-scoped) never matches it — the dependency is deterministically created
    fresh on every import."""
    return Organization.objects.create(name="Org Owns The LLM Config")


@pytest.fixture
def cdt_node(org_owning_the_llm_config, default_org):
    provider, _ = Provider.objects.get_or_create(name="openai")
    model = LLMModel.objects.create(
        name="gpt-4o-partial-import-scoping", llm_provider=provider
    )
    llm_config = LLMConfig.objects.create(
        custom_name="partial-import-scoping-cfg",
        model=model,
        org=org_owning_the_llm_config,
    )
    # The graph itself lives in the org that will run the partial import
    # (view-level org-scoping resolves the graph by the active org); only the
    # node's default_llm_config dependency is scoped to a different org, so
    # `LLMConfigStrategy.find_existing` (org-scoped) never matches it and the
    # dependency is deterministically created fresh on every import.
    graph = Graph.objects.create(name="partial-import-scoping-graph", org=default_org)
    return ClassificationDecisionTableNode.objects.create(
        graph=graph, default_llm_config=llm_config, node_name="cdt_node"
    )


@pytest.mark.django_db
class TestPartialImportOrgScoping:
    def test_superadmin_partial_import_stamps_active_org(
        self, cdt_node, default_org, superadmin_user
    ):
        # Regression: partial import used to create the dependency with
        # org=None, violating the NOT NULL org constraint (IntegrityError 500).
        # The node's default_llm_config is always created (it belongs to a
        # different org than the one importing, so find_existing never
        # matches), so this deterministically exercises org stamping.
        graph = cdt_node.graph
        data = _cdt_node_export(cdt_node)
        file = data_to_json_file(data=data, filename="nodes.json")

        llm_configs_before = LLMConfig.objects.count()
        client = _partial_client(superadmin_user, default_org)
        resp = client.post(
            reverse("graphs-partial-import", args=[graph.id]),
            {"file": file},
            format="multipart",
        )

        assert resp.status_code == 200, resp.content
        assert LLMConfig.objects.count() == llm_configs_before + 1
        # every llm_config (including the newly imported one) lives in an org
        assert not LLMConfig.objects.filter(org__isnull=True).exists()

    def test_denied_without_llm_configs_create_permission(
        self, cdt_node, default_org, django_user_model
    ):
        # FLOWS.UPDATE passes the view-level gate, but the default_llm_config
        # dependency needs LLM_CONFIGS.CREATE — which this role lacks — so the
        # import is rejected and rolled back (nothing persisted).
        role = _custom_role(default_org, {ResourceType.FLOWS: Permission.UPDATE})
        user = _member(django_user_model, default_org, role, "flows-only@example.com")

        graph = cdt_node.graph
        data = _cdt_node_export(cdt_node)
        file = data_to_json_file(data=data, filename="nodes.json")

        llm_configs_before = LLMConfig.objects.count()
        client = _partial_client(user, default_org)
        resp = client.post(
            reverse("graphs-partial-import", args=[graph.id]),
            {"file": file},
            format="multipart",
        )

        assert resp.status_code == 403
        assert "llm_configs" in json.dumps(resp.json())
        assert LLMConfig.objects.count() == llm_configs_before  # rolled back

    def test_denied_without_flows_update_at_view_gate(
        self, cdt_node, default_org, django_user_model
    ):
        # Only FLOWS.READ: blocked by HasOrgPermission before the service runs.
        role = _custom_role(default_org, {ResourceType.FLOWS: Permission.READ})
        user = _member(django_user_model, default_org, role, "readonly@example.com")

        graph = cdt_node.graph
        data = _cdt_node_export(cdt_node)
        file = data_to_json_file(data=data, filename="nodes.json")

        llm_configs_before = LLMConfig.objects.count()
        client = _partial_client(user, default_org)
        resp = client.post(
            reverse("graphs-partial-import", args=[graph.id]),
            {"file": file},
            format="multipart",
        )

        assert resp.status_code == 403
        assert LLMConfig.objects.count() == llm_configs_before

    def test_org_admin_partial_import_succeeds(
        self, cdt_node, default_org, django_user_model
    ):
        # Org Admin has CREATE on every workspace resource → import succeeds
        # and the new llm_config is stamped with the active org.
        org_admin_role = Role.objects.get(name=BuiltInRole.ORG_ADMIN, is_built_in=True)
        user = _member(
            django_user_model, default_org, org_admin_role, "orgadmin@example.com"
        )

        graph = cdt_node.graph
        data = _cdt_node_export(cdt_node)
        file = data_to_json_file(data=data, filename="nodes.json")

        llm_configs_before = LLMConfig.objects.count()
        client = _partial_client(user, default_org)
        resp = client.post(
            reverse("graphs-partial-import", args=[graph.id]),
            {"file": file},
            format="multipart",
        )

        assert resp.status_code == 200, resp.content
        assert LLMConfig.objects.count() == llm_configs_before + 1
        assert not LLMConfig.objects.filter(org__isnull=True).exists()
