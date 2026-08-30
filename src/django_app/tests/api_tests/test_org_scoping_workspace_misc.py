import pytest
from rest_framework.test import APIClient

from tables.models import Label
from tables.models.webhook_models import WebhookTrigger
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


# ---- fixtures ----


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
def client_member(db, django_user_model, org_a):  # flows = CRU
    return _client(
        _user(django_user_model, org_a, BuiltInRole.MEMBER, "wm@example.com"), org_a
    )


def _results(resp):
    body = resp.data
    return body["results"] if isinstance(body, dict) and "results" in body else body


# ---- Label (gated as FLOWS, own org column) ----


@pytest.mark.django_db
def test_label_list_only_active_org(client_member, org_a, org_b):
    Label.objects.create(name="mine", org=org_a)
    Label.objects.create(name="theirs", org=org_b)
    results = _results(client_member.get("/api/labels/"))
    assert len(results) == 1


@pytest.mark.django_db
def test_label_retrieve_cross_org_404(client_member, org_b):
    other = Label.objects.create(name="theirs", org=org_b)
    assert client_member.get(f"/api/labels/{other.id}/").status_code == 404


@pytest.mark.django_db
def test_label_create_lands_in_active_org(client_member, org_a):
    resp = client_member.post("/api/labels/", {"name": "new"}, format="json")
    assert resp.status_code == 201, resp.data
    assert Label.objects.get(id=resp.data["id"]).org_id == org_a.id


@pytest.mark.django_db
def test_two_orgs_reuse_top_level_label_name(client_member, org_b):
    Label.objects.create(name="Shared", org=org_b)
    resp = client_member.post("/api/labels/", {"name": "Shared"}, format="json")
    assert resp.status_code == 201


# ---- WebhookTrigger (EST-3491: top-level org-owned resource, own `org` FK) ----


@pytest.mark.django_db
def test_webhook_trigger_unattached_is_visible_in_own_org(client_member, org_a):
    # WebhookTrigger now owns `org` directly (like Graph) rather than being
    # scoped transitively through a trigger node, so an org's own trigger is
    # visible regardless of whether any node references it yet.
    WebhookTrigger.objects.create(path="orphanpath", org=org_a)
    results = _results(client_member.get("/api/webhook-triggers/"))
    assert len(results) == 1


@pytest.mark.django_db
def test_webhook_trigger_of_another_org_is_hidden(client_member, org_b):
    WebhookTrigger.objects.create(path="otherorgpath", org=org_b)
    results = _results(client_member.get("/api/webhook-triggers/"))
    assert len(results) == 0

# NOTE (EST-3491): the standalone /api/ngrok-config/ endpoint
# (NgrokWebhookConfigViewSet) never had a live route registered in
# tables/urls.py and NgrokWebhookConfig.trigger is a required OneToOneField,
# so the two tests that used to live here (`test_ngrok_read_allowed_for_member`,
# `test_ngrok_write_denied_for_member`) were already exercising a dead route
# against an uncreatable row. They have been removed as part of formally
# deleting NgrokWebhookConfigViewSet / NgrokWebhookConfigModelSerializer.
# ngrok_config is now written only via the nested WebhookTrigger payload,
# scoped by WebhookTrigger.org (see webhook_trigger_api_test.py).
