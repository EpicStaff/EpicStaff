"""Storage rules for a Classification Decision Table node's `metadata["explanations"]`.

Two kinds of writer share them. `PUT …/explanations/` refuses a map these rules
would cut. Every serializer taking a node's `metadata` as free JSON — bulk save,
node create/update, import — stores only what they keep, so a save never fails
over an explanation: graphs already hold unvalidated ones and the UI cannot
delete them.

The rules run on untrusted input of any size, so the work is bounded: at most
`MAX_EXAMINED_KEYS` keys are examined, entries are checked with plain Python
rather than a serializer each, and only counts are kept unless the caller asks
for the reasons.
"""

import heapq
import json
import re
from dataclasses import dataclass

from rest_framework.settings import api_settings
from utils.logger import logger

from tables.constants.cdt_explanation_limits import (
    MAX_EXPLANATION_TEXT_LENGTH,
    MAX_FINGERPRINT_LENGTH,
    MAX_GENERATED_BY_LENGTH,
    MAX_STEP_KEY_LENGTH,
    MAX_STORED_EXPLANATIONS,
    MAX_STORED_EXPLANATIONS_BYTES,
)

# Past this many keys a map is over the count limit however its entries look, so
# the rest are left out unexamined.
MAX_EXAMINED_KEYS = MAX_STORED_EXPLANATIONS * 2

# The fields of a stored entry and their length limits; anything else is dropped.
_ENTRY_FIELD_LIMITS = {
    "text": MAX_EXPLANATION_TEXT_LENGTH,
    "generatedBy": MAX_GENERATED_BY_LENGTH,
    "fingerprint": MAX_FINGERPRINT_LENGTH,
}

# What DRF's ProhibitNullCharactersValidator and ProhibitSurrogateCharactersValidator
# refuse: Postgres jsonb cannot hold NUL, and a lone surrogate cannot be encoded.
_UNSTORABLE_CHARACTER = re.compile("[\x00\ud800-\udfff]")

_INVALID_STEP_KEY_MESSAGE = (
    f"Step keys must be 1 to {MAX_STEP_KEY_LENGTH} characters long, "
    "without null or surrogate characters."
)


@dataclass
class ExplanationsReview:
    kept: dict
    malformed: int = 0
    over_limit: int = 0
    # Why entries cannot be stored, keyed by step key; only when asked for. Bad
    # step keys share one entry under the non-field key, never echoing the key.
    errors: dict | None = None


def review_explanations(explanations: dict, *, collect_errors: bool = False) -> ExplanationsReview:
    """Apply the storage rules to a node's explanations map.

    Keys are taken in code-point order. A malformed entry is skipped; once the
    count or total size limit is reached, every later entry is left out.

    Args:
        collect_errors: Record why each entry was skipped, for a 400. Off, only
            counts are kept, so the cost does not grow with what is refused.
    """
    examined = (
        sorted(explanations)
        if len(explanations) <= MAX_EXAMINED_KEYS
        else heapq.nsmallest(MAX_EXAMINED_KEYS, explanations)
    )
    review = ExplanationsReview(
        kept={},
        over_limit=len(explanations) - len(examined),
        errors={} if collect_errors else None,
    )
    # Compact JSON of the kept map: the braces, then each `"key":{...}` plus a comma.
    stored_size = 2
    for position, step_key in enumerate(examined):
        if not _is_storable_step_key(step_key):
            review.malformed += 1
            if collect_errors:
                review.errors[api_settings.NON_FIELD_ERRORS_KEY] = [_INVALID_STEP_KEY_MESSAGE]
            continue
        entry, problems = _clean_entry(explanations[step_key])
        if problems:
            review.malformed += 1
            if collect_errors:
                review.errors[step_key] = problems
            continue

        entry_size = len(_compact_json({step_key: entry})) - 2 + (1 if review.kept else 0)
        if (
            len(review.kept) == MAX_STORED_EXPLANATIONS
            or stored_size + entry_size > MAX_STORED_EXPLANATIONS_BYTES
        ):
            review.over_limit += len(examined) - position
            break
        review.kept[step_key] = entry
        stored_size += entry_size
    return review


def sanitize_metadata_explanations(metadata, *, node_id: int | None = None):
    """Return `metadata` with `explanations` cut down to what may be stored.

    Logs one warning with the counts when anything is dropped, never the content.
    Metadata that is not an object, or has no `explanations` key, is returned
    untouched.

    Args:
        node_id: Only for the warning; `None` for a node being created.
    """
    if not isinstance(metadata, dict) or "explanations" not in metadata:
        return metadata
    explanations = metadata["explanations"]
    if not isinstance(explanations, dict):
        logger.warning(
            "Dropping CDT explanations that are not an object (node {}, got {})",
            node_id,
            type(explanations).__name__,
        )
        return {**metadata, "explanations": {}}

    review = review_explanations(explanations)
    if review.malformed or review.over_limit:
        logger.warning(
            "Dropping CDT explanations (node {}): {} malformed, {} over the limits, {} kept",
            node_id,
            review.malformed,
            review.over_limit,
            len(review.kept),
        )
    return {**metadata, "explanations": review.kept}


class CdtExplanationsSanitizingMixin:
    """For serializers taking a CDT node's `metadata` as free JSON.

    Stores only the explanations `review_explanations` keeps. Place it before the
    serializer base class.
    """

    def validate_metadata(self, metadata):
        return sanitize_metadata_explanations(metadata, node_id=getattr(self.instance, "pk", None))


def _is_storable_step_key(step_key) -> bool:
    return (
        isinstance(step_key, str)
        and 0 < len(step_key) <= MAX_STEP_KEY_LENGTH
        and not _UNSTORABLE_CHARACTER.search(step_key)
    )


def _clean_entry(entry) -> tuple[dict | None, dict | list | None]:
    """Return the entry as stored and no problems, or no entry and its problems."""
    if not isinstance(entry, dict):
        return None, ["Each explanation must be an object."]
    cleaned, problems = {}, {}
    for field_name, max_length in _ENTRY_FIELD_LIMITS.items():
        if field_name not in entry:
            problems[field_name] = ["This field is required."]
            continue
        value = entry[field_name]
        # Checked in this order so a huge value is refused before it is scanned.
        if not isinstance(value, str):
            problems[field_name] = ["Not a valid string."]
        elif not value:
            problems[field_name] = ["This field may not be blank."]
        elif len(value) > max_length:
            problems[field_name] = [f"Ensure this field has no more than {max_length} characters."]
        elif _UNSTORABLE_CHARACTER.search(value):
            problems[field_name] = ["Null and surrogate characters are not allowed."]
        else:
            cleaned[field_name] = value
    if problems:
        return None, problems
    return cleaned, None


def _compact_json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
