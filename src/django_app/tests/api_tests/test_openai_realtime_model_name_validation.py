"""`OpenAIRealtimeConfig` model_name validation over the live API (request branch
of `OpenAIRealtimeModelNameValidationMixin`; the `context["org_id"]` branch is
covered in tests/import_export_tests/).
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIRequestFactory

from tables.models.llm_models import RealtimeModel
from tables.models.realtime_models import OpenAIRealtimeConfig
from tables.serializers.model_serializers.realtime_serializers import (
    OpenAIRealtimeConfigSerializer,
)
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

DEAD_MODEL_NAME = "gpt-4o-realtime-preview-2024-12-17"
VALID_MODEL_NAME = "gpt-realtime-1.5"


@pytest.mark.django_db
def test_create_with_registered_model_name_succeeds(
    auth_client, default_org, openai_realtime_builtin_model
):
    url = reverse("openairealtimeconfig-list")
    resp = auth_client.post(
        url, {"custom_name": "cfg", "model_name": VALID_MODEL_NAME}, format="json"
    )
    assert resp.status_code == 201, resp.data


@pytest.mark.django_db
def test_create_with_unregistered_model_name_rejected(
    auth_client, default_org, openai_realtime_builtin_model
):
    url = reverse("openairealtimeconfig-list")
    resp = auth_client.post(
        url, {"custom_name": "cfg", "model_name": DEAD_MODEL_NAME}, format="json"
    )
    assert resp.status_code == 400, resp.data
    # custom_exception_handler flattens DRF's {"model_name": [...]} into
    # {"message": "model_name: <error text>", ...} -- see
    # django_app/settings/rest_framework.py EXCEPTION_HANDLER.
    assert "model_name" in resp.data["message"]


@pytest.mark.django_db
def test_update_with_unchanged_stale_model_name_is_not_revalidated(
    auth_client, default_org, openai_realtime_builtin_model
):
    # Simulates a row that predates the registry (created directly, bypassing
    # the validator) -- its model_name is stale but must not block edits to
    # unrelated fields, since the frontend resends the full form on PUT.
    instance = OpenAIRealtimeConfig.objects.create(
        org=default_org, custom_name="cfg", model_name=DEAD_MODEL_NAME
    )
    url = reverse("openairealtimeconfig-detail", args=[instance.pk])
    resp = auth_client.patch(url, {"custom_name": "renamed"}, format="json")
    assert resp.status_code == 200, resp.data

    instance.refresh_from_db()
    assert instance.custom_name == "renamed"
    assert instance.model_name == DEAD_MODEL_NAME


@pytest.mark.django_db
def test_update_changing_to_unregistered_model_name_rejected(
    auth_client, default_org, openai_realtime_builtin_model
):
    instance = OpenAIRealtimeConfig.objects.create(
        org=default_org, custom_name="cfg", model_name=VALID_MODEL_NAME
    )
    url = reverse("openairealtimeconfig-detail", args=[instance.pk])
    resp = auth_client.patch(url, {"model_name": "totally-made-up-model"}, format="json")
    assert resp.status_code == 400, resp.data

    instance.refresh_from_db()
    assert instance.model_name == VALID_MODEL_NAME


@pytest.mark.django_db
def test_create_with_org_custom_model_name_succeeds(auth_client, default_org, openai_provider):
    RealtimeModel.objects.create(
        name="org-custom-model", provider=openai_provider, is_custom=True, org=default_org
    )
    url = reverse("openairealtimeconfig-list")
    resp = auth_client.post(
        url, {"custom_name": "cfg", "model_name": "org-custom-model"}, format="json"
    )
    assert resp.status_code == 201, resp.data


@pytest.mark.django_db
def test_create_with_foreign_org_custom_model_name_rejected(
    auth_client, default_org, openai_provider, beta
):
    RealtimeModel.objects.create(
        name="foreign-org-custom-model",
        provider=openai_provider,
        is_custom=True,
        org=beta,
    )
    url = reverse("openairealtimeconfig-list")
    resp = auth_client.post(
        url,
        {
            "custom_name": "cfg",
            "model_name": "foreign-org-custom-model",
            "org": beta.id,
        },
        format="json",
    )
    assert resp.status_code == 400, resp.data
    assert "model_name" in resp.data["message"]
    assert not OpenAIRealtimeConfig.objects.filter(custom_name="cfg").exists()


@pytest.mark.django_db
def test_create_with_foreign_org_in_body_uses_user_org_not_body_org(
    auth_client, default_org, openai_realtime_builtin_model, beta
):
    url = reverse("openairealtimeconfig-list")
    resp = auth_client.post(
        url,
        {"custom_name": "cfg", "model_name": VALID_MODEL_NAME, "org": beta.id},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["org"] == default_org.id

    instance = OpenAIRealtimeConfig.objects.get(id=resp.data["id"])
    assert instance.org_id == default_org.id


@pytest.mark.django_db
def test_create_with_non_numeric_org_in_body_does_not_cause_error(
    auth_client, default_org, openai_realtime_builtin_model
):
    url = reverse("openairealtimeconfig-list")
    resp = auth_client.post(
        url,
        {"custom_name": "cfg", "model_name": VALID_MODEL_NAME, "org": "not-a-number"},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["org"] == default_org.id


@pytest.mark.django_db
def test_error_identical_for_nonexistent_vs_foreign_custom_model(
    auth_client, default_org, openai_provider, beta
):
    RealtimeModel.objects.create(
        name="secret-model", provider=openai_provider, is_custom=True, org=beta
    )
    url = reverse("openairealtimeconfig-list")

    foreign_resp = auth_client.post(
        url, {"custom_name": "cfg-a", "model_name": "secret-model"}, format="json"
    )
    nonexistent_resp = auth_client.post(
        url, {"custom_name": "cfg-b", "model_name": "completely-made-up-model"}, format="json"
    )

    assert foreign_resp.status_code == 400, foreign_resp.data
    assert nonexistent_resp.status_code == 400, nonexistent_resp.data
    foreign_message = foreign_resp.data["message"].replace("secret-model", "<name>")
    nonexistent_message = nonexistent_resp.data["message"].replace(
        "completely-made-up-model", "<name>"
    )
    assert foreign_message == nonexistent_message


@pytest.mark.django_db
def test_request_org_wins_over_context_org_id(admin_acme, acme, beta, openai_provider):
    RealtimeModel.objects.create(
        name="acme-only-model", provider=openai_provider, is_custom=True, org=acme
    )
    RealtimeModel.objects.create(
        name="beta-only-model", provider=openai_provider, is_custom=True, org=beta
    )
    request = APIRequestFactory().post("/", HTTP_X_ORGANIZATION_ID=str(acme.id))
    request.user = admin_acme
    context = {"request": request, "org_id": beta.id}

    acme_serializer = OpenAIRealtimeConfigSerializer(
        data={"custom_name": "cfg-acme", "model_name": "acme-only-model"}, context=context
    )
    beta_serializer = OpenAIRealtimeConfigSerializer(
        data={"custom_name": "cfg-beta", "model_name": "beta-only-model"}, context=context
    )

    assert acme_serializer.is_valid(), acme_serializer.errors
    assert not beta_serializer.is_valid()
    assert "model_name" in beta_serializer.errors
