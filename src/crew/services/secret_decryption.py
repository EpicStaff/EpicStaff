"""Decryption of the secret values django_app seals with the transport key.

crew forwards most sealed values to the services that use them, still sealed. It decrypts
only the ones it uses itself: the LLM configs of Classification Decision Table prompts.
Each function returns a decrypted copy, so the plaintext lives only for the one call that
needs it and never reaches the node data, the state or the session messages.
"""

import re

from foundation.cryptographer import AbstractCryptographer, CryptographerError
from src.shared.models.ai_providers import LLMData
from src.shared.models.system_one import SystemOneConfigData

__all__ = ["SecretDecryptionError", "decrypt_llm_data", "decrypt_system_one_config"]

# Byte-identical to the producer's, in django_app tables/services/secrets/secret_resolver.py.
_SECRET_MARKER_RE = re.compile(r"epicstaff_secret\(\s*([^)]+?)\s*\)")


class SecretDecryptionError(Exception):
    """A transport-sealed secret does not open with the transport key.

    The message names the config field only, never the value or its ciphertext.
    """

    def __init__(self, field: str):
        self.field = field
        super().__init__(f"{field} could not be decrypted.")


def decrypt_llm_data(llm: LLMData, cryptographer: AbstractCryptographer) -> LLMData:
    """Return a copy of `llm` with its `api_key` and `extra_headers` markers decrypted.

    Raises:
        SecretDecryptionError: A sealed value does not open with `cryptographer`.
    """
    config = llm.config
    decrypted_config = config.model_copy(
        update={
            "api_key": _decrypt_api_key(config.api_key, "api_key", cryptographer),
            "extra_headers": _decrypt_header_markers(
                config.extra_headers, "extra_headers", cryptographer
            ),
        }
    )
    return llm.model_copy(update={"config": decrypted_config})


def decrypt_system_one_config(
    config: SystemOneConfigData, cryptographer: AbstractCryptographer
) -> SystemOneConfigData:
    """Return a copy of `config` with its own `api_key` and its LLM config decrypted.

    Raises:
        SecretDecryptionError: A sealed value does not open with `cryptographer`.
    """
    return config.model_copy(
        update={
            "api_key": _decrypt_api_key(config.api_key, "api_key", cryptographer),
            "llm_data": (
                decrypt_llm_data(config.llm_data, cryptographer)
                if config.llm_data is not None
                else None
            ),
        }
    )


def _decrypt_api_key(
    sealed: str | None, field: str, cryptographer: AbstractCryptographer
) -> str | None:
    # An empty api_key means no key, as it did before keys were sealed.
    if not sealed:
        return sealed
    try:
        return cryptographer.decrypt(sealed)
    except CryptographerError:
        raise SecretDecryptionError(field) from None


def _decrypt_header_markers(
    headers: dict[str, str] | None, field: str, cryptographer: AbstractCryptographer
) -> dict[str, str] | None:
    if not headers:
        return headers
    try:
        return {
            key: (
                _SECRET_MARKER_RE.sub(lambda match: cryptographer.decrypt(match.group(1)), value)
                if isinstance(value, str)
                else value
            )
            for key, value in headers.items()
        }
    except CryptographerError:
        raise SecretDecryptionError(field) from None
