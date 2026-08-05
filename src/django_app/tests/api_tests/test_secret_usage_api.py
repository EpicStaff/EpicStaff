"""The two HTTP surfaces.

An explicit APIClient is built here rather than using the shared auth_client
fixture: tests/settings.py clears DEFAULT_AUTHENTICATION_CLASSES, which makes that
fixture return 403 for everything. Pattern follows
tests/api_tests/test_secret_selection_cross_org.py.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from tables.models import LLMConfig, McpTool, PythonCode
from tables.models.graph_models import Graph, PythonNode
from tables.models.llm_models import LLMModel
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.secrets import secret_service

DECLARING_CODE = 'def main(**kwargs):\n    return get_secret("USAGE_KEY")\n'


def _results(resp):
    """The rows out of a list response, paginated or not.

    Copied from tests/api_tests/test_secret_api.py:91 — the project's pagination
    is LimitOffsetPagination with a PAGE_SIZE of 500000, and this endpoint's shape
    should not be assumed either way by a test that is about usage counts.
    """
    body = resp.data
    return body["results"] if isinstance(body, dict) and "results" in body else body


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org SecretUsageApi")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Org SecretUsageApi Other")


def _client(*, django_user_model, org, role_name, email):
    role = Role.objects.get(name=role_name, is_built_in=True, org__isnull=True)
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def admin_client(db, django_user_model, org):
    return _client(
        django_user_model=django_user_model,
        org=org,
        role_name=BuiltInRole.ORG_ADMIN,
        email="usage_admin@example.com",
    )


@pytest.fixture
def secret(org):
    return secret_service.create(text="sk-api", org=org, name="USAGE_KEY")


@pytest.fixture
def used_secret(org, secret):
    """The secret referenced from a flow, a tool and an LLM config."""
    graph = Graph.objects.create(name="API flow", org=org)
    PythonNode.objects.create(
        graph=graph,
        node_name="charge_card",
        python_code=PythonCode.objects.create(code=DECLARING_CODE),
    )
    McpTool.objects.create(
        name="api tool",
        transport="https://example.com/sse",
        tool_name="search",
        org=org,
        auth_secret=secret,
    )
    LLMConfig.objects.create(
        custom_name="api cfg",
        model=LLMModel.objects.create(name="gpt-4o-api", llm_provider=None, org=org),
        org=org,
        api_key_secret=secret,
    )
    return secret


@pytest.mark.django_db
class TestUsageCountOnList:
    def test_unused_secret_reports_zero(self, admin_client, secret):
        resp = admin_client.get("/api/secrets/")

        assert resp.status_code == 200, resp.content
        row = next(item for item in _results(resp) if item["id"] == secret.pk)
        assert row["usage_count"] == 0

    def test_used_secret_reports_its_resource_count(self, admin_client, used_secret):
        resp = admin_client.get("/api/secrets/")

        row = next(item for item in _results(resp) if item["id"] == used_secret.pk)
        assert row["usage_count"] == 3

    def test_usage_count_is_read_only(self, admin_client, org):
        """A client-supplied value must be ignored, not stored or echoed back."""
        resp = admin_client.post(
            "/api/secrets/",
            {"name": "WRITE_ATTEMPT", "value": "sk-write", "usage_count": 99},
            format="json",
        )

        assert resp.status_code == 201, resp.content
        assert resp.data["usage_count"] == 0

    def test_query_count_does_not_grow_with_the_number_of_secrets(
        self, admin_client, org
    ):
        """The real regression risk: a SerializerMethodField that sweeps per row.
        Counts are compared rather than pinned to a number, so the test asserts the
        property (no growth) instead of a brittle constant.
        """
        secret_service.create(text="sk-n1", org=org, name="N_KEY_1")
        with CaptureQueriesContext(connection) as few:
            admin_client.get("/api/secrets/")

        for index in range(2, 12):
            secret_service.create(text=f"sk-n{index}", org=org, name=f"N_KEY_{index}")
        with CaptureQueriesContext(connection) as many:
            admin_client.get("/api/secrets/")

        assert len(many) == len(few)


@pytest.fixture
def viewer_client(db, django_user_model, org):
    return _client(
        django_user_model=django_user_model,
        org=org,
        role_name=BuiltInRole.VIEWER,
        email="usage_viewer@example.com",
    )


@pytest.fixture
def member_client(db, django_user_model, org):
    return _client(
        django_user_model=django_user_model,
        org=org,
        role_name=BuiltInRole.MEMBER,
        email="usage_member@example.com",
    )


@pytest.mark.django_db
class TestUsageDetailEndpoint:
    def test_unused_secret_returns_zero_and_no_categories(self, admin_client, secret):
        resp = admin_client.get(f"/api/secrets/{secret.pk}/usage/")

        assert resp.status_code == 200, resp.content
        assert resp.data == {"total": 0, "categories": []}

    def test_payload_shape_across_all_three_categories(self, admin_client, used_secret):
        resp = admin_client.get(f"/api/secrets/{used_secret.pk}/usage/")

        assert resp.status_code == 200, resp.content
        assert resp.data["total"] == 3
        assert [category["key"] for category in resp.data["categories"]] == [
            "flows",
            "tools",
            "llm_configs",
        ]

        flows = resp.data["categories"][0]["items"]
        assert len(flows) == 1
        assert flows[0]["name"] == "API flow"
        assert flows[0]["nodes"] == [{"name": "charge_card", "node_type": "python"}]

        assert resp.data["categories"][1]["items"] == [{"name": "api tool"}]
        assert resp.data["categories"][2]["items"] == [{"name": "api cfg"}]

    def test_total_matches_the_lists_usage_count(self, admin_client, used_secret):
        """The chip and the headline must never disagree."""
        listed = admin_client.get("/api/secrets/")
        row = next(item for item in _results(listed) if item["id"] == used_secret.pk)
        detail = admin_client.get(f"/api/secrets/{used_secret.pk}/usage/")

        assert row["usage_count"] == detail.data["total"]

    def test_another_orgs_secret_is_404_not_403(self, admin_client, other_org):
        """403 would confirm the row exists. Queryset scoping must make it a 404."""
        foreign = secret_service.create(
            text="sk-foreign", org=other_org, name="FOREIGN_KEY"
        )

        resp = admin_client.get(f"/api/secrets/{foreign.pk}/usage/")

        assert resp.status_code == 404, resp.content

    def test_missing_org_header_is_400(self, db, django_user_model, org, secret):
        role = Role.objects.get(
            name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
        )
        user = django_user_model.objects.create_user(
            email="usage_noheader@example.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(user=user, org=org, role=role)
        client = APIClient()
        client.force_authenticate(user=user)

        resp = client.get(f"/api/secrets/{secret.pk}/usage/")

        assert resp.status_code == 400, resp.content
        assert resp.data["code"] == "org_context_required"

    def test_viewer_is_denied(self, viewer_client, secret):
        """The seeded viewer bitmask is 192 (USE|LIST) with no READ bit, and usage
        is mapped to READ — so the whole Secrets surface stays Org-Admin-only."""
        resp = viewer_client.get(f"/api/secrets/{secret.pk}/usage/")

        assert resp.status_code == 403, resp.content

    def test_member_is_denied(self, member_client, secret):
        resp = member_client.get(f"/api/secrets/{secret.pk}/usage/")

        assert resp.status_code == 403, resp.content
