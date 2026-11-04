"""CRUD, author isolation, cross-org isolation, and validation tests for
ToolFilterPreset and FlowFilterPreset endpoints.

Both endpoints are structurally identical: org-scoped, private to the author,
same serializer shape (name + filter_body), same uniqueness constraint
(org, created_by, name). Tests are parametrized across the two where the
logic is the same.
"""

import pytest
from django.urls import reverse

from rbac.models import OrganizationUser
from tables.models.flow_filter_preset_models import FlowFilterPreset
from tables.models.tool_filter_preset_models import ToolFilterPreset
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PRESET_CONFIGS = {
    "tool": {
        "model": ToolFilterPreset,
        "list_url": "toolfilterpreset-list",
        "detail_url": "toolfilterpreset-detail",
        "valid_body": {"showFavoriteOnly": True, "sortOrder": "name"},
        "valid_body_alt": {"unusedOnly": True},
    },
    "flow": {
        "model": FlowFilterPreset,
        "list_url": "flowfilterpreset-list",
        "detail_url": "flowfilterpreset-detail",
        "valid_body": {"sortOrder": "name", "includedLabelIds": [1, 2]},
        "valid_body_alt": {"includedFlowIds": [10]},
    },
}


def _client_in_org(client_as, user, org):
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


def _items(response):
    body = response.json()
    return body["results"] if isinstance(body, dict) and "results" in body else body


# ---------------------------------------------------------------------------
# Extra fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def colleague_acme(db, django_user_model, acme, role_org_admin):
    """A second user in Acme - same org, different person."""
    user = django_user_model.objects.create_user(
        email="colleague-filter-preset@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_org_admin)
    return user


@pytest.fixture
def admin_beta(db, django_user_model, beta, role_org_admin):
    """An admin in Beta org."""
    user = django_user_model.objects.create_user(
        email="admin-beta-filter-preset@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=beta, role=role_org_admin)
    return user


@pytest.fixture
def acme_client(client_as, admin_acme, acme):
    return _client_in_org(client_as, admin_acme, acme)


@pytest.fixture
def colleague_client(client_as, colleague_acme, acme):
    return _client_in_org(client_as, colleague_acme, acme)


@pytest.fixture
def beta_client(client_as, admin_beta, beta):
    return _client_in_org(client_as, admin_beta, beta)


# ---------------------------------------------------------------------------
# Happy-path CRUD
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCreateReadUpdateDelete:
    @pytest.mark.parametrize("preset_type", ["tool", "flow"])
    def test_create_and_retrieve(self, acme_client, preset_type):
        cfg = PRESET_CONFIGS[preset_type]
        payload = {"name": "My preset", "filter_body": cfg["valid_body"]}

        create_response = acme_client.post(
            reverse(cfg["list_url"]), payload, format="json"
        )
        assert create_response.status_code == 201
        body = create_response.json()
        assert body["name"] == "My preset"
        assert body["filter_body"] == cfg["valid_body"]
        assert "id" in body
        assert "created_at" in body
        assert "updated_at" in body

        detail_response = acme_client.get(
            reverse(cfg["detail_url"], kwargs={"pk": body["id"]})
        )
        assert detail_response.status_code == 200
        assert detail_response.json()["name"] == "My preset"

    @pytest.mark.parametrize("preset_type", ["tool", "flow"])
    def test_list_returns_own_presets(self, acme_client, preset_type):
        cfg = PRESET_CONFIGS[preset_type]
        acme_client.post(
            reverse(cfg["list_url"]),
            {"name": "First", "filter_body": cfg["valid_body"]},
            format="json",
        )
        acme_client.post(
            reverse(cfg["list_url"]),
            {"name": "Second", "filter_body": cfg["valid_body_alt"]},
            format="json",
        )

        response = acme_client.get(reverse(cfg["list_url"]))
        assert response.status_code == 200
        names = {item["name"] for item in _items(response)}
        assert names == {"First", "Second"}

    @pytest.mark.parametrize("preset_type", ["tool", "flow"])
    def test_update_full(self, acme_client, preset_type):
        cfg = PRESET_CONFIGS[preset_type]
        created = acme_client.post(
            reverse(cfg["list_url"]),
            {"name": "Original", "filter_body": cfg["valid_body"]},
            format="json",
        ).json()

        update_response = acme_client.put(
            reverse(cfg["detail_url"], kwargs={"pk": created["id"]}),
            {"name": "Renamed", "filter_body": cfg["valid_body_alt"]},
            format="json",
        )
        assert update_response.status_code == 200
        assert update_response.json()["name"] == "Renamed"
        assert update_response.json()["filter_body"] == cfg["valid_body_alt"]

    @pytest.mark.parametrize("preset_type", ["tool", "flow"])
    def test_partial_update(self, acme_client, preset_type):
        cfg = PRESET_CONFIGS[preset_type]
        created = acme_client.post(
            reverse(cfg["list_url"]),
            {"name": "Original", "filter_body": cfg["valid_body"]},
            format="json",
        ).json()

        patch_response = acme_client.patch(
            reverse(cfg["detail_url"], kwargs={"pk": created["id"]}),
            {"name": "Patched"},
            format="json",
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["name"] == "Patched"
        # filter_body unchanged
        assert patch_response.json()["filter_body"] == cfg["valid_body"]

    @pytest.mark.parametrize("preset_type", ["tool", "flow"])
    def test_delete(self, acme_client, preset_type):
        cfg = PRESET_CONFIGS[preset_type]
        created = acme_client.post(
            reverse(cfg["list_url"]),
            {"name": "To delete", "filter_body": cfg["valid_body"]},
            format="json",
        ).json()

        delete_response = acme_client.delete(
            reverse(cfg["detail_url"], kwargs={"pk": created["id"]})
        )
        assert delete_response.status_code == 204
        assert not cfg["model"].objects.filter(pk=created["id"]).exists()

    @pytest.mark.parametrize("preset_type", ["tool", "flow"])
    def test_create_with_empty_filter_body(self, acme_client, preset_type):
        cfg = PRESET_CONFIGS[preset_type]
        response = acme_client.post(
            reverse(cfg["list_url"]),
            {"name": "Empty body", "filter_body": {}},
            format="json",
        )
        assert response.status_code == 201
        assert response.json()["filter_body"] == {}


# ---------------------------------------------------------------------------
# Author isolation (same org, different user)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAuthorIsolation:
    @pytest.mark.parametrize("preset_type", ["tool", "flow"])
    def test_colleague_cannot_see_other_users_presets_in_list(
        self, acme_client, colleague_client, preset_type
    ):
        cfg = PRESET_CONFIGS[preset_type]
        acme_client.post(
            reverse(cfg["list_url"]),
            {"name": "Author's preset", "filter_body": cfg["valid_body"]},
            format="json",
        )

        response = colleague_client.get(reverse(cfg["list_url"]))
        assert response.status_code == 200
        assert _items(response) == []

    @pytest.mark.parametrize("preset_type", ["tool", "flow"])
    def test_colleague_gets_404_on_detail(self, acme_client, colleague_client, preset_type):
        cfg = PRESET_CONFIGS[preset_type]
        created = acme_client.post(
            reverse(cfg["list_url"]),
            {"name": "Private", "filter_body": cfg["valid_body"]},
            format="json",
        ).json()

        response = colleague_client.get(
            reverse(cfg["detail_url"], kwargs={"pk": created["id"]})
        )
        assert response.status_code == 404

    @pytest.mark.parametrize("preset_type", ["tool", "flow"])
    @pytest.mark.parametrize("method", ["put", "patch", "delete"])
    def test_colleague_cannot_modify_other_users_preset(
        self, acme_client, colleague_client, preset_type, method
    ):
        cfg = PRESET_CONFIGS[preset_type]
        created = acme_client.post(
            reverse(cfg["list_url"]),
            {"name": "Mine", "filter_body": cfg["valid_body"]},
            format="json",
        ).json()

        url = reverse(cfg["detail_url"], kwargs={"pk": created["id"]})
        payload = {"name": "Hijacked", "filter_body": cfg["valid_body"]}
        response = getattr(colleague_client, method)(url, payload, format="json")
        assert response.status_code == 404

        # Row unchanged
        preset = cfg["model"].objects.get(pk=created["id"])
        assert preset.name == "Mine"


# ---------------------------------------------------------------------------
# Cross-org isolation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCrossOrgIsolation:
    @pytest.mark.parametrize("preset_type", ["tool", "flow"])
    def test_other_org_list_excludes_presets(self, acme_client, beta_client, preset_type):
        cfg = PRESET_CONFIGS[preset_type]
        acme_client.post(
            reverse(cfg["list_url"]),
            {"name": "Acme only", "filter_body": cfg["valid_body"]},
            format="json",
        )

        response = beta_client.get(reverse(cfg["list_url"]))
        assert response.status_code == 200
        assert _items(response) == []

    @pytest.mark.parametrize("preset_type", ["tool", "flow"])
    @pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
    def test_other_org_detail_routes_404(
        self, acme_client, beta_client, preset_type, method
    ):
        cfg = PRESET_CONFIGS[preset_type]
        created = acme_client.post(
            reverse(cfg["list_url"]),
            {"name": "Acme preset", "filter_body": cfg["valid_body"]},
            format="json",
        ).json()

        url = reverse(cfg["detail_url"], kwargs={"pk": created["id"]})
        payload = {"name": "Stolen", "filter_body": cfg["valid_body"]}
        response = getattr(beta_client, method)(url, payload, format="json")
        assert response.status_code == 404

        # Row unchanged in DB
        preset = cfg["model"].objects.get(pk=created["id"])
        assert preset.name == "Acme preset"


# ---------------------------------------------------------------------------
# Unique name validation (per user, per org)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUniqueNamePerAuthor:
    @pytest.mark.parametrize("preset_type", ["tool", "flow"])
    def test_duplicate_name_same_user_400(self, acme_client, preset_type):
        cfg = PRESET_CONFIGS[preset_type]
        url = reverse(cfg["list_url"])
        first = acme_client.post(
            url, {"name": "Dupe", "filter_body": cfg["valid_body"]}, format="json"
        )
        assert first.status_code == 201

        second = acme_client.post(
            url, {"name": "Dupe", "filter_body": cfg["valid_body_alt"]}, format="json"
        )
        assert second.status_code == 400
        assert "name" in second.json()["message"].lower()

    @pytest.mark.parametrize("preset_type", ["tool", "flow"])
    def test_rename_to_existing_own_name_400(self, acme_client, preset_type):
        cfg = PRESET_CONFIGS[preset_type]
        url = reverse(cfg["list_url"])
        first = acme_client.post(
            url, {"name": "Alpha", "filter_body": cfg["valid_body"]}, format="json"
        ).json()
        acme_client.post(
            url, {"name": "Beta", "filter_body": cfg["valid_body_alt"]}, format="json"
        )

        clash = acme_client.patch(
            reverse(cfg["detail_url"], kwargs={"pk": first["id"]}),
            {"name": "Beta"},
            format="json",
        )
        assert clash.status_code == 400

    @pytest.mark.parametrize("preset_type", ["tool", "flow"])
    def test_rename_to_own_current_name_ok(self, acme_client, preset_type):
        cfg = PRESET_CONFIGS[preset_type]
        created = acme_client.post(
            reverse(cfg["list_url"]),
            {"name": "Same", "filter_body": cfg["valid_body"]},
            format="json",
        ).json()

        response = acme_client.patch(
            reverse(cfg["detail_url"], kwargs={"pk": created["id"]}),
            {"name": "Same"},
            format="json",
        )
        assert response.status_code == 200

    @pytest.mark.parametrize("preset_type", ["tool", "flow"])
    def test_colleague_can_use_same_name(
        self, acme_client, colleague_client, preset_type
    ):
        cfg = PRESET_CONFIGS[preset_type]
        acme_client.post(
            reverse(cfg["list_url"]),
            {"name": "Shared name", "filter_body": cfg["valid_body"]},
            format="json",
        )

        response = colleague_client.post(
            reverse(cfg["list_url"]),
            {"name": "Shared name", "filter_body": cfg["valid_body"]},
            format="json",
        )
        assert response.status_code == 201

    @pytest.mark.parametrize("preset_type", ["tool", "flow"])
    def test_other_org_can_use_same_name(self, acme_client, beta_client, preset_type):
        cfg = PRESET_CONFIGS[preset_type]
        acme_client.post(
            reverse(cfg["list_url"]),
            {"name": "Cross-org name", "filter_body": cfg["valid_body"]},
            format="json",
        )

        response = beta_client.post(
            reverse(cfg["list_url"]),
            {"name": "Cross-org name", "filter_body": cfg["valid_body"]},
            format="json",
        )
        assert response.status_code == 201


# ---------------------------------------------------------------------------
# filter_body shape validation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestToolFilterBodyValidation:
    def test_unknown_key_rejected(self, acme_client):
        response = acme_client.post(
            reverse("toolfilterpreset-list"),
            {"name": "Bad", "filter_body": {"bogusKey": True}},
            format="json",
        )
        assert response.status_code == 400
        assert "bogusKey" in str(response.json())

    def test_wrong_type_rejected(self, acme_client):
        response = acme_client.post(
            reverse("toolfilterpreset-list"),
            {"name": "Bad", "filter_body": {"showFavoriteOnly": "yes"}},
            format="json",
        )
        assert response.status_code == 400
        assert "showFavoriteOnly" in str(response.json())

    def test_non_dict_filter_body_rejected(self, acme_client):
        response = acme_client.post(
            reverse("toolfilterpreset-list"),
            {"name": "Bad", "filter_body": [1, 2, 3]},
            format="json",
        )
        assert response.status_code == 400

    def test_nullable_field_accepts_null(self, acme_client):
        response = acme_client.post(
            reverse("toolfilterpreset-list"),
            {"name": "Nullable", "filter_body": {"includedToolIds": None}},
            format="json",
        )
        assert response.status_code == 201

    def test_all_valid_tool_keys_accepted(self, acme_client):
        body = {
            "showFavoriteOnly": True,
            "showNotFavoriteOnly": False,
            "sourceBuiltIn": True,
            "sourceCustom": False,
            "usageBuckets": [1, 2],
            "unusedOnly": False,
            "sortOrder": "name",
            "includedToolIds": [1],
            "includedLabelIds": None,
            "customConditions": None,
        }
        response = acme_client.post(
            reverse("toolfilterpreset-list"),
            {"name": "Full", "filter_body": body},
            format="json",
        )
        assert response.status_code == 201


@pytest.mark.django_db
class TestFlowFilterBodyValidation:
    def test_unknown_key_rejected(self, acme_client):
        response = acme_client.post(
            reverse("flowfilterpreset-list"),
            {"name": "Bad", "filter_body": {"unknownField": 42}},
            format="json",
        )
        assert response.status_code == 400
        assert "unknownField" in str(response.json())

    def test_wrong_type_rejected(self, acme_client):
        response = acme_client.post(
            reverse("flowfilterpreset-list"),
            {"name": "Bad", "filter_body": {"sortOrder": 123}},
            format="json",
        )
        assert response.status_code == 400
        assert "sortOrder" in str(response.json())

    def test_non_dict_filter_body_rejected(self, acme_client):
        response = acme_client.post(
            reverse("flowfilterpreset-list"),
            {"name": "Bad", "filter_body": "not a dict"},
            format="json",
        )
        assert response.status_code == 400

    def test_nullable_field_accepts_null(self, acme_client):
        response = acme_client.post(
            reverse("flowfilterpreset-list"),
            {"name": "Nullable", "filter_body": {"includedFlowIds": None}},
            format="json",
        )
        assert response.status_code == 201

    def test_all_valid_flow_keys_accepted(self, acme_client):
        body = {
            "sortOrder": "updated_at",
            "includedFlowIds": [1, 2],
            "includedLabelIds": [3],
            "customConditions": [{"field": "name", "op": "eq", "value": "test"}],
        }
        response = acme_client.post(
            reverse("flowfilterpreset-list"),
            {"name": "Full", "filter_body": body},
            format="json",
        )
        assert response.status_code == 201

    def test_tool_specific_key_rejected_on_flow_endpoint(self, acme_client):
        """A tool-specific key like showFavoriteOnly is not valid for flow presets."""
        response = acme_client.post(
            reverse("flowfilterpreset-list"),
            {"name": "Bad", "filter_body": {"showFavoriteOnly": True}},
            format="json",
        )
        assert response.status_code == 400
        assert "showFavoriteOnly" in str(response.json())


# ---------------------------------------------------------------------------
# Missing required fields
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRequiredFields:
    @pytest.mark.parametrize("preset_type", ["tool", "flow"])
    def test_missing_name_400(self, acme_client, preset_type):
        cfg = PRESET_CONFIGS[preset_type]
        response = acme_client.post(
            reverse(cfg["list_url"]),
            {"filter_body": cfg["valid_body"]},
            format="json",
        )
        assert response.status_code == 400
