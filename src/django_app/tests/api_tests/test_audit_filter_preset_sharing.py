"""Audit filter presets are private to their author or shared within the org:
anyone with AUDIT:read can see, export and copy a shared preset, nobody but the
author sees a private one, only the author can edit, delete or share a preset,
sharing is one-way, and another org never sees any of them."""

import json

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
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
        is_shared=True,
    )


@pytest.fixture
def private_preset(acme, admin_acme):
    return AuditFilterPreset.objects.create(
        org=acme,
        created_by=admin_acme,
        name="My private",
        filter_body={"query": "status = ok"},
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


def _copy_url(preset):
    return reverse("auditfilterpreset-copy", kwargs={"pk": preset.id})


def _items(response):
    body = response.json()
    return body["results"] if isinstance(body, dict) else body


def _import(client, name, filter_body=None, **extra):
    payload = {
        "main_entity": EntityType.AUDIT_FILTER_PRESET,
        "version": 3,
        EntityType.AUDIT_FILTER_PRESET: [
            {"id": 1, "name": name, "filter_body": filter_body or {"query": ""}, **extra}
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
        assert [(item["id"], item["is_owner"]) for item in _items(response)] == [
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
        response = colleague_client.post(_copy_url(authors_preset), {}, format="json")

        assert response.status_code == 201
        body = response.json()
        # A copy only competes with the copier's own names.
        assert body["name"] == "Failed runs"
        assert body["is_owner"] is True
        assert body["is_shared"] is False
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
        assert _items(response) == []

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


NAME_TAKEN = "You already have a preset with this name."


@pytest.fixture
def third_admin_acme(db, django_user_model, acme, role_org_admin):
    user = django_user_model.objects.create_user(
        email="third-admin-acme-preset@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_org_admin)
    return user


def _create(client, name, is_shared=False):
    return client.post(
        reverse("auditfilterpreset-list"),
        {"name": name, "filter_body": {"query": ""}, "is_shared": is_shared},
        format="json",
    )


def _imported_name(response):
    assert response.status_code == 200
    return response.json()[EntityType.AUDIT_FILTER_PRESET]["created"]["items"][0]["name"]


@pytest.mark.django_db
class TestPresetNameUniquePerAuthor:
    @pytest.mark.parametrize("is_shared", [False, True])
    def test_own_name_taken_400s_whatever_the_visibility(
        self, author_client, authors_preset, private_preset, is_shared
    ):
        # The author already has "Failed runs" shared and "My private" private.
        for taken in (authors_preset.name, private_preset.name):
            response = _create(author_client, taken, is_shared=is_shared)

            assert response.status_code == 400
            assert response.json()["message"].startswith("name:")
            assert NAME_TAKEN in response.json()["message"]
        assert AuditFilterPreset.objects.count() == 2

    def test_renaming_onto_another_own_name_400s(
        self, author_client, authors_preset, private_preset
    ):
        clash = author_client.patch(
            _detail_url(private_preset), {"name": authors_preset.name}, format="json"
        )
        same_name = author_client.patch(
            _detail_url(private_preset), {"name": private_preset.name}, format="json"
        )

        assert clash.status_code == 400
        assert same_name.status_code == 200

    @pytest.mark.parametrize("is_shared", [False, True])
    def test_colleague_may_use_the_same_name(
        self, colleague_client, colleague_acme, authors_preset, private_preset, is_shared
    ):
        for name in (authors_preset.name, private_preset.name):
            response = _create(colleague_client, name, is_shared=is_shared)

            assert response.status_code == 201
            assert response.json()["name"] == name
            created = AuditFilterPreset.objects.get(pk=response.json()["id"])
            assert created.created_by_id == colleague_acme.id

    def test_two_authors_shared_presets_with_one_name_both_listed(
        self, client_as, colleague_client, colleague_acme, third_admin_acme, acme, authors_preset
    ):
        response = _create(colleague_client, authors_preset.name, is_shared=True)
        assert response.status_code == 201

        third_member = _client_in_org(client_as, third_admin_acme, acme)
        listed = {
            (item["name"], item["created_by_name"])
            for item in _items(third_member.get(reverse("auditfilterpreset-list")))
        }

        assert listed == {
            ("Failed runs", author.display_name or author.email)
            for author in (authors_preset.created_by, colleague_acme)
        }
        assert len(listed) == 2


@pytest.mark.django_db
class TestCopyAndImportNumberAmongOwnNames:
    def test_copy_numbers_among_the_copiers_own_names(
        self, author_client, colleague_client, authors_preset, private_preset
    ):
        # The author already owns both names, so their copies are numbered - shared or not.
        own_shared_as_private = author_client.post(_copy_url(authors_preset), {}, format="json")
        own_private_as_shared = author_client.post(
            _copy_url(private_preset), {"is_shared": True}, format="json"
        )
        colleagues_shared_copy = colleague_client.post(
            _copy_url(authors_preset), {"is_shared": True}, format="json"
        )

        assert own_shared_as_private.json()["name"] == "Failed runs (2)"
        assert own_private_as_shared.json()["name"] == "My private (2)"
        assert colleagues_shared_copy.json()["name"] == "Failed runs"

    def test_import_numbers_among_the_importers_own_names(
        self, author_client, colleague_client, authors_preset, private_preset
    ):
        over_own_private = _imported_name(_import(author_client, "My private", {"query": "new"}))
        over_own_shared = _imported_name(_import(author_client, authors_preset.name))
        colleagues_import = _imported_name(_import(colleague_client, authors_preset.name))

        assert over_own_private == "My private (2)"
        assert over_own_shared == "Failed runs (2)"
        assert colleagues_import == "Failed runs"
        private_preset.refresh_from_db()
        assert private_preset.filter_body == {"query": "status = ok"}

    @pytest.mark.parametrize("via", ["copy", "import"])
    def test_numbered_name_of_a_max_length_name_fits_the_column(
        self, colleague_client, acme, colleague_acme, via
    ):
        long_name = "n" * 150
        long_preset = AuditFilterPreset.objects.create(
            org=acme, created_by=colleague_acme, name=long_name, filter_body={}
        )

        if via == "copy":
            response = colleague_client.post(_copy_url(long_preset), {}, format="json")
            assert response.status_code == 201
            new_name = response.json()["name"]
        else:
            new_name = _imported_name(_import(colleague_client, long_name))

        assert new_name == "n" * 146 + " (2)"
        assert len(new_name) == 150

    def test_import_name_with_trailing_space_is_numbered_not_a_500(
        self, author_client, private_preset
    ):
        new_name = _imported_name(_import(author_client, private_preset.name + " "))

        assert new_name == "My private (2)"

    def test_next_free_name_takes_first_gap_and_strips_an_existing_number(
        self, acme, beta, admin_acme, colleague_acme, authors_preset
    ):
        AuditFilterPreset.objects.create(org=acme, created_by=admin_acme, name="Failed runs (3)")

        assert next_free_preset_name(acme.id, admin_acme.id, "Fresh") == "Fresh"
        assert next_free_preset_name(acme.id, admin_acme.id, "Failed runs") == "Failed runs (2)"
        assert (
            next_free_preset_name(acme.id, admin_acme.id, "Failed runs (3)") == "Failed runs (2)"
        )
        assert next_free_preset_name(acme.id, colleague_acme.id, "Failed runs") == "Failed runs"
        assert next_free_preset_name(beta.id, admin_acme.id, "Failed runs") == "Failed runs"


@pytest.mark.django_db
class TestPrivatePresetVisibleOnlyToAuthor:
    def test_list_shows_colleague_only_shared_and_author_both(
        self, author_client, colleague_client, authors_preset, private_preset
    ):
        url = reverse("auditfilterpreset-list")
        author_ids = {item["id"] for item in _items(author_client.get(url))}
        colleague_ids = [item["id"] for item in _items(colleague_client.get(url))]

        assert author_ids == {authors_preset.id, private_preset.id}
        assert colleague_ids == [authors_preset.id]

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
    def test_colleague_detail_routes_404(self, colleague_client, private_preset, method, route):
        url = reverse(route, kwargs={"pk": private_preset.id})
        response = getattr(colleague_client, method)(url, {}, format="json")

        assert response.status_code == 404
        assert AuditFilterPreset.objects.count() == 1

    def test_colleague_bulk_export_with_a_private_id_400s(
        self, colleague_client, authors_preset, private_preset
    ):
        response = colleague_client.post(
            reverse("auditfilterpreset-bulk-export"),
            {"ids": [authors_preset.id, private_preset.id]},
            format="json",
        )

        assert response.status_code == 400
        assert response.json()["message"] == "Some entity IDs do not exist"

    def test_author_retrieves_and_exports_own_private_preset(self, author_client, private_preset):
        retrieve = author_client.get(_detail_url(private_preset))
        bulk = author_client.post(
            reverse("auditfilterpreset-bulk-export"), {"ids": [private_preset.id]}, format="json"
        )

        assert retrieve.status_code == 200
        assert retrieve.json()["is_shared"] is False
        assert bulk.status_code == 200
        exported = json.loads(bulk.content)[EntityType.AUDIT_FILTER_PRESET]
        assert exported == [
            {"id": private_preset.id, "name": "My private", "filter_body": {"query": "status = ok"}}
        ]


@pytest.mark.django_db
class TestSharingIsOneWay:
    def test_create_defaults_to_private(self, author_client):
        response = author_client.post(
            reverse("auditfilterpreset-list"),
            {"name": "Fresh", "filter_body": {"query": ""}},
            format="json",
        )

        assert response.status_code == 201
        assert response.json()["is_shared"] is False
        assert AuditFilterPreset.objects.get(pk=response.json()["id"]).is_shared is False

    def test_create_directly_as_shared(self, author_client):
        response = _create(author_client, "Fresh", is_shared=True)

        assert response.status_code == 201
        assert AuditFilterPreset.objects.get(pk=response.json()["id"]).is_shared is True

    def test_author_moves_private_preset_to_shared(
        self, author_client, colleague_client, private_preset
    ):
        response = author_client.patch(
            _detail_url(private_preset), {"is_shared": True}, format="json"
        )

        assert response.status_code == 200
        assert response.json()["is_shared"] is True
        private_preset.refresh_from_db()
        assert private_preset.is_shared is True
        assert colleague_client.get(_detail_url(private_preset)).status_code == 200

    @pytest.mark.parametrize("method", ["put", "patch"])
    def test_unsharing_400s_and_leaves_preset_untouched(
        self, author_client, authors_preset, method
    ):
        response = getattr(author_client, method)(
            _detail_url(authors_preset),
            {"name": "Renamed", "filter_body": {"query": ""}, "is_shared": False},
            format="json",
        )

        assert response.status_code == 400
        assert response.json()["message"].startswith("is_shared:")
        authors_preset.refresh_from_db()
        assert (authors_preset.is_shared, authors_preset.name) == (True, "Failed runs")

    def test_put_without_is_shared_keeps_preset_shared(self, author_client, authors_preset):
        response = author_client.put(
            _detail_url(authors_preset),
            {"name": "Renamed", "filter_body": {"query": ""}},
            format="json",
        )

        assert response.status_code == 200
        authors_preset.refresh_from_db()
        assert authors_preset.is_shared is True

    def test_non_author_cannot_share_a_private_preset(self, colleague_client, private_preset):
        response = colleague_client.patch(
            _detail_url(private_preset), {"is_shared": True}, format="json"
        )

        assert response.status_code == 404
        private_preset.refresh_from_db()
        assert private_preset.is_shared is False


@pytest.mark.django_db
class TestCopyVisibility:
    def test_copy_to_shared_presets(self, author_client, admin_acme, private_preset):
        response = author_client.post(_copy_url(private_preset), {"is_shared": True}, format="json")

        assert response.status_code == 201
        clone = AuditFilterPreset.objects.get(pk=response.json()["id"])
        assert (clone.is_shared, clone.created_by_id) == (True, admin_acme.id)
        private_preset.refresh_from_db()
        assert private_preset.is_shared is False


@pytest.mark.django_db
class TestImportIsPrivate:
    def test_import_ignores_is_shared_in_the_file(self, author_client, admin_acme):
        response = _import(author_client, "From file", is_shared=True)

        assert response.status_code == 200
        imported = AuditFilterPreset.objects.get(name="From file")
        assert (imported.is_shared, imported.created_by_id) == (False, admin_acme.id)


@pytest.mark.django_db
class TestCreatedByName:
    def test_display_name_with_email_fallback(
        self, colleague_client, colleague_acme, admin_acme, acme, authors_preset
    ):
        admin_acme.display_name = "Ada Admin"
        admin_acme.save(update_fields=["display_name"])
        colleague_acme.display_name = None
        colleague_acme.save(update_fields=["display_name"])
        AuditFilterPreset.objects.create(
            org=acme, created_by=colleague_acme, name="Mine", filter_body={}
        )

        names = {
            item["name"]: item["created_by_name"]
            for item in _items(colleague_client.get(reverse("auditfilterpreset-list")))
        }

        assert names == {"Failed runs": "Ada Admin", "Mine": colleague_acme.email}

    def test_list_query_count_does_not_grow_with_authors(
        self, colleague_client, colleague_acme, member_only, acme, authors_preset
    ):
        url = reverse("auditfilterpreset-list")
        # Warm-up, so caches filled by a first request do not skew the comparison.
        colleague_client.get(url)
        with CaptureQueriesContext(connection) as one_author:
            assert colleague_client.get(url).status_code == 200

        for author in (colleague_acme, member_only):
            AuditFilterPreset.objects.create(
                org=acme, created_by=author, name=f"By {author.email}", is_shared=True
            )
        with CaptureQueriesContext(connection) as three_authors:
            assert len(_items(colleague_client.get(url))) == 3

        assert len(three_authors.captured_queries) == len(one_author.captured_queries)
