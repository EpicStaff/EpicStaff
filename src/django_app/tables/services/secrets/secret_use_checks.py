"""One `check_<entity>_write(actor, instance, data)` per entity whose writes can need secrets:USE.

`instance` is the persisted row, or None on create. `data` is the serializer's
validated data, keyed by model attribute names; a key absent from it is unchanged,
so the persisted value stands in for it. Each check raises SecretUseDeniedError
when the write needs secrets:USE and `actor` lacks it, or when `actor` is a
pinned-org principal and the row would reference a secret it may not reference.
"""

from collections.abc import Callable

from ai_models.repository import CatalogRepository
from tables.models.base_models import without_internal_rows
from tables.models.secret_models import Secret
from tables.services.secrets.exceptions import ModelEndpointNotSettableError
from tables.services.secrets.linked_ids import linked_ids
from tables.services.secrets.secret_resolver import extract_secret_marker_names
from tables.services.secrets.secret_use_service import (
    SecretActor,
    principal_of,
    secret_use_service,
)

SecretUseCheck = Callable[[SecretActor | None, object, dict], None]


def check_llm_config_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate an LLMConfig write: its secrets and the connection fields that decide where they go.

    See `_check_model_config_write`.
    """
    _check_model_config_write(actor, instance, data, provider_field="llm_provider")


def check_embedding_config_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate an EmbeddingConfig write: its secrets and the connection fields that decide where they go.

    See `_check_model_config_write`.
    """
    _check_model_config_write(actor, instance, data, provider_field="embedding_provider")


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


def check_system_one_config_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate a change of a SystemOneConfig's API-key secret.

    The config has no destination field: the TypeSafe and OpenAI endpoints are constants.
    Choosing an LLM config is not a secret use, as for agents.
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
    """Gate a write of the PythonCode a parent nests at `attribute`: its declared secrets and its code.

    Changing the declared secrets needs secrets:USE (reported under `attribute` +
    `secret_ids`). So does changing the code, entrypoint, venv or global kwargs of code
    that declares a secret after the write (reported under that field): the secrets are
    handed to the code at run time. Values are compared, so the bulk save's resend of
    unchanged code is free. Binned secrets count as declared. A pinned-org principal
    is also checked against the secrets it may reference.

    Args:
        parent: The persisted row nesting the PythonCode, or None when the write creates it.
        parent_data: The parent's validated data. An absent or None `attribute` leaves
            the PythonCode alone or detaches it; data without `secrets` keeps the declaration.
        attribute: The parent's attribute holding the PythonCode, e.g. `"python_code"`.
    """
    _check_python_code_write(actor, parent, parent_data, attribute=attribute)


def _check_python_code_write(
    actor: SecretActor | None, parent, parent_data: dict, *, attribute: str
) -> frozenset | None:
    """Run `check_python_code_write`; return the secrets declared after the write if it had to read them, else None.

    The return value lets a caller that gates more fields of the same parent
    (`check_python_code_tool_write`) reuse the read instead of repeating it.
    """
    python_code_data = parent_data.get(attribute)
    if python_code_data is None:
        return None
    persisted_python_code = _persisted_value(parent, attribute)
    # Read at most once: a related manager is read through a query unless the caller
    # prefetched it (the graph bulk save does).
    current_secret_ids = None
    if "secrets" in python_code_data or principal_of(actor) is not None:
        current_secret_ids = _declared_secret_ids(persisted_python_code)
        secret_use_service.check_references(
            actor,
            field_path=(attribute, "secret_ids"),
            current=current_secret_ids,
            incoming=python_code_data.get("secrets", current_secret_ids),
        )
    # New code is gated by the reference check above: declaring any secret changes the set.
    if persisted_python_code is None:
        return None
    changed_field = _changed_code_field(persisted_python_code, python_code_data)
    if changed_field is None:
        return None
    field_name, current_value, incoming_value = changed_field
    secret_ids_after_write = _secret_ids_after_write(
        persisted_python_code, python_code_data, current_secret_ids
    )
    secret_use_service.check_code(
        actor,
        field_path=(attribute, field_name),
        declares_secret=bool(secret_ids_after_write),
        current=current_value,
        incoming=incoming_value,
    )
    return secret_ids_after_write


def check_python_node_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate a PythonNode's code and declared secrets (`check_python_code_write`)."""
    check_python_code_write(actor, instance, data, attribute="python_code")


def check_webhook_trigger_node_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate a WebhookTriggerNode's code and declared secrets (`check_python_code_write`).

    The node's `webhook_trigger` is not gated: attaching a trigger moves none of its
    secrets, whose own changes are checked where the trigger is written.
    """
    check_python_code_write(actor, instance, data, attribute="python_code")


def check_python_code_tool_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate a PythonCodeTool's code and `variables` while the code declares a secret.

    The code is gated by `check_python_code_write`. The variables' defaults are merged
    into the code's globals at run time, so changing them is gated the same way
    (reported under `variables`).
    """
    secret_ids = _check_python_code_write(actor, instance, data, attribute="python_code")
    if instance is None or "variables" not in data or data["variables"] == instance.variables:
        return
    if secret_ids is None:
        secret_ids = _secret_ids_after_write(instance.python_code, data.get("python_code") or {})
    secret_use_service.check_code(
        actor,
        field_path=("variables",),
        declares_secret=bool(secret_ids),
        current=instance.variables,
        incoming=data["variables"],
        secret_ids=secret_ids,
    )


def check_python_code_tool_config_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate a PythonCodeToolConfig's `configuration` while its tool's code declares a secret.

    The configuration is merged over the tool code's globals at run time, so it is gated
    like the code (reported under `configuration`). Every new config counts, since unset
    variables are stored as null and a null overrides the default; moving a config to
    another tool counts too. Deleting a config needs nothing.
    """
    tool = data.get("tool", _persisted_value(instance, "tool"))
    configuration = data.get("configuration", _persisted_value(instance, "configuration"))
    current = (instance.tool_id, instance.configuration) if instance is not None else None
    incoming = (tool.pk, configuration)
    if current == incoming:
        return
    secret_ids = _declared_secret_ids(tool.python_code)
    secret_use_service.check_code(
        actor,
        field_path=("configuration",),
        declares_secret=bool(secret_ids),
        current=current,
        incoming=incoming,
        secret_ids=secret_ids,
    )


def check_venv_write(
    actor: SecretActor | None, binding, data: dict, *, read_current_libs: Callable[[], list]
) -> None:
    """Gate a change of a venv's `libs` while any code that runs in it declares a secret.

    A library runs inside the code's process, which holds its secrets, so installing one
    is gated like changing the code (reported under `libs`). Binned code counts. The
    current libraries live in the sandbox, so `read_current_libs` is called only for a
    venv such code runs in. Libraries are compared by name, specification and version,
    not by description or order.
    """
    if "libs" not in data:
        return
    secret_ids = _secret_ids_declared_in_venv(binding)
    if not secret_ids:
        return
    secret_use_service.check_code(
        actor,
        field_path=("libs",),
        declares_secret=True,
        current=_installed(read_current_libs()),
        incoming=_installed(data["libs"]),
        secret_ids=secret_ids,
    )


def check_cdt_node_write(actor: SecretActor | None, instance, data: dict) -> None:
    """Gate a ClassificationDecisionTableNode's pre and post code: their declared secrets, and their code while it declares any.

    See `check_python_code_write`. Detaching a PythonCode (sending it as null) drops its
    declaration with it, which needs no secrets:USE.
    """
    check_python_code_write(actor, instance, data, attribute="pre_python_code")
    check_python_code_write(actor, instance, data, attribute="post_python_code")


def check_quickstart(actor: SecretActor | None, data: dict) -> None:
    """Gate a quickstart that reuses an existing secret as the bundle's API key.

    A quickstart only creates rows, so any `api_key_secret_id` is a new reference.
    A raw `api_key` needs no secrets:USE: it becomes a new secret the caller owns.
    The request names no destination: quickstart picks each config's model itself,
    by the provider's fixed model name, and leaves each config's `connection` empty, so
    the key goes to the provider's own endpoint and there is nothing to gate here.
    """
    secret_use_service.check_references(
        actor,
        field_path=("api_key_secret_id",),
        current=None,
        incoming=data.get("api_key_secret_id"),
    )


#: The config fields whose string values may hold `epicstaff_secret(<name>)` markers.
_MODEL_CONFIG_MARKER_FIELDS = ("extra_headers", "connection")


def _check_model_config_write(
    actor: SecretActor | None, instance, data: dict, *, provider_field: str
) -> None:
    """Gate a write of an LLM or embedding config.

    A config carries a secret when it references its API-key secret or holds a marker
    in `extra_headers` or `connection`. Choosing the API-key secret, or adding a marker
    to either field, needs secrets:USE; removing one is free. The connection fields
    that decide where the requests go (`_endpoint_field_names`) are the destination of
    those secrets: changing one on a config that carries a secret after the write
    needs secrets:USE too, reported under `connection` and the field. Model rows hold
    no endpoint, so switching the model only picks between the vendors' own hosts and
    is free. A pinned-org principal never sets an endpoint field at all.
    """
    current_connection = _persisted_value(instance, "connection") or {}
    incoming_connection = data.get("connection", current_connection)
    endpoint_names = _endpoint_field_names(
        instance, data, current_connection, incoming_connection, provider_field=provider_field
    )
    _refuse_endpoint_change_by_principal(
        actor, endpoint_names, current_connection, incoming_connection
    )

    _check_secret_reference(actor, instance, data, attribute="api_key_secret")
    carries_secret = _references_secret_after_write(instance, data, "api_key_secret")
    for field_name in _MODEL_CONFIG_MARKER_FIELDS:
        current_value = _persisted_value(instance, field_name)
        incoming_value = data.get(field_name, current_value)
        secret_use_service.check_markers(
            actor,
            field_path=(field_name,),
            current_headers=current_value,
            incoming_headers=incoming_value,
        )
        carries_secret = carries_secret or bool(extract_secret_marker_names(incoming_value))

    # Checked one field at a time so the denial names the field the caller changed.
    for name in endpoint_names:
        secret_use_service.check_destination(
            actor,
            field_path=("connection", name),
            carries_secret=carries_secret,
            current=current_connection.get(name),
            incoming=incoming_connection.get(name),
        )


def _endpoint_field_names(
    instance, data: dict, *connections: dict, provider_field: str
) -> list[str]:
    """The keys of `connections` that decide where the config's requests go.

    A key counts when the catalog marks it an endpoint for the config's provider
    before or after the write, or when neither provider declares it at all (a provider
    the catalog no longer knows, or a key a stale config kept): an unknown field is
    treated as an endpoint, since a false positive only asks for a permission.
    """
    repository = CatalogRepository.default()
    declared, endpoints = set(), set()
    for model in (_persisted_value(instance, "model"), data.get("model")):
        provider = getattr(model, provider_field, None) if model is not None else None
        provider_spec = repository.provider(provider.name) if provider is not None else None
        for field in provider_spec.connection_fields if provider_spec else ():
            declared.add(field.name)
            if field.endpoint:
                endpoints.add(field.name)
    keys = set().union(*connections)
    return sorted(name for name in keys if name in endpoints or name not in declared)


def _refuse_endpoint_change_by_principal(
    actor: SecretActor | None, endpoint_names: list[str], current: dict, incoming: dict
) -> None:
    """Keep a pinned-org principal (a plugin's service account) from setting where a config sends requests.

    People in the organization may add their own keys to a config a plugin wrote, so a
    plugin never sets, changes or clears an endpoint field, on create or on update.
    Only a value that differs from the stored one counts; empty and missing are the same.
    """
    if principal_of(actor) is None:
        return
    changed = tuple(
        f"connection.{name}"
        for name in endpoint_names
        if (incoming.get(name) or None) != (current.get(name) or None)
    )
    if changed:
        raise ModelEndpointNotSettableError(fields=changed)


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


#: What a PythonCode runs, as (validated-data key, model attribute and API field).
_CODE_FIELDS = (
    ("code", "code"),
    ("entrypoint", "entrypoint"),
    ("venv", "venv_id"),
    ("global_kwargs", "global_kwargs"),
)


def _changed_code_field(python_code, python_code_data: dict):
    """The first of `_CODE_FIELDS` the write changes, as (field, current, incoming), or None."""
    for data_key, field_name in _CODE_FIELDS:
        current = getattr(python_code, field_name)
        incoming = python_code_data.get(data_key, current)
        # `venv` arrives as a row; compare its pk with the persisted `venv_id`.
        incoming = getattr(incoming, "pk", incoming)
        # The serializer trims surrounding whitespace off `code` and `entrypoint`, so a
        # resend of stored text that still carries it (written by another path) is no change.
        if isinstance(current, str) and isinstance(incoming, str):
            current, incoming = current.strip(), incoming.strip()
        if incoming != current:
            return field_name, current, incoming
    return None


def _secret_ids_after_write(
    persisted_python_code, python_code_data: dict, current_secret_ids: frozenset | None = None
) -> frozenset:
    """The secrets a PythonCode declares once `python_code_data` is written.

    Args:
        current_secret_ids: The persisted declaration, when the caller has read it already.
    """
    if "secrets" in python_code_data:
        return linked_ids(python_code_data["secrets"])
    if current_secret_ids is not None:
        return current_secret_ids
    return _declared_secret_ids(persisted_python_code)


def _secret_ids_declared_in_venv(binding) -> frozenset:
    """The secrets any PythonCode running in `binding` declares, binned ones included. One query."""
    rows = without_internal_rows(Secret.all_objects.filter(python_codes__venv=binding))
    return frozenset(rows.values_list("pk", flat=True))


def _installed(libs):
    """What a list of libraries installs, comparable whatever their order."""
    if not isinstance(libs, list) or not all(isinstance(lib, dict) for lib in libs):
        # A fresh object equals nothing, so an unreadable value always counts as a change.
        return object()
    return sorted(
        (str(lib.get("name")), lib.get("specification") or "", lib.get("version") or "")
        for lib in libs
    )


def _declared_secret_ids(python_code) -> frozenset:
    return linked_ids(python_code.secrets) if python_code is not None else frozenset()


def _persisted_value(instance, attribute: str):
    return getattr(instance, attribute) if instance is not None else None


def _one_to_one_row(instance, related_name: str):
    # A missing reverse one-to-one row raises RelatedObjectDoesNotExist, an
    # AttributeError, which the getattr default turns into None, as it does for a
    # None instance on create.
    return getattr(instance, related_name, None)
