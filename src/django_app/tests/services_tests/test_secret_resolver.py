import pytest

from tables.models import Secret
from tables.models.rbac_models import Organization
from tables.services.secrets import (
    SecretResolutionError,
    secret_resolver,
    secret_service,
)


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org SecretResolver")


@pytest.mark.django_db
class TestResolveById:
    def test_none_id_returns_none(self):
        assert secret_resolver.resolve(secret_id=None) is None

    def test_returns_exact_plaintext(self, org):
        secret = secret_service.create(
            text="sk-resolver-plaintext-1234", org=org, name="resolver-happy"
        )
        assert (
            secret_resolver.resolve(secret_id=secret.pk) == "sk-resolver-plaintext-1234"
        )

    def test_missing_row_raises(self, org):
        secret = secret_service.create(text="sk-doomed", org=org, name="resolver-gone")
        secret_id = secret.pk
        secret.delete()

        with pytest.raises(SecretResolutionError):
            secret_resolver.resolve(secret_id=secret_id)

    def test_corrupt_ciphertext_raises_resolution_error_not_decryption_error(self, org):
        secret = secret_service.create(text="sk-fine", org=org, name="resolver-corrupt")
        Secret.objects.filter(pk=secret.pk).update(value="not-valid-fernet")

        # The caller sees one exception type regardless of the underlying cause.
        with pytest.raises(SecretResolutionError):
            secret_resolver.resolve(secret_id=secret.pk)

    def test_error_message_names_context_and_never_the_value(self, org):
        secret = secret_service.create(
            text="sk-must-not-appear", org=org, name="resolver-msg"
        )
        Secret.objects.filter(pk=secret.pk).update(value="not-valid-fernet")

        with pytest.raises(SecretResolutionError) as exc:
            secret_resolver.resolve(
                secret_id=secret.pk, context="LLMConfigData.api_key"
            )

        message = str(exc.value)
        assert "LLMConfigData.api_key" in message
        assert str(secret.pk) in message
        assert "sk-must-not-appear" not in message


from src.shared.models import (
    EmbedderConfigData,
    LLMConfigData,
    McpToolData,
    RealtimeAgentChatData,
)

CARRIERS = [
    (LLMConfigData, "api_key_secret_id", "api_key"),
    (EmbedderConfigData, "api_key_secret_id", "api_key"),
    (McpToolData, "auth_secret_id", "auth"),
    (RealtimeAgentChatData, "rt_api_key_secret_id", "rt_api_key"),
    (RealtimeAgentChatData, "transcript_api_key_secret_id", "transcript_api_key"),
]


class TestCarrierFields:
    """The carrier must be readable in-process but invisible in every dump: it is
    what keeps Secret row ids out of Session.graph_schema and off the wire."""

    @pytest.mark.parametrize("model_cls,carrier,target", CARRIERS)
    def test_carrier_declared_and_paired_with_its_target(
        self, model_cls, carrier, target
    ):
        assert carrier in model_cls.model_fields, f"{model_cls.__name__}.{carrier}"
        assert target in model_cls.model_fields, f"{model_cls.__name__}.{target}"
        assert carrier == f"{target}_secret_id", "convention is <field>_secret_id"

    @pytest.mark.parametrize("model_cls,carrier,target", CARRIERS)
    def test_carrier_defaults_to_none(self, model_cls, carrier, target):
        assert model_cls.model_fields[carrier].default is None

    @pytest.mark.parametrize("model_cls,carrier,target", CARRIERS)
    def test_carrier_excluded_from_both_dump_paths(self, model_cls, carrier, target):
        assert (
            model_cls.model_fields[carrier].exclude is True
        ), f"{model_cls.__name__}.{carrier} must be Field(exclude=True)"

    def test_llm_config_dump_omits_carrier_and_keeps_target(self):
        cfg = LLMConfigData(model="gpt-4o", api_key_secret_id=42)

        assert cfg.api_key_secret_id == 42
        assert "api_key_secret_id" not in cfg.model_dump(mode="json")
        assert "api_key_secret_id" not in cfg.model_dump_json()
        assert cfg.model_dump(mode="json")["api_key"] is None

    def test_realtime_target_accepts_none(self):
        # Task 4 builds this payload with the slot empty; it must validate.
        chat = RealtimeAgentChatData.model_construct(rt_api_key=None)
        assert chat.rt_api_key is None
        assert RealtimeAgentChatData.model_fields["rt_api_key"].default is None


from pydantic import BaseModel

from src.shared.models import EmbedderData, LLMData


@pytest.mark.django_db
class TestResolvePayload:
    def test_fills_nested_slots_across_lists_and_leaves_input_clean(self, org):
        llm_secret = secret_service.create(
            text="sk-llm-nested", org=org, name="payload-llm"
        )
        embed_secret = secret_service.create(
            text="sk-embed-nested", org=org, name="payload-embed"
        )

        class Holder(BaseModel):
            llms: list[LLMData] = []
            embedder: EmbedderData | None = None

        payload = Holder(
            llms=[
                LLMData(
                    provider="openai",
                    config=LLMConfigData(
                        model="gpt-4o", api_key_secret_id=llm_secret.pk
                    ),
                )
            ],
            embedder=EmbedderData(
                provider="openai",
                config=EmbedderConfigData(
                    model="text-embedding-3-small",
                    api_key_secret_id=embed_secret.pk,
                ),
            ),
        )

        resolved = secret_resolver.resolve_payload(payload=payload)

        assert resolved.llms[0].config.api_key == "sk-llm-nested"
        assert resolved.embedder.config.api_key == "sk-embed-nested"

        # The input object is what gets persisted to graph_schema — it must not
        # have been touched.
        assert payload.llms[0].config.api_key is None
        assert payload.embedder.config.api_key is None

    def test_walks_into_dict_values(self, org):
        secret = secret_service.create(text="sk-in-dict", org=org, name="payload-dict")

        class Holder(BaseModel):
            by_name: dict[str, LLMConfigData] = {}

        resolved = secret_resolver.resolve_payload(
            payload=Holder(
                by_name={
                    "a": LLMConfigData(model="gpt-4o", api_key_secret_id=secret.pk)
                }
            )
        )
        assert resolved.by_name["a"].api_key == "sk-in-dict"

    def test_null_carrier_leaves_slot_none(self):
        resolved = secret_resolver.resolve_payload(
            payload=LLMConfigData(model="gpt-4o")
        )
        assert resolved.api_key is None

    def test_non_secret_fields_untouched(self, org):
        secret = secret_service.create(text="sk-keep", org=org, name="payload-keep")
        resolved = secret_resolver.resolve_payload(
            payload=LLMConfigData(
                model="gpt-4o",
                temperature=0.25,
                base_url="https://example.test",
                api_key_secret_id=secret.pk,
            )
        )
        assert resolved.model == "gpt-4o"
        assert resolved.temperature == 0.25
        assert resolved.base_url == "https://example.test"

    def test_unresolvable_carrier_raises_with_locating_context(self, org):
        secret = secret_service.create(text="sk-x", org=org, name="payload-doomed")
        secret_id = secret.pk
        secret.delete()

        with pytest.raises(SecretResolutionError) as exc:
            secret_resolver.resolve_payload(
                payload=LLMConfigData(model="gpt-4o", api_key_secret_id=secret_id)
            )

        assert "LLMConfigData.api_key" in str(exc.value)

    def test_dump_of_resolved_payload_still_omits_the_carrier(self, org):
        secret = secret_service.create(text="sk-dump", org=org, name="payload-dump")
        resolved = secret_resolver.resolve_payload(
            payload=LLMConfigData(model="gpt-4o", api_key_secret_id=secret.pk)
        )

        dumped = resolved.model_dump_json()
        assert "sk-dump" in dumped
        assert "api_key_secret_id" not in dumped
