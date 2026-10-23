"""One `check_<entity>_write(actor, instance, data)` per entity whose writes can need secrets:USE.

`instance` is the persisted row, or None on create. `data` is the serializer's
validated data, keyed by model attribute names; a key absent from it is unchanged,
so the persisted value stands in for it. Each check raises SecretUseDeniedError
when the write needs secrets:USE and `actor` lacks it.

The LLM and embedding config and model checks lock the model row they read
(`select_for_update`), so they must run inside the transaction that saves the write.
"""

from collections.abc import Callable

from django.db import models
from tables.models.embedding_models import EmbeddingConfig, EmbeddingModel
from tables.models.llm_models import LLMConfig, LLMModel
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
    _check_model_switch(actor, instance, data, carries_secret=carries_secret, model_class=LLMModel)


def check_embedding_config_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate an EmbeddingConfig write: its API-key secret, its header markers, and its model's `base_url`."""
    _check_api_key_and_header_markers(actor, instance, data)
    _check_model_switch(
        actor,
        instance,
        data,
        carries_secret=_config_carries_secret_after_write(instance, data),
        model_class=EmbeddingModel,
    )


def check_llm_model_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate a change of an LLMModel's `base_url` while a config of it carries a secret."""
    _check_model_base_url(actor, instance, data, model_class=LLMModel, config_class=LLMConfig)


def check_embedding_model_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate a change of an EmbeddingModel's `base_url` while a config of it carries a secret."""
    _check_model_base_url(
        actor, instance, data, model_class=EmbeddingModel, config_class=EmbeddingConfig
    )


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


def check_python_code_write(
    actor: SecretActor | None, parent, parent_data: dict, *, attribute: str
) -> None:
    """Gate a change of the secrets declared by the PythonCode a parent nests at `attribute`.

    Reported under `attribute` + `secret_ids`. Only the declaration needs
    secrets:USE. Editing the `code` or `venv_id` of a PythonCode that already
    declares secrets is free, even though the new code reads those secrets at run
    time: the declaration is what grants that access.

    Args:
        parent: The persisted row nesting the PythonCode (a node or a tool), or None
            when the write creates it.
        parent_data: The parent's validated data, keyed by model attribute names.
            An absent or None `attribute` leaves the PythonCode alone or detaches it;
            PythonCode data without a `secrets` key leaves the declaration as it is.
        attribute: The parent's attribute holding the PythonCode, e.g. `"python_code"`.
    """
    python_code_data = parent_data.get(attribute)
    # Checked before the persisted PythonCode is read: loading it costs a query per
    # parent, which a write that leaves the declaration alone does not need.
    if python_code_data is None or "secrets" not in python_code_data:
        return
    persisted_python_code = _persisted_value(parent, attribute)
    secret_use_service.check_references(
        actor,
        field_path=(attribute, "secret_ids"),
        current=persisted_python_code.secrets if persisted_python_code is not None else None,
        incoming=python_code_data["secrets"],
    )


def check_python_node_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate a change of the secrets a PythonNode's code declares."""
    check_python_code_write(actor, instance, data, attribute="python_code")


def check_webhook_trigger_node_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate a change of the secrets a WebhookTriggerNode's code declares.

    The node's `webhook_trigger` is not gated: attaching a trigger moves none of its
    secrets, whose own changes are checked where the trigger is written.
    """
    check_python_code_write(actor, instance, data, attribute="python_code")


def check_python_code_tool_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate a change of the secrets a PythonCodeTool's code declares."""
    check_python_code_write(actor, instance, data, attribute="python_code")


def check_cdt_node_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate a change of the secrets a ClassificationDecisionTableNode's pre and post code declare.

    Detaching a PythonCode (sending it as null) drops its declaration with it, which
    needs no secrets:USE.
    """
    check_python_code_write(actor, instance, data, attribute="pre_python_code")
    check_python_code_write(actor, instance, data, attribute="post_python_code")


def check_quickstart(actor: SecretActor | None, data: dict) -> None:
    """Gate a quickstart that reuses an existing secret as the bundle's API key.

    A quickstart only creates rows, so any `api_key_secret_id` is a new reference.
    A raw `api_key` needs no secrets:USE: it becomes a new secret the caller owns.
    The request names no destination: quickstart picks each config's model itself,
    by the provider's fixed model name, and refuses an org model with its own
    `base_url` (`QuickstartService._get_or_create_model`), so there is nothing to gate here.
    """
    secret_use_service.check_references(
        actor,
        field_path=("api_key_secret_id",),
        current=None,
        incoming=data.get("api_key_secret_id"),
    )


def check_config_import(
    actor: SecretActor | None, data: dict, *, marker_fields: tuple[str, ...]
) -> None:
    """Gate an imported config whose header fields carry secret markers.

    Import always creates the config, so every marker in it is new; a config the
    import reuses (`find_existing`) is never written and never reaches this check.

    Args:
        marker_fields: The header dict fields of this config type whose
            `epicstaff_secret(<name>)` markers reference secrets by name.
    """
    for field_name in marker_fields:
        secret_use_service.check_markers(
            actor,
            field_path=(field_name,),
            current_headers=None,
            incoming_headers=data.get(field_name),
        )


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
    actor: SecretActor | None,
    instance,
    data: dict,
    *,
    carries_secret: bool,
    model_class: type[models.Model],
) -> None:
    """A config sends its requests to its model's `base_url`, so switching models can move them.

    Both models' `base_url` are read from their rows locked FOR UPDATE, not from the
    validated objects: a concurrent edit of either model's `base_url` locks the same
    row (`_check_model_base_url`), so whichever write runs second sees what the first
    committed instead of both passing on stale reads.
    """
    # Before either model is read: a config without a secret may switch freely, and
    # locking a model costs a query.
    if not carries_secret or "model" not in data:
        return
    current_model_id = _persisted_value(instance, "model_id")
    incoming_model = data["model"]
    incoming_model_id = incoming_model.pk if incoming_model is not None else None
    if incoming_model_id == current_model_id:
        return
    base_url_by_model_id = _lock_models_and_read_base_urls(
        model_class, (current_model_id, incoming_model_id)
    )
    secret_use_service.check_destination(
        actor,
        field_path=("model",),
        carries_secret=carries_secret,
        current=base_url_by_model_id.get(current_model_id),
        incoming=base_url_by_model_id.get(incoming_model_id),
    )


def _check_model_base_url(
    actor: SecretActor | None,
    instance,
    data: dict,
    *,
    model_class: type[models.Model],
    config_class: type[models.Model],
) -> None:
    # No config can use a model that is only being created.
    if instance is None:
        return
    incoming_base_url = data.get("base_url", instance.base_url)
    # Skips the lock and the config query on the usual edit; the service still treats
    # None and "" as the same destination when they differ here.
    if incoming_base_url == instance.base_url:
        return
    # Locked before the configs are counted: a config switching to this model in a
    # concurrent request locks this row too, so it has either committed (and is
    # counted) or waits and then reads the new `base_url`. Not covered: a config that
    # already uses this model gaining a secret concurrently, as that write locks no model.
    current_base_url = (
        model_class.objects.select_for_update()
        .values_list("base_url", flat=True)
        .get(pk=instance.pk)
    )
    if incoming_base_url == current_base_url:
        return
    secret_use_service.check_destination(
        actor,
        field_path=("base_url",),
        carries_secret=_any_config_of_model_carries_secret(config_class, instance),
        current=current_base_url,
        incoming=incoming_base_url,
    )


def _lock_models_and_read_base_urls(
    model_class: type[models.Model], model_ids: tuple[int | None, ...]
) -> dict[int, str | None]:
    # Locked in ascending pk order, so two configs switching between the same two
    # models in opposite directions take the locks in the same order and cannot
    # deadlock. A model deleted meanwhile is missing here and reads as no `base_url`:
    # a save that still points the config at it fails on the foreign key.
    return dict(
        model_class.objects.select_for_update()
        .filter(pk__in=[model_id for model_id in model_ids if model_id is not None])
        .order_by("pk")
        .values_list("pk", "base_url")
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
        secret_id is not None or extract_secret_marker_names(headers) for secret_id, headers in rows
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


def _persisted_value(instance, attribute: str):
    return getattr(instance, attribute) if instance is not None else None


def _one_to_one_row(instance, related_name: str):
    # A missing reverse one-to-one row raises RelatedObjectDoesNotExist, an
    # AttributeError, which the getattr default turns into None, as it does for a
    # None instance on create.
    return getattr(instance, related_name, None)
