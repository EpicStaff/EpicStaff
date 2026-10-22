"""One `check_<entity>_write(actor, instance, data)` per entity whose writes can need secrets:USE.

`instance` is the persisted row, or None on create. `data` is the serializer's
validated data, keyed by model attribute names; a key absent from it is unchanged,
so the persisted value stands in for it. Each check raises SecretUseDeniedError
when the write needs secrets:USE and `actor` lacks it.
"""

from django.db import models
from tables.models.embedding_models import EmbeddingConfig
from tables.models.llm_models import LLMConfig
from tables.services.secrets.secret_resolver import extract_secret_marker_names
from tables.services.secrets.secret_use_service import SecretActor, secret_use_service


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


def _check_api_key_and_header_markers(actor: SecretActor | None, instance, data: dict) -> None:
    current_secret_id = _persisted_value(instance, "api_key_secret_id")
    secret_use_service.check_references(
        actor,
        field_path=("api_key_secret_id",),
        current=current_secret_id,
        incoming=data.get("api_key_secret", current_secret_id),
    )
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
    if "api_key_secret" in data:
        has_api_key_secret = data["api_key_secret"] is not None
    else:
        has_api_key_secret = _persisted_value(instance, "api_key_secret_id") is not None
    headers = data.get("extra_headers", _persisted_value(instance, "extra_headers"))
    return has_api_key_secret or bool(extract_secret_marker_names(headers))


def _model_base_url(model_row) -> str | None:
    return model_row.base_url if model_row is not None else None


def _persisted_value(instance, attribute: str):
    return getattr(instance, attribute) if instance is not None else None
