import pytest
from rest_framework.test import APIClient

from tables.models import LLMConfig, Provider
from tables.models.embedding_models import EmbeddingConfig
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.quickstart_service import QuickstartService


def _org_admin(django_user_model, org, email):
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


def _member(django_user_model, org, email):
    role = Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


def _client(user, org):
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return c


@pytest.mark.django_db
def test_quickstart_configs_land_in_active_org(db, django_user_model):
    org = Organization.objects.create(name="Org A")
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(
        email="qa@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    # quickstart looks the provider up by name (key in PROVIDER_CONFIGS);
    # the *Model rows are get_or_create'd by the service and stay global.
    Provider.objects.create(name="openai")

    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))

    resp = client.post(
        "/api/quickstart/", {"provider": "openai", "api_key": "sk-test"}, format="json"
    )
    assert resp.status_code == 200, resp.data

    # every config quickstart created is stamped with the active org
    assert LLMConfig.objects.exists()
    assert LLMConfig.objects.exclude(org=org).count() == 0
    assert EmbeddingConfig.objects.exclude(org=org).count() == 0


@pytest.mark.django_db
def test_quickstart_requires_org_header(db, django_user_model):
    org = Organization.objects.create(name="Org A")
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(
        email="qa2@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    Provider.objects.create(name="openai")

    client = APIClient()
    client.force_authenticate(user=user)  # no X-Organization-Id

    resp = client.post(
        "/api/quickstart/", {"provider": "openai", "api_key": "sk-test"}, format="json"
    )
    assert resp.status_code == 400  # org_context_required


@pytest.mark.django_db
def test_quickstart_post_denied_without_llm_config_create(db, django_user_model):
    org = Organization.objects.create(name="Org A")
    user = _member(django_user_model, org, "qm@example.com")  # llm_configs READ only
    Provider.objects.create(name="openai")
    resp = _client(user, org).post(
        "/api/quickstart/", {"provider": "openai", "api_key": "sk-test"}, format="json"
    )
    assert resp.status_code == 403  # needs LLM_CONFIGS CREATE


@pytest.mark.django_db
def test_quickstart_apply_denied_for_non_superadmin(db, django_user_model):
    org = Organization.objects.create(name="Org A")
    admin = _org_admin(django_user_model, org, "qadmin@example.com")
    resp = _client(admin, org).post("/api/quickstart/apply/", {}, format="json")
    assert resp.status_code == 403  # global DefaultModels write is superadmin-only


@pytest.mark.django_db
def test_quickstart_apply_allowed_for_superadmin(db, django_user_model):
    org = Organization.objects.create(name="Org A")
    Provider.objects.create(name="openai")
    QuickstartService().quickstart("openai", "sk-test", org_id=org.id)  # seed a config
    root = django_user_model.objects.create_user(
        email="root@example.com", password="StrongPass123!", is_superadmin=True
    )
    resp = _client(root, org).post("/api/quickstart/apply/", {}, format="json")
    assert resp.status_code == 200, resp.data


@pytest.mark.django_db
def test_quickstart_get_last_config_scoped_to_active_org(db, django_user_model):
    # org_a runs quickstart; org_b must not see org_a's last_config (which would
    # otherwise leak another org's config and its api key).
    org_a = Organization.objects.create(name="Org A")
    org_b = Organization.objects.create(name="Org B")
    Provider.objects.create(name="openai")
    admin_a = _org_admin(django_user_model, org_a, "a@example.com")
    member_b = _member(django_user_model, org_b, "b@example.com")

    client_a = _client(admin_a, org_a)
    assert (
        client_a.post(
            "/api/quickstart/",
            {"provider": "openai", "api_key": "sk-a"},
            format="json",
        ).status_code
        == 200
    )

    resp_a = client_a.get("/api/quickstart/")
    assert resp_a.status_code == 200
    assert resp_a.data["last_config"] is not None

    # org_b ran no quickstart and cannot see org_a's config
    resp_b = _client(member_b, org_b).get("/api/quickstart/")
    assert resp_b.status_code == 200
    assert resp_b.data["last_config"] is None


@pytest.mark.django_db
def test_quickstart_get_requires_org_membership(db, django_user_model):
    # A member of org_a sending org_b's header is not a member of org_b -> 403.
    org_a = Organization.objects.create(name="Org A")
    org_b = Organization.objects.create(name="Org B")
    member_a = _member(django_user_model, org_a, "m@example.com")
    assert _client(member_a, org_b).get("/api/quickstart/").status_code == 403
