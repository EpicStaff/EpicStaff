import copy
from typing import Any


# ---------------------------------------------------------------------------
# Schedule-trigger node normalizer
# ---------------------------------------------------------------------------


def _normalize_schedule_trigger_entry(entry: dict) -> dict:
    """
    Reconstruct a bulk-save–shaped schedule_trigger node entry from a flat
    camelCase canvas payload.
    """
    if "schedule" in entry:
        return entry

    data: dict = entry.get("data")
    if not isinstance(data, dict):
        return entry

    entry = copy.copy(entry)

    if "is_active" not in entry and "isActive" in data:
        entry["is_active"] = data["isActive"]

    if "current_runs" not in entry and "currentRuns" in data:
        entry["current_runs"] = data["currentRuns"]

    def _blank_to_none(value):
        return None if value == "" else value

    entry["schedule"] = {
        "run_mode": data.get("runMode"),
        "timezone": data.get("timezone"),
        "start_date_time": _blank_to_none(data.get("startDateTime")),
        "next_run_date_time": _blank_to_none(data.get("nextRunDateTime")),
        "interval": {
            "every": data.get("intervalEvery"),
            "unit": data.get("intervalUnit"),
            "weekdays": data.get("weekdays") or [],
        },
        "end": {
            "type": data.get("endType"),
            "date_time": _blank_to_none(data.get("endDateTime")),
            "max_runs": data.get("maxRuns"),
        },
    }

    return entry


# ---------------------------------------------------------------------------
# Dispatch table — add new normalizers here for future node types.
# ---------------------------------------------------------------------------

_NORMALIZERS: dict[str, callable] = {
    "schedule_trigger_node_list": _normalize_schedule_trigger_entry,
}

# List keys whose entries do NOT carry the universal canvas metadata fields
# (position/size/color/icon/nodeNumber), so `_apply_common_metadata_and_cleanup`
# must not run on them:
#   - edge_list / conditional_edge_list: connections, not canvas nodes — they
#     have no position/size/color/icon of their own. conditional_edge_list is
#     additionally out of scope for op-normalize entirely (separate,
#     already-decided FE-side fix).
_METADATA_CLEANUP_EXCLUDED_LIST_KEYS: frozenset[str] = frozenset(
    {"edge_list", "conditional_edge_list"}
)

# Top-level canvas fields that get folded into ``metadata`` (via setdefault)
# and then deleted, once their content is no longer needed. Maps each field
# to its fallback value when absent from both the entry and an existing
# ``metadata`` dict.
_METADATA_FIELD_DEFAULTS: dict[str, Any] = {
    "position": {"x": 0, "y": 0},
    "size": {},
    "color": None,
    "icon": None,
}


def _fold_metadata(entry: dict, *, with_defaults: bool) -> dict:
    """Fold canvas-only metadata fields into ``metadata`` and drop dead weight"""
    entry = copy.copy(entry)

    metadata = dict(entry.get("metadata") or {})
    if with_defaults:
        for field, default in _METADATA_FIELD_DEFAULTS.items():
            metadata.setdefault(field, entry.get(field, default))
    else:
        for field in _METADATA_FIELD_DEFAULTS:
            if field in entry:
                metadata.setdefault(field, entry[field])
    if "nodeNumber" in entry:
        metadata.setdefault("nodeNumber", entry["nodeNumber"])
    entry["metadata"] = metadata

    for field in (
        "data",
        "ports",
        "type",
        "position",
        "size",
        "color",
        "icon",
        "nodeNumber",
    ):
        entry.pop(field, None)

    return entry


def _apply_common_metadata_and_cleanup(entry: dict) -> dict:
    """Full-entry metadata fold — see ``_fold_metadata`` (``with_defaults=True``)."""
    return _fold_metadata(entry, with_defaults=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_op_entry(list_key: str, entry: dict) -> dict:
    """Return a bulk-save–shaped copy of *entry* for the given *list_key*"""
    normalizer = _NORMALIZERS.get(list_key)
    if normalizer is not None:
        entry = normalizer(entry)

    if list_key in _METADATA_CLEANUP_EXCLUDED_LIST_KEYS:
        return entry

    return _apply_common_metadata_and_cleanup(entry)


def normalize_partial_op_entry(list_key: str, entry: dict) -> dict:
    """Return a bulk-save-shaped copy of a PARTIAL *entry* for *list_key*"""
    normalizer = _NORMALIZERS.get(list_key)
    if normalizer is not None and "data" in entry:
        entry = normalizer(entry)

    if list_key in _METADATA_CLEANUP_EXCLUDED_LIST_KEYS:
        return copy.copy(entry)

    return _fold_metadata(entry, with_defaults=False)
