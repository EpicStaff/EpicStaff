from typing import Any

from rbac.validation.base import BaseRBACValidator, FieldError

VERIFICATION_PHRASE_FIELD = "verification_phrase"


class HardDeleteValidationService(BaseRBACValidator):
    """Validates the request body of a permanent (non-dry-run) delete.

    The phrase is never echoed back in an error: a user's phrase embeds their email.
    """

    def extract_verification_phrase(self, data: Any) -> str | None:
        """Return the submitted phrase, or None when absent; the service decides whether it matches."""
        if not isinstance(data, dict):
            self._raise_if_any(
                [FieldError(VERIFICATION_PHRASE_FIELD, "Request body must be a JSON object.")]
            )
        phrase = data.get(VERIFICATION_PHRASE_FIELD)
        if phrase is not None and not isinstance(phrase, str):
            self._raise_if_any(
                [
                    FieldError(
                        VERIFICATION_PHRASE_FIELD,
                        "Must be a string.",
                    )
                ]
            )
        return phrase
