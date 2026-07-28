from tables.exceptions import CustomAPIExeption


class SecretDecryptionError(CustomAPIExeption):
    """Raised by SecretCipher.open() when a ciphertext cannot be decrypted
    under the current key: tampered, truncated, or sealed under a different
    key than the one currently derived from SECRET_KEY."""

    status_code = 500
    default_detail = "Secret value could not be decrypted."
    default_code = "secret_decryption_error"


class SecretTooLargeError(CustomAPIExeption):
    """Raised by SecretCipher.seal() when the plaintext exceeds MAX_PLAINTEXT_BYTES."""

    status_code = 400
    default_detail = "Secret value is too large."
    default_code = "secret_too_large"
