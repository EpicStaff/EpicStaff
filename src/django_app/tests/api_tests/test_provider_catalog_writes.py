"""The provider catalog is global: anyone authenticated reads it, and only a
superadmin on a user session writes it. An API key never writes it — not the
system key and not a superadmin's own key — because one write reaches every
organization (a delete cascades into every org's realtime models)."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from rbac.access.gates import DenyApiKeyAuth
from tables.models import Provider
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

PROVIDERS_URL = "/api/providers/"


def _detail_url(provider):
    return f"{PROVIDERS_URL}{provider.id}/"


def _write(client, method, provider):
    if method == "post":
        return client.post(PROVIDERS_URL, {"name": "created-provider"}, format="json")
    if method == "delete":
        return client.delete(_detail_url(provider))
    return getattr(client, method)(
        _detail_url(provider), {"name": "renamed-provider"}, format="json"
    )


def _catalog():
    return set(Provider.objects.values_list("id", "name"))


TEST_PROVIDER_NAMES = ["catalog-provider", "created-provider", "renamed-provider"]


def _names_written_by_this_test():
    return set(
        Provider.objects.filter(name__in=TEST_PROVIDER_NAMES).values_list("name", flat=True)
    )


WRITE_METHODS = ["post", "put", "patch", "delete"]


@pytest.fixture
def provider(db):
    return Provider.objects.create(name="catalog-provider")


@pytest.fixture
def system_key_client(issue_api_key):
    raw, _ = issue_api_key(user=None, name="system")
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw)
    return client


@pytest.fixture
def superadmin_user_key_client(issue_api_key, superadmin, acme):
    raw, _ = issue_api_key(user=superadmin, org=acme, name="superadmin-key")
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw, HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def key_client(request):
    return request.getfixturevalue(request.param)


KEY_CLIENTS = ["system_key_client", "superadmin_user_key_client"]


@pytest.mark.django_db
class TestApiKeysCannotWriteTheCatalog:
    @pytest.mark.parametrize("key_client", KEY_CLIENTS, indirect=True)
    @pytest.mark.parametrize("method", WRITE_METHODS)
    def test_write_is_refused_and_catalog_unchanged(self, key_client, method, provider):
        catalog_before = _catalog()

        response = _write(key_client, method, provider)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["message"] == DenyApiKeyAuth.message
        assert _catalog() == catalog_before

    @pytest.mark.parametrize("key_client", KEY_CLIENTS, indirect=True)
    def test_read_stays_open(self, key_client, provider):
        response = key_client.get(PROVIDERS_URL)

        assert response.status_code == status.HTTP_200_OK
        assert "catalog-provider" in {row["name"] for row in response.json()["results"]}


@pytest.mark.django_db
class TestSessionWrites:
    @pytest.mark.parametrize(
        "method, expected_status, expected_names",
        [
            ("post", status.HTTP_201_CREATED, {"catalog-provider", "created-provider"}),
            ("put", status.HTTP_200_OK, {"renamed-provider"}),
            ("patch", status.HTTP_200_OK, {"renamed-provider"}),
            ("delete", status.HTTP_204_NO_CONTENT, set()),
        ],
    )
    def test_superadmin_session_writes(
        self, superadmin_client, provider, method, expected_status, expected_names
    ):
        response = _write(superadmin_client, method, provider)

        assert response.status_code == expected_status
        assert _names_written_by_this_test() == expected_names

    @pytest.mark.parametrize("method", WRITE_METHODS)
    def test_regular_user_session_write_is_refused(self, auth_client, provider, method):
        catalog_before = _catalog()

        response = _write(auth_client, method, provider)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert _catalog() == catalog_before
