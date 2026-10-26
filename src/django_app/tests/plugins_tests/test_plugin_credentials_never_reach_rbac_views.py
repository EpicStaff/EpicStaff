"""rbac's views never read a plugin credential: they pin people's authentication or refuse it."""

import pytest
from plugins.identity.service_account_authentication import PluginServiceAccountAuthentication
from rbac.access.gates import DenyApiKeyAuth, DenyPluginCredential

from tests.plugins_tests.view_walker import drf_views

pytestmark = [pytest.mark.django_db]


def test_every_rbac_view_pins_people_s_authentication_or_refuses_plugin_credentials(plugins_enabled):
    exposed = sorted(
        {
            f"{view.dotted_path} ({view.route})"
            for view in drf_views()
            if view.dotted_path.startswith("rbac.")
            and any(issubclass(authenticator, PluginServiceAccountAuthentication) for authenticator in view.authentication_classes)
            and not all(
                any(issubclass(permission, (DenyApiKeyAuth, DenyPluginCredential)) for permission in permissions)
                for permissions in view.permission_classes_by_action.values()
            )
        }
    )

    assert exposed == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/profile/"),
        ("get", "/api/permissions/me/"),
        ("get", "/api/admin/organizations/"),
        ("post", "/api/auth/ws-ticket/"),
        ("post", "/api/auth/sse-ticket/"),
        ("get", "/api/admin/roles/"),
    ],
)
def test_a_real_key_gets_nothing_from_rbac(weather_client, method, path):
    response = getattr(weather_client, method)(path, {}, format="json")

    assert response.status_code in (401, 403)
