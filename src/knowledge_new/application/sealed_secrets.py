import re
from dataclasses import replace

from application.commands import RunIndex, RunSearch
from domain.errors import SecretDecryptError
from foundation.cryptographer import AbstractCryptographer, CryptographerError

__all__ = ["open_sealed_secrets"]

# Byte-identical to the producer's, in django_app tables/services/secrets/secret_resolver.py.
_SECRET_MARKER_RE = re.compile(r"epicstaff_secret\(\s*([^)]+?)\s*\)")


def open_sealed_secrets[TCommand: (RunIndex, RunSearch)](
    command: TCommand, cryptographer: AbstractCryptographer
) -> TCommand:
    """Return a copy of `command` with its sealed secrets decrypted.

    The API keys arrive as ciphertext, and header values carry
    `epicstaff_secret(<ciphertext>)` markers. A None API key stays None.

    Raises:
        SecretDecryptError: A secret cannot be decrypted with `cryptographer`.
            The message names the field, never its value.
    """
    return replace(
        command,
        embedding_api_key=_open_api_key(
            command.embedding_api_key, "embedding_api_key", cryptographer
        ),
        llm_api_key=_open_api_key(command.llm_api_key, "llm_api_key", cryptographer),
        embedding_extra_headers=_open_headers(
            command.embedding_extra_headers, "embedding_extra_headers", cryptographer
        ),
        llm_extra_headers=_open_headers(
            command.llm_extra_headers, "llm_extra_headers", cryptographer
        ),
    )


def _open_api_key(
    sealed: str | None, field: str, cryptographer: AbstractCryptographer
) -> str | None:
    if sealed is None:
        return None
    try:
        return cryptographer.decrypt(sealed)
    except CryptographerError as error:
        raise SecretDecryptError(field=field) from error


def _open_headers(
    headers: dict[str, str], field: str, cryptographer: AbstractCryptographer
) -> dict[str, str]:
    try:
        return _resolve_header_markers(headers, cryptographer)
    except CryptographerError as error:
        raise SecretDecryptError(field=field) from error


def _resolve_header_markers(
    headers: dict | None, cryptographer: AbstractCryptographer
) -> dict | None:
    # A new dict, so the command's own headers are never modified.
    if not headers:
        return headers

    return {
        key: (
            _SECRET_MARKER_RE.sub(lambda match: cryptographer.decrypt(match.group(1)), value)
            if isinstance(value, str)
            else value
        )
        for key, value in headers.items()
    }
