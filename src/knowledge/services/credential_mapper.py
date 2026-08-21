"""Injects the credential Django resolved into the config dicts the strategies read.

This service holds no SECRET_KEY and has no HTTP route to Django, so a Secret id
would be unresolvable here -- Django resolves at the publish boundary and sends
plaintext over Redis. The api_key columns these dicts used to be filled from no
longer exist in the database.

Raising on a configured-but-absent credential is deliberate. Every embedder in
this service does `api_key or os.getenv(...)`, and NaiveRAGStrategy's
_set_embedder_config catches every exception and falls back to a default OpenAI
embedder built from os.environ. A silent None therefore does not fail -- it
quietly authenticates with the container's ambient key, which belongs to no
particular organization. A loud error is the only way this stays visible.
"""

from dataclasses import dataclass

from loguru import logger


class MissingCredentialError(RuntimeError):
    """A RAG has a credential configured but none arrived in the Redis message."""


@dataclass(frozen=True)
class RagCredentials:
    """The plaintext credentials Django resolved for one RAG."""

    embedder_api_key: str | None = None
    llm_api_key: str | None = None


CONFIGURED_FLAG = "api_key_secret_configured"


def apply_credential(*, config: dict, api_key: str | None, context: str) -> dict:
    """Return a copy of `config` with `api_key` set from the message credential."""
    resolved = dict(config)
    secret_configured = bool(resolved.pop(CONFIGURED_FLAG, False))

    if secret_configured and not api_key:
        raise MissingCredentialError(
            f"{context}: a credential is configured for this RAG but none arrived "
            f"in the message. Refusing to fall back to an ambient environment key."
        )

    if api_key:
        resolved["api_key"] = api_key
    else:
        logger.warning(
            "{}: no credential configured; the provider client will fall back to "
            "its environment variable.",
            context,
        )
    return resolved
