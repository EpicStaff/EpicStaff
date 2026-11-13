from foundation.cryptographer import AbstractCryptographer, CryptographerError


class SecretDecryptionError(Exception):
    """A transport-sealed secret could not be decrypted; the message names the field, never the value."""


def decrypt_transport_secret(
    cryptographer: AbstractCryptographer, value: str | None, *, field_name: str
) -> str | None:
    """Return the plaintext of a secret django_app sealed with the transport key.

    None is returned as is: an unset credential is sent unsealed.

    Raises:
        SecretDecryptionError: `value` is not a ciphertext under the transport keys.
    """
    if value is None:
        return None
    try:
        return cryptographer.decrypt(value)
    except CryptographerError as error:
        raise SecretDecryptionError(f"{field_name} could not be decrypted") from error
