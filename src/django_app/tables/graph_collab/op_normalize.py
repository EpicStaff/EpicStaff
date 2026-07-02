"""
Op-time normalization: convert flat FE canvas node payloads to bulk-save shape.

When the frontend sends a NodeCreatedMessage or NodeUpdatedMessage over the
WebSocket, the node payload (message.node) is in the *canvas* shape — the form
used internally by the flow editor.  Some node types embed nested data inside a
``data`` dict rather than at the top level, and use a flat FK id where the
bulk-save serializer expects a nested writable object.

This module reconstructs the bulk-save–shaped node entry from the flat canvas
payload, so the snapshot stored in Redis is always valid input for
``GraphBulkSaveInputSerializer``, regardless of whether the entry originated
from a DB seed or from a live WS op.

As of FE commit d8989d1cb ("send backend-compatible payload over WS for
autosave"), ``buildNodeBackendPayload()`` on the frontend now constructs the
bulk-save shape directly for most node types, so per-type normalizers for
those types are dead code and have been removed.  ``_NORMALIZERS`` currently
holds only ``schedule_trigger_node_list``, pending an FE-side data-integrity
fix (a wrong-key typo in ``buildSchedulePayload()``'s "once" mode) that is
unrelated to shape and out of this module's scope.  ``decision_table``,
``classification_decision_table``, and ``conditional_edge_list`` never had
normalizers here and remain FE-only blockers, also out of scope.

Extension point
---------------
``_NORMALIZERS`` is a dict keyed on ``list_key`` (the snapshot key such as
``"python_node_list"``).  To add normalization for another node type, register a
function with the signature::

    def _normalize_<type>_entry(entry: dict) -> dict: ...

and add it to ``_NORMALIZERS``.  The function receives the raw op entry and
must treat it as read-only, creating its own shallow copy if it needs to
mutate it (see ``_normalize_schedule_trigger_entry`` for the pattern). It must
return a dict in bulk-save shape and must be idempotent: if the entry is
already in bulk-save shape the returned dict must be equivalent to the input.

Unregistered list_keys pass through unchanged (no log spam).
"""

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Schedule-trigger node normalizer
# ---------------------------------------------------------------------------


def _normalize_schedule_trigger_entry(entry: dict) -> dict:
    """Reconstruct a bulk-save–shaped schedule_trigger node entry from a flat
    camelCase canvas payload.

    Idempotent: if ``schedule`` is already present at the top level, the entry
    is returned unchanged.

    Flat canvas shape (FE WS payload, all fields flat & camelCase inside
    ``data``)::

        {
            "id": 90,
            "type": "schedule_trigger",
            "data": {
                "isActive": False,
                "runMode": "once",
                "timezone": "UTC",
                "startDateTime": "",
                "nextRunDateTime": None,
                "intervalEvery": None,
                "intervalUnit": None,
                "weekdays": [],
                "endType": "never",
                "endDateTime": None,
                "maxRuns": None,
                "currentRuns": 0,
            },
            ...
        }

    Bulk-save shape (required by ScheduleTriggerNodeSerializer)::

        {
            "id": 90,
            "is_active": False,
            "current_runs": 0,
            "schedule": {
                "run_mode": "once",
                "timezone": "UTC",
                "start_date_time": None,
                "next_run_date_time": None,
                "interval": {"every": None, "unit": None, "weekdays": []},
                "end": {"type": "never", "date_time": None, "max_runs": None},
            },
            ...
        }

    Verified against:
      - ScheduleTriggerNode (graph_models.py) — flat model columns
        (is_active, timezone, run_mode, start_date_time, every, unit,
        weekdays, end_type, end_date_time, max_runs, current_runs,
        next_run_date_time).
      - ScheduleTriggerNodeSerializer / _ScheduleConfigInputSerializer /
        _ScheduleIntervalInputSerializer / _ScheduleEndInputSerializer
        (trigger_serializers.py) — the write shape nests run_mode, timezone,
        start_date_time under ``schedule``, further nesting interval fields
        under ``schedule.interval`` and end fields under ``schedule.end``.

    Empty string ``""`` for a datetime field is coerced to ``None`` (the FE
    canvas uses ``""`` as its "unset" sentinel; the serializer expects null).
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


def _apply_common_metadata_and_cleanup(entry: dict) -> dict:
    """Fold canvas-only metadata fields into ``metadata`` and drop dead weight.

    Every node entry (regardless of list_key) gets a ``metadata`` dict built
    from its top-level canvas fields — ``position``, ``size``, ``color``,
    ``icon``, and ``nodeNumber`` (when present; singleton types like
    ``start``/``end`` never carry it).  ``setdefault`` is used at every step
    so a ``metadata`` dict that already arrived in bulk-save shape (e.g. from
    the DB-seed path, or from a per-type normalizer that already wrote into
    ``metadata``) is never clobbered — only gaps are filled in.

    Once folded, the now-redundant top-level copies (``position``, ``size``,
    ``color``, ``icon``, ``nodeNumber``) are removed, along with the
    canvas-only scaffolding fields ``data``, ``ports``, and ``type`` that no
    backend or bulk-save consumer reads.

    Idempotent: calling this twice is a no-op the second time — the fields it
    would read (``position``, etc.) are already gone, and ``metadata`` is
    already fully populated.
    """
    entry = copy.copy(entry)

    metadata = dict(entry.get("metadata") or {})
    for field, default in _METADATA_FIELD_DEFAULTS.items():
        metadata.setdefault(field, entry.get(field, default))
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_op_entry(list_key: str, entry: dict) -> dict:
    """Return a bulk-save–shaped copy of *entry* for the given *list_key*.

    Runs two stages, in order:

    1. The per-type normalizer registered in ``_NORMALIZERS`` for *list_key*
       (if any), which reads ``entry["data"]`` and lifts/renames/reshapes
       fields into bulk-save shape. Unregistered list_keys skip this stage
       (no log spam — most node types don't need it because their FE payload
       already matches the serializer shape).
    2. The universal metadata/cleanup stage
       (``_apply_common_metadata_and_cleanup``), which folds the canvas-only
       ``position``/``size``/``color``/``icon``/``nodeNumber`` fields into a
       ``metadata`` dict and deletes the now-dead ``data``/``ports``/``type``
       fields. This runs for every list_key except ``edge_list`` and
       ``conditional_edge_list`` (edges have no canvas position/size/color/icon).

    The per-type normalizer runs first specifically so it can still read
    ``entry["data"]`` before stage 2 deletes it.

    Args:
        list_key: The snapshot list key (e.g. ``"python_node_list"``).
        entry:    The raw node dict from the FE WS op message.

    Returns:
        A dict suitable for storage in the snapshot (bulk-save shape).
    """
    normalizer = _NORMALIZERS.get(list_key)
    if normalizer is not None:
        entry = normalizer(entry)

    if list_key in _METADATA_CLEANUP_EXCLUDED_LIST_KEYS:
        return entry

    return _apply_common_metadata_and_cleanup(entry)
