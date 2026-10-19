"""API clients for a user whose custom role holds exactly the permissions a test grants."""

from rbac.models import Organization, OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission
from rest_framework.test import APIClient

FULL_CRUD = int(
    Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE
)


def client_with_grants(
    *, org: Organization, django_user_model, email: str, resource_permissions: dict
):
    """An APIClient for a user whose custom role holds the given per-resource permission bitmasks."""
    role = Role.objects.create(name=f"role-{email}", org=org, is_built_in=False)
    for resource_type, bitmask in resource_permissions.items():
        RolePermission.objects.create(
            role=role, resource_type=resource_type, permissions=bitmask
        )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client
