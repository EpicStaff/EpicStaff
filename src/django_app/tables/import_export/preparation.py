"""The boundary step both import services run before they write anything."""

from agents.models import SurfacePlace, ToolMode
from django.db import models
from rest_framework.exceptions import ValidationError

from tables.import_export.enums import EntityType
from tables.import_export.strategies.mcp_tools import COMPARED_FIELDS as MCP_COMPARED_FIELDS
from tables.import_export.strategies.python_tools import (
    COMPARED_FIELDS as PYTHON_TOOL_COMPARED_FIELDS,
)
from tables.import_export.utils import nest_owned_surface_entries
from tables.models import McpTool, PythonCode, PythonCodeTool


def prepare_import_data(export_data: dict) -> dict:
    """Validate an import bundle and return it ready for the import services.

    The one boundary step ImportService and PartialImportService share, run
    before their transaction opens, so a rejected file writes nothing.

    Raises:
        ValidationError: A Surface, tool or AgentDefinition entry is malformed,
            or AgentDefinition ids repeat.
    """
    errors = [
        *_surface_entry_errors(export_data),
        *_tool_entry_errors(export_data),
        *_agent_entry_errors(export_data),
    ]
    if errors:
        raise ValidationError({"detail": errors})
    return nest_owned_surface_entries(export_data)


def _surface_entry_errors(export_data: dict) -> list[str]:
    """List the Surface entries the reuse lookups cannot compare reliably.

    `instructions` and tool `mode` are text columns: a number in the file would
    be compared in SQL as its string form but stored by the import as something
    else, silently forking a copy on every import. Tool rows are bulk-created
    without model validation, so a mode outside ToolMode would be stored (or
    fail as a 500), and a tool listed twice would collapse into one row while
    the reuse lookup still counts two -- never matching again.
    """
    tool_id_fields = {
        EntityType.PYTHON_CODE_TOOL: "python_tool_id",
        EntityType.MCP_TOOL: "mcp_tool_id",
    }
    errors = []
    for entry in export_data.get(EntityType.SURFACE, []):
        if not isinstance(entry, dict):
            errors.append("Surface entry is not an object.")
            continue
        entry_id = entry.get("id")
        if not _is_int(entry_id):
            errors.append(f"Surface {entry_id}: id must be an integer.")
        if "instructions" in entry and not isinstance(entry["instructions"], str):
            errors.append(f"Surface {entry_id}: instructions must be text.")
        tools = entry.get("tools", {})
        if not isinstance(tools, dict):
            errors.append(f"Surface {entry_id}: tools must be an object.")
            continue
        for entity_type, id_field in tool_id_fields.items():
            tool_entries = tools.get(entity_type, [])
            if not isinstance(tool_entries, list):
                errors.append(f"Surface {entry_id}: {entity_type} tools must be a list.")
                continue
            seen_tool_ids = set()
            for tool_entry in tool_entries:
                if (
                    not isinstance(tool_entry, dict)
                    or not _is_int(tool_entry.get(id_field))
                    or tool_entry.get("mode") not in ToolMode.values
                ):
                    errors.append(
                        f"Surface {entry_id}: each {entity_type} tool needs an integer "
                        f"{id_field} and a mode of {sorted(ToolMode.values)}."
                    )
                    continue
                if tool_entry[id_field] in seen_tool_ids:
                    errors.append(
                        f"Surface {entry_id}: {entity_type} tool {tool_entry[id_field]} "
                        "is listed more than once."
                    )
                seen_tool_ids.add(tool_entry[id_field])
    return errors


def _agent_entry_errors(export_data: dict) -> list[str]:
    """List the AgentDefinition entries the import cannot place surfaces for.

    An export always writes `owned_surfaces` and `default_surfaces` as lists; a
    null or malformed one would fail mid-import as a 500. A default row may not
    point at a surface another agent in the file owns -- the state the agents
    API rejects. A surface listed by several agents belongs to the first, as in
    nest_owned_surface_entries.
    """
    errors = []
    owner_by_surface_id = {}
    default_rows_by_agent = []
    for entry in export_data.get(EntityType.AGENT_DEFINITION, []):
        if not isinstance(entry, dict):
            errors.append("AgentDefinition entry is not an object.")
            continue
        agent_id = entry.get("id")
        label = f"AgentDefinition {agent_id}"
        if not _is_int(agent_id):
            errors.append(f"{label}: id must be an integer.")
            continue

        owned_surface_ids = entry.get("owned_surfaces", [])
        if not isinstance(owned_surface_ids, list) or not all(
            _is_int(surface_id) for surface_id in owned_surface_ids
        ):
            errors.append(f"{label}: owned_surfaces must be a list of integer ids.")
            owned_surface_ids = []
        for surface_id in owned_surface_ids:
            owner_by_surface_id.setdefault(surface_id, agent_id)

        default_rows = entry.get("default_surfaces", [])
        if not isinstance(default_rows, list) or not all(
            isinstance(row, dict)
            and _is_int(row.get("surface_id"))
            and row.get("place") in SurfacePlace.values
            for row in default_rows
        ):
            errors.append(
                f"{label}: default_surfaces must be a list of objects with an integer "
                f"surface_id and a place of {sorted(SurfacePlace.values)}."
            )
            default_rows = []
        default_rows_by_agent.append((label, agent_id, default_rows))

    for label, agent_id, default_rows in default_rows_by_agent:
        for row in default_rows:
            owner_id = owner_by_surface_id.get(row["surface_id"])
            if owner_id is not None and owner_id != agent_id:
                errors.append(
                    f"{label}: default surface {row['surface_id']} is owned by "
                    f"AgentDefinition {owner_id}."
                )
    return errors


def _is_int(value) -> bool:
    """Return whether `value` is an integer and not a bool."""
    return type(value) is int


def _json_types_for(field: models.Field) -> tuple[type, ...] | None:
    """Return the JSON value types an export writes for `field`; None for any."""
    if isinstance(field, models.JSONField):
        return None
    if isinstance(field, models.BooleanField):
        return (bool,)
    if isinstance(field, models.FloatField):
        return (int, float)
    if isinstance(field, models.IntegerField):
        return (int,)
    if isinstance(field, models.CharField | models.TextField):
        return (str,)
    raise TypeError(f"No import type rule for {type(field).__name__} {field.name}.")


def _field_rules(model, field_names) -> dict[str, tuple[bool, tuple[type, ...] | None]]:
    """Map each field to (accepts None, accepted JSON types), built once at import."""
    rules = {}
    for field_name in field_names:
        field = model._meta.get_field(field_name)
        rules[field_name] = (field.null, _json_types_for(field))
    return rules


# Fields the reuse lookups compare, checked against the model field types. Built
# at module load, so a compared field without a type rule fails at startup.
# A python code entry must carry code and libraries; its other fields are
# optional, as the import serializer allows.
_TOOL_FIELD_RULES = {
    EntityType.PYTHON_CODE_TOOL: _field_rules(
        PythonCodeTool, ("name", *PYTHON_TOOL_COMPARED_FIELDS)
    ),
    EntityType.MCP_TOOL: _field_rules(McpTool, ("name", *MCP_COMPARED_FIELDS)),
}
_PYTHON_CODE_FIELD_RULES = _field_rules(
    PythonCode, ("code", "libraries", "entrypoint", "global_kwargs")
)
_REQUIRED_PYTHON_CODE_FIELDS = ("code", "libraries")


def _tool_entry_errors(export_data: dict) -> list[str]:
    """List the tool entries whose compared values the lookups cannot use.

    Values must have the JSON type an export writes for the model field: text
    for text fields, a number (not a bool) for numeric ones, a bool for boolean
    ones. Django would otherwise coerce them differently from the import
    serializer, or raise inside the lookup (a 500) for "yes" or "abc".
    """
    errors = []
    for entity_type, field_rules in _TOOL_FIELD_RULES.items():
        for entry in export_data.get(entity_type, []):
            if not isinstance(entry, dict):
                errors.append(f"{entity_type} entry is not an object.")
                continue
            label = f"{entity_type} {entry.get('id')}"
            errors.extend(_field_type_errors(label, field_rules, entry))
            if entity_type != EntityType.PYTHON_CODE_TOOL:
                continue
            python_code = entry.get("python_code")
            if not isinstance(python_code, dict):
                errors.append(f"{label}: python_code must be an object.")
                continue
            errors.extend(
                _field_type_errors(
                    f"{label} python_code",
                    _PYTHON_CODE_FIELD_RULES,
                    python_code,
                    required=_REQUIRED_PYTHON_CODE_FIELDS,
                )
            )
    return errors


def _field_type_errors(
    label: str, field_rules: dict, data: dict, required: tuple[str, ...] = ()
) -> list[str]:
    errors = []
    for field_name, (accepts_none, json_types) in field_rules.items():
        if field_name not in data:
            if field_name in required:
                errors.append(f"{label}: {field_name} is required.")
            continue
        value = data[field_name]
        if value is None:
            fits = accepts_none
        elif json_types is None:
            fits = True
        else:
            fits = isinstance(value, json_types) and (
                bool in json_types or not isinstance(value, bool)
            )
        if not fits:
            errors.append(f"{label}: {field_name} has the wrong type.")
    return errors
