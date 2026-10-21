from tables.exceptions import CustomAPIExeption


class SecretDecryptionError(CustomAPIExeption):
    """Raised by SecretEncryption.decrypt() when an encryptedtext cannot be
    decrypted under the current key: tampered, truncated, or encrypted under a
    different key than the one currently derived from SECRET_KEY."""

    status_code = 500
    default_detail = "Secret value could not be decrypted."
    default_code = "secret_decryption_error"


class SecretTooLargeError(CustomAPIExeption):
    """Raised by SecretEncryption.encrypt() when the text exceeds MAX_TEXT_BYTES."""

    status_code = 400
    default_detail = "Secret value is too large."
    default_code = "secret_too_large"


class SecretResolutionError(CustomAPIExeption):
    """Raised when a non-null Secret reference cannot be turned into plaintext:
    the row is gone, or its value cannot be decrypted. A null reference is not an
    error — it means no credential is configured, which is legitimate for
    providers that need none."""

    status_code = 500
    default_detail = "Secret could not be resolved."
    default_code = "secret_resolution_error"


class UndeclaredSecretError(CustomAPIExeption):
    """Raised when code reads a secret its PythonCode did not declare.

    The declaration is the allow-list, so this is a caller mistake rather than an
    infrastructure fault — hence 400. Raised inside run_session's try block so its
    existing handler marks the session ERROR with a reason and publishes nothing.
    """

    status_code = 400
    default_detail = "Code reads a secret that was not declared for it."
    default_code = "undeclared_secret"


class SecretUseDeniedError(Exception):
    """Raised by SecretReferenceGuard when a write changes which secrets reach where without secrets:USE.

    A domain error, not an API one: each writer phrases it for its own caller. The
    serializer adapter turns it into a 400 keyed by `field_name`; an import reports
    that nothing was imported.
    """

    def __init__(self, *, field_name: str, message: str):
        super().__init__(message)
        self.field_name = field_name
        self.message = message


class SecretInjectionDeniedError(CustomAPIExeption):
    """Raised building a payload whose config sends its secret to an unapproved custom destination.

    Approved means the config's `secret_binding_approved_by` still holds secrets:USE
    in its org; a NULL approver fails closed. This catches an approver who has since
    lost USE, left the org or been deleted, and a binding no USE holder ever approved.
    It does not detect a direct database edit of the destination: such an edit leaves
    the approver in place. A caller fix rather than an infrastructure fault -- hence
    400. Names the config, never a secret value.
    """

    status_code = 400
    default_detail = "A config may not send its secret to its custom destination."
    default_code = "secret_injection_denied"
