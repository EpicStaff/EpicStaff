import uuid

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from tables.models import Graph
from tables.models.graph_models import GraphSessionMessage
from tables.models.session_models import Session
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


# ---- fixtures ----


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def role_org_admin(db):
    return Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="S-Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="S-Org B")


def _client(user, org):
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def member_client_a(db, django_user_model, org_a, role_member):
    user = django_user_model.objects.create_user(
        email="s_member_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_member)
    return _client(user, org_a)


@pytest.fixture
def admin_client_a(db, django_user_model, org_a, role_org_admin):
    user = django_user_model.objects.create_user(
        email="s_admin_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_org_admin)
    return _client(user, org_a)


def _make_session(org, name):
    graph = Graph.objects.create(name=name, org=org)
    return Session.objects.create(
        graph=graph, status=Session.SessionStatus.PENDING, variables={}
    )


def _make_message(session):
    return GraphSessionMessage.objects.create(
        session=session,
        created_at=timezone.now(),
        message_data={"message_type": "start"},
        uuid=uuid.uuid4(),
    )


def _results(resp):
    body = resp.data
    return body["results"] if isinstance(body, dict) and "results" in body else body


# ---- session list / detail isolation ----


@pytest.mark.django_db
def test_session_list_only_active_org(member_client_a, org_a, org_b):
    s_a = _make_session(org_a, "SA flow")
    s_b = _make_session(org_b, "SB flow")
    resp = member_client_a.get("/api/sessions/?detailed=false")
    assert resp.status_code == 200
    ids = {s["id"] for s in _results(resp)}
    assert s_a.id in ids
    assert s_b.id not in ids


@pytest.mark.django_db
def test_session_detail_cross_org_returns_404(member_client_a, org_b):
    s_b = _make_session(org_b, "SB flow")
    resp = member_client_a.get(f"/api/sessions/{s_b.id}/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_session_request_without_header_is_rejected(member_client_a, org_a):
    member_client_a.credentials()  # drop the org header
    resp = member_client_a.get("/api/sessions/")
    assert resp.status_code == 400  # org_context_required


# ---- graph session messages scoped via session -> graph -> org ----


@pytest.mark.django_db
def test_graph_session_messages_only_active_org(member_client_a, org_a, org_b):
    s_a = _make_session(org_a, "SA flow")
    s_b = _make_session(org_b, "SB flow")
    _make_message(s_a)
    _make_message(s_b)

    # Messages for the active org's session are visible.
    resp_a = member_client_a.get(f"/api/graph-session-messages/?session_id={s_a.id}")
    assert resp_a.status_code == 200
    assert len(_results(resp_a)) == 1

    # Messages for another org's session are filtered out (empty).
    resp_b = member_client_a.get(f"/api/graph-session-messages/?session_id={s_b.id}")
    assert resp_b.status_code == 200
    assert len(_results(resp_b)) == 0


@pytest.mark.django_db
def test_bulk_delete_deleted_count_matches_rows_actually_removed(admin_client_a, org_a):
    # Member role has flows CRU (no DELETE) -- bulk_delete requires DELETE,
    # so use the Org Admin client here (see rbac_action_map on SessionViewSet).
    s1 = _make_session(org_a, "flow 1")
    s2 = _make_session(org_a, "flow 2")

    resp = admin_client_a.post(
        "/api/sessions/bulk_delete/", {"ids": [s1.id, s2.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted"] == 2
    assert resp.data["ids"] == [s1.id, s2.id]
    assert not Session.objects.filter(id__in=[s1.id, s2.id]).exists()


@pytest.mark.django_db
def test_bulk_delete_does_not_count_rows_removed_concurrently(
    admin_client_a, org_a, monkeypatch
):
    # Simulates a row being deleted by another process between the initial
    # queryset fetch and this loop reaching it: Session.delete() then returns
    # (0, {}) without raising. The reported "deleted" count must reflect that
    # zero, not the loop iteration count.
    s1 = _make_session(org_a, "flow 1")
    s2 = _make_session(org_a, "flow 2")

    original_delete = Session.delete
    call_count = {"n": 0}

    def fake_delete(self, *args, **kwargs):
        call_count["n"] += 1
        if self.id == s1.id:
            # Pretend this row was already removed concurrently.
            return (0, {})
        return original_delete(self, *args, **kwargs)

    monkeypatch.setattr(Session, "delete", fake_delete)

    resp = admin_client_a.post(
        "/api/sessions/bulk_delete/", {"ids": [s1.id, s2.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert call_count["n"] == 2
    assert resp.data["deleted"] == 1
    assert resp.data["ids"] == [s1.id, s2.id]


# ---- export endpoints require the EXPORT permission ----


@pytest.mark.django_db
def test_session_export_requires_export_permission(
    member_client_a, admin_client_a, org_a
):
    session = _make_session(org_a, "SA flow")
    # Member has no EXPORT on flows.
    assert member_client_a.get(f"/api/sessions/{session.id}/export/").status_code == 403
    # Org Admin does.
    assert admin_client_a.get(f"/api/sessions/{session.id}/export/").status_code == 200
