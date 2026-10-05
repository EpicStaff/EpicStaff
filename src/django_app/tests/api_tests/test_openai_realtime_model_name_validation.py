"""Coverage for `OpenAIRealtimeModelNameValidationMixin.validate_model_name`
(EST-3146) on the live API (OpenAIRealtimeConfigSerializer), exercised
end-to-end through the real view (`auth_client`), not an isolated serializer
instantiation -- this is a genuine DRF `request` in serializer context, so it
exercises the request-based org-resolution branch (as opposed to the
import-path tests in tests/import_export_tests/, which exercise the
data-based branch).

`openai_realtime_builtin_model` (tests/fixtures.py) seeds the registry the
validator checks against -- the shared test DB has no builtin OpenAI
realtime models by default.
"""

import pytest
from django.urls import reverse

from tables.models.llm_models import RealtimeModel
from tables.models.realtime_models import OpenAIRealtimeConfig

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
