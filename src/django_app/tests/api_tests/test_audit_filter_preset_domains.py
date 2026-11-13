"""Audit filter presets are kept per audit domain: `?domain=sessions` (the default)
lists, creates, copies, exports and imports the session-audit presets under
AUDIT:read, `?domain=user_actions` the user-action presets under USER_AUDIT:read.
A preset of one domain is invisible from the other, names are unique per domain,
and an invalid domain is a 400 before any data is read."""

import json

import pytest
from django.urls import reverse

from rbac.models import OrganizationUser
from rbac.models.enums import Permission, ResourceType
from tables.import_export.enums import EntityType
from tables.models.audit_filter_preset_models import AuditFilterPreset
from tests.helpers import data_to_json_file
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

SESSIONS = "sessions"
USER_ACTIONS = "user_actions"


@pytest.fixture
def admin_beta(db, django_user_model, beta, role_org_admin):
    user = django_user_model.objects.create_user(
        email="admin-beta-preset-domain@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=beta, role=role_org_admin)
    return user


@pytest.fixture
def colleague_acme(db, django_user_model, acme, role_org_admin):
    user = django_user_model.objects.create_user(
        email="colleague-acme-preset-domain@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_org_admin)
    return user


def _client_in_org(client_as, user, org):
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def author_client(client_as, admin_acme, acme):
    return _client_in_org(client_as, admin_acme, acme)


def _preset(org, author, name, domain, filter_body=None, is_shared=False):
    return AuditFilterPreset.objects.create(
        org=org,
        created_by=author,
        name=name,
        domain=domain,
        filter_body=filter_body or {"query": "status = failed"},
        is_shared=is_shared,
    )


def _with_domain(url, domain):
    return f"{url}?domain={domain}"


def _list_url(domain):
    return _with_domain(reverse("auditfilterpreset-list"), domain)


def _detail_url(preset, domain):
    return _with_domain(reverse("auditfilterpreset-detail", kwargs={"pk": preset.id}), domain)


def _items(response):
    body = response.json()
    return body["results"] if isinstance(body, dict) else body


def _import(client, entries, domain=None):
    payload = {
        "main_entity": EntityType.AUDIT_FILTER_PRESET,
        "version": 3,
        EntityType.AUDIT_FILTER_PRESET: entries,
    }
    url = reverse("auditfilterpreset-import-presets")
    return client.post(
        url if domain is None else _with_domain(url, domain),
        {"file": data_to_json_file(payload, "import.json")},
        format="multipart",
    )


@pytest.mark.django_db
class TestDomainPermission:
    @pytest.mark.parametrize(
        ("granted", "denied_domain", "allowed_domain"),
        [
            (ResourceType.AUDIT, USER_ACTIONS, SESSIONS),
            (ResourceType.USER_AUDIT, SESSIONS, USER_ACTIONS),
        ],
    )
    def test_each_domain_needs_its_own_audit_read(
        self, client_as, custom_role_user, acme, granted, denied_domain, allowed_domain
    ):
        user = custom_role_user(acme, f"{granted.value}-only@example.com", {granted: Permission.READ})
        client = _client_in_org(client_as, user, acme)

        assert client.get(_list_url(denied_domain)).status_code == 403
        assert (
            client.post(
                _list_url(denied_domain), {"name": "x", "filter_body": {}}, format="json"
            ).status_code
            == 403
        )
        assert client.get(_list_url(allowed_domain)).status_code == 200

    def test_missing_domain_means_sessions(self, client_as, custom_role_user, acme, admin_acme):
        sessions_preset = _preset(acme, admin_acme, "shared", SESSIONS, is_shared=True)
        user = custom_role_user(acme, "audit-reader@example.com", {ResourceType.AUDIT: Permission.READ})
        client = _client_in_org(client_as, user, acme)

        response = client.get(reverse("auditfilterpreset-list"))

        assert response.status_code == 200
        assert [item["id"] for item in _items(response)] == [sessions_preset.id]

    @pytest.mark.parametrize("domain", ["bogus", "", "SESSIONS"])
    def test_invalid_domain_is_400_even_for_a_superadmin(
        self, superadmin_in_acme, acme, admin_acme, domain
    ):
        preset = _preset(acme, admin_acme, "mine", SESSIONS, is_shared=True)

        list_response = superadmin_in_acme.get(_list_url(domain))
        detail_response = superadmin_in_acme.get(_detail_url(preset, domain))

        assert list_response.status_code == 400
        assert "domain" in list_response.json()["message"]
        assert detail_response.status_code == 400


@pytest.mark.django_db
class TestPresetsPerDomain:
    def test_presets_listed_per_domain(self, author_client, acme, admin_acme):
        sessions_preset = _preset(acme, admin_acme, "sessions one", SESSIONS)
        user_actions_preset = _preset(acme, admin_acme, "user actions one", USER_ACTIONS)

        sessions_list = author_client.get(_list_url(SESSIONS))
        user_actions_list = author_client.get(_list_url(USER_ACTIONS))

        assert [item["id"] for item in _items(sessions_list)] == [sessions_preset.id]
        assert [item["id"] for item in _items(user_actions_list)] == [user_actions_preset.id]

    @pytest.mark.parametrize("method", ["get", "patch", "delete"])
    def test_a_preset_is_not_found_from_the_other_domain(
        self, author_client, acme, admin_acme, method
    ):
        sessions_preset = _preset(acme, admin_acme, "sessions one", SESSIONS)

        url = _detail_url(sessions_preset, USER_ACTIONS)
        # A GET body would replace the URL's query string, dropping ?domain=.
        response = (
            author_client.get(url)
            if method == "get"
            else getattr(author_client, method)(url, {"name": "renamed"}, format="json")
        )

        assert response.status_code == 404
        sessions_preset.refresh_from_db()
        assert sessions_preset.name == "sessions one"

    def test_create_stamps_the_request_domain(self, author_client):
        response = author_client.post(
            _list_url(USER_ACTIONS),
            {"name": "who deleted flows", "filter_body": {"query": 'action = "delete"'}},
            format="json",
        )

        assert response.status_code == 201
        assert AuditFilterPreset.objects.get(pk=response.json()["id"]).domain == USER_ACTIONS

    def test_same_name_allowed_in_both_domains(self, author_client, acme, admin_acme):
        _preset(acme, admin_acme, "Failed", SESSIONS)

        first = author_client.post(
            _list_url(USER_ACTIONS), {"name": "Failed", "filter_body": {}}, format="json"
        )
        duplicate = author_client.post(
            _list_url(USER_ACTIONS), {"name": "Failed", "filter_body": {}}, format="json"
        )

        assert first.status_code == 201
        assert duplicate.status_code == 400
        assert set(
            AuditFilterPreset.objects.filter(name="Failed").values_list("domain", flat=True)
        ) == {SESSIONS, USER_ACTIONS}

    def test_rename_onto_a_name_used_only_in_the_other_domain_is_allowed(
        self, author_client, acme, admin_acme
    ):
        _preset(acme, admin_acme, "Taken in sessions", SESSIONS)
        user_actions_preset = _preset(acme, admin_acme, "mine", USER_ACTIONS)

        response = author_client.patch(
            _detail_url(user_actions_preset, USER_ACTIONS),
            {"name": "Taken in sessions"},
            format="json",
        )

        assert response.status_code == 200

    def test_user_actions_body_rejects_match_scope(self, author_client):
        body = {"query": "", "match_scope": {"children": True}}

        user_actions_response = author_client.post(
            _list_url(USER_ACTIONS), {"name": "scoped", "filter_body": body}, format="json"
        )
        sessions_response = author_client.post(
            _list_url(SESSIONS), {"name": "scoped", "filter_body": body}, format="json"
        )

        assert user_actions_response.status_code == 400
        assert "match_scope" in json.dumps(user_actions_response.json())
        assert sessions_response.status_code == 201

    def test_user_actions_body_accepts_its_own_keys(self, author_client):
        body = {
            "filters": {"field": "action", "op": "eq", "value": "delete"},
            "cursor": "abc",
            "size": 20,
            "ui_state": {"version": 1},
        }

        response = author_client.post(
            _list_url(USER_ACTIONS), {"name": "deletes", "filter_body": body}, format="json"
        )

        assert response.status_code == 201
        assert AuditFilterPreset.objects.get(name="deletes").filter_body == body

    def test_copy_stays_in_the_domain_and_numbers_against_it_only(
        self, author_client, acme, admin_acme
    ):
        # A sessions preset already holds "Failed (2)"; it must not push the copy to (3).
        _preset(acme, admin_acme, "Failed (2)", SESSIONS)
        original = _preset(acme, admin_acme, "Failed", USER_ACTIONS)

        response = author_client.post(
            _with_domain(reverse("auditfilterpreset-copy", kwargs={"pk": original.id}), USER_ACTIONS),
            {},
            format="json",
        )

        assert response.status_code == 201
        clone = AuditFilterPreset.objects.get(pk=response.json()["id"])
        assert (clone.name, clone.domain) == ("Failed (2)", USER_ACTIONS)

    def test_visibility_rules_hold_in_user_actions(
        self, client_as, colleague_acme, acme, admin_acme
    ):
        shared = _preset(acme, admin_acme, "shared", USER_ACTIONS, is_shared=True)
        private = _preset(acme, admin_acme, "private", USER_ACTIONS)
        colleague_client = _client_in_org(client_as, colleague_acme, acme)

        listed = colleague_client.get(_list_url(USER_ACTIONS))
        delete_shared = colleague_client.delete(_detail_url(shared, USER_ACTIONS))

        assert [item["id"] for item in _items(listed)] == [shared.id]
        assert colleague_client.get(_detail_url(private, USER_ACTIONS)).status_code == 404
        assert delete_shared.status_code == 404
        assert AuditFilterPreset.objects.filter(pk=shared.pk).exists()

    def test_another_orgs_user_actions_preset_is_404(
        self, client_as, admin_beta, beta, acme, admin_acme
    ):
        acme_preset = _preset(acme, admin_acme, "acme shared", USER_ACTIONS, is_shared=True)
        beta_client = _client_in_org(client_as, admin_beta, beta)

        assert beta_client.get(_detail_url(acme_preset, USER_ACTIONS)).status_code == 404
        assert _items(beta_client.get(_list_url(USER_ACTIONS))) == []


@pytest.mark.django_db
class TestImportExportPerDomain:
    def test_export_carries_the_domain(self, author_client, acme, admin_acme):
        preset = _preset(acme, admin_acme, "deletes", USER_ACTIONS)

        response = author_client.get(
            _with_domain(reverse("auditfilterpreset-export", kwargs={"pk": preset.id}), USER_ACTIONS)
        )

        assert response.status_code == 200
        [entry] = json.loads(response.content)[EntityType.AUDIT_FILTER_PRESET]
        assert entry["domain"] == USER_ACTIONS

    def test_exported_user_actions_file_imports_into_another_org_in_user_actions(
        self, author_client, client_as, admin_beta, beta, acme, admin_acme
    ):
        preset = _preset(acme, admin_acme, "deletes", USER_ACTIONS, filter_body={"query": "x"})
        exported = author_client.get(
            _with_domain(reverse("auditfilterpreset-export", kwargs={"pk": preset.id}), USER_ACTIONS)
        )
        beta_client = _client_in_org(client_as, admin_beta, beta)

        response = beta_client.post(
            _with_domain(reverse("auditfilterpreset-import-presets"), USER_ACTIONS),
            {"file": data_to_json_file(json.loads(exported.content), "export.json")},
            format="multipart",
        )

        assert response.status_code == 200
        imported = AuditFilterPreset.objects.get(org=beta)
        assert (imported.name, imported.domain, imported.filter_body, imported.created_by_id) == (
            "deletes",
            USER_ACTIONS,
            {"query": "x"},
            admin_beta.id,
        )

    def test_import_old_file_lands_in_sessions(self, author_client):
        response = _import(author_client, [{"id": 1, "name": "old file", "filter_body": {"query": ""}}])

        assert response.status_code == 200
        assert AuditFilterPreset.objects.get(name="old file").domain == SESSIONS

    def test_import_user_actions_file_lands_in_user_actions(self, author_client):
        response = _import(
            author_client,
            [{"id": 1, "name": "deletes", "domain": USER_ACTIONS, "filter_body": {"query": "x"}}],
            domain=USER_ACTIONS,
        )

        assert response.status_code == 200
        assert AuditFilterPreset.objects.get(name="deletes").domain == USER_ACTIONS

    @pytest.mark.parametrize(
        ("file_domain", "request_domain"),
        [(USER_ACTIONS, SESSIONS), (SESSIONS, USER_ACTIONS), (None, USER_ACTIONS), ("bogus", SESSIONS)],
    )
    def test_import_into_other_domain_rejected(self, author_client, file_domain, request_domain):
        entry = {"id": 1, "name": "wrong domain", "filter_body": {"query": ""}}
        if file_domain is not None:
            entry["domain"] = file_domain

        response = _import(author_client, [entry], domain=request_domain)

        assert response.status_code == 400
        assert not AuditFilterPreset.objects.exists()

    def test_import_does_not_reuse_a_preset_of_the_other_domain(
        self, author_client, acme, admin_acme
    ):
        sessions_preset = _preset(acme, admin_acme, "same search", SESSIONS, filter_body={"query": "x"})

        response = _import(
            author_client,
            [{"id": 1, "name": "same search", "domain": USER_ACTIONS, "filter_body": {"query": "x"}}],
            domain=USER_ACTIONS,
        )

        assert response.status_code == 200
        summary = response.json()[EntityType.AUDIT_FILTER_PRESET]
        assert (summary["created"]["count"], summary["reused"]["count"]) == (1, 0)
        created = AuditFilterPreset.objects.exclude(pk=sessions_preset.pk).get()
        # The sessions preset's name does not count against the user_actions domain.
        assert (created.name, created.domain) == ("same search", USER_ACTIONS)

    def test_import_validates_the_body_against_the_domain(self, author_client):
        response = _import(
            author_client,
            [
                {
                    "id": 1,
                    "name": "scoped",
                    "domain": USER_ACTIONS,
                    "filter_body": {"match_scope": {"children": True}},
                }
            ],
            domain=USER_ACTIONS,
        )

        assert response.status_code == 400
        assert not AuditFilterPreset.objects.exists()
