"""Smoke tests for the service-layer readers of the six Secret FKs.

The FK-wiring change renamed the raw credential columns out from under several
services. Every one of them is now wired: quickstart and Telegram directly, the
converter via id-carrying payload fields, and the FlowAssistant streaming path
via SecretResolver.resolve called by the caller of LiteLLMClient (never by
LiteLLMClient itself — see litellm_client.py). Nothing here is deferred any more.
"""

import pytest

from tables.models import EmbeddingConfig, LLMConfig, Provider, RealtimeConfig
from tables.models.graph_models import Graph, TelegramTriggerNode
from tables.models.rbac_models import Organization
from tables.services.quickstart_service import QuickstartService
from tables.services.secrets import secret_encryption
from tables.services.telegram_trigger_service import TelegramTriggerService


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org SecretCallSites")


@pytest.fixture
def fresh_telegram_service():
    """TelegramTriggerService is a SingletonMeta, so a cached instance from an
    earlier construction would silently keep its original dependencies. Drop it
    so each test gets a service built with its own stubs."""
    from utils.singleton_meta import SingletonMeta

    previous = SingletonMeta._instances.get(TelegramTriggerService)

    def _build(**kwargs):
        SingletonMeta._instances.pop(TelegramTriggerService, None)
        return TelegramTriggerService(**kwargs)

    yield _build

    # Restore, not just clear: other tests call TelegramTriggerService() with no
    # arguments and rely on an already-cached instance being there.
    if previous is None:
        SingletonMeta._instances.pop(TelegramTriggerService, None)
    else:
        SingletonMeta._instances[TelegramTriggerService] = previous


@pytest.mark.django_db
class TestQuickstartWrapsKeyInSecret:
    """/api/quickstart is the new-org onboarding flow; its whole input is a
    provider API key, so it must produce Secret-backed configs, not raw keys."""

    def test_quickstart_creates_secret_backed_configs(self, org):
        Provider.objects.get_or_create(name="openai")

        result = QuickstartService().quickstart(
            provider="openai", api_key="sk-quickstart-test-9876", org_id=org.id
        )

        assert result, "quickstart returned nothing"

        llm_config = LLMConfig.objects.filter(org=org).first()
        assert llm_config is not None, "quickstart created no LLMConfig"
        assert llm_config.api_key_secret is not None, "api_key was not stored as Secret"
        assert llm_config.api_key_secret.org_id == org.id
        assert (
            secret_encryption.decrypt(encryptedtext=llm_config.api_key_secret.value)
            == "sk-quickstart-test-9876"
        )

        # Every config type quickstart creates for this provider is Secret-backed.
        # They all share the one Secret created for the bundle — see
        # test_quickstart_secret_reuse.py for the sharing assertions.
        for model_cls in (EmbeddingConfig, RealtimeConfig):
            config = model_cls.objects.filter(org=org).first()
            if config is None:
                continue
            assert (
                config.api_key_secret is not None
            ), f"{model_cls.__name__} has no Secret attached"
            assert (
                secret_encryption.decrypt(encryptedtext=config.api_key_secret.value)
                == "sk-quickstart-test-9876"
            )

    def test_quickstart_secret_names_do_not_collide(self, org):
        Provider.objects.get_or_create(name="openai")
        QuickstartService().quickstart(
            provider="openai", api_key="sk-first", org_id=org.id
        )
        QuickstartService().quickstart(
            provider="openai", api_key="sk-second", org_id=org.id
        )

        names = list(
            LLMConfig.objects.filter(org=org)
            .exclude(api_key_secret=None)
            .values_list("api_key_secret__name", flat=True)
        )
        assert len(names) == len(set(names)), f"duplicate Secret names: {names}"


@pytest.mark.django_db
class TestTelegramRegistrationReadsSecret:
    """register_telegram_trigger used to read the deleted raw column; the bug was
    invisible because the post_save receiver swallows the exception."""

    def test_registration_skips_cleanly_when_no_secret_attached(
        self, org, fresh_telegram_service
    ):
        from types import SimpleNamespace

        graph = Graph.objects.create(name="telegram-no-secret", org=org)
        node = TelegramTriggerNode.objects.create(
            graph=graph, node_name="telegram_no_secret"
        )
        service = fresh_telegram_service(
            session_manager_service=SimpleNamespace(),
            webhook_trigger_service=None,
        )

        # No AttributeError, no Telegram API call — just an early return.
        assert service.register_telegram_trigger(telegram_trigger_instance=node) is None

    def test_registration_sends_the_decrypted_key_to_telegram(
        self, org, monkeypatch, fresh_telegram_service
    ):
        from types import SimpleNamespace

        from tables.models.webhook_models import (
            NgrokWebhookConfig,
            ProviderType,
            WebhookTrigger,
        )
        from tables.services.secrets import secret_service

        graph = Graph.objects.create(name="telegram-with-secret", org=org)
        webhook_trigger = WebhookTrigger.objects.create(
            path="telegram-secret-path",
            provider_type=ProviderType.NGROK,
            org=org,
        )
        NgrokWebhookConfig.objects.create(
            name="ngrok-telegram-test",
            trigger=webhook_trigger,
            auth_token_secret=secret_service.create(
                text="ngrok-token-test", org=org, name="ngrok-telegram-test-secret"
            ),
        )
        node = TelegramTriggerNode.objects.create(
            graph=graph,
            node_name="telegram_with_secret",
            webhook_trigger=webhook_trigger,
            telegram_bot_api_key_secret=secret_service.create(
                text="bot-token-zzz9", org=org, name="telegram-registration-key"
            ),
        )

        service = fresh_telegram_service(
            session_manager_service=SimpleNamespace(),
            webhook_trigger_service=SimpleNamespace(
                wait_for_tunnel_url_for_trigger=lambda trigger: "https://tunnel.test",
                # register_telegram_trigger now unconditionally
                # pushes the WebhookNodeAuth credential before calling
                # Telegram -- needs this on the stub too.
                register_webhooks=lambda: True,
            ),
        )

        seen = {}

        def fake_call(method, api_key, endpoint, params=None):
            seen.update(
                method=method, api_key=api_key, endpoint=endpoint, params=params
            )
            return {"ok": True}

        monkeypatch.setattr(service, "_call_telegram_api", fake_call)

        service.register_telegram_trigger(telegram_trigger_instance=node)

        assert seen["endpoint"] == "setWebhook"
        assert (
            seen["api_key"] == "bot-token-zzz9"
        ), "Telegram was handed something other than the decrypted bot token"


@pytest.mark.django_db
class TestPayloadAndInProcessConsumers:
    """Both former plaintext readers are now wired through SecretResolver — the
    converter emits ids into the payload, litellm_client resolves in-process."""

    def test_converter_service_can_convert_embedding_config(self, org):
        from tables.models import EmbeddingModel
        from tables.services.converter_service import ConverterService

        provider, _ = Provider.objects.get_or_create(name="openai")
        model = EmbeddingModel.objects.create(
            name="text-embedding-conv-test", embedding_provider=provider
        )
        config = EmbeddingConfig.objects.create(
            custom_name="conv-test", model=model, org=org
        )

        data = ConverterService().convert_embedding_config_to_pydantic(
            embedding_config=config
        )

        assert data.config.api_key is None
        assert data.config.api_key_secret_id is None

    def test_secret_resolver_resolves_litellm_config_api_key(self, org):
        """The resolver turns a LiteLLM config's api_key_secret FK into plaintext.

        LiteLLMClient no longer calls the resolver itself (it is constructed on
        an async request path — see litellm_client.py docstring); the caller
        resolves this value. This test covers that resolution in isolation.
        """
        from tables.models import LLMModel
        from tables.services.secrets import secret_resolver, secret_service

        provider, _ = Provider.objects.get_or_create(name="openai")
        model = LLMModel.objects.create(name="gpt-4o-lite-test", llm_provider=provider)
        secret = secret_service.create(
            text="sk-litellm-resolved", org=org, name="litellm-key"
        )
        config = LLMConfig.objects.create(
            custom_name="lite-test", model=model, org=org, api_key_secret=secret
        )

        api_key = secret_resolver.resolve(
            secret_id=config.api_key_secret_id,
            org_id=config.org_id,
            context="LiteLLMClient.api_key",
        )

        assert api_key == "sk-litellm-resolved"

    def test_litellm_client_build_kwargs_includes_supplied_api_key(self, org):
        from tables.models import LLMModel
        from tables.services.llm_clients.litellm_client import LiteLLMClient

        provider, _ = Provider.objects.get_or_create(name="openai")
        model = LLMModel.objects.create(name="gpt-4o-lite-test", llm_provider=provider)
        config = LLMConfig.objects.create(custom_name="lite-test", model=model, org=org)

        kwargs = LiteLLMClient(
            llm_config=config, api_key="sk-litellm-resolved"
        )._build_kwargs(messages=[], tools=[])

        assert kwargs["api_key"] == "sk-litellm-resolved"

    def test_litellm_client_omits_api_key_when_none(self, org):
        from tables.models import LLMModel
        from tables.services.llm_clients.litellm_client import LiteLLMClient

        provider, _ = Provider.objects.get_or_create(name="openai")
        model = LLMModel.objects.create(name="gpt-4o-lite-nokey", llm_provider=provider)
        config = LLMConfig.objects.create(
            custom_name="lite-no-key", model=model, org=org
        )

        kwargs = LiteLLMClient(llm_config=config, api_key=None)._build_kwargs(
            messages=[], tools=[]
        )

        assert "api_key" not in kwargs
