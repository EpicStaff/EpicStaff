"""A PythonCodeTool's declared secrets are readable over the API, names only."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from tables.models import PythonCode
from tables.models.python_models import PythonCodeTool
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.secrets import secret_service


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org ToolDeclRead")


@pytest.fixture
def admin_client(db, django_user_model, org):
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(
        email="tooldeclread_admin@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def secret(org):
    return secret_service.create(
        text="sk-tooldeclread", org=org, name="TOOLDECLREAD_KEY"
    )


@pytest.mark.django_db
class TestToolDeclarationReadDoesNotNPlusOne:
    def _add_tool(self, org, secret, name):
        python_code = PythonCode.objects.create(
            code='def main(**kwargs):\n    return get_secret("TOOLDECLREAD_KEY")\n',
            entrypoint="main",
        )
        python_code.secrets.set([secret])
        return PythonCodeTool.objects.create(
            org=org,
            name=name,
            description="",
            python_code=python_code,
        )

    def _secrets_query_count(self, captured) -> int:
        """Count only the queries hitting the PythonCode.secrets M2M join table."""
        secrets_table = PythonCode.secrets.through._meta.db_table
        return sum(
            1 for query in captured.captured_queries if secrets_table in query["sql"]
        )

    def test_query_count_is_flat_in_tool_count(self, admin_client, org, secret):
        self._add_tool(org, secret, "t1")
        with CaptureQueriesContext(connection) as one_tool:
            admin_client.get("/api/python-code-tool/")

        for name in ("t2", "t3", "t4", "t5"):
            self._add_tool(org, secret, name)
        with CaptureQueriesContext(connection) as five_tools:
            admin_client.get("/api/python-code-tool/")

        one_tool_secrets_queries = self._secrets_query_count(one_tool)
        five_tools_secrets_queries = self._secrets_query_count(five_tools)

        # Filtered to the secrets M2M table rather than compared as raw totals:
        # a separate, pre-existing N+1 in org_scoped_label_ids (EST-3773, label
        # org-scoping) also scales with tool count and is out of this phase's
        # scope — do not "helpfully" switch this back to a total-count
        # assertion, it will fail on that unrelated N+1.
        assert five_tools_secrets_queries == one_tool_secrets_queries, (
            f"reading five declaring tools cost {five_tools_secrets_queries} "
            f"secrets-table queries against {one_tool_secrets_queries} for one — "
            "the declaration is not prefetched"
        )
