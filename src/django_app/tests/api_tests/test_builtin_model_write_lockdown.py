import pytest
from rest_framework.test import APIClient

from tables.models import Provider
from tables.models.embedding_models import EmbeddingModel
from tables.models.llm_models import (
    LLMModel,
    RealtimeModel,
    RealtimeTranscriptionModel,
)
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


@pytest.fixture
def role_admin(db):
    return Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def provider(db):
    return Provider.objects.create(name="prov")


def _client(user, org):
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return c


@pytest.fixture
def client_admin_a(db, django_user_model, org_a, role_admin):
    user = django_user_model.objects.create_user(
        email="admin_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_admin)
    return _client(user, org_a)


@pytest.fixture
def client_member_a(db, django_user_model, org_a, role_member):
    user = django_user_model.objects.create_user(
        email="m_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_member)
    return _client(user, org_a)


@pytest.fixture
def client_superadmin(db, django_user_model, org_a):
    user = django_user_model.objects.create_user(
        email="root@example.com", password="StrongPass123!", is_superadmin=True
    )
    return _client(user, org_a)


def _builtins(provider, org_a):
    """A (route, built-in row, own-org row, patch payload) tuple per registry."""
    return [
        (
            "llm-models",
            LLMModel.objects.create(
                name="builtin-llm", llm_provider=provider, is_custom=False
            ),
            LLMModel.objects.create(
                name="mine-llm", llm_provider=provider, is_custom=True, org=org_a
            ),
            {"base_url": "https://attacker.example"},
        ),
        (
            "embedding-models",
            EmbeddingModel.objects.create(
                name="builtin-emb", embedding_provider=provider, is_custom=False
            ),
            EmbeddingModel.objects.create(
                name="mine-emb", embedding_provider=provider, is_custom=True, org=org_a
            ),
            {"base_url": "https://attacker.example"},
        ),
        (
            "realtime-models",
            RealtimeModel.objects.create(
                name="builtin-rt", provider=provider, is_custom=False
            ),
            RealtimeModel.objects.create(
                name="mine-rt", provider=provider, is_custom=True, org=org_a
            ),
            {"name": "renamed-rt"},
        ),
        (
            "realtime-transcription-models",
            RealtimeTranscriptionModel.objects.create(
                name="builtin-tr", provider=provider, is_custom=False
            ),
            RealtimeTranscriptionModel.objects.create(
                name="mine-tr", provider=provider, is_custom=True, org=org_a
            ),
            {"name": "renamed-tr"},
        ),
    ]


@pytest.mark.django_db
def test_builtin_patch_denied_for_org_admin(client_admin_a, provider, org_a):
    for route, builtin, _own, payload in _builtins(provider, org_a):
        resp = client_admin_a.patch(
            f"/api/{route}/{builtin.id}/", payload, format="json"
        )
        assert resp.status_code == 403, route
        assert resp.data["code"] == "built_in_model_immutable", route


@pytest.mark.django_db
def test_builtin_delete_denied_for_org_admin(client_admin_a, provider, org_a):
    for route, builtin, _own, _payload in _builtins(provider, org_a):
        resp = client_admin_a.delete(f"/api/{route}/{builtin.id}/")
        assert resp.status_code == 403, route
        assert resp.data["code"] == "built_in_model_immutable", route
        assert type(builtin).objects.filter(id=builtin.id).exists(), route


@pytest.mark.django_db
def test_builtin_write_denied_for_superadmin(client_superadmin, provider, org_a):
    """The lockdown is unconditional: built-ins are seeded by upload_models, never
    through the API, so superadmin loses nothing real."""
    for route, builtin, _own, payload in _builtins(provider, org_a):
        patch = client_superadmin.patch(
            f"/api/{route}/{builtin.id}/", payload, format="json"
        )
        assert patch.status_code == 403, route
        assert patch.data["code"] == "built_in_model_immutable", route

        delete = client_superadmin.delete(f"/api/{route}/{builtin.id}/")
        assert delete.status_code == 403, route


@pytest.mark.django_db
def test_builtin_base_url_cannot_be_repointed(client_admin_a, provider, org_a):
    """The specific cross-tenant escalation: repointing a built-in's base_url
    would redirect every org's inference traffic."""
    builtin = LLMModel.objects.create(
        name="gpt-4o", llm_provider=provider, is_custom=False, predefined=True
    )
    resp = client_admin_a.patch(
        f"/api/llm-models/{builtin.id}/",
        {"base_url": "https://attacker.example"},
        format="json",
    )
    assert resp.status_code == 403
    builtin.refresh_from_db()
    assert builtin.base_url is None


@pytest.mark.django_db
def test_own_custom_row_still_writable(client_admin_a, provider, org_a):
    """The lockdown must not over-reach: an org's own rows stay editable."""
    for route, _builtin, own, payload in _builtins(provider, org_a):
        patch = client_admin_a.patch(f"/api/{route}/{own.id}/", payload, format="json")
        assert patch.status_code == 200, (route, patch.data)

        delete = client_admin_a.delete(f"/api/{route}/{own.id}/")
        assert delete.status_code == 204, route


@pytest.mark.django_db
def test_builtin_still_readable(client_member_a, provider, org_a):
    """Built-ins stay visible — the lockdown is about writes only."""
    for route, builtin, _own, _payload in _builtins(provider, org_a):
        assert (
            client_member_a.get(f"/api/{route}/{builtin.id}/").status_code == 200
        ), route
