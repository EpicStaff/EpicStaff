import pytest
from rest_framework.test import APIClient

from tables.models import Agent, LLMConfig, Provider
from tables.models.llm_models import LLMModel
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


# ---- fixtures (mirror tests/api_tests/test_org_scoping_core.py) ----


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


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


@pytest.fixture
def member_a(db, django_user_model, org_a, role_member):
    user = django_user_model.objects.create_user(
        email="m_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_member)
    return user


@pytest.fixture
def admin_a(db, django_user_model, org_a, role_admin):
    user = django_user_model.objects.create_user(
        email="admin_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_admin)
    return user


@pytest.fixture
def superadmin(db, django_user_model):
    return django_user_model.objects.create_user(
        email="root@example.com", password="StrongPass123!", is_superadmin=True
    )


def _client(user, org):
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return c


@pytest.fixture
def client_a(member_a, org_a):  # Member: llm_configs READ only
    return _client(member_a, org_a)


@pytest.fixture
def client_admin_a(admin_a, org_a):  # Org Admin: llm_configs CRUD
    return _client(admin_a, org_a)


def _results(resp):
    body = resp.data
    return body["results"] if isinstance(body, dict) and "results" in body else body


def _builtin_model():
    p = Provider.objects.create(name="prov")
    return LLMModel.objects.create(name="m", llm_provider=p, is_custom=False)


# ---- strict config scoping (LLMConfig) ----


@pytest.mark.django_db
def test_llmconfig_list_only_active_org(client_a, org_a, org_b):
    m = _builtin_model()
    LLMConfig.objects.create(custom_name="A cfg", model=m, org=org_a)
    LLMConfig.objects.create(custom_name="B cfg", model=m, org=org_b)
    names = {c["custom_name"] for c in _results(client_a.get("/api/llm-configs/"))}
    assert "A cfg" in names and "B cfg" not in names


@pytest.mark.django_db
def test_llmconfig_detail_cross_org_404(client_a, org_b):
    m = _builtin_model()
    other = LLMConfig.objects.create(custom_name="B cfg", model=m, org=org_b)
    assert client_a.get(f"/api/llm-configs/{other.id}/").status_code == 404


@pytest.mark.django_db
def test_llmconfig_create_lands_in_active_org(client_admin_a, org_a):
    m = _builtin_model()
    resp = client_admin_a.post(
        "/api/llm-configs/", {"custom_name": "New", "model": m.id}, format="json"
    )
    assert resp.status_code == 201
    assert LLMConfig.objects.get(id=resp.data["id"]).org_id == org_a.id


@pytest.mark.django_db
def test_llmconfig_create_denied_for_member(client_a):
    m = _builtin_model()
    resp = client_a.post(
        "/api/llm-configs/", {"custom_name": "Nope", "model": m.id}, format="json"
    )
    assert resp.status_code == 403  # Member has llm_configs READ only


@pytest.mark.django_db
def test_two_orgs_reuse_custom_name(client_admin_a, org_b):
    m = _builtin_model()
    LLMConfig.objects.create(custom_name="Shared", model=m, org=org_b)
    resp = client_admin_a.post(
        "/api/llm-configs/", {"custom_name": "Shared", "model": m.id}, format="json"
    )
    assert resp.status_code == 201


# ---- hybrid model scoping (LLMModel: built-in global + custom per-org) ----


@pytest.mark.django_db
def test_llmmodel_builtins_visible_to_every_org(client_a):
    p = Provider.objects.create(name="prov")
    LLMModel.objects.create(
        name="gpt-builtin", llm_provider=p, is_custom=False
    )  # org NULL
    names = {m["name"] for m in _results(client_a.get("/api/llm-models/"))}
    assert "gpt-builtin" in names


@pytest.mark.django_db
def test_llmmodel_custom_isolated_per_org(client_a, org_a, org_b):
    p = Provider.objects.create(name="prov")
    LLMModel.objects.create(name="mine", llm_provider=p, is_custom=True, org=org_a)
    LLMModel.objects.create(name="theirs", llm_provider=p, is_custom=True, org=org_b)
    names = {m["name"] for m in _results(client_a.get("/api/llm-models/"))}
    assert "mine" in names and "theirs" not in names


@pytest.mark.django_db
def test_llmmodel_create_lands_in_active_org_as_custom(client_admin_a, org_a):
    p = Provider.objects.create(name="prov")
    resp = client_admin_a.post(
        "/api/llm-models/",
        {"name": "custom-new", "llm_provider": p.id, "predefined": True},
        format="json",
    )
    assert resp.status_code == 201
    created = LLMModel.objects.get(id=resp.data["id"])
    assert created.org_id == org_a.id
    assert created.is_custom is True  # forced custom so it does NOT leak globally
    assert created.predefined is False  # API cannot mint a predefined built-in


# ---- Provider registry write-lockdown ----


@pytest.mark.django_db
def test_provider_read_allowed_for_member(client_a):
    Provider.objects.create(name="readable")
    assert client_a.get("/api/providers/").status_code == 200


@pytest.mark.django_db
def test_provider_write_denied_for_member(client_a):
    assert (
        client_a.post("/api/providers/", {"name": "x"}, format="json").status_code
        == 403
    )


@pytest.mark.django_db
def test_provider_write_allowed_for_superadmin(superadmin, org_a):
    c = _client(superadmin, org_a)
    assert c.post("/api/providers/", {"name": "x"}, format="json").status_code == 201


# ---- cross-org reference rejection on Agent ----


@pytest.mark.django_db
def test_agent_cannot_reference_other_orgs_llmconfig(member_a, org_a, org_b):
    # Member has agents CRU, so the create itself is permitted; the cross-org
    # llm_config ref must be the thing that fails (rejected like a missing pk).
    client = _client(member_a, org_a)
    m = _builtin_model()
    other_cfg = LLMConfig.objects.create(custom_name="B cfg", model=m, org=org_b)
    resp = client.post(
        "/api/agents/",
        {"role": "r", "goal": "g", "backstory": "b", "llm_config": other_cfg.id},
        format="json",
    )
    assert resp.status_code == 400
    # the custom exception handler nests field errors inside `message`
    assert "llm_config" in str(resp.data)


@pytest.mark.django_db
def test_agent_can_reference_same_org_llmconfig(member_a, org_a):
    client = _client(member_a, org_a)
    m = _builtin_model()
    cfg = LLMConfig.objects.create(custom_name="A cfg", model=m, org=org_a)
    resp = client.post(
        "/api/agents/",
        {"role": "r", "goal": "g", "backstory": "b", "llm_config": cfg.id},
        format="json",
    )
    assert resp.status_code == 201
    assert Agent.objects.get(id=resp.data["id"]).llm_config_id == cfg.id
