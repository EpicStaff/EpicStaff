"""Write rules the LLM and embedding config serializers share: the model catalog checks a
config's `parameters` and `connection`, a config may name its model by provider and name,
and the flat fields the catalog replaced are refused by name."""

from collections.abc import Mapping

from django.db import transaction
from drf_spectacular.utils import extend_schema_field
from rbac.access.asserts import assert_org_permission
from rbac.authorship.policy import resolve_author
from rbac.models.enums import Permission, ResourceType
from rbac.scoping.fields import resolve_active_org_id
from rest_framework import serializers

from ai_models.domain.specs import ModelKind
from ai_models.services.catalog_model_resolver import (
    CatalogModelResolver,
    UnknownCatalogModelError,
)
from ai_models.services.config_validation import ConfigValidationService

REMOVED_CONFIG_FIELDS = (
    "temperature",
    "top_p",
    "stop",
    "max_tokens",
    "presence_penalty",
    "frequency_penalty",
    "logit_bias",
    "seed",
    "logprobs",
    "top_logprobs",
    "reasoning_effort",
    "base_url",
    "api_version",
    "deployment_id",
    "deployment",
    "task_type",
)
REMOVED_MODEL_FIELDS = ("base_url", "api_version", "deployment_id", "deployment")
_REMOVED_FIELD_MESSAGE = "Moved to parameters/connection."
# Validation runs only when a write changes one of these, so renaming a config whose
# stored values a catalog update made stale still saves, even when an edit form resends
# them unchanged. The provider and model name pair arrives here as `model`.
_CATALOG_CHECKED_FIELDS = ("model", "parameters", "connection")


def reject_removed_fields(data: object, field_names: tuple[str, ...]) -> None:
    """Refuse a request that still sends a field the model catalog replaced, naming each one."""
    if not isinstance(data, Mapping):
        return
    sent = [name for name in field_names if name in data]
    if sent:
        raise serializers.ValidationError({name: [_REMOVED_FIELD_MESSAGE] for name in sent})


@extend_schema_field({"type": "string", "nullable": True})
class _ModelIdentityField(serializers.CharField):
    """On write, names the config's model; on read, the stored model's provider or model name.

    Reads null when the config has no model (or its model has no provider). Null is
    accepted on write so a client can send a response back as it read it; the parent
    serializer resolves or checks written values in `validate`.
    """

    def __init__(self, **kwargs):
        super().__init__(required=False, allow_null=True, **kwargs)

    def get_attribute(self, config):
        return self.parent._model_identity(config.model)[self.field_name]


class CatalogConfigFieldsMixin(serializers.Serializer):
    """Check a config's `parameters` and `connection` against the model catalog on write.

    Validation runs on create, and on update when the write changes the model,
    `parameters` or `connection`; it then checks the whole resulting set. An update that
    keeps the provider may leave out a required connection field the stored config already
    lacked: that config shows "needs review" instead.

    A config names its model either by `model` (a row id) or by the pair
    `provider` + `model_name`, resolved by `CatalogModelResolver` in the active
    organization; a new custom row it returns is saved in the same transaction as the
    config. Reads return the pair as stored (the provider row's name and the model row's
    name) next to `model`, so a client needs no model list to show a config. A write may
    send that pair back with `model`: it is ignored when it names that same model, and
    refused when it names another. A create without `parameters` stores the model's
    defaults. `needs_review` and `review_reasons` say how far a stored config has drifted
    from the catalog.

    Concrete serializers set `model_kind` and `provider_field` (the
    model's provider foreign key), and must be built with the request in their context.
    """

    model_kind: ModelKind
    provider_field: str

    provider = _ModelIdentityField()
    model_name = _ModelIdentityField()
    needs_review = serializers.SerializerMethodField()
    review_reasons = serializers.SerializerMethodField()

    def to_internal_value(self, data):
        reject_removed_fields(data, REMOVED_CONFIG_FIELDS)
        return super().to_internal_value(data)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        sent_pair = {name: attrs.pop(name) for name in ("provider", "model_name") if name in attrs}
        if sent_pair and "model" in attrs:
            self._reject_pair_naming_another_model(attrs["model"], sent_pair)
        elif sent_pair:
            attrs["model"] = self._model_named(
                sent_pair.get("provider"), sent_pair.get("model_name")
            )
        if self.instance is None or self._changes_catalog_fields(attrs):
            self._validate_against_catalog(attrs)
        return attrs

    def create(self, validated_data):
        with transaction.atomic():
            self._save_new_custom_model(validated_data)
            return super().create(validated_data)

    def update(self, instance, validated_data):
        with transaction.atomic():
            self._save_new_custom_model(validated_data)
            return super().update(instance, validated_data)

    def get_needs_review(self, config) -> bool:
        return bool(self.get_review_reasons(config))

    def get_review_reasons(self, config) -> list[str]:
        # Both review fields read this; a list response renders every config with one
        # serializer, so the reasons are kept per config instead of computed twice.
        reasons_by_config = self.__dict__.setdefault("_review_reasons_by_config", {})
        if config.pk not in reasons_by_config:
            provider, model_name = self._catalog_names(config.model)
            reasons_by_config[config.pk] = ConfigValidationService().review_reasons(
                self.model_kind,
                provider,
                model_name,
                config.parameters,
                config.connection,
                custom_model=config.model is not None and config.model.is_custom,
            )
        return reasons_by_config[config.pk]

    def _changes_catalog_fields(self, attrs: dict) -> bool:
        # A model the pair resolves to a new custom row has no pk yet, so it never
        # equals the stored one.
        return any(
            name in attrs and attrs[name] != getattr(self.instance, name)
            for name in _CATALOG_CHECKED_FIELDS
        )

    def _validate_against_catalog(self, attrs: dict) -> None:
        model = attrs.get("model", self.instance.model if self.instance else None)
        provider, model_name = self._catalog_names(model)
        service = ConfigValidationService()
        if self.instance is None and "parameters" not in attrs:
            attrs["parameters"] = service.defaults(self.model_kind, provider, model_name)
        keeps_provider = (
            self.instance is not None and self._catalog_names(self.instance.model)[0] == provider
        )
        service.validate(
            self.model_kind,
            provider,
            model_name,
            attrs.get("parameters", self.instance.parameters if self.instance else {}),
            attrs.get("connection", self.instance.connection if self.instance else {}),
            self._org_id(),
            stored_connection=self.instance.connection if keeps_provider else None,
        )

    def _reject_pair_naming_another_model(self, model, sent_pair: dict) -> None:
        identity = self._model_identity(model)
        if any(value != identity[name] for name, value in sent_pair.items()):
            raise serializers.ValidationError(
                {
                    "model": [
                        "provider and model_name must name the same model as model; send model alone to change it."
                    ]
                }
            )

    def _model_named(self, provider: str | None, model_name: str | None):
        missing = [
            name
            for name, value in (("provider", provider), ("model_name", model_name))
            if not value
        ]
        if missing:
            raise serializers.ValidationError(
                {name: ["This field is required."] for name in missing}
            )

        request = self.context["request"]
        org_id = self._org_id()
        try:
            model = CatalogModelResolver().resolve(
                self.model_kind,
                provider,
                model_name,
                org_id=org_id,
                author=resolve_author(request.user),
            )
        except UnknownCatalogModelError as error:
            raise serializers.ValidationError({error.field: [str(error)]}) from error
        if model.pk is None and self.instance is not None:
            # Updating a config needs llm_configs update; the row this save adds needs create.
            assert_org_permission(request.user, org_id, ResourceType.LLM_CONFIGS, Permission.CREATE)
        return model

    def _save_new_custom_model(self, validated_data: dict) -> None:
        model = validated_data.get("model")
        if model is not None:
            validated_data["model"] = CatalogModelResolver().save_if_new(model)

    def _model_identity(self, model) -> dict[str, str | None]:
        """Return `model` as a response names it: provider and model name, null when absent."""
        provider, model_name = self._catalog_names(model)
        return {"provider": provider or None, "model_name": model_name or None}

    def _catalog_names(self, model) -> tuple[str, str]:
        """Return the provider and model name the catalog knows `model` by; empty without one."""
        if model is None:
            return "", ""
        provider = getattr(model, self.provider_field)
        return (provider.name if provider else ""), model.name

    def _org_id(self) -> int:
        if self.instance is not None:
            return self.instance.org_id
        return resolve_active_org_id(self.context["request"])
