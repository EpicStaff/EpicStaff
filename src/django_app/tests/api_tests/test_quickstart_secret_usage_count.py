"""A quickstart bundle's secret reports every config it backs, not just one.

Regression target: the configs a run creates all carry the bundle name, and the
usage view counted a named resource once per distinct name — so the whole bundle
folded into one `llm_configs` entry and a secret backing four configs read as
backing one. The resource type in the usage key is what tells them apart, which
is why these assert on a bundle whose configs deliberately still share a name.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from tables.models import Secret
from tables.models.embedding_models import EmbeddingModel
from tables.models.llm_models import (
    LLMModel,
    RealtimeModel,
    RealtimeTranscriptionModel,
)
from tables.models.provider import Provider
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.secrets.usage_service import secret_usage_service


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org QuickstartUsageCount")


@pytest.fixture
def client_a(db, django_user_model, org):
    """The project's `auth_client` fixture is inert under tests/settings.py
    (DEFAULT_AUTHENTICATION_CLASSES is cleared), so build the client directly."""
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(
        email="admin_quickstart_usage@example.com", password="StrongPass123!"
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


def run_quickstart(client, url, *, provider="openai", api_key="sk-test"):
    resp = client.post(url, {"provider": provider, "api_key": api_key}, format="json")
    assert resp.status_code == 200, resp.content
    return resp


def llm_config_items(secret):
    """The `llm_configs` category of this secret's usage payload."""
    summary = secret_usage_service.summary(secret=secret)
    return next(
        category["items"]
        for category in summary["categories"]
        if category["key"] == "llm_configs"
    )


@pytest.mark.django_db
class TestABundleSecretReportsEveryConfigItBacks:
    def test_an_openai_bundle_reports_all_four_configs(
        self, client_a, org, openai_seeded, quickstart_url
    ):
        run_quickstart(client_a, quickstart_url)
        secret = Secret.objects.filter(org=org).get()

        items = llm_config_items(secret)

        # One name, four resources — exactly the collision the type key exists for.
        assert {item["name"] for item in items} == {"quickstart_openai"}
        assert sorted(item["type"] for item in items) == [
            "embedding_config",
            "llm_config",
            "realtime_config",
            "realtime_transcription_config",
        ]

    def test_the_count_matches_the_configs_the_secret_backs(
        self, client_a, org, openai_seeded, quickstart_url
    ):
        """The list chip, not just the dialog: it reached 1 by the same folding."""
        run_quickstart(client_a, quickstart_url)
        secret = Secret.objects.filter(org=org).get()

        assert secret_usage_service.count_for(secret=secret) == 4

    def test_a_gemini_bundle_reports_the_three_configs_it_creates(
        self, client_a, org, gemini_seeded, quickstart_url
    ):
        """Gemini creates no transcription config, so the count follows the bundle
        rather than being a fixed four."""
        run_quickstart(client_a, quickstart_url, provider="gemini", api_key="gm-key")
        secret = Secret.objects.filter(org=org).get()

        assert sorted(item["type"] for item in llm_config_items(secret)) == [
            "embedding_config",
            "llm_config",
            "realtime_config",
        ]
        assert secret_usage_service.count_for(secret=secret) == 3

    def test_each_run_gets_its_own_secret_counted_separately(
        self, client_a, org, openai_seeded, quickstart_url
    ):
        """Two bundles share a name prefix but not a secret, so neither secret may
        pick up the other bundle's configs."""
        run_quickstart(client_a, quickstart_url, api_key="sk-1")
        run_quickstart(client_a, quickstart_url, api_key="sk-2")

        for secret in Secret.objects.filter(org=org):
            assert secret_usage_service.count_for(secret=secret) == 4
