from django.core.exceptions import PermissionDenied
from tables.exceptions import CustomAPIExeption
from tables.services.run_admission import RunAdmissionRefusedError


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
    """Raised when a write needs secrets:USE and the actor does not hold it.

    A domain error, not an HTTP one: `utils.exception_handler` renders it as a 400
    naming `field_path`, and the flow bulk save reports it as that node's errors.
    """

    def __init__(self, *, field_path: tuple[str, ...], message: str):
        super().__init__(message)
        self.field_path = field_path
        self.message = message

    def field_errors(self) -> dict:
        """Return the message nested along `field_path`, shaped like a serializer's `errors`.

        `("python_code", "secret_ids")` gives `{"python_code": {"secret_ids": [message]}}`,
        what the nested PythonCode serializer would report for that field.
        """
        errors = [self.message]
        for segment in reversed(self.field_path):
            errors = {segment: errors}
        return errors


class ModelEndpointNotSettableError(Exception):
    """Raised when a pinned-org principal (a plugin's service account) sets a model's endpoint.

    A domain error, not an HTTP one: `utils.exception_handler` renders it as a 400
    naming each field, and the model import strategy re-raises it as a validation error.
    """

    message = (
        "This credential cannot set where a model sends requests; the organization's "
        "configurations may use this model with their own keys."
    )

    def __init__(self, *, fields: tuple[str, ...]):
        super().__init__(self.message)
        self.fields = fields

    def field_errors(self) -> dict:
        """Return the message under each field, shaped like a serializer's `errors`."""
        return {field_name: [self.message] for field_name in self.fields}


class IncompletePluginCredentialError(PermissionDenied):
    """Raised when a plugin credential's user does not implement `PinnedOrgPrincipal`.

    Such a caller is refused, never taken for a person whose writes nothing limits. A
    Django PermissionDenied, so `utils.exception_handler` renders it as a 403.
    """

    message = "This credential cannot write here."

    def __init__(self):
        super().__init__(self.message)


class SecretMarkerNotReferenceableError(RunAdmissionRefusedError):
    """Work a pinned-org principal (a plugin's service account) starts would resolve an
    `epicstaff_secret(<name>)` header marker to a secret the principal may not reference.

    A marker binds by name when the work starts, so the name may mean another secret than when
    the row was written. Names no secret: the caller may not know which one the name means now.
    """

    status_code = 409
    default_code = "secret_marker_not_referenceable"
    default_detail = (
        "This credential can reference only secrets it created, but a model configuration "
        "used here names another secret in a header, so this cannot start."
    )
    log_key = "secret_marker_not_referenceable"
