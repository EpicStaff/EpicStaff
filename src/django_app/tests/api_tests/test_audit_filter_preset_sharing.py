"""Audit filter presets are shared within an org: anyone with AUDIT:read can
see, export and copy them, only the author can edit or delete them, and
another org never sees them at all."""

import json

import pytest
from django.urls import reverse

from rbac.models import OrganizationUser
from tables.import_export.enums import EntityType
from tables.models.audit_filter_preset_models import AuditFilterPreset
from tables.services.copy_services.audit_filter_preset_copy_service import (
    next_free_preset_name,
)
from tests.helpers import data_to_json_file
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def colleague_acme(db, django_user_model, acme, role_org_admin):
    """A second Org Admin of Acme - same org as the author, not the author."""
    user = django_user_model.objects.create_user(
        email="colleague-acme-preset@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_org_admin)
    return user


@pytest.fixture
def admin_beta(db, django_user_model, beta, role_org_admin):
    user = django_user_model.objects.create_user(
        email="admin-beta-preset@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=beta, role=role_org_admin)
    return user


@pytest.fixture
def authors_preset(acme, admin_acme):
    return AuditFilterPreset.objects.create(
        org=acme,
        created_by=admin_acme,
        name="Failed runs",
        filter_body={"query": "status = failed"},
    )


def _client_in_org(client_as, user, org):
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def author_client(client_as, admin_acme, acme):
    return _client_in_org(client_as, admin_acme, acme)


@pytest.fixture
def colleague_client(client_as, colleague_acme, acme):
    return _client_in_org(client_as, colleague_acme, acme)


@pytest.fixture
def beta_client(client_as, admin_beta, beta):
    return _client_in_org(client_as, admin_beta, beta)


def _detail_url(preset):
    return reverse("auditfilterpreset-detail", kwargs={"pk": preset.id})


def _import(client, name, filter_body=None):
    payload = {
        "main_entity": EntityType.AUDIT_FILTER_PRESET,
        "version": 3,
        EntityType.AUDIT_FILTER_PRESET: [
            {"id": 1, "name": name, "filter_body": filter_body or {"query": ""}}
        ],
    }
    return client.post(
        reverse("auditfilterpreset-import-presets"),
        {"file": data_to_json_file(payload, "import.json")},
        format="multipart",
    )


@pytest.mark.django_db
class TestPresetVisibleToWholeOrg:
    def test_list_includes_another_users_preset_with_is_owner_false(
        self, colleague_client, authors_preset
    ):
        response = colleague_client.get(reverse("auditfilterpreset-list"))

        assert response.status_code == 200
        items = response.json()
        items = items["results"] if isinstance(items, dict) else items
        assert [(item["id"], item["is_owner"]) for item in items] == [
            (authors_preset.id, False)
        ]

    def test_retrieve_is_owner_reflects_the_caller(
        self, author_client, colleague_client, authors_preset
    ):
        author_response = author_client.get(_detail_url(authors_preset))
        colleague_response = colleague_client.get(_detail_url(authors_preset))

        assert author_response.status_code == 200
        assert author_response.json()["is_owner"] is True
        assert colleague_response.status_code == 200
        assert colleague_response.json()["is_owner"] is False

    def test_copy_of_another_users_preset_belongs_to_the_copier(
        self, colleague_client, colleague_acme, authors_preset
    ):
        url = reverse("auditfilterpreset-copy", kwargs={"pk": authors_preset.id})
        response = colleague_client.post(url, {}, format="json")

        assert response.status_code == 201
        body = response.json()
        # The original name is taken in the org (by the author), so it is renumbered.
        assert body["name"] == "Failed runs (2)"
        assert body["is_owner"] is True
        clone = AuditFilterPreset.objects.get(pk=body["id"])
        assert clone.created_by_id == colleague_acme.id
        assert clone.org_id == authors_preset.org_id
        assert clone.filter_body == authors_preset.filter_body

    def test_export_single_of_another_users_preset(self, colleague_client, authors_preset):
        url = reverse("auditfilterpreset-export", kwargs={"pk": authors_preset.id})
        response = colleague_client.get(url)

        assert response.status_code == 200
        exported = json.loads(response.content)[EntityType.AUDIT_FILTER_PRESET]
        assert [item["id"] for item in exported] == [authors_preset.id]

    def test_bulk_export_of_another_users_preset(self, colleague_client, authors_preset):
        url = reverse("auditfilterpreset-bulk-export")
        response = colleague_client.post(url, {"ids": [authors_preset.id]}, format="json")

        assert response.status_code == 200
        exported = json.loads(response.content)[EntityType.AUDIT_FILTER_PRESET]
        assert [item["id"] for item in exported] == [authors_preset.id]


@pytest.mark.django_db
class TestOnlyAuthorCanChangePreset:
    @pytest.mark.parametrize("method", ["put", "patch"])
    def test_non_author_update_404s_and_leaves_row_unchanged(
        self, colleague_client, authors_preset, method
    ):
        response = getattr(colleague_client, method)(
            _detail_url(authors_preset),
            {"name": "Hijacked", "filter_body": {"query": ""}},
            format="json",
        )

        assert response.status_code == 404
        authors_preset.refresh_from_db()
        assert authors_preset.name == "Failed runs"
        assert authors_preset.filter_body == {"query": "status = failed"}

    def test_non_author_destroy_404s_and_keeps_row(self, colleague_client, authors_preset):
        response = colleague_client.delete(_detail_url(authors_preset))

        assert response.status_code == 404
        assert AuditFilterPreset.objects.filter(pk=authors_preset.pk).exists()

    def test_author_can_update_and_destroy(self, author_client, authors_preset):
        patch_response = author_client.patch(
            _detail_url(authors_preset), {"name": "Renamed"}, format="json"
        )
        delete_response = author_client.delete(_detail_url(authors_preset))

        assert patch_response.status_code == 200
        assert patch_response.json()["is_owner"] is True
        assert patch_response.json()["name"] == "Renamed"
        assert delete_response.status_code == 204
        assert not AuditFilterPreset.objects.filter(pk=authors_preset.pk).exists()


@pytest.mark.django_db
class TestPresetInvisibleToOtherOrg:
    def test_list_excludes_other_orgs_presets(self, beta_client, authors_preset):
        response = beta_client.get(reverse("auditfilterpreset-list"))

        assert response.status_code == 200
        items = response.json()
        items = items["results"] if isinstance(items, dict) else items
        assert items == []

    @pytest.mark.parametrize(
        ("method", "route"),
        [
            ("get", "auditfilterpreset-detail"),
            ("patch", "auditfilterpreset-detail"),
            ("delete", "auditfilterpreset-detail"),
            ("post", "auditfilterpreset-copy"),
            ("get", "auditfilterpreset-export"),
        ],
    )
    def test_other_org_detail_routes_404(self, beta_client, authors_preset, method, route):
        url = reverse(route, kwargs={"pk": authors_preset.id})
        response = getattr(beta_client, method)(url, {}, format="json")

        assert response.status_code == 404
        assert AuditFilterPreset.objects.filter(pk=authors_preset.pk).count() == 1

    def test_other_org_bulk_export_400s(self, beta_client, authors_preset):
        url = reverse("auditfilterpreset-bulk-export")
        response = beta_client.post(url, {"ids": [authors_preset.id]}, format="json")

        assert response.status_code == 400


@pytest.mark.django_db
class TestPresetNameUniquePerOrg:
    def test_same_name_by_another_user_in_same_org_400s(
        self, colleague_client, authors_preset
    ):
        response = colleague_client.post(
            reverse("auditfilterpreset-list"),
            {"name": authors_preset.name, "filter_body": {"query": ""}},
            format="json",
        )

        assert response.status_code == 400
        assert response.json()["message"].startswith("name:")
        assert AuditFilterPreset.objects.filter(name=authors_preset.name).count() == 1

    def test_same_name_in_another_org_is_allowed(self, beta_client, authors_preset, beta):
        response = beta_client.post(
            reverse("auditfilterpreset-list"),
            {"name": authors_preset.name, "filter_body": {"query": ""}},
            format="json",
        )

        assert response.status_code == 201
        assert response.json()["is_owner"] is True
        assert AuditFilterPreset.objects.get(pk=response.json()["id"]).org_id == beta.id

    def test_author_renaming_onto_a_taken_name_400s(
        self, author_client, colleague_acme, acme, authors_preset
    ):
        AuditFilterPreset.objects.create(
            org=acme, created_by=colleague_acme, name="Colleague's", filter_body={}
        )

        response = author_client.patch(
            _detail_url(authors_preset), {"name": "Colleague's"}, format="json"
        )

        assert response.status_code == 400

    def test_colleague_import_of_authors_name_creates_a_numbered_preset(
        self, colleague_client, colleague_acme, authors_preset
    ):
        response = _import(colleague_client, authors_preset.name, {"query": "new"})

        assert response.status_code == 200
        entity_summary = response.json()[EntityType.AUDIT_FILTER_PRESET]
        assert entity_summary["reused"]["count"] == 0
        assert entity_summary["created"]["count"] == 1
        assert entity_summary["created"]["items"][0]["name"] == "Failed runs (2)"
        imported = AuditFilterPreset.objects.get(name="Failed runs (2)")
        assert imported.created_by_id == colleague_acme.id
        assert imported.filter_body == {"query": "new"}
        authors_preset.refresh_from_db()
        assert authors_preset.filter_body == {"query": "status = failed"}

    @pytest.mark.parametrize("via", ["copy", "import"])
    def test_numbered_name_of_a_max_length_name_fits_the_column(
        self, colleague_client, acme, admin_acme, via
    ):
        long_name = "n" * 150
        long_preset = AuditFilterPreset.objects.create(
            org=acme, created_by=admin_acme, name=long_name, filter_body={}
        )

        if via == "copy":
            response = colleague_client.post(
                reverse("auditfilterpreset-copy", kwargs={"pk": long_preset.id}),
                {},
                format="json",
            )
            assert response.status_code == 201
            new_name = response.json()["name"]
        else:
            response = _import(colleague_client, long_name)
            assert response.status_code == 200
            summary = response.json()[EntityType.AUDIT_FILTER_PRESET]
            new_name = summary["created"]["items"][0]["name"]

        assert new_name == "n" * 146 + " (2)"
        assert len(new_name) == 150

    def test_import_name_with_trailing_space_is_numbered_not_a_500(
        self, colleague_client, authors_preset
    ):
        response = _import(colleague_client, authors_preset.name + " ")

        assert response.status_code == 200
        created = response.json()[EntityType.AUDIT_FILTER_PRESET]["created"]["items"]
        assert created[0]["name"] == "Failed runs (2)"

    def test_next_free_name_takes_first_gap_and_strips_an_existing_number(
        self, acme, beta, admin_acme, authors_preset
    ):
        AuditFilterPreset.objects.create(
            org=acme, created_by=admin_acme, name="Failed runs (3)", filter_body={}
        )

        assert next_free_preset_name(acme.id, "Fresh") == "Fresh"
        assert next_free_preset_name(acme.id, "Failed runs") == "Failed runs (2)"
        assert next_free_preset_name(acme.id, "Failed runs (3)") == "Failed runs (2)"
        assert next_free_preset_name(beta.id, "Failed runs") == "Failed runs"
