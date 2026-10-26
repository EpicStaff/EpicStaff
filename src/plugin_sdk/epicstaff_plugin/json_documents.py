"""Strict JSON reading and the canonical JSON form used for signed package documents."""

import json
from typing import Any

from epicstaff_plugin.problems import PackageProblemsError, Problem


class _JsonRuleError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    # Plain json.loads keeps the last of a repeated key, so a reviewer reading the file
    # could see one value while the platform uses another.
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise _JsonRuleError(f"the key {key!r} appears more than once")
        document[key] = value
    return document


def _reject_constant(name: str) -> Any:
    raise _JsonRuleError(f"{name} is not valid JSON")


def load_json_object(raw: bytes, loc: str, file_name: str) -> dict[str, Any]:
    """Decode `raw` as one UTF-8 JSON object, refusing repeated keys and NaN or Infinity.

    Raises:
        PackageProblemsError: The bytes are not such an object; the problem is located at `loc`.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise PackageProblemsError([Problem(loc, f"{file_name} is not UTF-8")]) from None
    try:
        document = json.loads(
            text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant
        )
    except (json.JSONDecodeError, _JsonRuleError) as error:
        raise PackageProblemsError(
            [Problem(loc, f"{file_name} is not valid JSON: {error}")]
        ) from None
    if not isinstance(document, dict):
        raise PackageProblemsError([Problem(loc, f"{file_name} must hold a JSON object")])
    return document


def canonical_json(document: Any) -> bytes:
    """Return the one byte form a signed JSON document may have: sorted keys, no spaces, UTF-8."""
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
