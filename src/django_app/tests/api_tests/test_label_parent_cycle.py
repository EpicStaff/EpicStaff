import pytest
from rest_framework.test import APIClient

from tables.models.label_models import Label
from tables.models.rbac_models import Organization, OrganizationUser, Role


# ---- fixtures ----


@pytest.fixture
def org_admin_role(db):
    return Role.objects.get(name="Org Admin", is_built_in=True, org__isnull=True)


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def member_a(db, django_user_model, org_a, org_admin_role):
    user = django_user_model.objects.create_user(
        email="member_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=org_admin_role)
    return user


@pytest.fixture
def client_a(member_a, org_a):
    client = APIClient()
    client.force_authenticate(user=member_a)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return client


def _assert_parent_error(resp):
    """Assert the response body flags `parent` as the failing field.

    `utils.exception_handler.custom_exception_handler` collapses a plain
    DRF `ValidationError({"parent": [...]})` into a single string:
    `response.data["message"] == f"{exc.__class__.__name__}: {exc.args[0]}"`
    (e.g. `"ValidationError: {'parent': [...]}"`). It only adds a
    structured `response.data["errors"]` list for exceptions that expose a
    custom `.errors` attribute (see `tables.services.rbac.rbac_exceptions`),
    which the serializer's `_validate_no_parent_cycle` does not use — so
    `message` is genuinely the only place the field name is exposed here.
    """
    assert "errors" not in resp.data, (
        "structured 'errors' field appeared — update this assertion to use it "
        "instead of string-matching 'message'"
    )
    message = resp.data["message"]
    assert isinstance(message, str)
    assert "parent" in message.lower()


# ---- self-parent (EST-3618) ----


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint", ["labels", "tool-labels"])
def test_patch_label_parent_to_self_returns_400_not_500(client_a, org_a, endpoint):
    scope = Label.Scope.FLOW if endpoint == "labels" else Label.Scope.TOOL
    label = Label.objects.create(name="Loopy", org=org_a, scope=scope)

    resp = client_a.patch(
        f"/api/{endpoint}/{label.id}/",
        {"parent": label.id},
        format="json",
    )

    assert resp.status_code == 400
    _assert_parent_error(resp)


# ---- two-label loop ----


@pytest.mark.django_db
def test_two_label_parent_loop_second_request_is_400_not_500(client_a, org_a):
    label1 = Label.objects.create(name="Label1", org=org_a, scope=Label.Scope.FLOW)
    label2 = Label.objects.create(name="Label2", org=org_a, scope=Label.Scope.FLOW)

    resp1 = client_a.patch(
        f"/api/labels/{label1.id}/", {"parent": label2.id}, format="json"
    )
    assert resp1.status_code == 200

    resp2 = client_a.patch(
        f"/api/labels/{label2.id}/", {"parent": label1.id}, format="json"
    )
    assert resp2.status_code == 400
    _assert_parent_error(resp2)


# ---- deeper loop A -> B -> C -> A ----


@pytest.mark.django_db
def test_deeper_three_label_loop_is_400(client_a, org_a):
    label_a = Label.objects.create(name="LabelA", org=org_a, scope=Label.Scope.FLOW)
    label_b = Label.objects.create(
        name="LabelB", org=org_a, scope=Label.Scope.FLOW, parent=label_a
    )
    label_c = Label.objects.create(
        name="LabelC", org=org_a, scope=Label.Scope.FLOW, parent=label_b
    )

    # Attempt to close the loop: A's parent -> C (A is an ancestor of C).
    resp = client_a.patch(
        f"/api/labels/{label_a.id}/", {"parent": label_c.id}, format="json"
    )
    assert resp.status_code == 400
    _assert_parent_error(resp)


# ---- sanity: legit re-parent still works ----


@pytest.mark.django_db
def test_legit_reparent_to_non_descendant_succeeds_and_full_path_is_correct(
    client_a, org_a
):
    root = Label.objects.create(name="Root", org=org_a, scope=Label.Scope.FLOW)
    other_root = Label.objects.create(
        name="OtherRoot", org=org_a, scope=Label.Scope.FLOW
    )
    child = Label.objects.create(
        name="Child", org=org_a, scope=Label.Scope.FLOW, parent=root
    )

    resp = client_a.patch(
        f"/api/labels/{child.id}/", {"parent": other_root.id}, format="json"
    )
    assert resp.status_code == 200
    assert resp.data["full_path"] == "OtherRoot/Child"

    child.refresh_from_db()
    assert child.parent_id == other_root.id


# ---- model-level: Label.full_path defensive hardening ----


@pytest.mark.django_db
def test_full_path_returns_partial_path_on_corrupted_cycle_without_crashing(org_a):
    label1 = Label.objects.create(name="Label1", org=org_a, scope=Label.Scope.FLOW)
    label2 = Label.objects.create(
        name="Label2", org=org_a, scope=Label.Scope.FLOW, parent=label1
    )

    # Bypass the serializer entirely to force a stored cycle, simulating a
    # row already corrupted in a live DB before this fix shipped.
    Label.objects.filter(pk=label1.pk).update(parent_id=label2.pk)

    label1.refresh_from_db()
    # Must not raise RecursionError — returns a partial path instead.
    result = label1.full_path
    assert isinstance(result, str)
    assert result != ""
