"""The confirmation phrases of the permanent deletes, computed by the server only.

A SuperAdmin types the phrase the preview shows. It is compared exactly, with no trimming and
no case folding, against the phrase computed when the delete is asked for, so a name changed
in between refuses the delete.
"""

from plugins.exceptions import InvalidPurgePhraseError


def grant_purge_phrase(identifier: str, organization_name: str) -> str:
    return f"purge-{identifier}-{organization_name}"


def plugin_purge_phrase(identifier: str) -> str:
    return f"purge-{identifier}"


def assert_purge_phrase(submitted: str | None, expected: str) -> None:
    """Refuse a missing phrase or one that is not exactly `expected`.

    Raises:
        InvalidPurgePhraseError: The phrase is missing or different.
    """
    if submitted != expected:
        raise InvalidPurgePhraseError()
