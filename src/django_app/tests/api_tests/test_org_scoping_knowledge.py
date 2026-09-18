import pytest
from rest_framework.test import APIClient

from tables.models import SourceCollection
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


# ---- fixtures ----


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def role_admin(db):
    return Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _user(django_user_model, org, role, email):
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


def _client(user, org):
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return c


@pytest.fixture
def client_member(db, django_user_model, org_a, role_member):  # knowledge READ only
    return _client(
        _user(django_user_model, org_a, role_member, "km@example.com"), org_a
    )


@pytest.fixture
def client_admin(db, django_user_model, org_a, role_admin):  # knowledge CRUD
    return _client(_user(django_user_model, org_a, role_admin, "ka@example.com"), org_a)


def _results(resp):
    body = resp.data
    return body["results"] if isinstance(body, dict) and "results" in body else body


# ---- SourceCollection (top-level, KNOWLEDGE_SOURCES) ----


@pytest.mark.django_db
def test_collection_list_only_active_org(client_member, org_a, org_b):
    SourceCollection.objects.create(collection_name="A coll", org=org_a)
    SourceCollection.objects.create(collection_name="B coll", org=org_b)
    names = {
        c["collection_name"]
        for c in _results(client_member.get("/api/source-collections/"))
    }
    assert "A coll" in names and "B coll" not in names


@pytest.mark.django_db
def test_collection_retrieve_cross_org_404(client_member, org_b):
    other = SourceCollection.objects.create(collection_name="B coll", org=org_b)
    assert (
        client_member.get(f"/api/source-collections/{other.collection_id}/").status_code
        == 404
    )


@pytest.mark.django_db
def test_collection_create_lands_in_active_org(client_admin, org_a):
    resp = client_admin.post(
        "/api/source-collections/", {"collection_name": "New"}, format="json"
    )
    assert resp.status_code == 201, resp.data
    assert (
        SourceCollection.objects.get(collection_id=resp.data["collection_id"]).org_id
        == org_a.id
    )


@pytest.mark.django_db
def test_collection_create_denied_for_member(client_member):
    resp = client_member.post(
        "/api/source-collections/", {"collection_name": "Nope"}, format="json"
    )
    assert resp.status_code == 403  # Member has knowledge_sources READ only


@pytest.mark.django_db
def test_two_orgs_reuse_collection_name(client_admin, org_b):
    SourceCollection.objects.create(collection_name="Shared", org=org_b)
    resp = client_admin.post(
        "/api/source-collections/", {"collection_name": "Shared"}, format="json"
    )
    assert resp.status_code == 201
    # the active-org copy keeps the exact name (per-org uniqueness, no dedupe suffix)
    assert resp.data["collection_name"] == "Shared"


@pytest.mark.django_db
def test_bulk_delete_ignores_other_org_ids(client_admin, org_a, org_b):
    mine = SourceCollection.objects.create(collection_name="mine", org=org_a)
    theirs = SourceCollection.objects.create(collection_name="theirs", org=org_b)
    resp = client_admin.post(
        "/api/source-collections/bulk-delete/",
        {"collection_ids": [mine.collection_id, theirs.collection_id]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    assert not SourceCollection.objects.filter(
        collection_id=mine.collection_id
    ).exists()
    assert SourceCollection.objects.filter(collection_id=theirs.collection_id).exists()


@pytest.mark.django_db
def test_copy_own_collection_lands_in_org(client_admin, org_a):
    src = SourceCollection.objects.create(collection_name="src", org=org_a)
    resp = client_admin.post(
        f"/api/source-collections/{src.collection_id}/copy/",
        {"new_collection_name": "copy"},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    new_id = resp.data["collection"]["collection_id"]
    assert SourceCollection.objects.get(collection_id=new_id).org_id == org_a.id


@pytest.mark.django_db
def test_copy_cross_org_404(client_admin, org_b):
    other = SourceCollection.objects.create(collection_name="theirs", org=org_b)
    resp = client_admin.post(
        f"/api/source-collections/{other.collection_id}/copy/",
        {"new_collection_name": "copy"},
        format="json",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_available_rags_cross_org_404(client_member, org_b):
    other = SourceCollection.objects.create(collection_name="theirs", org=org_b)
    resp = client_member.get(
        f"/api/source-collections/{other.collection_id}/available-rags/"
    )
    assert resp.status_code == 404
