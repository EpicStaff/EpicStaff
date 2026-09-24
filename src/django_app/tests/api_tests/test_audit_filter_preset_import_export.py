import json

import pytest
from django.urls import reverse

from tables.import_export.enums import EntityType
from tables.models.audit_filter_preset_models import AuditFilterPreset
from tests.helpers import data_to_json_file


@pytest.fixture
def preset(regular_user, default_org):
    return AuditFilterPreset.objects.create(
        org=default_org,
        created_by=regular_user,
        name="my preset",
        filter_body={"query": "status = failed"},
    )


def _envelope(presets: list[dict]) -> dict:
    """Matches the shape ExportService/JsonExportFormatStrategy actually
    produce (and what a real export download looks like): {main_entity,
    version, <EntityType>: [...]}, not the bare/`{"presets": [...]}` shape
    - see AUDIT_FILTER_PRESET_IMPORT / AuditFilterPresetViewSet.import_presets."""
    return {
        "main_entity": EntityType.AUDIT_FILTER_PRESET,
        "version": 3,
        EntityType.AUDIT_FILTER_PRESET: presets,
    }


@pytest.mark.django_db
class TestAuditFilterPresetExport:
    def test_export_single_returns_envelope_with_preset(self, auth_client, preset):
        url = reverse("auditfilterpreset-export", kwargs={"pk": preset.id})
        response = auth_client.get(url)

        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["main_entity"] == EntityType.AUDIT_FILTER_PRESET
        assert data[EntityType.AUDIT_FILTER_PRESET] == [
            {"id": preset.id, "name": preset.name, "filter_body": preset.filter_body}
        ]

    def test_bulk_export_returns_envelope_with_all_ids(self, auth_client, preset):
        url = reverse("auditfilterpreset-bulk-export")
        response = auth_client.post(url, {"ids": [preset.id]}, format="json")

        assert response.status_code == 200
        data = json.loads(response.content)
        assert data[EntityType.AUDIT_FILTER_PRESET] == [
            {"id": preset.id, "name": preset.name, "filter_body": preset.filter_body}
        ]

    def test_bulk_export_unknown_id_400s(self, auth_client, preset):
        url = reverse("auditfilterpreset-bulk-export")
        response = auth_client.post(
            url, {"ids": [preset.id, 999999]}, format="json"
        )

        assert response.status_code == 400

    def test_bulk_export_repeated_id_exports_it_once(self, auth_client, preset):
        url = reverse("auditfilterpreset-bulk-export")
        response = auth_client.post(
            url, {"ids": [preset.id, preset.id]}, format="json"
        )

        assert response.status_code == 200
        data = json.loads(response.content)
        assert [item["id"] for item in data[EntityType.AUDIT_FILTER_PRESET]] == [
            preset.id
        ]

    def test_export_of_another_orgs_preset_404s(
        self, auth_client, django_user_model
    ):
        from tables.models.rbac_models import Organization

        other_org = Organization.objects.create(name="Other org for presets")
        other_owner = django_user_model.objects.create_user(
            email="preset-owner-other-org@example.com", password="StrongPass123!"
        )
        foreign_preset = AuditFilterPreset.objects.create(
            org=other_org,
            created_by=other_owner,
            name="foreign",
            filter_body={"query": ""},
        )

        url = reverse("auditfilterpreset-export", kwargs={"pk": foreign_preset.id})
        response = auth_client.get(url)

        assert response.status_code == 404


@pytest.mark.django_db
class TestAuditFilterPresetImport:
    def _import(self, auth_client, payload, filename="import.json"):
        file = data_to_json_file(payload, filename)
        url = reverse("auditfilterpreset-import-presets")
        return auth_client.post(url, {"file": file}, format="multipart")

    def _entity_summary(self, data: dict) -> dict:
        """The response is the raw `IDMapper.get_detailed_summary()` dict,
        keyed by entity type - same shape GraphViewSet.partial_import
        returns."""
        return data[EntityType.AUDIT_FILTER_PRESET]

    def test_import_single_creates_preset(self, auth_client, regular_user):
        payload = _envelope(
            [{"id": 1, "name": "single preset", "filter_body": {"query": ""}}]
        )
        response = self._import(auth_client, payload)

        assert response.status_code == 200
        entity_summary = self._entity_summary(response.json())
        assert entity_summary["total"] == 1
        assert entity_summary["reused"]["count"] == 0
        assert entity_summary["created"]["count"] == 1
        assert entity_summary["created"]["items"][0]["name"] == "single preset"

        created = AuditFilterPreset.objects.get(name="single preset")
        assert created.created_by_id == regular_user.id

    def test_import_batch_creates_presets(self, auth_client):
        payload = _envelope(
            [
                {"id": 1, "name": "batch preset 1", "filter_body": {"query": ""}},
                {
                    "id": 2,
                    "name": "batch preset 2",
                    "filter_body": {"match_scope": {"children": True}},
                },
            ]
        )
        response = self._import(auth_client, payload)

        assert response.status_code == 200
        entity_summary = self._entity_summary(response.json())
        assert entity_summary["created"]["count"] == 2
        assert entity_summary["reused"]["count"] == 0
        assert (
            AuditFilterPreset.objects.filter(
                name__in=["batch preset 1", "batch preset 2"]
            ).count()
            == 2
        )

    def test_import_duplicate_name_skipped(self, auth_client, preset):
        payload = _envelope(
            [{"id": 1, "name": preset.name, "filter_body": {"query": "new"}}]
        )
        response = self._import(auth_client, payload)

        assert response.status_code == 200
        entity_summary = self._entity_summary(response.json())
        assert entity_summary["created"]["count"] == 0
        assert entity_summary["reused"]["count"] == 1
        assert entity_summary["reused"]["items"][0]["name"] == preset.name
        assert AuditFilterPreset.objects.filter(name=preset.name).count() == 1
        # existing row untouched - reused, not overwritten
        preset.refresh_from_db()
        assert preset.filter_body == {"query": "status = failed"}

    def test_import_missing_name_400s_not_500(self, auth_client):
        """A malformed item (missing the required "name") is rejected with
        a 400 via AuditFilterPresetStrategy.find_existing's validation, not
        an unhandled 500. Per the shared ImportService's single atomic
        transaction, this aborts the whole request rather than reporting
        that one item independently in `failed` - see the import_presets
        docstring for that known limitation."""
        payload = _envelope([{"id": 1, "filter_body": {"query": ""}}])
        response = self._import(auth_client, payload)

        assert response.status_code == 400
        assert not AuditFilterPreset.objects.exists()

    def test_import_rejects_filter_body_the_create_endpoint_would_reject(
        self, auth_client
    ):
        payload = _envelope(
            [{"id": 1, "name": "bad body", "filter_body": {"not_a_key": 1}}]
        )
        response = self._import(auth_client, payload)

        assert response.status_code == 400
        assert not AuditFilterPreset.objects.filter(name="bad body").exists()

    def test_import_rejects_name_over_max_length(self, auth_client):
        payload = _envelope([{"id": 1, "name": "n" * 151, "filter_body": {}}])
        response = self._import(auth_client, payload)

        assert response.status_code == 400
        assert not AuditFilterPreset.objects.exists()

    def test_import_ignores_org_and_created_by_from_file(
        self, auth_client, regular_user, default_org
    ):
        payload = _envelope(
            [
                {
                    "id": 1,
                    "name": "spoofed owner",
                    "filter_body": {"query": ""},
                    "org": 999999,
                    "created_by": 999999,
                }
            ]
        )
        response = self._import(auth_client, payload)

        assert response.status_code == 200
        created = AuditFilterPreset.objects.get(name="spoofed owner")
        assert created.created_by_id == regular_user.id
        assert created.org_id == default_org.id

    def test_import_wrong_main_entity_400s(self, auth_client):
        payload = {
            "main_entity": EntityType.LABEL,
            EntityType.LABEL: [],
        }
        response = self._import(auth_client, payload)
        assert response.status_code == 400

    def test_deleting_the_owner_deletes_their_presets(self, preset, regular_user):
        regular_user.delete()

        assert not AuditFilterPreset.objects.filter(pk=preset.pk).exists()

    def test_import_invalid_json_400s_not_500(self, auth_client):
        from io import BytesIO

        file = BytesIO(b"not valid json {{{")
        file.name = "bad.json"
        url = reverse("auditfilterpreset-import-presets")
        response = auth_client.post(url, {"file": file}, format="multipart")

        assert response.status_code == 400
