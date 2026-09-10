import pytest
from django.db import IntegrityError, transaction
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
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


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
def client_admin_b(db, django_user_model, org_b, role_admin):
    user = django_user_model.objects.create_user(
        email="admin_b@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_b, role=role_admin)
    return _client(user, org_b)


# route, provider field name, model class
_REGISTRIES = [
    ("llm-models", "llm_provider", LLMModel),
    ("embedding-models", "embedding_provider", EmbeddingModel),
    ("realtime-models", "provider", RealtimeModel),
    ("realtime-transcription-models", "provider", RealtimeTranscriptionModel),
]


@pytest.mark.django_db
@pytest.mark.parametrize("route,provider_field,model_cls", _REGISTRIES)
def test_two_orgs_can_use_the_same_model_name(
    client_admin_a, client_admin_b, org_a, org_b, route, provider_field, model_cls
):
    """The global unique_together made org A's private name block org B — a
    cross-org denial of service and an existence leak."""
    p = Provider.objects.create(name="prov")
    payload = {"name": "gpt-5o", provider_field: p.id}

    a = client_admin_a.post(f"/api/{route}/", payload, format="json")
    b = client_admin_b.post(f"/api/{route}/", payload, format="json")

    assert a.status_code == 201, (route, a.data)
    assert b.status_code == 201, (route, b.data)
    assert model_cls.objects.get(id=a.data["id"]).org_id == org_a.id
    assert model_cls.objects.get(id=b.data["id"]).org_id == org_b.id


@pytest.mark.django_db
@pytest.mark.parametrize("route,provider_field,model_cls", _REGISTRIES)
def test_duplicate_name_within_one_org_is_a_400_not_a_500(
    client_admin_a, route, provider_field, model_cls
):
    """DRF cannot auto-validate a UniqueConstraint that includes the
    server-stamped org, so without OrgScopedUniqueTogetherValidator this
    surfaces as an IntegrityError 500."""
    p = Provider.objects.create(name="prov")
    payload = {"name": "dup", provider_field: p.id}

    first = client_admin_a.post(f"/api/{route}/", payload, format="json")
    assert first.status_code == 201, (route, first.data)

    second = client_admin_a.post(f"/api/{route}/", payload, format="json")
    assert second.status_code == 400, (route, second.status_code, second.data)


@pytest.mark.django_db
@pytest.mark.parametrize("route,provider_field,model_cls", _REGISTRIES)
def test_org_row_may_shadow_a_builtin_name(
    client_admin_a, org_a, route, provider_field, model_cls
):
    """A per-org override of a catalog model is legitimate and must be allowed."""
    p = Provider.objects.create(name="prov")
    model_cls.objects.create(name="gpt-4o", is_custom=False, **{provider_field: p})

    resp = client_admin_a.post(
        f"/api/{route}/", {"name": "gpt-4o", provider_field: p.id}, format="json"
    )

    assert resp.status_code == 201, (route, resp.data)
    assert model_cls.objects.filter(name="gpt-4o", **{provider_field: p}).count() == 2


@pytest.mark.django_db
@pytest.mark.parametrize("route,provider_field,model_cls", _REGISTRIES)
def test_two_builtins_cannot_share_a_name(route, provider_field, model_cls):
    """Postgres treats NULLs as distinct, so the per-org constraint alone would
    let duplicate built-ins accumulate. The partial constraint stops that."""
    p = Provider.objects.create(name="prov")
    model_cls.objects.create(name="gpt-4o", is_custom=False, **{provider_field: p})

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            model_cls.objects.create(
                name="gpt-4o", is_custom=False, **{provider_field: p}
            )
