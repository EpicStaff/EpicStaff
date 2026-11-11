import pytest
from django.urls import reverse
from rest_framework import status

from rbac.identity.api_keys.principals import SystemServicePrincipal
from tables.models import LLMConfig, LLMModel, Provider
from tables.models.embedding_models import EmbeddingConfig, EmbeddingModel
from tables.models.llm_models import SystemOneConfig
from tables.models.realtime_models import GeminiRealtimeConfig, OpenAIRealtimeConfig
from tables.models.secret_models import Secret
from tables.services.quickstart_service import QuickstartService
from tables.services.secrets import secret_service
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _authors_of_rows_created_in(org) -> dict[str, set[int | None]]:
    return {
        model.__name__: set(
            model.objects.filter(org=org).values_list("created_by_id", flat=True)
        )
        for model in (
            Secret,
            LLMConfig,
            EmbeddingConfig,
            LLMModel,
            EmbeddingModel,
            OpenAIRealtimeConfig,
            SystemOneConfig,
        )
    }


@pytest.fixture
def openai_provider(db) -> Provider:
    return Provider.objects.create(name="openai")


@pytest.mark.django_db
def test_quickstart_authors_every_created_row_with_acting_user(
    openai_provider, acme, admin_acme
):
    result = QuickstartService().quickstart(
        provider="openai", api_key="sk-test", org_id=acme.id, user=admin_acme
    )

    assert result["success"], result
    assert _authors_of_rows_created_in(acme) == {
        "Secret": {admin_acme.id},
        "LLMConfig": {admin_acme.id},
        "EmbeddingConfig": {admin_acme.id},
        "LLMModel": {admin_acme.id},
        "EmbeddingModel": {admin_acme.id},
        "OpenAIRealtimeConfig": {admin_acme.id},
        "SystemOneConfig": {admin_acme.id},
    }


@pytest.mark.django_db
def test_quickstart_authors_gemini_realtime_config_with_acting_user(acme, admin_acme):
    Provider.objects.create(name="gemini")

    result = QuickstartService().quickstart(
        provider="gemini", api_key="sk-test", org_id=acme.id, user=admin_acme
    )

    assert result["success"], result
    assert set(
        GeminiRealtimeConfig.objects.filter(org=acme).values_list("created_by_id", flat=True)
    ) == {admin_acme.id}


@pytest.mark.django_db
def test_quickstart_reusing_a_secret_keeps_the_secret_author(
    openai_provider, acme, admin_acme, member_only
):
    secret = secret_service.create(
        text="sk-shared", name="shared-key", org=acme, created_by=member_only
    )

    result = QuickstartService().quickstart(
        provider="openai", secret=secret, org_id=acme.id, user=admin_acme
    )

    assert result["success"], result
    secret.refresh_from_db()
    assert secret.created_by_id == member_only.id
    assert result["llm_config"].created_by_id == admin_acme.id


@pytest.mark.django_db
@pytest.mark.parametrize(
    "acting_user", [None, SystemServicePrincipal()], ids=["no-user", "system-principal"]
)
def test_quickstart_without_a_real_user_leaves_rows_unauthored(
    openai_provider, acme, acting_user
):
    result = QuickstartService().quickstart(
        provider="openai", api_key="sk-test", org_id=acme.id, user=acting_user
    )

    assert result["success"], result
    assert all(
        authors == {None} for authors in _authors_of_rows_created_in(acme).values()
    ), _authors_of_rows_created_in(acme)


@pytest.mark.django_db
def test_quickstart_endpoint_authors_configs_with_requesting_user(
    openai_provider, client_as, admin_acme, acme
):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = client.post(
        reverse("quickstart"), {"provider": "openai", "api_key": "sk-test"}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert LLMConfig.objects.get(org=acme).created_by_id == admin_acme.id
    assert EmbeddingConfig.objects.get(org=acme).created_by_id == admin_acme.id


@pytest.mark.django_db
def test_openai_quickstart_creates_one_system_one_config_sharing_the_bundle_secret(
    openai_provider, acme, admin_acme
):
    result = QuickstartService().quickstart(
        provider="openai", api_key="sk-test", org_id=acme.id, user=admin_acme
    )

    assert result["success"], result
    system_one_config = SystemOneConfig.objects.get(org=acme)
    assert system_one_config.provider == "openai"
    assert system_one_config.model_name == "gpt-6-luna"
    assert system_one_config.llm_config_id is None
    assert system_one_config.custom_name == result["config_name"]
    assert system_one_config.api_key_secret_id == result["llm_config"].api_key_secret_id


@pytest.mark.django_db
def test_non_openai_quickstart_creates_no_system_one_config(acme, admin_acme):
    Provider.objects.create(name="gemini")

    result = QuickstartService().quickstart(
        provider="gemini", api_key="sk-test", org_id=acme.id, user=admin_acme
    )

    assert result["success"], result
    assert not SystemOneConfig.objects.filter(org=acme).exists()


@pytest.mark.django_db
def test_openai_quickstart_reusing_a_secret_points_system_one_config_at_it(
    openai_provider, acme, admin_acme
):
    secret = secret_service.create(text="sk-shared", name="shared-key", org=acme)

    result = QuickstartService().quickstart(
        provider="openai", secret=secret, org_id=acme.id, user=admin_acme
    )

    assert result["success"], result
    assert SystemOneConfig.objects.get(org=acme).api_key_secret_id == secret.id


@pytest.mark.django_db
def test_second_openai_quickstart_creates_a_second_system_one_config(
    openai_provider, acme, admin_acme
):
    service = QuickstartService()
    service.quickstart(provider="openai", api_key="sk-1", org_id=acme.id, user=admin_acme)

    result = service.quickstart(
        provider="openai", api_key="sk-2", org_id=acme.id, user=admin_acme
    )

    assert result["success"], result
    assert set(
        SystemOneConfig.objects.filter(org=acme).values_list("custom_name", flat=True)
    ) == {"quickstart_openai", "quickstart_openai_1"}


@pytest.mark.django_db
def test_existing_system_one_config_name_is_skipped_by_quickstart(
    openai_provider, acme, admin_acme
):
    SystemOneConfig.objects.create(
        custom_name="quickstart_openai", provider="openai", model_name="gpt-6-luna", org=acme
    )

    result = QuickstartService().quickstart(
        provider="openai", api_key="sk-test", org_id=acme.id, user=admin_acme
    )

    assert result["success"], result
    assert result["config_name"] == "quickstart_openai_1"
    assert SystemOneConfig.objects.filter(org=acme).count() == 2
