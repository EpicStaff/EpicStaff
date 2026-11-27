"""Remove the stored LLM settings the committed catalog no longer lets their model take.

The catalog stopped listing sampling settings for models LiteLLM sends none to (Claude 4.7
and later, GPT on Bedrock) and stopped offering `reasoning_effort` "none" on Claude models
that always think. A config still storing one shows "needs review" and its runs are
refused. Removing them changes no run: such a sampling value made the call fail or equalled
the default, and "none" on an always-thinking model was already sent as nothing.

Forward, for every LLM config whose model the committed `ai_models/data/catalog.json` knows:

- `temperature`, `top_p` and `top_k` leave `parameters` when the model's `parameter_names`
  does not list them, null values included;
- `reasoning_effort` "none" leaves `parameters` when the model's `options.reasoning_effort`
  does not offer it.

No other key or value is touched. A config without a model, on a provider or model the
catalog does not know, or with a provider that no longer runs LLMs keeps everything, and so
does every config when the catalog file is missing or not in the expected shape. Embedding
configs are not touched.

The catalog is read with `json` by the reader frozen below, never through the `ai_models`
classes, so later changes to those classes cannot change what this migration does.
"""

import itertools
import json
from pathlib import Path

from django.db import migrations
from loguru import logger

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "catalog.json"
BATCH_SIZE = 500

LLM_KIND = "llm"
SAMPLING_SETTINGS = ("temperature", "top_p", "top_k")
REASONING_EFFORT = "reasoning_effort"
NO_REASONING_EFFORT = "none"


class _FrozenCatalogReader:
    """The committed catalog's LLM models; the catalog format as of this migration."""

    def __init__(self, providers: dict, llm_models: dict) -> None:
        self._providers = providers
        self._llm_models = llm_models
        self._provider_by_alias = {
            alias: name for name, provider in providers.items() for alias in provider["aliases"]
        }
        self._models_by_lookup_name: dict[str, dict] = {}

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
                "Model catalog {path} not usable ({problem}); no config setting is removed",
                path=path,
                problem=problem,
            )
            return None
        return cls(data["providers"], data["models"][LLM_KIND])

    def llm_model(self, provider_name: str, model_name: str) -> dict | None:
        """Return the catalog entry of the model; None when the catalog does not know it."""
        provider_name = provider_name.strip().lower()
        provider_name = self._provider_by_alias.get(provider_name, provider_name)
        provider = self._providers.get(provider_name)
        if provider is None or LLM_KIND not in provider["kinds"]:
            return None
        if provider_name not in self._models_by_lookup_name:
            self._models_by_lookup_name[provider_name] = {
                _lookup_name(provider_name, name): model
                for name, model in self._llm_models.get(provider_name, {}).items()
            }
        return self._models_by_lookup_name[provider_name].get(
            _lookup_name(provider_name, model_name)
        )


def _lookup_name(provider_name: str, model_name: str) -> str:
    # litellm_lookup_name of src/shared/litellm_model_names.py, frozen: rows and catalog keys
    # hold a model as "<provider>/<name>" or bare, and both forms name the same model.
    model_name = model_name.strip()
    if model_name.startswith(f"{provider_name}/"):
        return model_name
    return f"{provider_name}/{model_name}"


def _is_text_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _has_another_shape(model: object) -> bool:
    if not isinstance(model, dict) or not _is_text_list(model.get("parameter_names")):
        return True
    options = model.get("options", {})
    return not isinstance(options, dict) or not _is_text_list(options.get(REASONING_EFFORT, []))


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
        ):
            return f"provider {name} has another shape"
    if not isinstance(models.get(LLM_KIND), dict):
        return f"no {LLM_KIND} models mapping"
    for provider_name, by_name in models[LLM_KIND].items():
        if not isinstance(by_name, dict) or any(
            _has_another_shape(model) for model in by_name.values()
        ):
            return f"{LLM_KIND} models of {provider_name} have another shape"
    return None


def _removed_settings(parameters: dict, catalog_model: dict) -> list[str]:
    removed = [
        name
        for name in SAMPLING_SETTINGS
        if name in parameters and name not in catalog_model["parameter_names"]
    ]
    offered_efforts = catalog_model.get("options", {}).get(REASONING_EFFORT)
    if (
        parameters.get(REASONING_EFFORT) == NO_REASONING_EFFORT
        and offered_efforts is not None
        and NO_REASONING_EFFORT not in offered_efforts
    ):
        removed.append(REASONING_EFFORT)
    return removed


def remove_settings_models_no_longer_accept(apps, schema_editor):
    catalog = _FrozenCatalogReader.load(CATALOG_PATH)
    if catalog is None:
        return
    config_model = apps.get_model("ai_models", "LLMConfig")
    configs = (
        config_model.objects.filter(model__llm_provider__isnull=False)
        .select_related("model__llm_provider")
        .only("pk", "parameters", "model__name", "model__llm_provider__name")
        .order_by("pk")
    )
    changed = []
    removed_names = set()
    for config in configs.iterator(chunk_size=BATCH_SIZE):
        if not isinstance(config.parameters, dict):
            continue
        catalog_model = catalog.llm_model(config.model.llm_provider.name, config.model.name)
        if catalog_model is None:
            continue
        removed = _removed_settings(config.parameters, catalog_model)
        if removed:
            config.parameters = {
                name: value for name, value in config.parameters.items() if name not in removed
            }
            changed.append(config)
            removed_names.update(removed)
    for batch in itertools.batched(changed, BATCH_SIZE):
        config_model.objects.bulk_update(batch, ["parameters"])
    if changed:
        # Names only: a config's values are the user's.
        logger.warning(
            "Removed {} from {} LLM config(s): their model no longer accepts the stored value",
            ", ".join(sorted(removed_names)),
            len(changed),
        )


class Migration(migrations.Migration):
    dependencies = [
        ("ai_models", "0006_own_org_custom_models"),
    ]

    operations = [
        # Backward is a no-op: the removed values are not kept anywhere to restore.
        migrations.RunPython(remove_settings_models_no_longer_accept, migrations.RunPython.noop),
    ]
