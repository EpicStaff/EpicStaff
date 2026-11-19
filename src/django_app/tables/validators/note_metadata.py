import re
from typing import Any

from rest_framework import serializers

NOTE_BACKGROUND_COLOR_KEY = "backgroundColor"

# The note colour picker and every default only ever produce `#RRGGBB`. Anything wider
# (a CSS keyword, `url(...)`, a declaration list) is drawn by the browser as a CSS
# background and could make every viewer fetch an outside URL, so the rule stays a
# hex pattern and never becomes a CSS parser.
_NOTE_COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{6}")


def _has_invalid_note_color(metadata: Any) -> bool:
    if not isinstance(metadata, dict) or NOTE_BACKGROUND_COLOR_KEY not in metadata:
        return False
    color = metadata[NOTE_BACKGROUND_COLOR_KEY]
    if color is None:
        return False
    return not (isinstance(color, str) and _NOTE_COLOR_PATTERN.fullmatch(color))


def validate_note_metadata(metadata: Any) -> None:
    """Reject a note whose `backgroundColor` is anything but absent, null or `#RRGGBB`."""
    if _has_invalid_note_color(metadata):
        raise serializers.ValidationError(
            f"'{NOTE_BACKGROUND_COLOR_KEY}' must be a hex colour in the form #RRGGBB."
        )


def drop_invalid_note_color(metadata: Any) -> Any:
    """Return `metadata` without its `backgroundColor` when that colour is not valid.

    Used where a whole flow is recreated from stored data (import, version restore):
    one bad note colour must not fail the flow, so it is dropped and the note falls
    back to the default colour. The rest of the metadata is kept unchanged.
    """
    if not _has_invalid_note_color(metadata):
        return metadata
    return {key: value for key, value in metadata.items() if key != NOTE_BACKGROUND_COLOR_KEY}
