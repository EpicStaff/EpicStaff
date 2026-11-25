from loguru import logger

from tables.import_export.enums import EntityType
from tables.import_export.version_conversions.base import VersionConverter

# The v5 columns this conversion folds, frozen: the current models no longer have them.
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
EMBEDDING_SETTING_COLUMNS = ("task_type",)
# Connection key -> the v5 column holding it.
LLM_CONFIG_ENDPOINT_COLUMNS = {"base_url": "base_url", "api_version": "api_version"}
LLM_MODEL_ENDPOINT_COLUMNS = {
    "base_url": "base_url",
    "api_version": "api_version",
    "deployment_id": "deployment_id",
}
EMBEDDING_MODEL_ENDPOINT_COLUMNS = {"base_url": "base_url", "deployment_id": "deployment"}

_FOLDS = (
    (
        EntityType.LLM_CONFIG,
        EntityType.LLM_MODEL,
        LLM_SETTING_COLUMNS,
        LLM_CONFIG_ENDPOINT_COLUMNS,
        LLM_MODEL_ENDPOINT_COLUMNS,
    ),
    (
        EntityType.EMBEDDING_CONFIG,
        EntityType.EMBEDDING_MODEL,
        EMBEDDING_SETTING_COLUMNS,
        {},
        EMBEDDING_MODEL_ENDPOINT_COLUMNS,
    ),
)


@VersionConverter.register(from_version=5)
def v5_to_v6(data: dict) -> dict:
    """
    v5 -> v6:
    - An export can be a zip archive: `export.json` plus the files it names. A v5
      file never carries a knowledge collection, so its entries need no change.
    The fold the `ai_models` data migration does to stored configs:
    - LLM and embedding config setting columns move into `parameters`; null ones are left out.
    - Endpoint columns move into the config's `connection`: its model row's `base_url`,
      `api_version` and deployment, else the config's own `base_url` and `api_version`.
      Empty ones are left out.
      Only a custom model row's endpoint is copied; a built-in row's is dropped with a warning.
    - Model rows lose their endpoint columns.
    An entry already in the v6 shape carries none of these columns and keeps its
    `parameters` and `connection` as they are.
    Settings the model does not take are dropped later by the config import strategy, which
    knows the model catalog.
    """
    for config_type, model_type, settings, config_endpoints, model_endpoints in _FOLDS:
        endpoints_by_model_id = {
            model.get("id"): _pop_model_endpoint(model, model_endpoints, model_type)
            for model in data.get(model_type, [])
        }
        for config in data.get(config_type, []):
            folded_parameters = {
                column: value
                for column in settings
                if (value := config.pop(column, None)) is not None
            }
            own_endpoint = {
                key: config.pop(column, None) for key, column in config_endpoints.items()
            }
            # Runs read the endpoint from the model row only, so the row's value wins.
            folded_connection = {
                **_non_empty(own_endpoint),
                **endpoints_by_model_id.get(config.get("model"), {}),
            }
            # An unversioned partial file can already be in the v6 shape: what its
            # `parameters` and `connection` hold wins over anything folded here.
            config["parameters"] = {**folded_parameters, **(config.get("parameters") or {})}
            config["connection"] = {**folded_connection, **(config.get("connection") or {})}
    return data


def _pop_model_endpoint(model: dict, columns: dict[str, str], model_type: str) -> dict:
    endpoint = _non_empty({key: model.pop(column, None) for key, column in columns.items()})
    if endpoint and not model.get("is_custom"):
        logger.warning(
            "Dropping endpoint fields {} of built-in {} id={} during v5->v6 conversion: "
            "only an organization's own model hands its endpoint to its configs",
            sorted(endpoint),
            model_type,
            model.get("id"),
        )
        return {}
    return endpoint


def _non_empty(values: dict) -> dict:
    return {key: value for key, value in values.items() if value}
