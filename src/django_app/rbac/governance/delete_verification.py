from rbac.exceptions import InvalidVerificationPhraseError

DELETE_PHRASE_PREFIX = "delete-"


def assert_delete_phrase(submitted: str | None, expected_target: str) -> None:
    """Require `submitted` to be exactly `DELETE_PHRASE_PREFIX + expected_target`, with no trimming or case folding.

    Raises:
        InvalidVerificationPhraseError: The phrase is missing, lacks the prefix, or names a different target.
    """
    if submitted != f"{DELETE_PHRASE_PREFIX}{expected_target}":
        raise InvalidVerificationPhraseError()
