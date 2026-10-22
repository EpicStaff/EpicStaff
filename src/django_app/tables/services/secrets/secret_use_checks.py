"""One `check_<entity>_write(actor, instance, data)` per entity whose writes can need secrets:USE.

`instance` is the persisted row, or None on create. `data` is the serializer's
validated data, keyed by model attribute names; a key absent from it is unchanged,
so the persisted value stands in for it. Each check raises SecretUseDeniedError
when the write needs secrets:USE and `actor` lacks it.
"""

from collections.abc import Callable

from django.db import models
from tables.models.embedding_models import EmbeddingConfig
from tables.models.llm_models import LLMConfig
from tables.services.secrets.secret_resolver import extract_secret_marker_names
from tables.services.secrets.secret_use_service import SecretActor, secret_use_service

SecretUseCheck = Callable[[SecretActor | None, object, dict], None]


def check_llm_config_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate an LLMConfig write: its API-key secret, its header markers, and its destination.

    The destination is the config's own `base_url` together with its model's
    `base_url`. The config's own `base_url` is not read at run time today; it is
    gated anyway so wiring it up later does not open a way around this check.
    """
    _check_api_key_and_header_markers(actor, instance, data)
    carries_secret = _config_carries_secret_after_write(instance, data)
    # Checked one part at a time so the denial names the field the caller changed;
    # a change to either part changes the destination.
    current_base_url = _persisted_value(instance, "base_url")
    secret_use_service.check_destination(
        actor,
        field_path=("base_url",),
        carries_secret=carries_secret,
        current=current_base_url,
        incoming=data.get("base_url", current_base_url),
    )
    _check_model_switch(actor, instance, data, carries_secret=carries_secret)


def check_embedding_config_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate an EmbeddingConfig write: its API-key secret, its header markers, and its model's `base_url`."""
    _check_api_key_and_header_markers(actor, instance, data)
    _check_model_switch(
        actor, instance, data, carries_secret=_config_carries_secret_after_write(instance, data)
    )


def check_llm_model_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate a change of an LLMModel's `base_url` while a config of it carries a secret."""
    _check_model_base_url(actor, instance, data, config_class=LLMConfig)


def check_embedding_model_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate a change of an EmbeddingModel's `base_url` while a config of it carries a secret."""
    _check_model_base_url(actor, instance, data, config_class=EmbeddingConfig)


def check_realtime_config_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate a change of a RealtimeConfig's API-key secret."""
    _check_secret_reference(actor, instance, data, attribute="api_key_secret")


def check_realtime_transcription_config_write(
    actor: SecretActor | None, instance, data: dict
) -> None:
    """Gate a change of a RealtimeTranscriptionConfig's API-key secret."""
    _check_secret_reference(actor, instance, data, attribute="api_key_secret")


def check_openai_realtime_config_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate an OpenAIRealtimeConfig write: its two API-key secrets and its `base_url`.

    The realtime service sends the realtime key and the transcription key to the
    config's `base_url` alike, so either one makes the `base_url` a destination
    of a secret.
    """
    _check_secret_reference(actor, instance, data, attribute="api_key_secret")
    _check_secret_reference(actor, instance, data, attribute="transcription_api_key_secret")
    current_base_url = _persisted_value(instance, "base_url")
    secret_use_service.check_destination(
        actor,
        field_path=("base_url",),
        carries_secret=_references_secret_after_write(instance, data, "api_key_secret")
        or _references_secret_after_write(instance, data, "transcription_api_key_secret"),
        current=current_base_url,
        incoming=data.get("base_url", current_base_url),
    )


def check_elevenlabs_realtime_config_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate a change of an ElevenLabsRealtimeConfig's API-key secret.

    The config has no destination field: the realtime service always calls ElevenLabs.
    """
    _check_secret_reference(actor, instance, data, attribute="api_key_secret")


def check_gemini_realtime_config_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate a change of a GeminiRealtimeConfig's API-key secret.

    The config has no destination field: the realtime service always calls Gemini.
    """
    _check_secret_reference(actor, instance, data, attribute="api_key_secret")


def check_twilio_channel_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate a change of a TwilioChannel's auth-token secret.

    The channel has no destination field: the stored token is only used to verify
    the signature of Twilio's inbound requests, never sent anywhere.
    """
    _check_secret_reference(actor, instance, data, attribute="auth_token_secret")


def check_mcp_tool_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate an McpTool write: its auth secret and its `transport`.

    The agent service opens the MCP client on `transport` and sends the auth
    secret with every request to it, so `transport` is the secret's destination.
    """
    _check_secret_reference(actor, instance, data, attribute="auth_secret")
    current_transport = _persisted_value(instance, "transport")
    secret_use_service.check_destination(
        actor,
        field_path=("transport",),
        carries_secret=_references_secret_after_write(instance, data, "auth_secret"),
        current=current_transport,
        incoming=data.get("transport", current_transport),
    )


def check_webhook_trigger_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate a WebhookTrigger write: its auth secret and its nested ngrok auth token.

    Both live on one-to-one rows of the trigger (`auth`, `ngrok`), which a trigger
    may not have yet; a missing row links to no secret. An omitted `ngrok_config`,
    or one sent as null, leaves the token as it is.
    """
    current_auth = _one_to_one_row(instance, "auth")
    current_auth_secret_id = current_auth.secret_id if current_auth is not None else None
    secret_use_service.check_references(
        actor,
        field_path=("auth_secret_id",),
        current=current_auth_secret_id,
        incoming=data.get("auth_secret_id", current_auth_secret_id),
    )

    ngrok_data = data.get("ngrok_config")
    if not ngrok_data:
        return
    current_ngrok = _one_to_one_row(instance, "ngrok")
    current_token_secret_id = (
        current_ngrok.auth_token_secret_id if current_ngrok is not None else None
    )
    secret_use_service.check_references(
        actor,
        field_path=("ngrok_config", "auth_token_secret_id"),
        current=current_token_secret_id,
        incoming=ngrok_data.get("auth_token_secret", current_token_secret_id),
    )


def check_telegram_trigger_node_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate a change of a TelegramTriggerNode's bot API-key secret.

    The node has no destination field: the bot key is only ever sent to the
    Telegram Bot API at its fixed host.
    """
    _check_secret_reference(actor, instance, data, attribute="telegram_bot_api_key_secret")


def _check_api_key_and_header_markers(actor: SecretActor | None, instance, data: dict) -> None:
    _check_secret_reference(actor, instance, data, attribute="api_key_secret")
    current_headers = _persisted_value(instance, "extra_headers")
    secret_use_service.check_markers(
        actor,
        field_path=("extra_headers",),
        current_headers=current_headers,
        incoming_headers=data.get("extra_headers", current_headers),
    )


def _check_model_switch(
    actor: SecretActor | None, instance, data: dict, *, carries_secret: bool
) -> None:
    """A config sends its requests to its model's `base_url`, so switching models can move them."""
    current_model = _persisted_value(instance, "model")
    secret_use_service.check_destination(
        actor,
        field_path=("model",),
        carries_secret=carries_secret,
        current=_model_base_url(current_model),
        incoming=_model_base_url(data.get("model", current_model)),
    )


def _check_model_base_url(
    actor: SecretActor | None, instance, data: dict, *, config_class: type[models.Model]
) -> None:
    # No config can use a model that is only being created.
    if instance is None:
        return
    current_base_url = instance.base_url
    incoming_base_url = data.get("base_url", current_base_url)
    # Skips the config query on the usual edit; the service still treats None and ""
    # as the same destination when they differ here.
    if incoming_base_url == current_base_url:
        return
    secret_use_service.check_destination(
        actor,
        field_path=("base_url",),
        carries_secret=_any_config_of_model_carries_secret(config_class, instance),
        current=current_base_url,
        incoming=incoming_base_url,
    )


def _any_config_of_model_carries_secret(config_class: type[models.Model], model_row) -> bool:
    """Whether any config of `model_row`, in any organization, carries an API-key secret or a header marker.

    Not narrowed to the active org: a custom model belongs to one org only, and
    counting more configs can only deny more.
    """
    rows = config_class.objects.filter(model=model_row).values_list(
        "api_key_secret_id", "extra_headers"
    )
    return any(
        secret_id is not None or extract_secret_marker_names(headers)
        for secret_id, headers in rows
    )


def _config_carries_secret_after_write(instance, data: dict) -> bool:
    headers = data.get("extra_headers", _persisted_value(instance, "extra_headers"))
    return _references_secret_after_write(instance, data, "api_key_secret") or bool(
        extract_secret_marker_names(headers)
    )


def _check_secret_reference(
    actor: SecretActor | None, instance, data: dict, *, attribute: str
) -> None:
    """Gate a change of the secret FK `attribute`, reported under its API field `<attribute>_id`."""
    field_name = f"{attribute}_id"
    current_secret_id = _persisted_value(instance, field_name)
    secret_use_service.check_references(
        actor,
        field_path=(field_name,),
        current=current_secret_id,
        incoming=data.get(attribute, current_secret_id),
    )


def _references_secret_after_write(instance, data: dict, attribute: str) -> bool:
    if attribute in data:
        return data[attribute] is not None
    return _persisted_value(instance, f"{attribute}_id") is not None


def _model_base_url(model_row) -> str | None:
    return model_row.base_url if model_row is not None else None


def _persisted_value(instance, attribute: str):
    return getattr(instance, attribute) if instance is not None else None


def _one_to_one_row(instance, related_name: str):
    # A missing reverse one-to-one row raises RelatedObjectDoesNotExist, an
    # AttributeError, which the getattr default turns into None, as it does for a
    # None instance on create.
    return getattr(instance, related_name, None)
