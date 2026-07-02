import pytest
from rest_framework.test import APIClient

from tables.models import Graph
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


# These tests exercise the RBAC gating on StorageAPIView without touching the
# storage backend (every assertion fails before any manager.* call).


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _user(django_user_model, org, role_name, email):
    role = Role.objects.get(name=role_name, is_built_in=True, org__isnull=True)
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


def _client(user, org):
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return c


@pytest.fixture
def client_member(db, django_user_model, org_a):  # files = CRU + EXPORT
    return _client(
        _user(django_user_model, org_a, BuiltInRole.MEMBER, "fm@example.com"), org_a
    )


@pytest.fixture
def client_viewer(db, django_user_model, org_a):  # files = READ only
    return _client(
        _user(django_user_model, org_a, BuiltInRole.VIEWER, "fv@example.com"), org_a
    )


@pytest.mark.django_db
def test_cross_org_move_denied_for_member(client_member, org_a, org_b):
    resp = client_member.post(
        "/api/storage/move/",
        {
            "from_path": "a.txt",
            "to_path": "b.txt",
            "source_org_id": org_a.id,
            "destination_org_id": org_b.id,
        },
        format="json",
    )
    assert resp.status_code == 403  # cross-org transfer is superadmin-only


@pytest.mark.django_db
def test_cross_org_copy_denied_for_member(client_member, org_a, org_b):
    resp = client_member.post(
        "/api/storage/copy/",
        {
            "from_path": "a.txt",
            "to_path": "b.txt",
            "source_org_id": org_a.id,
            "destination_org_id": org_b.id,
        },
        format="json",
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_graph_files_cross_org_404(client_member, org_b):
    other = Graph.objects.create(name="B flow", org=org_b)
    resp = client_member.get(f"/api/storage/graph-files/?graph_id={other.id}")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_upload_denied_for_viewer(client_viewer):
    # Viewer has FILES READ only -> CREATE (upload) is denied before any backend call.
    resp = client_viewer.post("/api/storage/upload/", {"path": ""}, format="multipart")
    assert resp.status_code == 403
