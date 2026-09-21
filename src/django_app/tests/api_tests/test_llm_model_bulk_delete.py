"""Iteration 6 (LLMModel half) of the backend bulk-delete rollout.

`LLMConfig.model = ForeignKey(LLMModel, on_delete=CASCADE)` -- deleting an
LLMModel force-deletes referencing LLMConfig rows, so the guard here is
cascade-aware: it reuses `llm_config_delete_service.get_usage` to check
whether each cascaded LLMConfig is itself safe to lose, not just whether the
model-to-config link is visible. Contrast with EmbeddingModel (SET_NULL,
plain one-hop) in test_embedding_model_bulk_delete.py.
"""

import pytest
from rest_framework.test import APIClient

from tables.models import Agent, LLMConfig, LLMModel
from tables.models.rbac_models import Organization, OrganizationUser, Role, RolePermission
from tables.models.rbac_models.rbac_enums import BuiltInRole, Permission, ResourceType


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _org_admin_client(django_user_model, org, email):
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return c


def _custom_role_client(django_user_model, org, email, **resource_permissions):
    role = Role.objects.create(name=f"custom-{email}", is_built_in=False, org=org)
    for resource_type, permissions in resource_permissions.items():
        RolePermission.objects.create(
            role=role, resource_type=resource_type, permissions=int(permissions)
        )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return c


def _custom_model(org, name="m"):
    return LLMModel.objects.create(org=org, name=name, is_custom=True, predefined=False)


def _predefined_model(name="predef"):
    return LLMModel.objects.create(org=None, name=name, is_custom=False, predefined=True)


@pytest.mark.django_db
def test_bulk_delete_happy_path(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    m1, m2 = _custom_model(org_a, "m1"), _custom_model(org_a, "m2")

    resp = client.post(
        "/api/llm-models/bulk-delete/", {"ids": [m1.id, m2.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert sorted(resp.data["deleted_ids"]) == sorted([m1.id, m2.id])
    assert not LLMModel.objects.filter(id__in=[m1.id, m2.id]).exists()


@pytest.mark.django_db
def test_bulk_delete_cross_org_id_not_found(django_user_model, org_a, org_b):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    other = _custom_model(org_b, "other")

    resp = client.post("/api/llm-models/bulk-delete/", {"ids": [other.id]}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["not_found_ids"] == [other.id]


@pytest.mark.django_db
def test_bulk_delete_nonexistent_id_not_found(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")

    resp = client.post("/api/llm-models/bulk-delete/", {"ids": [999999]}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["not_found_ids"] == [999999]


@pytest.mark.django_db
def test_bulk_delete_duplicate_ids_deleted_once(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    m = _custom_model(org_a, "m")

    resp = client.post("/api/llm-models/bulk-delete/", {"ids": [m.id, m.id]}, format="json")

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_count"] == 1
    assert resp.data["deleted_ids"] == [m.id]


@pytest.mark.django_db
def test_bulk_delete_empty_ids_rejected(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")

    resp = client.post("/api/llm-models/bulk-delete/", {"ids": []}, format="json")

    assert resp.status_code == 400


@pytest.mark.django_db
def test_bulk_delete_without_delete_permission_forbidden(django_user_model, org_a):
    client = _custom_role_client(
        django_user_model, org_a, "viewer@example.com",
        **{ResourceType.LLM_CONFIGS: Permission.READ},
    )
    m = _custom_model(org_a, "m")

    resp = client.post("/api/llm-models/bulk-delete/", {"ids": [m.id]}, format="json")

    assert resp.status_code == 403
    assert LLMModel.objects.filter(id=m.id).exists()


@pytest.mark.django_db
def test_bulk_delete_predefined_model_skipped(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    model = _predefined_model("predef")

    resp = client.post("/api/llm-models/bulk-delete/", {"ids": [model.id]}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["skipped_ids"] == [{"id": model.id, "reason": "predefined"}]
    assert LLMModel.objects.filter(id=model.id).exists()
    assert str(model.id) not in resp.data["usage"]


@pytest.mark.django_db
def test_bulk_delete_custom_model_with_fully_visible_config_proceeds_and_cascades(
    django_user_model, org_a
):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    model = _custom_model(org_a, "m")
    config = LLMConfig.objects.create(org=org_a, custom_name="cfg", model=model)
    agent = Agent.objects.create(
        org=org_a, role="r", goal="g", backstory="b", llm_config=config
    )

    resp = client.post("/api/llm-models/bulk-delete/", {"ids": [model.id]}, format="json")

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_ids"] == [model.id]
    assert not LLMModel.objects.filter(id=model.id).exists()
    assert not LLMConfig.objects.filter(id=config.id).exists()  # cascaded
    agent.refresh_from_db()
    assert agent.llm_config_id is None


@pytest.mark.django_db
def test_bulk_delete_custom_model_with_cascaded_blocked_config_is_blocked(
    django_user_model, org_a
):
    # Caller can manage LLM_CONFIGS (models+configs) but cannot see AGENTS --
    # the cascaded LLMConfig is itself blocked, so deleting the model must be
    # blocked too, even though the model->config link is fully visible.
    client = _custom_role_client(
        django_user_model, org_a, "deleter@example.com",
        **{ResourceType.LLM_CONFIGS: Permission.DELETE | Permission.READ},
    )
    model = _custom_model(org_a, "m")
    config = LLMConfig.objects.create(org=org_a, custom_name="cfg", model=model)
    Agent.objects.create(org=org_a, role="r", goal="g", backstory="b", llm_config=config)

    resp = client.post("/api/llm-models/bulk-delete/", {"ids": [model.id]}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["skipped_ids"] == [{"id": model.id, "reason": "in_use_restricted"}]
    assert LLMModel.objects.filter(id=model.id).exists()
    assert LLMConfig.objects.filter(id=config.id).exists()
    usage = resp.data["usage"][str(model.id)]
    assert usage["blocked"] is True


@pytest.mark.django_db
def test_bulk_delete_mixed_predefined_and_blocked_and_deletable(django_user_model, org_a):
    client = _custom_role_client(
        django_user_model, org_a, "deleter2@example.com",
        **{ResourceType.LLM_CONFIGS: Permission.DELETE | Permission.READ},
    )
    predefined = _predefined_model("predef")
    blocked_model = _custom_model(org_a, "blocked")
    blocked_config = LLMConfig.objects.create(
        org=org_a, custom_name="cfg", model=blocked_model
    )
    Agent.objects.create(
        org=org_a, role="r", goal="g", backstory="b", llm_config=blocked_config
    )
    deletable_model = _custom_model(org_a, "deletable")

    resp = client.post(
        "/api/llm-models/bulk-delete/",
        {"ids": [predefined.id, blocked_model.id, deletable_model.id]},
        format="json",
    )

    assert resp.status_code == 207, resp.data
    assert resp.data["deleted_ids"] == [deletable_model.id]
    skipped_by_id = {s["id"]: s["reason"] for s in resp.data["skipped_ids"]}
    assert skipped_by_id == {
        predefined.id: "predefined",
        blocked_model.id: "in_use_restricted",
    }


@pytest.mark.django_db
def test_bulk_delete_dry_run_does_not_delete(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    model = _custom_model(org_a, "m")

    resp = client.post(
        "/api/llm-models/bulk-delete/", {"ids": [model.id], "dry_run": True}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["dry_run"] is True
    assert LLMModel.objects.filter(id=model.id).exists()


@pytest.mark.django_db
def test_single_destroy_predefined_blocked(django_user_model, org_a):
    # Pre-existing behavior, unrelated to this guard:
    # BasePredefinedRestrictedViewSet.get_queryset() already filters
    # predefined=True out of the destroy-action queryset, so get_object()
    # 404s before perform_destroy ever runs -- not a 403.
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    model = _predefined_model("predef")

    resp = client.delete(f"/api/llm-models/{model.id}/")

    assert resp.status_code == 404, resp.data
    assert LLMModel.objects.filter(id=model.id).exists()


@pytest.mark.django_db
def test_single_destroy_cascaded_blocked_config(django_user_model, org_a):
    client = _custom_role_client(
        django_user_model, org_a, "deleter3@example.com",
        **{ResourceType.LLM_CONFIGS: Permission.DELETE | Permission.READ},
    )
    model = _custom_model(org_a, "m")
    config = LLMConfig.objects.create(org=org_a, custom_name="cfg", model=model)
    Agent.objects.create(org=org_a, role="r", goal="g", backstory="b", llm_config=config)

    resp = client.delete(f"/api/llm-models/{model.id}/")

    assert resp.status_code == 403, resp.data
    assert LLMModel.objects.filter(id=model.id).exists()
