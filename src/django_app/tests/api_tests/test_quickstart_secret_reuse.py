"""Quickstart creates ONE Secret per run, shared by every config in the bundle,
and lets the caller reuse a Secret they already own instead of minting another.

Regression target: before this, every config in a bundle got its own Secret row
holding an identical copy of the key — four rows per openai run, growing
unbounded across runs, because _attach_api_key_secret ran once per config.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from tables.models import Secret
from tables.models.embedding_models import EmbeddingConfig, EmbeddingModel
from tables.models.llm_models import (
    LLMConfig,
    LLMModel,
    RealtimeConfig,
    RealtimeModel,
    RealtimeTranscriptionConfig,
    RealtimeTranscriptionModel,
)
from tables.models.provider import Provider
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.secrets import secret_encryption, secret_service


def error_text(resp):
    """Validation details as one string, whatever shape the body has.

    The view raises ValidationError, and utils/exception_handler.py flattens every
    APIException into {"status_code", "code", "message"} — so the per-field dict
    DRF produces is not what reaches the client.
    """
    return str(resp.data)


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org QuickstartReuse")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Org QuickstartReuse Other")


@pytest.fixture
def client_a(db, django_user_model, org):
    """The project's `auth_client` fixture is inert under tests/settings.py
    (DEFAULT_AUTHENTICATION_CLASSES is cleared), so build the client directly."""
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(
        email="admin_quickstart_reuse@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def quickstart_url():
    return reverse("quickstart")


@pytest.fixture
def openai_seeded(db):
    """QuickstartService does Provider.objects.get(name=...) and get_or_create for
    each model. Mirrors `openai_provider_seeded` in quickstart_test.py."""
    provider = Provider.objects.create(name="openai")
    LLMModel.objects.get_or_create(name="gpt-4o-mini", llm_provider=provider)
    EmbeddingModel.objects.get_or_create(
        name="text-embedding-3-small", embedding_provider=provider
    )
    RealtimeModel.objects.get_or_create(
        name="gpt-4o-mini-realtime-preview-2024-12-17", provider=provider
    )
    RealtimeTranscriptionModel.objects.get_or_create(
        name="whisper-1", provider=provider
    )
    return provider


@pytest.fixture
def gemini_seeded(db):
    provider = Provider.objects.create(name="gemini")
    LLMModel.objects.get_or_create(name="gemini-1.5-pro", llm_provider=provider)
    EmbeddingModel.objects.get_or_create(
        name="text-embedding-004", embedding_provider=provider
    )
    RealtimeModel.objects.get_or_create(
        name="gemini-2.0-flash-live-001", provider=provider
    )
    return provider


@pytest.mark.django_db
def test_cold_start_creates_one_secret_shared_by_the_whole_bundle(
    client_a, org, openai_seeded, quickstart_url
):
    resp = client_a.post(
        quickstart_url,
        {"provider": "openai", "api_key": "sk-cold-start"},
        format="json",
    )
    assert resp.status_code == 200, resp.content

    secrets = Secret.objects.filter(org=org)
    assert secrets.count() == 1, "one Secret per run, not one per config"
    secret = secrets.get()

    name = "quickstart_openai"
    assert LLMConfig.objects.get(custom_name=name).api_key_secret_id == secret.id
    assert EmbeddingConfig.objects.get(custom_name=name).api_key_secret_id == secret.id
    assert RealtimeConfig.objects.get(custom_name=name).api_key_secret_id == secret.id
    assert (
        RealtimeTranscriptionConfig.objects.get(custom_name=name).api_key_secret_id
        == secret.id
    )
    assert secret_encryption.decrypt(encryptedtext=secret.value) == "sk-cold-start"


@pytest.mark.django_db
def test_bundle_secret_is_named_after_the_bundle(
    client_a, org, openai_seeded, quickstart_url
):
    client_a.post(
        quickstart_url, {"provider": "openai", "api_key": "sk-1"}, format="json"
    )

    assert Secret.objects.filter(org=org).get().name == "quickstart-openai-api-key"


@pytest.mark.django_db
def test_second_run_gets_its_own_bundle_named_secret(
    client_a, org, openai_seeded, quickstart_url
):
    client_a.post(
        quickstart_url, {"provider": "openai", "api_key": "sk-1"}, format="json"
    )
    client_a.post(
        quickstart_url, {"provider": "openai", "api_key": "sk-2"}, format="json"
    )

    # Two runs, two secrets — it was eight before this change.
    assert Secret.objects.filter(org=org).count() == 2
    assert set(Secret.objects.filter(org=org).values_list("name", flat=True)) == {
        "quickstart-openai-api-key",
        "quickstart-openai-1-api-key",
    }


@pytest.mark.django_db
def test_gemini_three_config_bundle_shares_one_secret(
    client_a, org, gemini_seeded, quickstart_url
):
    resp = client_a.post(
        quickstart_url, {"provider": "gemini", "api_key": "gm-key"}, format="json"
    )
    assert resp.status_code == 200, resp.content

    secret = Secret.objects.filter(org=org).get()
    name = "quickstart_gemini"
    assert LLMConfig.objects.get(custom_name=name).api_key_secret_id == secret.id
    assert EmbeddingConfig.objects.get(custom_name=name).api_key_secret_id == secret.id
    # gemini creates a realtime config but quickstart() discards the return value,
    # so it is queried by name rather than read off the response.
    assert RealtimeConfig.objects.get(custom_name=name).api_key_secret_id == secret.id
    assert not RealtimeTranscriptionConfig.objects.filter(custom_name=name).exists()


@pytest.mark.django_db
def test_reuse_by_id_creates_no_new_secret(
    client_a, org, openai_seeded, quickstart_url
):
    existing = secret_service.create(text="sk-mine", org=org, name="my-openai-key")

    resp = client_a.post(
        quickstart_url,
        {"provider": "openai", "api_key_secret_id": existing.id},
        format="json",
    )
    assert resp.status_code == 200, resp.content

    assert Secret.objects.filter(org=org).count() == 1, "reuse must create nothing"

    name = "quickstart_openai"
    for model in (
        LLMConfig,
        EmbeddingConfig,
        RealtimeConfig,
        RealtimeTranscriptionConfig,
    ):
        assert model.objects.get(custom_name=name).api_key_secret_id == existing.id


@pytest.mark.django_db
def test_both_credential_forms_rejected(client_a, org, openai_seeded, quickstart_url):
    existing = secret_service.create(text="sk-mine", org=org, name="my-openai-key")

    resp = client_a.post(
        quickstart_url,
        {
            "provider": "openai",
            "api_key": "sk-plain",
            "api_key_secret_id": existing.id,
        },
        format="json",
    )

    assert resp.status_code == 400, resp.content
    assert "not both" in error_text(resp)
    assert not LLMConfig.objects.filter(custom_name="quickstart_openai").exists()


@pytest.mark.django_db
def test_neither_credential_form_rejected(client_a, openai_seeded, quickstart_url):
    resp = client_a.post(quickstart_url, {"provider": "openai"}, format="json")

    assert resp.status_code == 400, resp.content
    assert "api_key_secret_id" in error_text(resp)
    assert not LLMConfig.objects.filter(custom_name="quickstart_openai").exists()


@pytest.mark.django_db
def test_blank_api_key_rejected(client_a, openai_seeded, quickstart_url):
    """api_key keeps DRF's default allow_blank=False, so "" never reaches the
    exactly-one-of check and no keyless bundle can be created."""
    resp = client_a.post(
        quickstart_url, {"provider": "openai", "api_key": ""}, format="json"
    )

    assert resp.status_code == 400, resp.content
    # "may not be blank", not the exactly-one-of message: the field-level check
    # rejects "" before validate() ever sees it.
    assert "may not be blank" in error_text(resp)
    assert not LLMConfig.objects.filter(custom_name="quickstart_openai").exists()


@pytest.mark.django_db
def test_foreign_org_secret_rejected(
    client_a, org, other_org, openai_seeded, quickstart_url
):
    foreign = secret_service.create(text="sk-theirs", org=other_org, name="their-key")

    resp = client_a.post(
        quickstart_url,
        {"provider": "openai", "api_key_secret_id": foreign.id},
        format="json",
    )

    assert resp.status_code == 400, resp.content
    assert "does not exist" in error_text(resp)
    assert not LLMConfig.objects.filter(custom_name="quickstart_openai").exists()
    assert not Secret.objects.filter(org=org).exists()


@pytest.mark.django_db
def test_foreign_secret_error_matches_a_nonexistent_id(
    client_a, other_org, openai_seeded, quickstart_url
):
    """Existence in another org must not be revealed: the rejection for a foreign
    secret must be indistinguishable from one for an id that does not exist."""
    foreign = secret_service.create(text="sk-theirs", org=other_org, name="their-key")
    missing_id = Secret.objects.order_by("-pk").first().pk + 1000

    a = client_a.post(
        quickstart_url,
        {"provider": "openai", "api_key_secret_id": foreign.id},
        format="json",
    )
    b = client_a.post(
        quickstart_url,
        {"provider": "openai", "api_key_secret_id": missing_id},
        format="json",
    )

    assert a.status_code == b.status_code == 400

    def without_digits(detail):
        return "".join(ch for ch in str(detail) if not ch.isdigit())

    assert without_digits(error_text(a)) == without_digits(error_text(b))
