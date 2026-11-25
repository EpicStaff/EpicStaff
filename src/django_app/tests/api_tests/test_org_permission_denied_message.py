from types import SimpleNamespace

import pytest

from agents.models.surface_models import Surface
from rbac.access.gates import HasOrgPermission
from rbac.models.enums import Permission, ResourceType

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db


@pytest.fixture
def no_surfaces_user(custom_role_user, acme):
    return custom_role_user(acme, "no-surfaces@example.com", {ResourceType.AGENTS: Permission.READ})


@pytest.mark.parametrize(
    ("method", "path", "message"),
    [
        ("get", "/api/surfaces/{id}/usage/", "You do not have permission to read surfaces."),
        ("post", "/api/surfaces/", "You do not have permission to create surfaces."),
        ("patch", "/api/surfaces/{id}/", "You do not have permission to update surfaces."),
        ("delete", "/api/surfaces/{id}/", "You do not have permission to delete surfaces."),
    ],
    ids=["custom-action", "create", "partial-update", "destroy"],
)
def test_denial_names_the_missing_permission(client_as, no_surfaces_user, acme, method, path, message):
    surface = Surface.objects.create(name="shared", org=acme)
    client = client_as(no_surfaces_user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = getattr(client, method)(path.format(id=surface.pk), {}, format="json")

    assert response.status_code == 403, response.content
    assert response.json()["message"] == message


def test_combined_requirement_names_each_alternative(no_surfaces_user, acme):
    gate = HasOrgPermission()
    request = SimpleNamespace(user=no_surfaces_user, auth=None, headers={"X-Organization-Id": str(acme.id)})
    view = SimpleNamespace(
        rbac_resource_type=ResourceType.SURFACES,
        rbac_action_map={"read_or_use": Permission.READ | Permission.USE},
        action="read_or_use",
        kwargs={},
    )

    assert gate.has_permission(request, view) is False
    assert gate.message == "You do not have permission to read or use surfaces."
