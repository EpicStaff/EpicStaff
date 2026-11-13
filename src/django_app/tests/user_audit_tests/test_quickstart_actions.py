"""A quickstart run records one `created` action per row it created, and an apply records
the org's default models as updated; neither leaves a fallback record.

Presentation tests through the real endpoints; only the auditor sender is replaced.
"""

import pytest
from rest_framework import status

from rbac.models import OrganizationUser
from tables.models.default_models import DefaultModels
from tables.models.embedding_models import EmbeddingModel
from tables.models.llm_models import LLMModel
from tables.models.provider import Provider
from tables.services.quickstart_service import QuickstartService
from tables.services.secrets import secret_service
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

QUICKSTART_MODELS = QuickstartService.PROVIDER_CONFIGS


@pytest.fixture
def admin_client(client_as, admin_acme, acme, beta, role_member):
    # A member of a second org too, so the record's org can only be the checked one.
    OrganizationUser.objects.create(user=admin_acme, org=beta, role=role_member)
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _seed_built_in_models(provider_name: str) -> Provider:
    provider = Provider.objects.create(name=provider_name)
    models = QUICKSTART_MODELS[provider_name]
    LLMModel.objects.create(name=models["llm_model"], llm_provider=provider)
    EmbeddingModel.objects.create(name=models["embedding_model"], embedding_provider=provider)
    return provider


def _recorded(events):
    # Sorted: the order rows are recorded in is not part of the contract.
    return sorted(
        (event.action, event.org_id, event.actor_user_id, event.target_type, event.target_name, event.route)
        for event in events
    )


@pytest.mark.parametrize(
    ("provider_name", "provider_config_types"),
    [
        ("openai", ["OpenAI voice config", "System One config"]),
        ("gemini", ["Gemini voice config"]),
    ],
)
def test_quickstart_records_each_created_row_in_the_checked_org(
    admin_client, admin_acme, acme, sent_events, django_capture_on_commit_callbacks,
    provider_name, provider_config_types,
):
    _seed_built_in_models(provider_name)

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(
            "/api/quickstart/", {"provider": provider_name, "api_key": "sk-test"}, format="json"
        )

    assert response.status_code == status.HTTP_200_OK, response.content
    bundle = f"quickstart_{provider_name}"
    assert _recorded(sent_events) == sorted(
        [
            ("created", acme.id, admin_acme.id, "secret", f"quickstart-{provider_name}-api-key", None),
            ("created", acme.id, admin_acme.id, "LLM config", bundle, None),
            ("created", acme.id, admin_acme.id, "embedding config", bundle, None),
            *(
                ("created", acme.id, admin_acme.id, config_type, bundle, None)
                for config_type in provider_config_types
            ),
        ]
    )


def test_quickstart_records_the_models_it_had_to_create(
    admin_client, acme, sent_events, django_capture_on_commit_callbacks
):
    # No built-in models: quickstart creates the org's own.
    Provider.objects.create(name="openai")

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(
            "/api/quickstart/", {"provider": "openai", "api_key": "sk-test"}, format="json"
        )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert sorted((event.target_type, event.target_name) for event in sent_events) == sorted(
        [
            ("LLM config", "quickstart_openai"),
            ("LLM model", QUICKSTART_MODELS["openai"]["llm_model"]),
            ("OpenAI voice config", "quickstart_openai"),
            ("System One config", "quickstart_openai"),
            ("embedding config", "quickstart_openai"),
            ("embedding model", QUICKSTART_MODELS["openai"]["embedding_model"]),
            ("secret", "quickstart-openai-api-key"),
        ]
    )


def test_quickstart_with_a_reused_secret_records_no_secret(
    admin_client, acme, sent_events, django_capture_on_commit_callbacks
):
    _seed_built_in_models("openai")
    existing = secret_service.create(text="sk-mine", org=acme, name="my-openai-key")

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(
            "/api/quickstart/",
            {"provider": "openai", "api_key_secret_id": existing.id},
            format="json",
        )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert sorted(event.target_type for event in sent_events) == [
        "LLM config",
        "OpenAI voice config",
        "System One config",
        "embedding config",
    ]


def test_failed_quickstart_records_nothing(
    admin_client, acme, sent_events, django_capture_on_commit_callbacks
):
    provider = Provider.objects.create(name="openai")
    # Refused after the secret and the LLM model were created, so both are rolled back.
    EmbeddingModel.objects.create(
        name=QUICKSTART_MODELS["openai"]["embedding_model"],
        embedding_provider=provider,
        org=acme,
        is_custom=True,
        base_url="https://attacker.example",
    )

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(
            "/api/quickstart/", {"provider": "openai", "api_key": "sk-test"}, format="json"
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert sent_events == []


def test_quickstart_apply_that_changes_nothing_records_nothing(
    admin_client, acme, sent_events, django_capture_on_commit_callbacks
):
    _seed_built_in_models("openai")
    admin_client.post("/api/quickstart/", {"provider": "openai", "api_key": "sk-test"}, format="json")
    admin_client.post("/api/quickstart/apply/", {}, format="json")
    sent_events.clear()

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post("/api/quickstart/apply/", {}, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert DefaultModels.objects.get(org=acme).agent_llm_config.custom_name == "quickstart_openai"
    assert sent_events == []
