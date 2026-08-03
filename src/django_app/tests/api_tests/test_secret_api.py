import pytest
from rest_framework.test import APIClient

from tables.models import Secret
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.secrets import secret_encryption


# ---- fixtures ----


@pytest.fixture
def role_org_admin(db):
    return Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def role_viewer(db):
    return Role.objects.get(name=BuiltInRole.VIEWER, is_built_in=True, org__isnull=True)


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


@pytest.fixture
def admin_a(db, django_user_model, org_a, role_org_admin):
    user = django_user_model.objects.create_user(
        email="admin_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_org_admin)
    return user


@pytest.fixture
def member_a(db, django_user_model, org_a, role_member):
    user = django_user_model.objects.create_user(
        email="member_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_member)
    return user


@pytest.fixture
def viewer_a(db, django_user_model, org_a, role_viewer):
    user = django_user_model.objects.create_user(
        email="viewer_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_viewer)
    return user


@pytest.fixture
def client_a(admin_a, org_a):
    client = APIClient()
    client.force_authenticate(user=admin_a)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return client


@pytest.fixture
def member_client_a(member_a, org_a):
    client = APIClient()
    client.force_authenticate(user=member_a)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return client


@pytest.fixture
def viewer_client_a(viewer_a, org_a):
    client = APIClient()
    client.force_authenticate(user=viewer_a)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return client


def _results(resp):
    body = resp.data
    return body["results"] if isinstance(body, dict) and "results" in body else body


# ---- tests ----


@pytest.mark.django_db
def test_create_lands_in_active_org(client_a, org_a):
    resp = client_a.post(
        "/api/secrets/",
        {"name": "OPENAI_KEY", "value": "sk-live-abc123"},
        format="json",
    )
    assert resp.status_code == 201
    secret = Secret.objects.get(id=resp.data["id"])
    assert secret.org_id == org_a.id
    assert secret.created_by is not None


@pytest.mark.django_db
def test_list_only_active_org(client_a, org_a, org_b):
    Secret.objects.create(name="A_SECRET", value="ciphertext-a", org=org_a)
    Secret.objects.create(name="B_SECRET", value="ciphertext-b", org=org_b)
    resp = client_a.get("/api/secrets/")
    assert resp.status_code == 200
    names = {s["name"] for s in _results(resp)}
    assert "A_SECRET" in names
    assert "B_SECRET" not in names


# No patch/put: the viewset exposes create/read/delete only, so those verbs are
# covered by test_update_verbs_are_not_exposed instead.
CROSS_ORG_ACTIONS = [
    ("get", None),
    ("delete", None),
]


@pytest.mark.django_db
@pytest.mark.parametrize("method, payload", CROSS_ORG_ACTIONS)
def test_detail_cross_org_returns_404(client_a, org_b, method, payload):
    other = Secret.objects.create(name="B_SECRET", value="ciphertext-b", org=org_b)
    resp = getattr(client_a, method)(
        f"/api/secrets/{other.id}/", payload, format="json"
    )
    assert resp.status_code == 404

    # Row genuinely untouched.
    other.refresh_from_db()
    assert other.name == "B_SECRET"
    assert Secret.objects.filter(id=other.id).exists()


@pytest.mark.django_db
def test_same_name_allowed_in_two_orgs(client_a, org_a, org_b):
    Secret.objects.create(name="SHARED_NAME", value="ciphertext", org=org_b)
    resp = client_a.post(
        "/api/secrets/",
        {"name": "SHARED_NAME", "value": "sk-live-abc123"},
        format="json",
    )
    assert resp.status_code == 201


@pytest.mark.django_db
def test_request_without_org_header_is_rejected(admin_a):
    client = APIClient()
    client.force_authenticate(user=admin_a)
    resp = client.get("/api/secrets/")
    assert resp.status_code == 400
    assert resp.data["code"] == "org_context_required"


@pytest.mark.django_db
def test_duplicate_name_same_org_returns_400_not_500(client_a, org_a):
    Secret.objects.create(name="OPENAI_KEY", value="ciphertext-a", org=org_a)
    resp = client_a.post(
        "/api/secrets/",
        {"name": "OPENAI_KEY", "value": "sk-live-abc123"},
        format="json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_value_never_appears_in_any_response(client_a):
    create_resp = client_a.post(
        "/api/secrets/",
        {"name": "OPENAI_KEY", "value": "sk-live-abc123"},
        format="json",
    )
    assert "value" not in create_resp.data
    assert create_resp.data["tail"] == "c123"
    secret_id = create_resp.data["id"]

    detail_resp = client_a.get(f"/api/secrets/{secret_id}/")
    assert "value" not in detail_resp.data

    list_resp = client_a.get("/api/secrets/")
    results = _results(list_resp)
    for item in results:
        assert "value" not in item


@pytest.mark.django_db
def test_create_without_value_returns_400(client_a):
    resp = client_a.post("/api/secrets/", {"name": "OPENAI_KEY"}, format="json")
    assert resp.status_code == 400
    # `value` is a plain required field now that there is no update path to omit
    # it on, so this is DRF's standard required-field message.
    assert "This field is required." in resp.data["message"]


@pytest.mark.django_db
def test_created_row_stores_encryptedtext_not_the_posted_text(client_a):
    resp = client_a.post(
        "/api/secrets/",
        {"name": "OPENAI_KEY", "value": "sk-live-abc123"},
        format="json",
    )
    secret = Secret.objects.get(id=resp.data["id"])
    assert secret.value != "sk-live-abc123"
    assert secret_encryption.decrypt(encryptedtext=secret.value) == "sk-live-abc123"


@pytest.mark.django_db
@pytest.mark.parametrize("verb", ["patch", "put"])
def test_update_verbs_are_not_exposed(client_a, org_a, verb):
    """A Secret's name and value are immutable once created — rotating a
    credential means creating a new Secret and repointing the configs at it.

    The rejection is 403 rather than 405 because HasOrgPermission runs in
    DRF's initial() before method dispatch: with no `update`/`partial_update`
    action routed, `view.action` is None, so the action map cannot resolve a
    required permission and the gate fails closed
    (tables/services/rbac/permissions.py:80-83).
    """
    secret = Secret.objects.create(name="IMMUTABLE", value="ciphertext", org=org_a)

    resp = getattr(client_a, verb)(
        f"/api/secrets/{secret.id}/",
        {"name": "RENAMED", "value": "sk-live-new"},
        format="json",
    )

    assert resp.status_code == 403
    secret.refresh_from_db()
    assert secret.name == "IMMUTABLE"
    assert secret.value == "ciphertext"


# No patch entry: the viewset no longer routes it, so there is no RBAC surface
# left to gate — test_update_verbs_are_not_exposed covers the verb instead.
SECRET_ACTIONS = [
    ("get", "/api/secrets/", None),
    ("get", "/api/secrets/{id}/", None),
    ("post", "/api/secrets/", {"name": "X", "value": "sk-live-x"}),
    ("delete", "/api/secrets/{id}/", None),
]


@pytest.mark.django_db
@pytest.mark.parametrize("client_fixture", ["member_client_a", "viewer_client_a"])
@pytest.mark.parametrize("method, path, payload", SECRET_ACTIONS)
def test_member_and_viewer_get_403_on_every_action(
    request, client_fixture, method, path, payload, org_a
):
    secret = Secret.objects.create(name="OPENAI_KEY", value="ciphertext", org=org_a)
    client = request.getfixturevalue(client_fixture)
    resp = getattr(client, method)(path.format(id=secret.id), payload, format="json")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_api_key_auth_cannot_access_secrets(admin_a, org_a, issue_api_key):
    # admin_a has full org-admin bits and would succeed via JWT (see client_a) —
    # this proves DenyApiKeyAuth blocks the API-key path specifically, regardless
    # of the underlying user's permissions.
    raw, _ = issue_api_key(user=admin_a)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw, HTTP_X_ORGANIZATION_ID=str(org_a.id))
    resp = client.get("/api/secrets/")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_leading_and_trailing_whitespace_is_trimmed(client_a):
    # A common paste artifact (clipboard trailing newline, accidental leading
    # space) — not a legitimate part of any real credential, so it's trimmed
    # rather than preserved, unlike stray *internal* whitespace.
    resp = client_a.post(
        "/api/secrets/",
        {"name": "OPENAI_KEY", "value": "  sk-live-abc123\n"},
        format="json",
    )
    assert resp.status_code == 201
    secret = Secret.objects.get(id=resp.data["id"])
    assert secret_encryption.decrypt(encryptedtext=secret.value) == "sk-live-abc123"
