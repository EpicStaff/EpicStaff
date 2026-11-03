"""A USER API key (a superadmin's too) reads the cross-org admin surface only in
the key's org: every org the request names is replaced by it, and a row of
another org read by id is a 404. A session (JWT) caller is unaffected."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from rbac.models import OrganizationConfig, OrganizationUser, Role

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

ROLES_URL = "/api/admin/roles/"
MEMBERSHIPS_URL = "/api/admin/memberships/"
ASSIGNABLE_USERS_URL = "/api/admin/memberships/assignable-users/"
ORGANIZATIONS_URL = "/api/admin/organizations/"
USERS_URL = "/api/admin/users/"
PLUGIN_ROLE_ROWS_URL = "/api/admin/plugin-role-permissions/rows/"


def plugin_role_permissions_url(role_id):
    return f"/api/admin/plugin-role-permissions/{role_id}/"


def retention_url(org_id):
    return f"/api/admin/organizations/{org_id}/retention/"


@pytest.fixture
def admin_of_both(django_user_model, acme, beta, role_org_admin):
    """Org Admin of Acme and of Beta."""
    user = django_user_model.objects.create_user(
        email="admin-both-scope@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_org_admin)
    OrganizationUser.objects.create(user=user, org=beta, role=role_org_admin)
    return user


@pytest.fixture
def beta_only_member(django_user_model, beta, role_member):
    user = django_user_model.objects.create_user(
        email="beta-only-scope@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=beta, role=role_member)
    return user


@pytest.fixture
def acme_role(acme):
    return Role.objects.create(name="Acme custom", org=acme, is_built_in=False)


@pytest.fixture
def beta_role(beta):
    return Role.objects.create(name="Beta custom", org=beta, is_built_in=False)


@pytest.fixture
def key_client(issue_api_key, acme):
    """Factory → a client authenticated by `user`'s USER key bound to Acme."""

    def _make(user):
        raw_key, _ = issue_api_key(user=user, org=acme)
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw_key)
        return client

    return _make


@pytest.fixture
def superadmin_jwt_client(superadmin):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(superadmin).access_token}"
    )
    return client


@pytest.fixture
def org_data(acme_role, beta_role, admin_of_both, beta_only_member):
    """Rows in both orgs for every list below."""


def _role_org_ids(response):
    return {role["org_id"] for role in response.json()["results"]}


def _membership_org_ids(response):
    return {membership["org"]["id"] for membership in response.json()["results"]}


def _organization_ids(response):
    return {organization["id"] for organization in response.json()["results"]}


def _user_emails(response):
    return {user["email"] for user in response.json()["results"]}


LIST_ORG_IDS = {
    ROLES_URL: _role_org_ids,
    MEMBERSHIPS_URL: _membership_org_ids,
    ORGANIZATIONS_URL: _organization_ids,
}


@pytest.mark.django_db
@pytest.mark.usefixtures("org_data")
@pytest.mark.parametrize("url", LIST_ORG_IDS)
def test_user_key_lists_only_its_org(key_client, admin_of_both, acme, url):
    response = key_client(admin_of_both).get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert LIST_ORG_IDS[url](response) == {acme.id}


@pytest.mark.django_db
@pytest.mark.usefixtures("org_data")
@pytest.mark.parametrize("url", LIST_ORG_IDS)
def test_user_key_list_ignores_other_org_ids(key_client, admin_of_both, acme, beta, url):
    response = key_client(admin_of_both).get(url, {"org_ids": str(beta.id)})

    assert response.status_code == status.HTTP_200_OK, response.content
    assert LIST_ORG_IDS[url](response) == {acme.id}


@pytest.mark.django_db
@pytest.mark.usefixtures("org_data")
def test_user_key_roles_ignore_other_assignable_org_ids(key_client, admin_of_both, acme, beta):
    response = key_client(admin_of_both).get(ROLES_URL, {"assignable_org_ids": str(beta.id)})

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _role_org_ids(response) == {acme.id}


@pytest.mark.django_db
@pytest.mark.usefixtures("org_data")
@pytest.mark.parametrize("url", LIST_ORG_IDS)
def test_superadmin_key_lists_only_its_org(key_client, superadmin, acme, beta, url):
    response = key_client(superadmin).get(url, {"org_ids": str(beta.id)})

    assert response.status_code == status.HTTP_200_OK, response.content
    assert LIST_ORG_IDS[url](response) == {acme.id}


@pytest.mark.django_db
@pytest.mark.usefixtures("org_data")
@pytest.mark.parametrize(
    "query",
    [{}, {"org_ids": "BETA"}, {"organization_id": "BETA"}],
    ids=["absent", "org_ids", "organization_id"],
)
def test_superadmin_key_lists_users_of_its_org_only(
    key_client, superadmin, admin_of_both, beta_only_member, beta, query
):
    query = {name: str(beta.id) for name in query}

    response = key_client(superadmin).get(USERS_URL, query)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _user_emails(response) == {admin_of_both.email}


def _membership_org_ids_of(response, user):
    (row,) = [row for row in response.json()["results"] if row["email"] == user.email]
    return {membership["organization"]["id"] for membership in row["memberships"]}


@pytest.mark.django_db
@pytest.mark.usefixtures("org_data")
def test_superadmin_key_sees_only_its_orgs_memberships_of_a_user(
    key_client, superadmin, admin_of_both, acme
):
    response = key_client(superadmin).get(USERS_URL)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _membership_org_ids_of(response, admin_of_both) == {acme.id}


@pytest.mark.django_db
@pytest.mark.usefixtures("org_data")
def test_superadmin_session_sees_every_membership_of_a_user(
    superadmin_jwt_client, admin_of_both, acme, beta
):
    response = superadmin_jwt_client.get(USERS_URL, {"org_ids": str(acme.id)})

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _membership_org_ids_of(response, admin_of_both) == {acme.id, beta.id}


@pytest.mark.django_db
@pytest.mark.usefixtures("org_data")
@pytest.mark.parametrize("caller", ["admin_of_both", "superadmin"])
def test_key_lists_assignable_users_of_its_org_only(
    request, key_client, admin_of_both, acme, caller
):
    response = key_client(request.getfixturevalue(caller)).get(ASSIGNABLE_USERS_URL)

    assert response.status_code == status.HTTP_200_OK, response.content
    rows = response.json()["results"]
    assert [row["email"] for row in rows] == [admin_of_both.email]
    assert rows[0]["org_ids"] == [acme.id]


@pytest.mark.django_db
@pytest.mark.parametrize("caller", ["admin_of_both", "superadmin"])
def test_key_cannot_open_role_of_other_org(request, key_client, beta_role, caller):
    response = key_client(request.getfixturevalue(caller)).get(f"{ROLES_URL}{beta_role.id}/")

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_key_can_open_role_of_its_org(key_client, admin_of_both, acme_role):
    response = key_client(admin_of_both).get(f"{ROLES_URL}{acme_role.id}/")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json()["id"] == acme_role.id


@pytest.mark.django_db
def test_key_can_open_built_in_role(key_client, admin_of_both, role_member):
    response = key_client(admin_of_both).get(f"{ROLES_URL}{role_member.id}/")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json()["id"] == role_member.id


@pytest.mark.django_db
@pytest.mark.parametrize("caller", ["admin_of_both", "superadmin"])
def test_key_cannot_open_other_organization(request, key_client, beta, caller):
    response = key_client(request.getfixturevalue(caller)).get(f"{ORGANIZATIONS_URL}{beta.id}/")

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_key_can_open_its_organization(key_client, admin_of_both, acme):
    response = key_client(admin_of_both).get(f"{ORGANIZATIONS_URL}{acme.id}/")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json()["id"] == acme.id


@pytest.mark.django_db
@pytest.mark.parametrize("caller", ["admin_of_both", "superadmin"])
def test_key_cannot_read_retention_of_other_organization(request, key_client, beta, caller):
    OrganizationConfig.objects.create(org=beta)

    response = key_client(request.getfixturevalue(caller)).get(retention_url(beta.id))

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_key_reads_retention_of_its_organization(key_client, admin_of_both, acme):
    OrganizationConfig.objects.create(org=acme)

    response = key_client(admin_of_both).get(retention_url(acme.id))

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json()["org_id"] == acme.id


@pytest.mark.django_db
@pytest.mark.parametrize("caller", ["admin_of_both", "superadmin"])
@pytest.mark.parametrize(
    "query", ["absent", "other_org", "malformed"], ids=["absent", "other_org", "malformed"]
)
def test_key_plugin_role_rows_use_key_org(request, key_client, acme, beta, caller, query):
    params = {"absent": {}, "other_org": {"org_id": beta.id}, "malformed": {"org_id": "x"}}

    response = key_client(request.getfixturevalue(caller)).get(
        PLUGIN_ROLE_ROWS_URL, params[query]
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json()["organization"]["id"] == acme.id


@pytest.mark.django_db
@pytest.mark.parametrize("query", [{}, {"org_id": "BETA"}], ids=["absent", "other_org"])
def test_key_plugin_permissions_of_built_in_role_use_key_org(
    key_client, admin_of_both, role_member, acme, beta, query
):
    query = {name: beta.id for name in query}

    response = key_client(admin_of_both).get(plugin_role_permissions_url(role_member.id), query)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json()["organization"]["id"] == acme.id


@pytest.mark.django_db
def test_key_cannot_open_plugin_permissions_of_other_org_role(
    key_client, admin_of_both, beta_role
):
    response = key_client(admin_of_both).get(plugin_role_permissions_url(beta_role.id))

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
@pytest.mark.usefixtures("org_data")
def test_jwt_superadmin_still_sees_every_org(
    superadmin_jwt_client, acme, beta, beta_role, beta_only_member
):
    for url, org_ids_of in LIST_ORG_IDS.items():
        response = superadmin_jwt_client.get(url)
        assert response.status_code == status.HTTP_200_OK, response.content
        assert {acme.id, beta.id} <= org_ids_of(response), url

    beta_users = superadmin_jwt_client.get(USERS_URL, {"org_ids": str(beta.id)})
    assert beta_only_member.email in _user_emails(beta_users)
    assert superadmin_jwt_client.get(f"{ROLES_URL}{beta_role.id}/").status_code == 200
    assert superadmin_jwt_client.get(f"{ORGANIZATIONS_URL}{beta.id}/").status_code == 200
    beta_rows = superadmin_jwt_client.get(PLUGIN_ROLE_ROWS_URL, {"org_id": beta.id})
    assert beta_rows.json()["organization"]["id"] == beta.id


@pytest.mark.django_db
def test_key_role_filter_ignores_a_role_held_in_another_org(
    key_client, superadmin, django_user_model, acme, beta, role_member, role_org_admin
):
    user = django_user_model.objects.create_user(
        email="member-acme-admin-beta@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_member)
    OrganizationUser.objects.create(user=user, org=beta, role=role_org_admin)
    client = key_client(superadmin)

    by_admin_role = client.get(USERS_URL, {"role_id": str(role_org_admin.id)})
    by_member_role = client.get(USERS_URL, {"role_id": str(role_member.id)})

    assert by_admin_role.status_code == status.HTTP_200_OK, by_admin_role.content
    assert user.email not in _user_emails(by_admin_role)
    assert user.email in _user_emails(by_member_role)
