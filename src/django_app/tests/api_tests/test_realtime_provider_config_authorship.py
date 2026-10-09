"""Voice (realtime provider) configs return the same authorship as LLM configs.

`created_by` and `last_edited_by` are user summaries (never an email), `created_at` and
`last_edited_at` ISO times; a create or a real edit through the API records the last edit.
"""

from dataclasses import dataclass
from datetime import timedelta

import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status

from rbac.authorship import record_last_edit
from rbac.models import OrganizationUser, ResourceLastEdit
from tables.models.realtime_models import (
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
    OpenAIRealtimeConfig,
)
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

PREVIOUS_EDIT_AT = timezone.now() - timedelta(days=1)
USER_SUMMARY_KEYS = {"id", "display_name", "avatar_url"}
AUTHORSHIP_KEYS = {"created_by", "created_at", "last_edited_by", "last_edited_at"}


@dataclass(frozen=True)
class ProviderConfig:
    basename: str
    model: type
    # Every key the endpoint returns besides authorship.
    own_keys: frozenset[str]

    def make_row(self, org, name: str, author=None):
        return self.model.objects.create(org=org, custom_name=name, created_by=author)


PROVIDER_CONFIGS = [
    ProviderConfig(
        "openairealtimeconfig",
        OpenAIRealtimeConfig,
        frozenset(
            {
                "id",
                "custom_name",
                "api_key_secret_id",
                "model_name",
                "base_url",
                "transcription_model_name",
                "transcription_api_key_secret_id",
                "voice_recognition_prompt",
                "org",
            }
        ),
    ),
    ProviderConfig(
        "elevenlabsrealtimeconfig",
        ElevenLabsRealtimeConfig,
        frozenset({"id", "custom_name", "api_key_secret_id", "model_name", "language", "org"}),
    ),
    ProviderConfig(
        "geminirealtimeconfig",
        GeminiRealtimeConfig,
        frozenset(
            {
                "id",
                "custom_name",
                "api_key_secret_id",
                "model_name",
                "voice_recognition_prompt",
                "org",
            }
        ),
    ),
]


def _summary(user) -> dict:
    return {"id": user.id, "display_name": user.display_name, "avatar_url": None}


def _last_edit_of(row) -> ResourceLastEdit | None:
    return ResourceLastEdit.objects.filter(
        content_type=ContentType.objects.get_for_model(row), object_id=row.pk
    ).first()


def _rows(body):
    return body["results"] if isinstance(body, dict) else body


@pytest.fixture
def named_admin(admin_acme):
    admin_acme.display_name = "Acme Voice Admin"
    admin_acme.save(update_fields=["display_name"])
    return admin_acme


@pytest.fixture
def colleague(db, django_user_model, acme, role_org_admin):
    user = django_user_model.objects.create_user(
        email="voice-config-colleague@example.com", password="StrongPass123!"
    )
    user.display_name = "Acme Voice Colleague"
    user.save(update_fields=["display_name"])
    OrganizationUser.objects.create(user=user, org=acme, role=role_org_admin)
    return user


@pytest.fixture
def client_in(client_as):
    def _make(user, org):
        client = client_as(user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
        return client

    return _make


@pytest.mark.django_db
@pytest.mark.parametrize("config", PROVIDER_CONFIGS, ids=lambda config: config.basename)
class TestRealtimeProviderConfigAuthorship:
    def test_create_records_the_caller_as_author_and_last_editor(
        self, config, client_in, named_admin, member_only, acme
    ):
        before = timezone.now()

        response = client_in(named_admin, acme).post(
            reverse(f"{config.basename}-list"),
            {"custom_name": "voice-config", "created_by": member_only.id},
            format="json",
        )

        after = timezone.now()
        assert response.status_code == status.HTTP_201_CREATED, response.content
        body = response.json()
        assert set(body) == config.own_keys | AUTHORSHIP_KEYS
        assert body["created_by"] == _summary(named_admin)
        assert body["last_edited_by"] == _summary(named_admin)
        assert before <= parse_datetime(body["created_at"]) <= after
        assert before <= parse_datetime(body["last_edited_at"]) <= after
        assert named_admin.email not in response.content.decode()
        row = config.model.objects.get(pk=body["id"])
        assert row.created_by_id == named_admin.id
        assert _last_edit_of(row).edited_by_id == named_admin.id

    def test_detail_and_list_render_user_summaries(
        self, config, client_in, named_admin, member_only, acme
    ):
        row = config.make_row(acme, "listed-config", author=named_admin)
        record_last_edit(row, named_admin)
        client = client_in(member_only, acme)

        detail = client.get(reverse(f"{config.basename}-detail", args=[row.pk]))
        listing = client.get(reverse(f"{config.basename}-list"))

        assert detail.status_code == status.HTTP_200_OK, detail.content
        assert listing.status_code == status.HTTP_200_OK, listing.content
        listed = next(item for item in _rows(listing.json()) if item["id"] == row.pk)
        for body in (detail.json(), listed):
            assert set(body["created_by"]) == USER_SUMMARY_KEYS
            assert body["created_by"] == _summary(named_admin)
            assert body["last_edited_by"] == _summary(named_admin)
            assert parse_datetime(body["created_at"]) == row.created_at
            assert body["last_edited_at"] is not None
        assert named_admin.email not in detail.content.decode() + listing.content.decode()

    def test_patch_by_colleague_replaces_last_edit_and_keeps_author(
        self, config, client_in, named_admin, colleague, acme
    ):
        row = config.make_row(acme, "edited-config", author=named_admin)
        record_last_edit(row, named_admin, edited_at=PREVIOUS_EDIT_AT)

        response = client_in(colleague, acme).patch(
            reverse(f"{config.basename}-detail", args=[row.pk]),
            {"custom_name": "renamed-config"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["created_by"] == _summary(named_admin)
        assert body["last_edited_by"] == _summary(colleague)
        last_edit = _last_edit_of(row)
        assert last_edit.edited_by_id == colleague.id
        assert last_edit.edited_at > PREVIOUS_EDIT_AT

    def test_other_org_gets_404_and_records_no_edit(
        self, config, client_in, named_admin, acme, beta
    ):
        beta_row = config.make_row(beta, "beta-config")
        url = reverse(f"{config.basename}-detail", args=[beta_row.pk])
        client = client_in(named_admin, acme)

        detail = client.get(url)
        patched = client.patch(url, {"custom_name": "hijacked"}, format="json")

        assert detail.status_code == status.HTTP_404_NOT_FOUND
        assert patched.status_code == status.HTTP_404_NOT_FOUND
        beta_row.refresh_from_db()
        assert beta_row.custom_name == "beta-config"
        assert _last_edit_of(beta_row) is None
