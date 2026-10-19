import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from rbac.access.catalog import applicable_actions_for, build_catalog
from rbac.models.enums import BuiltInRole, Permission, ResourceType
from rbac.models.role import Role, RolePermission

CHATS_ACTIONS = ["create", "read", "update", "delete", "use"]


def test_chats_resource_type_exists():
    assert ResourceType.CHATS == "chats"
    assert applicable_actions_for("chats") == CHATS_ACTIONS


@override_settings(CHAT_ENABLED=True)
def test_catalog_lists_chats_when_enabled():
    codes = [entry["code"] for entry in build_catalog()["resource_types"]]
    assert "chats" in codes


@override_settings(CHAT_ENABLED=False)
def test_catalog_hides_chats_when_disabled():
    codes = [entry["code"] for entry in build_catalog()["resource_types"]]
    assert "chats" not in codes
    assert applicable_actions_for("chats") == CHATS_ACTIONS


@pytest.mark.django_db
@override_settings(CHAT_ENABLED=True)
def test_catalog_endpoint_includes_chats(auth_client):
    response = auth_client.get(reverse("permissions_catalog"))

    assert response.status_code == status.HTTP_200_OK, response.content
    entry = next(item for item in response.data["resource_types"] if item["code"] == "chats")
    assert entry["applicable_actions"] == CHATS_ACTIONS
    assert entry["group"] == "workspace"


@pytest.mark.django_db
def test_builtin_roles_grant_chats(heal_builtin_roles):
    admin = Role.objects.get(name=BuiltInRole.ORG_ADMIN, org__isnull=True)
    member = Role.objects.get(name=BuiltInRole.MEMBER, org__isnull=True)
    viewer = Role.objects.get(name=BuiltInRole.VIEWER, org__isnull=True)

    admin_mask = RolePermission.objects.get(role=admin, resource_type="chats").permissions
    member_mask = RolePermission.objects.get(role=member, resource_type="chats").permissions
    assert admin_mask & Permission.USE and admin_mask & Permission.DELETE
    assert member_mask == Permission.READ | Permission.USE
    assert not RolePermission.objects.filter(role=viewer, resource_type="chats").exists()
