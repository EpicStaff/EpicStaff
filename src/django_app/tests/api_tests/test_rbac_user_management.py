"""/api/admin/users/: the superadmin-only user directory."""

from importlib import import_module

import pytest
from django.db.migrations.loader import MigrationLoader
from rest_framework import status
from rest_framework.test import APIClient

from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole

USERS_LIST = "/api/admin/users/"


def user_action_url(user_id, action):
    return f"/api/admin/users/{user_id}/{action}/"


@pytest.fixture
def role_superadmin(db):
    return Role.objects.get(name=BuiltInRole.SUPERADMIN, is_built_in=True, org__isnull=True)


@pytest.fixture
def role_org_admin(db):
    return Role.objects.get(name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True)


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def org_acme(db):
    return Organization.objects.create(name="Acme Inc")


@pytest.fixture
def org_globex(db):
    return Organization.objects.create(name="Globex Corp")


@pytest.fixture
def make_user(django_user_model):
    def _make(email, org=None, role=None, **fields):
        user = django_user_model.objects.create_user(email=email, password="StrongPass123!", **fields)
        if org is not None:
            OrganizationUser.objects.create(user=user, org=org, role=role)
        return user

    return _make


@pytest.fixture
def superadmin(make_user, org_acme, role_superadmin):
    return make_user("sa@x.com", org_acme, role_superadmin, is_superadmin=True)


@pytest.fixture
def org_admin_acme(make_user, org_acme, role_org_admin):
    return make_user("oa@x.com", org_acme, role_org_admin)


@pytest.fixture
def member_acme(make_user, org_acme, role_member):
    return make_user("m@x.com", org_acme, role_member)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _emails(response):
    return [user["email"] for user in response.data["results"]]


# ---- Permission gates ----


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "action"),
    [("get", None), ("post", "grant-superadmin"), ("post", "deactivate")],
    ids=["list", "grant-superadmin", "deactivate"],
)
@pytest.mark.parametrize(
    ("caller", "expected"),
    [
        ("anonymous", status.HTTP_401_UNAUTHORIZED),
        ("member", status.HTTP_403_FORBIDDEN),
        ("org-admin", status.HTTP_403_FORBIDDEN),
        # An API key bound to a user inherits exactly that user's permissions.
        ("member-api-key", status.HTTP_403_FORBIDDEN),
        ("system-api-key", status.HTTP_403_FORBIDDEN),
    ],
)
def test_only_a_superadmin_reaches_the_user_directory(
    member_acme, org_admin_acme, issue_api_key, method, action, caller, expected
):
    if caller in ("member", "org-admin"):
        client = client_for(member_acme if caller == "member" else org_admin_acme)
    else:
        client = APIClient()
        if caller.endswith("api-key"):
            raw, _ = issue_api_key(user=member_acme if caller == "member-api-key" else None, name=caller)
            client.credentials(HTTP_X_API_KEY=raw)
    url = USERS_LIST if action is None else user_action_url(member_acme.pk, action)

    response = getattr(client, method)(url)

    assert response.status_code == expected
    member_acme.refresh_from_db()
    assert (member_acme.is_superadmin, member_acme.is_active) == (False, True)


# ---- Listing ----


@pytest.fixture
def directory(superadmin, member_acme, org_acme, org_globex, role_member, make_user):
    """sa@x.com (superadmin, acme), m@x.com "Zaphod" (member, acme), globex@x.com
    (member, globex), both@x.com (acme + globex), lone-sa@x.com (superadmin, no org),
    off@x.com (inactive, acme)."""
    member_acme.display_name = "Zaphod"
    member_acme.save(update_fields=["display_name"])
    make_user("globex@x.com", org_globex, role_member)
    both = make_user("both@x.com", org_acme, role_member)
    OrganizationUser.objects.create(user=both, org=org_globex, role=role_member)
    make_user("lone-sa@x.com", is_superadmin=True)
    make_user("off@x.com", org_acme, role_member, is_active=False)
    return {"acme": org_acme.pk, "globex": org_globex.pk, "member_role": role_member.pk}


EVERYONE = {"sa@x.com", "m@x.com", "globex@x.com", "both@x.com", "lone-sa@x.com", "off@x.com"}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("", EVERYONE),
        ("email=m@", {"m@x.com"}),
        ("is_superadmin=true", {"sa@x.com", "lone-sa@x.com"}),
        ("organization_id={globex}", {"globex@x.com", "both@x.com"}),
        # Only accounts with a membership there; a superadmin without one is not in the org.
        ("org_ids={acme}", {"sa@x.com", "m@x.com", "both@x.com", "off@x.com"}),
        ("org_ids={acme},{globex}", {"sa@x.com", "m@x.com", "globex@x.com", "both@x.com", "off@x.com"}),
        ("org_ids=,", set()),
        ("org_ids=", EVERYONE),
        ("org_ids={globex}&organization_id={acme}", {"globex@x.com", "both@x.com"}),
        ("search=zaph", {"m@x.com"}),
        ("search=m@", {"m@x.com"}),
        ("search=zaph&email=sa@", {"m@x.com"}),
        ("status=active", EVERYONE - {"off@x.com"}),
        ("status=inactive", {"off@x.com"}),
        ("role_id={member_role}", {"m@x.com", "globex@x.com", "both@x.com", "off@x.com"}),
        ("role_id={member_role}&org_ids={globex}", {"globex@x.com", "both@x.com"}),
    ],
)
def test_list_filters(superadmin, directory, query, expected):
    response = client_for(superadmin).get(f"{USERS_LIST}?{query.format(**directory)}")

    assert response.status_code == status.HTTP_200_OK
    assert set(response.data) == {"count", "next", "previous", "results"}
    emails = _emails(response)
    assert sorted(emails) == sorted(expected)  # also: an account in two requested orgs appears once


@pytest.mark.django_db
def test_listed_memberships_are_not_narrowed_by_the_org_filter(superadmin, directory):
    response = client_for(superadmin).get(f"{USERS_LIST}?org_ids={directory['acme']}")

    row = next(user for user in response.data["results"] if user["email"] == "both@x.com")
    assert {membership["organization"]["id"] for membership in row["memberships"]} == {
        directory["acme"],
        directory["globex"],
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("query", "code"),
    [("org_ids=abc", "org_context_required"), ("status=bogus", "invalid"), ("role_id=abc", "invalid")],
)
def test_list_rejects_malformed_filters(superadmin, query, code):
    response = client_for(superadmin).get(f"{USERS_LIST}?{query}")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == code


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("ordering", "expected"),
    [
        ("", ["m@x.com", "sa@x.com"]),
        ("?ordering=bogus", ["m@x.com", "sa@x.com"]),
        ("?ordering=email", ["m@x.com", "sa@x.com"]),
        ("?ordering=-email", ["sa@x.com", "m@x.com"]),
    ],
    ids=["default-newest-first", "unknown-key-falls-back", "email", "email-descending"],
)
def test_list_ordering(superadmin, member_acme, ordering, expected):
    response = client_for(superadmin).get(USERS_LIST + ordering)

    assert response.status_code == status.HTTP_200_OK
    assert _emails(response) == expected


@pytest.mark.django_db
def test_the_user_directory_never_shows_custom_shortcuts(superadmin, member_acme):
    member_acme.custom_shortcuts = {"custom": [{"action": "node.task", "keys": "Shift+KeyT"}]}
    member_acme.save(update_fields=["custom_shortcuts"])

    response = client_for(superadmin).get(USERS_LIST)

    assert response.status_code == status.HTTP_200_OK
    row = next(user for user in response.data["results"] if user["email"] == member_acme.email)
    assert "custom_shortcuts" not in row


# ---- Creating ----


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("body", "expected_display_name"),
    [
        ({"email": "anna-maria@x.com"}, "Anna Maria"),
        ({"email": "anna-maria@x.com", "display_name": None}, "Anna Maria"),
        ({"email": "new@x.com", "display_name": "  Jane Doe  "}, "Jane Doe"),
        ({"email": "new@x.com", "display_name": "x" * 255}, "x" * 255),
    ],
    ids=["derived", "null-derived", "trimmed", "max-length"],
)
def test_create_user_without_an_org(superadmin, django_user_model, body, expected_display_name):
    response = client_for(superadmin).post(
        USERS_LIST, {"password": "StrongPass123!", **body}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert (response.data["email"], response.data["display_name"]) == (body["email"], expected_display_name)
    assert (response.data["memberships"], response.data["is_superadmin"]) == ([], False)
    assert django_user_model.objects.get(email=body["email"]).display_name == expected_display_name


@pytest.mark.django_db
@pytest.mark.parametrize("with_role", [True, False], ids=["given-role", "defaults-to-member"])
def test_create_user_into_an_org(superadmin, org_acme, role_member, role_org_admin, with_role):
    role = role_org_admin if with_role else role_member
    body = {"email": "new2@x.com", "password": "StrongPass123!", "organization_id": org_acme.pk}
    if with_role:
        body["role_id"] = role.pk

    response = client_for(superadmin).post(USERS_LIST, body, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    (membership,) = response.data["memberships"]
    assert (membership["organization"]["id"], membership["role"]["id"]) == (org_acme.pk, role.pk)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"display_name": "   "}, [{"field": "display_name", "value": "   ",
                                    "reason": "Must not be blank. Omit it or use null to derive it from the email."}]),
        ({"display_name": "x" * 256}, [{"field": "display_name", "value": "x" * 256,
                                        "reason": "Must be 255 characters or fewer."}]),
        ({"display_name": 123}, [{"field": "display_name", "value": 123, "reason": "Must be a string or null."}]),
        ({"email": "not-an-email", "display_name": "   "}, {"email", "display_name"}),
        ({"email": "not-an-email"}, {"email"}),
        ({"password": "123"}, {"password"}),
    ],
    ids=["blank-display-name", "too-long-display-name", "non-string-display-name",
         "email-and-display-name", "bad-email", "weak-password"],
)
def test_create_user_rejects_invalid_input(superadmin, django_user_model, body, expected):
    response = client_for(superadmin).post(
        USERS_LIST, {"email": "new@x.com", "password": "StrongPass123!", **body}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "invalid"
    errors = response.data["errors"]
    if isinstance(expected, set):
        assert expected <= {error["field"] for error in errors}
    else:
        assert errors == expected
    assert all(error["value"] == "***" for error in errors if error["field"] == "password")
    assert django_user_model.objects.count() == 1


@pytest.mark.django_db
def test_create_user_with_a_taken_email_is_rejected(superadmin):
    client = client_for(superadmin)
    client.post(USERS_LIST, {"email": "dup@x.com", "password": "StrongPass123!"}, format="json")

    response = client.post(USERS_LIST, {"email": "dup@x.com", "password": "StrongPass123!"}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "email_already_exists"


# ---- Superadmin flag and activation ----


@pytest.fixture
def second_superadmin(make_user, org_acme, role_superadmin):
    return make_user("sa2@x.com", org_acme, role_superadmin, is_superadmin=True)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("target", "action", "with_second_superadmin", "field", "value"),
    [
        ("member", "grant-superadmin", False, "is_superadmin", True),
        ("self", "grant-superadmin", False, "is_superadmin", True),
        ("second", "revoke-superadmin", True, "is_superadmin", False),
        ("self", "revoke-superadmin", True, "is_superadmin", False),
        ("member", "revoke-superadmin", False, "is_superadmin", False),
        ("member", "deactivate", False, "is_active", False),
    ],
    ids=["grant", "grant-idempotent", "revoke-other", "revoke-self-not-last", "revoke-idempotent", "deactivate"],
)
def test_superadmin_flag_and_activation_changes(
    superadmin, member_acme, second_superadmin, target, action, with_second_superadmin, field, value
):
    if not with_second_superadmin:
        second_superadmin.delete()
    user = {"member": member_acme, "self": superadmin, "second": second_superadmin}[target]

    response = client_for(superadmin).post(user_action_url(user.pk, action))

    assert response.status_code == status.HTTP_200_OK
    assert response.data[field] is value
    user.refresh_from_db()
    assert getattr(user, field) is value


@pytest.mark.django_db
def test_a_deactivated_user_can_be_reactivated(superadmin, member_acme):
    client = client_for(superadmin)
    client.post(user_action_url(member_acme.pk, "deactivate"))

    response = client.post(user_action_url(member_acme.pk, "reactivate"))

    assert (response.status_code, response.data["is_active"]) == (status.HTTP_200_OK, True)


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["revoke-superadmin", "deactivate"])
def test_the_last_active_superadmin_cannot_be_removed(superadmin, action):
    response = client_for(superadmin).post(user_action_url(superadmin.pk, action))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["code"] == "last_superadmin"
    superadmin.refresh_from_db()
    assert (superadmin.is_superadmin, superadmin.is_active) == (True, True)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("post", user_action_url(99999, "grant-superadmin")),
        # A non-numeric pk is a URL-resolver 404, not a 500.
        ("post", "/api/admin/users/a/grant-superadmin/"),
        ("post", "/api/admin/users/abc/revoke-superadmin/"),
        ("post", "/api/admin/users/-1/grant-superadmin/"),
        ("post", "/api/admin/organizations/abc/deactivate/"),
        ("patch", "/api/admin/organizations/abc/"),
    ],
)
def test_unknown_or_malformed_ids_are_404(superadmin, method, url):
    response = getattr(client_for(superadmin), method)(url, {"name": "X"}, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_granting_superadmin_drops_org_memberships_and_revoking_does_not_restore_them(
    superadmin, org_acme, org_globex, role_member, role_org_admin, make_user
):
    target = make_user("promote@x.com", org_acme, role_org_admin)
    OrganizationUser.objects.create(user=target, org=org_globex, role=role_member)
    client = client_for(superadmin)

    granted = client.post(user_action_url(target.pk, "grant-superadmin"))
    revoked = client.post(user_action_url(target.pk, "revoke-superadmin"))

    assert (granted.data["is_superadmin"], granted.data["memberships"]) == (True, [])
    assert (revoked.data["is_superadmin"], revoked.data["memberships"]) == (False, [])
    assert not OrganizationUser.objects.filter(user=target).exists()


@pytest.mark.django_db
def test_granting_an_existing_superadmin_writes_nothing(superadmin, org_acme, role_member, make_user):
    """It short-circuits before any write, so a pre-existing row survives; the data
    migration below reconciles those."""
    target = make_user("already@x.com", org_acme, role_member, is_superadmin=True)

    response = client_for(superadmin).post(user_action_url(target.pk, "grant-superadmin"))

    assert response.status_code == status.HTTP_200_OK
    assert OrganizationUser.objects.filter(user=target).count() == 1


@pytest.mark.django_db
def test_superadmin_membership_migration_purges_lesser_roles_but_keeps_bootstrap(
    org_acme, role_member, role_org_admin, role_superadmin, make_user
):
    sa_lesser = make_user("legacy-sa@x.com", org_acme, role_org_admin, is_superadmin=True)
    sa_bootstrap = make_user("bootstrap-sa@x.com", org_acme, role_superadmin, is_superadmin=True)
    ordinary = make_user("ordinary@x.com", org_acme, role_member)

    # The migration resolves `tables.OrganizationUser`, which only exists in
    # the historical state: the model has since moved to `rbac`.
    migration_name = "0211_purge_superadmin_memberships"
    historical_apps = (
        MigrationLoader(None, ignore_no_migrations=True).project_state(("tables", migration_name)).apps
    )
    module = import_module(f"tables.migrations.{migration_name}")
    module.purge_superadmin_memberships(historical_apps, None)

    assert not OrganizationUser.objects.filter(user=sa_lesser).exists()
    assert OrganizationUser.objects.filter(user=sa_bootstrap).exists()
    assert OrganizationUser.objects.filter(user=ordinary).exists()

    module.purge_superadmin_memberships(historical_apps, None)
    assert OrganizationUser.objects.filter(user=sa_bootstrap).count() == 1
    assert OrganizationUser.objects.filter(user=ordinary).count() == 1
