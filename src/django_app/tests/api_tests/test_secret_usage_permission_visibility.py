"""GET /api/secrets/ and /usage/ report only what the caller may read."""

import pytest
from rest_framework.test import APIClient

from tables.models import Organization
from tables.models.rbac_models import OrganizationUser, Role, RolePermission
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.services.secrets import secret_service

pytestmark = pytest.mark.django_db


def _client_reading(
    *, org: Organization, django_user_model, email: str, resource_types: list[str]
):
    """An APIClient for a user whose role holds READ on `resource_types` plus secrets."""
    role = Role.objects.create(name=f"role-{email}", org=org, is_built_in=False)
    RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.SECRETS.value,
        permissions=int(Permission.READ),
    )
    for resource_type in resource_types:
        RolePermission.objects.create(
            role=role, resource_type=resource_type, permissions=int(Permission.READ)
        )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def used_secret(default_org, llm_config):
    secret = secret_service.create(text="sk-live", org=default_org, name="OPENAI_KEY")
    llm_config.api_key_secret = secret
    llm_config.save(update_fields=["api_key_secret"])
    return secret


@pytest.fixture
def unused_secret(default_org):
    return secret_service.create(text="unused", org=default_org, name="UNUSED_KEY")


def _row(*, response, secret_id):
    """The one list row for this secret, whether or not the response is paginated."""
    body = response.json()
    rows = body["results"] if isinstance(body, dict) else body
    return next(row for row in rows if row["id"] == secret_id)


def test_list_reports_hidden_when_caller_cannot_read_the_resource(
    default_org, django_user_model, used_secret
):
    client = _client_reading(
        org=default_org,
        django_user_model=django_user_model,
        email="flows_only@example.com",
        resource_types=[ResourceType.FLOWS.value],
    )

    response = client.get("/api/secrets/")

    assert response.status_code == 200
    assert _row(response=response, secret_id=used_secret.pk)["usage_count"] == {
        "readable": 0,
        "hidden": 1,
    }


def test_list_reports_readable_when_caller_can_read_the_resource(
    default_org, django_user_model, used_secret
):
    client = _client_reading(
        org=default_org,
        django_user_model=django_user_model,
        email="llm_reader@example.com",
        resource_types=[ResourceType.LLM_CONFIGS.value],
    )

    response = client.get("/api/secrets/")

    assert _row(response=response, secret_id=used_secret.pk)["usage_count"] == {
        "readable": 1,
        "hidden": 0,
    }


def test_unused_secret_is_distinguishable_from_fully_hidden(
    default_org, django_user_model, used_secret, unused_secret
):
    """The whole point: 0/0 means unused, 0/1 means used but invisible."""
    client = _client_reading(
        org=default_org,
        django_user_model=django_user_model,
        email="states@example.com",
        resource_types=[ResourceType.FLOWS.value],
    )

    response = client.get("/api/secrets/")

    assert _row(response=response, secret_id=unused_secret.pk)["usage_count"] == {
        "readable": 0,
        "hidden": 0,
    }
    assert _row(response=response, secret_id=used_secret.pk)["usage_count"] == {
        "readable": 0,
        "hidden": 1,
    }


def test_retrieve_matches_list(default_org, django_user_model, used_secret):
    client = _client_reading(
        org=default_org,
        django_user_model=django_user_model,
        email="retrieve@example.com",
        resource_types=[ResourceType.FLOWS.value],
    )

    listed = _row(response=client.get("/api/secrets/"), secret_id=used_secret.pk)[
        "usage_count"
    ]
    retrieved = client.get(f"/api/secrets/{used_secret.pk}/").json()["usage_count"]

    assert retrieved == listed


def test_usage_detail_omits_unreadable_categories_and_reports_hidden_total(
    default_org, django_user_model, used_secret
):
    client = _client_reading(
        org=default_org,
        django_user_model=django_user_model,
        email="detail@example.com",
        resource_types=[ResourceType.FLOWS.value],
    )

    body = client.get(f"/api/secrets/{used_secret.pk}/usage/").json()

    assert body["readable_total"] == 0
    assert body["hidden_total"] == 1
    assert body["categories"] == []


def test_usage_detail_lists_readable_category(
    default_org, django_user_model, used_secret
):
    client = _client_reading(
        org=default_org,
        django_user_model=django_user_model,
        email="detail_ok@example.com",
        resource_types=[ResourceType.LLM_CONFIGS.value],
    )

    body = client.get(f"/api/secrets/{used_secret.pk}/usage/").json()

    assert body["readable_total"] == 1
    assert body["hidden_total"] == 0
    assert [category["key"] for category in body["categories"]] == ["llm_configs"]
