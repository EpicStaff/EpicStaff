import re
from typing import Any

from rest_framework import serializers

from tables.constants.persistence_constants import MAX_KEY_LENGTH

_FIELDS = {
    "read": ("key", "value"),
    "write": ("key", "value"),
    "delete": ("key",),
}
# Crew's `variables` is a DotDict, so a path starts with a name (`variables[0]` never
# resolves). ASCII matches the frontend. Crew's PersistenceNode checks the same rules at run
# time.
_STATE_PATH = re.compile(r"variables\.\w+(?:\.\w+|\[\d+\])*", re.ASCII)
_PATH_NAME = re.compile(r"\w+", re.ASCII)
# DotDict attribute access finds these before a stored key, so crew could never read a value
# kept under one of these names: the dict methods plus DotDict's own public methods.
DOTDICT_METHOD_NAMES = frozenset(
    {
        "add_property",
        "add_setter",
        "clear",
        "copy",
        "deep_dump",
        "fromkeys",
        "get",
        "items",
        "keys",
        "model_dump",
        "pop",
        "popitem",
        "setdefault",
        "update",
        "values",
    }
)


class PersistenceEntriesValidator:
    """Structural rules for PersistenceNode.entries. Key templates are rendered by crew.

    `value` is a flow state path in both modes that have one: the source of a write, the
    target a read stores into. Returned entries carry the stripped path.
    """

    def validate(self, mode: str, entries: Any) -> list[dict]:
        if not isinstance(entries, list):
            raise serializers.ValidationError({"entries": "Must be a list."})
        errors: list[str] = []
        # Entry index by exact key and by stripped source path, for write entries only.
        written_keys: dict[str, int] = {}
        written_sources: dict[str, int] = {}
        for index, entry in enumerate(entries):
            error = self._entry_error(mode, entry)
            if not error and mode == "write":
                error = self._duplicate_write_error(entry, index, written_keys, written_sources)
            if error:
                errors.append(f"Entry {index}: {error}")
        if errors:
            raise serializers.ValidationError({"entries": errors})
        if mode == "delete":
            return entries
        # Crew rejects a path with surrounding whitespace, and keeps a write's `|default` text
        # verbatim, so `variables.x|0 ` would default to "0 ".
        return [{**entry, "value": entry["value"].strip()} for entry in entries]

    def _entry_error(self, mode: str, entry: Any) -> str | None:
        if not isinstance(entry, dict):
            return "must be an object."
        unknown = set(entry) - set(_FIELDS[mode])
        if unknown:
            return f"unknown fields {sorted(unknown)} for mode '{mode}'."
        for field in _FIELDS[mode]:
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                return f"'{field}' must be a non-empty string."
        if len(entry["key"]) > MAX_KEY_LENGTH:
            return f"'key' must be at most {MAX_KEY_LENGTH} characters."
        if mode == "delete":
            return None
        path = entry["value"].strip()
        if mode == "read" and "|" in path:
            return (
                "'value' is where the stored value goes: use a plain state path like "
                "'variables.user.name', without '|default'."
            )
        return self._state_path_error(path.split("|", 1)[0])

    def _duplicate_write_error(
        self,
        entry: dict,
        index: int,
        written_keys: dict[str, int],
        written_sources: dict[str, int],
    ) -> str | None:
        """Two write entries must not share a key or a source; crew rejects both at run time."""
        key = entry["key"]
        first = written_keys.setdefault(key, index)
        if first != index:
            return f"key '{key}' is already written by entry {first}; use a different key."
        source = entry["value"].split("|", 1)[0].strip()
        first = written_sources.setdefault(source, index)
        if first != index:
            return f"'{source}' is already written by entry {first}; use a different variable."
        return None

    def _state_path_error(self, state_path: str) -> str | None:
        if not _STATE_PATH.fullmatch(state_path):
            return "'value' must be a state path like 'variables.user.name'."
        for name in _PATH_NAME.findall(state_path):
            if name.startswith("_"):
                return f"'value' names '{name}'; use a variable name without the leading '_'."
            if name in DOTDICT_METHOD_NAMES:
                return f"'value' names '{name}', a built-in method; use a different variable name."
        return None
