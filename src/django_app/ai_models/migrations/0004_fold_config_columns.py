"""Fold the configs' setting and endpoint columns into `parameters` and `connection`.

Forward, for every LLM and embedding config:

- `parameters` takes every non-null setting column (`task_type` for an embedding config)
  that the config's model supports according to the committed `ai_models/data/catalog.json`.
  Values are kept as they are, out of range or not: such a config shows "needs review"
  later. Which settings a model supports is decided as follows. The provider is looked up by
  name or alias, the model by name as LiteLLM would look it up (`<provider>/<model>`). A
  model the catalog does not know gets its provider's common list for that kind; a provider
  the catalog does not know, a model row without a provider and a config without a model
  keep every setting. A catalog file that is missing or not in the expected shape also keeps
  every setting, after one warning: the catalog can never make this migration drop data.
- `connection` takes `base_url` and `api_version` from the config's model row, which is
  where every run read them from, or from the config when the row has none, and
  `deployment_id` from `LLMModel.deployment_id` or `EmbeddingModel.deployment`. A model
  row's value is copied only into configs of the model row's own organization; a config on a
  built-in row or another organization's row that has an endpoint gets a warning naming the
  config and the dropped fields, never their values.
- `api_key_secret`, `extra_headers`, `timeout`, the token prices and `context_window` are
  not touched.

Backward (lossy): the `parameters` values go back to their columns and the endpoint values
in `connection` back to `LLMConfig.base_url` and `api_version`. A setting the forward fold
dropped cannot be restored; its column stays empty. An endpoint that lived on a model row is
restored on that row only when the row belongs to an organization and every config of that
organization using it holds the same value; otherwise the row's endpoint stays empty.

The catalog is read with `json` by the reader frozen below, never through the `ai_models`
classes, so later changes to those classes cannot change what this migration does.
"""

import itertools
import json
from collections import defaultdict
from pathlib import Path

from django.db import migrations
from loguru import logger

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "catalog.json"
BATCH_SIZE = 500

LLM_KIND = "llm"
EMBEDDING_KIND = "embedding"
LLM_SETTING_COLUMNS = (
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
)
# Connection key -> model row column holding it before this migration.
LLM_MODEL_ENDPOINT_COLUMNS = {
    "base_url": "base_url",
    "api_version": "api_version",
    "deployment_id": "deployment_id",
}
EMBEDDING_MODEL_ENDPOINT_COLUMNS = {"base_url": "base_url", "deployment_id": "deployment"}


class _FrozenCatalogReader:
    """Which settings the committed catalog lets a config keep; the catalog format as of this migration."""

    def __init__(self, providers: dict, models: dict) -> None:
        self._providers = providers
        self._models = models
        self._provider_by_alias = {
            alias: name for name, provider in providers.items() for alias in provider["aliases"]
        }
        self._models_by_lookup_name: dict[tuple[str, str], dict] = {}

    @classmethod
    def load(cls, path: Path) -> "_FrozenCatalogReader | None":
        """Return the reader, or None after one warning when the file is missing or has another shape."""
        try:
            data = json.loads(path.read_text())
            problem = _shape_problem(data)
        except (OSError, ValueError) as error:
            problem = str(error)
        if problem is not None:
            logger.warning(
                "Model catalog {path} not usable ({problem}); every non-null config setting is kept",
                path=path,
                problem=problem,
            )
            return None
        return cls(data["providers"], data["models"])

    def supported_settings(
        self, kind: str, provider_name: str | None, model_name: str | None
    ) -> frozenset[str] | None:
        """Return the settings a config may keep; None to keep every setting."""
        if provider_name is None or model_name is None:
            return None
        provider_name = provider_name.strip().lower()
        provider_name = self._provider_by_alias.get(provider_name, provider_name)
        provider = self._providers.get(provider_name)
        if provider is None:
            return None
        model = self._model(kind, provider_name, model_name)
        if model is not None and kind in provider["kinds"]:
            return frozenset(model["parameter_names"])
        return frozenset(provider["common_parameters"].get(kind, ()))

    def _model(self, kind: str, provider_name: str, model_name: str) -> dict | None:
        key = (kind, provider_name)
        if key not in self._models_by_lookup_name:
            self._models_by_lookup_name[key] = {
                _lookup_name(provider_name, name): model
                for name, model in self._models[kind].get(provider_name, {}).items()
            }
        return self._models_by_lookup_name[key].get(_lookup_name(provider_name, model_name))


def _lookup_name(provider_name: str, model_name: str) -> str:
    # litellm_lookup_name of src/shared/litellm_model_names.py, frozen: rows and catalog keys
    # hold a model as "<provider>/<name>" or bare, and both forms name the same model.
    model_name = model_name.strip()
    if model_name.startswith(f"{provider_name}/"):
        return model_name
    return f"{provider_name}/{model_name}"


def _is_text_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _shape_problem(data: object) -> str | None:
    """Name the first part of the catalog the reader cannot read; None when it reads all of it."""
    if not isinstance(data, dict):
        return "not a JSON object"
    providers, models = data.get("providers"), data.get("models")
    if not isinstance(providers, dict) or not isinstance(models, dict):
        return "no providers or models mapping"
    for name, provider in providers.items():
        if not (
            isinstance(provider, dict)
            and _is_text_list(provider.get("aliases"))
            and _is_text_list(provider.get("kinds"))
            and isinstance(provider.get("common_parameters"), dict)
            and all(_is_text_list(names) for names in provider["common_parameters"].values())
        ):
            return f"provider {name} has another shape"
    for kind in (LLM_KIND, EMBEDDING_KIND):
        if not isinstance(models.get(kind), dict):
            return f"no {kind} models mapping"
        for provider_name, by_name in models[kind].items():
            if not isinstance(by_name, dict) or not all(
                isinstance(model, dict) and _is_text_list(model.get("parameter_names"))
                for model in by_name.values()
            ):
                return f"{kind} models of {provider_name} have another shape"
    return None


def _kept_settings(
    catalog: _FrozenCatalogReader | None, kind: str, model, provider, values: dict
) -> dict:
    present = {name: value for name, value in values.items() if value is not None}
    if catalog is None or model is None:
        return present
    supported = catalog.supported_settings(kind, provider and provider.name, model.name)
    if supported is None:
        return present
    return {name: value for name, value in present.items() if name in supported}


def _own_organization_model(config):
    """Return the config's model row when it belongs to the config's organization."""
    model = config.model
    if model is not None and model.org_id is not None and model.org_id == config.org_id:
        return model
    return None


def _endpoint_model(config, columns: tuple[str, ...]):
    """Return the model row whose endpoint the config takes; warn when another org's or a built-in row's is dropped."""
    model = _own_organization_model(config)
    if model is None and config.model is not None:
        # Names only: an endpoint can carry an internal host or a token.
        dropped = [column for column in columns if getattr(config.model, column)]
        if dropped:
            logger.warning(
                "Not copying {} of {} id={} (org={}) into {} id={} (org={}): the model row is "
                "built-in or belongs to another organization. Set it on the config if it is needed.",
                ", ".join(dropped),
                type(config.model).__name__,
                config.model.pk,
                config.model.org_id,
                type(config).__name__,
                config.pk,
                config.org_id,
            )
    return model


def _without_empty(values: dict) -> dict:
    return {key: value for key, value in values.items() if value}


def _update_in_batches(model_class, rows, fields: list[str]) -> None:
    for batch in itertools.batched(rows, BATCH_SIZE):
        model_class.objects.bulk_update(batch, fields)


def _fold_llm_config(config, catalog):
    endpoint_model = _endpoint_model(config, ("base_url", "api_version", "deployment_id"))
    config.parameters = _kept_settings(
        catalog,
        LLM_KIND,
        config.model,
        config.model and config.model.llm_provider,
        {column: getattr(config, column) for column in LLM_SETTING_COLUMNS},
    )
    config.connection = _without_empty(
        {
            # Runs read the endpoint from the model row only, so the row's value wins.
            "base_url": getattr(endpoint_model, "base_url", None) or config.base_url,
            "api_version": getattr(endpoint_model, "api_version", None) or config.api_version,
            "deployment_id": getattr(endpoint_model, "deployment_id", None),
        }
    )
    return config


def _fold_embedding_config(config, catalog):
    endpoint_model = _endpoint_model(config, ("base_url", "deployment"))
    config.parameters = _kept_settings(
        catalog,
        EMBEDDING_KIND,
        config.model,
        config.model and config.model.embedding_provider,
        {"task_type": config.task_type},
    )
    config.connection = _without_empty(
        {
            "base_url": getattr(endpoint_model, "base_url", None),
            "deployment_id": getattr(endpoint_model, "deployment", None),
        }
    )
    return config


def fold_config_columns(apps, schema_editor):
    catalog = _FrozenCatalogReader.load(CATALOG_PATH)
    for config_name, provider_path, fold in (
        ("LLMConfig", "model__llm_provider", _fold_llm_config),
        ("EmbeddingConfig", "model__embedding_provider", _fold_embedding_config),
    ):
        config_model = apps.get_model("ai_models", config_name)
        configs = config_model.objects.select_related(provider_path).order_by("pk")
        _update_in_batches(
            config_model,
            (fold(config, catalog) for config in configs.iterator(chunk_size=BATCH_SIZE)),
            ["parameters", "connection"],
        )


def _restore_model_endpoints(model_class, values_by_model: dict, columns: dict) -> None:
    """Write back each endpoint every config of the row's organization agrees on."""
    for model_id, values_by_key in values_by_model.items():
        restored = {
            columns[key]: next(iter(values))
            for key, values in values_by_key.items()
            if len(values) == 1 and None not in values
        }
        if restored:
            model_class.objects.filter(pk=model_id).update(**restored)


def _unfold(
    apps, config_name: str, unfold_config, columns: list[str], model_name: str, endpoint_columns: dict
):
    config_model = apps.get_model("ai_models", config_name)
    values_by_model = defaultdict(lambda: defaultdict(set))

    def unfold(config):
        unfold_config(config)
        if _own_organization_model(config) is not None:
            for key in endpoint_columns:
                values_by_model[config.model_id][key].add(config.connection.get(key))
        return config

    configs = config_model.objects.select_related("model").order_by("pk")
    _update_in_batches(
        config_model, (unfold(config) for config in configs.iterator(chunk_size=BATCH_SIZE)), columns
    )
    _restore_model_endpoints(apps.get_model("ai_models", model_name), values_by_model, endpoint_columns)


def _unfold_llm_config(config) -> None:
    for column in LLM_SETTING_COLUMNS:
        setattr(config, column, config.parameters.get(column))
    config.base_url = config.connection.get("base_url")
    config.api_version = config.connection.get("api_version")


def _unfold_embedding_config(config) -> None:
    # The column is NOT NULL; without a stored value it keeps the default it was re-added with.
    config.task_type = config.parameters.get("task_type") or config.task_type


def unfold_config_columns(apps, schema_editor):
    _unfold(
        apps,
        "LLMConfig",
        _unfold_llm_config,
        [*LLM_SETTING_COLUMNS, "base_url", "api_version"],
        "LLMModel",
        LLM_MODEL_ENDPOINT_COLUMNS,
    )
    _unfold(
        apps,
        "EmbeddingConfig",
        _unfold_embedding_config,
        ["task_type"],
        "EmbeddingModel",
        EMBEDDING_MODEL_ENDPOINT_COLUMNS,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("ai_models", "0003_config_parameters_connection"),
    ]

    operations = [
        migrations.RunPython(fold_config_columns, unfold_config_columns),
    ]
