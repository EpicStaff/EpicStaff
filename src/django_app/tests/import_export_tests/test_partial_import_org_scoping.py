import json

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from tables.models import Crew
from tables.models.rbac_models import OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole, Permission, ResourceType
from tables.models.rbac_models.role import RolePermission
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


def _crew_node_export(crew_node):
    """Partial-export a single crew node (pulls its crew/agents/configs as deps)."""
    result = GraphPartialExportService(entity_registry).export(
        [NodeRef(entity_type=EntityType.CREW_NODE, node_id=crew_node.id)]
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


@pytest.mark.django_db
class TestPartialImportOrgScoping:
    def test_superadmin_partial_import_stamps_active_org(
        self, rich_seeded_db, default_org, superadmin_user
    ):
        # Regression: partial import used to create the Crew with org=None,
        # violating the NOT NULL org constraint (IntegrityError 500). The crew
        # node's crew is always created (CrewStrategy has no find_existing), so
        # this deterministically exercises org stamping.
        graph = rich_seeded_db["graph"]
        data = _crew_node_export(rich_seeded_db["crew_node"])
        file = data_to_json_file(data=data, filename="nodes.json")

        crews_before = Crew.objects.count()
        client = _partial_client(superadmin_user, default_org)
        resp = client.post(
            reverse("graphs-partial-import", args=[graph.id]),
            {"file": file},
            format="multipart",
        )

        assert resp.status_code == 200, resp.content
        assert Crew.objects.count() == crews_before + 1
        # every crew (including the newly imported one) lives in the active org
        assert not Crew.objects.filter(org__isnull=True).exists()

    def test_denied_without_projects_create_permission(
        self, rich_seeded_db, default_org, django_user_model
    ):
        # FLOWS.UPDATE passes the view-level gate, but the crew dependency needs
        # PROJECTS.CREATE — which this role lacks — so the import is rejected and
        # rolled back (nothing persisted).
        role = _custom_role(default_org, {ResourceType.FLOWS: Permission.UPDATE})
        user = _member(django_user_model, default_org, role, "flows-only@example.com")

        graph = rich_seeded_db["graph"]
        data = _crew_node_export(rich_seeded_db["crew_node"])
        file = data_to_json_file(data=data, filename="nodes.json")

        crews_before = Crew.objects.count()
        client = _partial_client(user, default_org)
        resp = client.post(
            reverse("graphs-partial-import", args=[graph.id]),
            {"file": file},
            format="multipart",
        )

        assert resp.status_code == 403
        assert "projects" in json.dumps(resp.json())
        assert Crew.objects.count() == crews_before  # rolled back

    def test_denied_without_flows_update_at_view_gate(
        self, rich_seeded_db, default_org, django_user_model
    ):
        # Only FLOWS.READ: blocked by HasOrgPermission before the service runs.
        role = _custom_role(default_org, {ResourceType.FLOWS: Permission.READ})
        user = _member(django_user_model, default_org, role, "readonly@example.com")

        graph = rich_seeded_db["graph"]
        data = _crew_node_export(rich_seeded_db["crew_node"])
        file = data_to_json_file(data=data, filename="nodes.json")

        crews_before = Crew.objects.count()
        client = _partial_client(user, default_org)
        resp = client.post(
            reverse("graphs-partial-import", args=[graph.id]),
            {"file": file},
            format="multipart",
        )

        assert resp.status_code == 403
        assert Crew.objects.count() == crews_before

    def test_org_admin_partial_import_succeeds(
        self, rich_seeded_db, default_org, django_user_model
    ):
        # Org Admin has CREATE on every workspace resource → import succeeds and
        # the new crew is stamped with the active org.
        org_admin_role = Role.objects.get(name=BuiltInRole.ORG_ADMIN, is_built_in=True)
        user = _member(
            django_user_model, default_org, org_admin_role, "orgadmin@example.com"
        )

        graph = rich_seeded_db["graph"]
        data = _crew_node_export(rich_seeded_db["crew_node"])
        file = data_to_json_file(data=data, filename="nodes.json")

        crews_before = Crew.objects.count()
        client = _partial_client(user, default_org)
        resp = client.post(
            reverse("graphs-partial-import", args=[graph.id]),
            {"file": file},
            format="multipart",
        )

        assert resp.status_code == 200, resp.content
        assert Crew.objects.count() == crews_before + 1
        assert not Crew.objects.filter(org__isnull=True).exists()
