"""Iteration 6 (EmbeddingModel half) of the backend bulk-delete rollout.

`EmbeddingConfig.model = ForeignKey(EmbeddingModel, on_delete=SET_NULL)` --
unlike LLMModel/LLMConfig (CASCADE), deleting an EmbeddingModel only nulls
the reference; the EmbeddingConfig row survives. So the guard here is plain
one-hop (is the referencing EmbeddingConfig visible), with no cascade-aware
check into that config's own downstream usage -- deleting a model never
force-deletes a config, so there's nothing to cascade-protect.
"""

import pytest
from rest_framework.test import APIClient

from tables.models import Crew, EmbeddingConfig, EmbeddingModel
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
    return EmbeddingModel.objects.create(
        org=org, name=name, is_custom=True, predefined=False
    )


def _predefined_model(name="predef"):
    return EmbeddingModel.objects.create(
        org=None, name=name, is_custom=False, predefined=True
    )


@pytest.mark.django_db
def test_bulk_delete_happy_path(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    m1, m2 = _custom_model(org_a, "m1"), _custom_model(org_a, "m2")

    resp = client.post(
        "/api/embedding-models/bulk-delete/", {"ids": [m1.id, m2.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert sorted(resp.data["deleted_ids"]) == sorted([m1.id, m2.id])
    assert not EmbeddingModel.objects.filter(id__in=[m1.id, m2.id]).exists()


@pytest.mark.django_db
def test_bulk_delete_cross_org_id_not_found(django_user_model, org_a, org_b):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    other = _custom_model(org_b, "other")

    resp = client.post(
        "/api/embedding-models/bulk-delete/", {"ids": [other.id]}, format="json"
    )

    assert resp.status_code == 207, resp.data
    assert resp.data["not_found_ids"] == [other.id]


@pytest.mark.django_db
def test_bulk_delete_empty_ids_rejected(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")

    resp = client.post("/api/embedding-models/bulk-delete/", {"ids": []}, format="json")

    assert resp.status_code == 400


@pytest.mark.django_db
def test_bulk_delete_without_delete_permission_forbidden(django_user_model, org_a):
    client = _custom_role_client(
        django_user_model, org_a, "viewer@example.com",
        **{ResourceType.LLM_CONFIGS: Permission.READ},
    )
    m = _custom_model(org_a, "m")

    resp = client.post("/api/embedding-models/bulk-delete/", {"ids": [m.id]}, format="json")

    assert resp.status_code == 403
    assert EmbeddingModel.objects.filter(id=m.id).exists()


@pytest.mark.django_db
def test_bulk_delete_predefined_model_skipped(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    model = _predefined_model("predef")

    resp = client.post(
        "/api/embedding-models/bulk-delete/", {"ids": [model.id]}, format="json"
    )

    assert resp.status_code == 207, resp.data
    assert resp.data["skipped_ids"] == [{"id": model.id, "reason": "predefined"}]
    assert EmbeddingModel.objects.filter(id=model.id).exists()


@pytest.mark.django_db
def test_bulk_delete_custom_model_with_config_proceeds_regardless_of_config_usage(
    django_user_model, org_a
):
    # Confirms NO cascade-aware check for EmbeddingModel: even though the
    # referencing config is itself used by a Crew the caller can't see (via
    # PROJECTS), the model deletion still proceeds (SET_NULL, not cascade).
    client = _custom_role_client(
        django_user_model, org_a, "deleter@example.com",
        **{ResourceType.LLM_CONFIGS: Permission.DELETE | Permission.READ},
    )
    model = _custom_model(org_a, "m")
    config = EmbeddingConfig.objects.create(org=org_a, custom_name="cfg", model=model)
    Crew.objects.create(org=org_a, name="crew", embedding_config=config)

    resp = client.post(
        "/api/embedding-models/bulk-delete/", {"ids": [model.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted_ids"] == [model.id]
    assert not EmbeddingModel.objects.filter(id=model.id).exists()
    config.refresh_from_db()
    assert config.model_id is None  # SET_NULL, config itself survives


@pytest.mark.django_db
def test_bulk_delete_hidden_config_blocked(django_user_model, org_a):
    # No LLM_CONFIGS:READ -> can't see the referencing config at all -> blocked.
    client = _custom_role_client(
        django_user_model, org_a, "deleter2@example.com",
        **{ResourceType.LLM_CONFIGS: Permission.DELETE},
    )
    model = _custom_model(org_a, "m")
    EmbeddingConfig.objects.create(org=org_a, custom_name="cfg", model=model)

    resp = client.post(
        "/api/embedding-models/bulk-delete/", {"ids": [model.id]}, format="json"
    )

    assert resp.status_code == 207, resp.data
    assert resp.data["skipped_ids"] == [{"id": model.id, "reason": "in_use_restricted"}]
    assert EmbeddingModel.objects.filter(id=model.id).exists()


@pytest.mark.django_db
def test_bulk_delete_dry_run_does_not_delete(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    model = _custom_model(org_a, "m")

    resp = client.post(
        "/api/embedding-models/bulk-delete/",
        {"ids": [model.id], "dry_run": True},
        format="json",
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["dry_run"] is True
    assert EmbeddingModel.objects.filter(id=model.id).exists()


@pytest.mark.django_db
def test_single_destroy_predefined_blocked(django_user_model, org_a):
    # Pre-existing behavior, unrelated to this guard:
    # BasePredefinedRestrictedViewSet.get_queryset() already filters
    # predefined=True out of the destroy-action queryset, so get_object()
    # 404s before perform_destroy ever runs -- not a 403.
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    model = _predefined_model("predef")

    resp = client.delete(f"/api/embedding-models/{model.id}/")

    assert resp.status_code == 404, resp.data
    assert EmbeddingModel.objects.filter(id=model.id).exists()
