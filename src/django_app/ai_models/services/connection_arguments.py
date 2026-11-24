"""A stored config `connection` translated to the LiteLLM arguments a call sends.

Stored connection fields are keyed by the catalog's field names (`base_url`); a LiteLLM
call takes them under each field's `litellm_argument` (`api_base`). Every payload that
carries a connection to another service is translated here.
"""

from tables.services.secrets.secret_resolver import extract_secret_marker_names
from utils.logger import logger

from ai_models.models import EmbeddingConfig, LLMConfig
from ai_models.repository import CatalogRepository

# Stored connection keys the provider's catalog entry no longer declares (its model or
# the provider left the catalog) that were sent before connection fields existed, under
# the LiteLLM argument they were sent as. Any other undeclared key is dropped.
_UNDECLARED_CONNECTION_ARGUMENTS = {
    "base_url": "api_base",
    "api_version": "api_version",
    "deployment_id": "deployment_id",
}


def _connection_arguments(
    config: EmbeddingConfig | LLMConfig, provider_name: str
) -> dict[str, str]:
    """Return the config's stored `connection` keyed by the LiteLLM argument each field is sent as.

    Markers in a secret field stay as they are; SecretResolver fills them on the published
    copy only. SecretResolver fills a marker in any connection value, so a marker in any
    other field (a value stored before markers were checked) is dropped here, or it would
    put the secret into an endpoint or a plain argument.
    """
    provider = CatalogRepository.default().provider(provider_name)
    fields = {field.name: field for field in (provider.connection_fields if provider else ())}
    arguments = {}
    for name, value in config.connection.items():
        # An empty field is "not set", so LiteLLM keeps its own default.
        if not value:
            continue
        field = fields.get(name)
        if extract_secret_marker_names({name: value}) and not (field and field.secret):
            logger.warning(
                "{} {}: connection field '{}' holds a secret marker but is not a secret "
                "field of its provider; it is not sent",
                type(config).__name__,
                config.pk,
                name,
            )
            continue
        argument = field.litellm_argument if field else _UNDECLARED_CONNECTION_ARGUMENTS.get(name)
        if argument:
            arguments[argument] = value
    return arguments


def embedding_config_connection(config: EmbeddingConfig) -> dict[str, str]:
    """Return the embedding config's connection under LiteLLM argument names.

    Reads `config.model.embedding_provider`: select it with the config to avoid two queries.
    """
    provider = config.model.embedding_provider if config.model else None
    return _connection_arguments(config, provider.name if provider else "")


def llm_config_connection(config: LLMConfig) -> dict[str, str]:
    """Return the LLM config's connection under LiteLLM argument names.

    Reads `config.model.llm_provider`: select it with the config to avoid two queries.
    """
    provider = config.model.llm_provider if config.model else None
    return _connection_arguments(config, provider.name if provider else "")
