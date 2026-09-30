"""Authenticated API clients shared by the bulk-delete API test modules.

Each module still defines its own `org_a` / `org_b` fixtures -- three lines
apiece, and the convention across `tests/api_tests/` -- so only the client
setup, which was copied verbatim into every module, lives here.
"""

from rest_framework.test import APIClient

from tables.models.rbac_models import OrganizationUser, Role, RolePermission
from tables.models.rbac_models.rbac_enums import BuiltInRole


def org_admin_client(django_user_model, org, email):
    """A client acting as a built-in Org Admin of `org`."""
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    return _client_for(django_user_model, org, email, role)


def custom_role_client(django_user_model, org, email, **resource_permissions):
    """A client whose role holds exactly `resource_permissions`, nothing else.

    Pass permissions as `**{ResourceType.X: Permission.A | Permission.B}`. Used
    to isolate combinations such as DELETE without READ, which the
    `in_use_restricted` guard depends on.
    """
    role = Role.objects.create(name=f"custom-{email}", is_built_in=False, org=org)
    for resource_type, permissions in resource_permissions.items():
        RolePermission.objects.create(
            role=role, resource_type=resource_type, permissions=int(permissions)
        )
    return _client_for(django_user_model, org, email, role)


def _client_for(django_user_model, org, email, role):
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client
