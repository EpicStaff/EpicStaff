"""The boundary step both import services run before they write anything."""

from copy import deepcopy

from agents.models import SurfacePlace, ToolMode
from loguru import logger
from rest_framework.exceptions import ValidationError

from tables.import_export.enums import EntityType
from tables.import_export.serializers.agent_definition import AgentDefinitionImportSerializer
from tables.import_export.serializers.mcp_tools import McpToolImportSerializer
from tables.import_export.serializers.python_tools import (
    PythonCodeImportSerializer,
    PythonCodeToolImportSerializer,
)
from tables.import_export.serializers.surface import SurfaceImportSerializer
from tables.import_export.strategies.agent_definition import (
    COMPARED_FIELDS as AGENT_COMPARED_FIELDS,
)
from tables.import_export.strategies.agent_definition import normalize_legacy_agent_entry
from tables.import_export.strategies.mcp_tools import COMPARED_FIELDS as MCP_COMPARED_FIELDS
from tables.import_export.strategies.python_tools import (
    COMPARED_FIELDS as PYTHON_TOOL_COMPARED_FIELDS,
)
from tables.import_export.utils import import_values, nest_owned_surface_entries


def prepare_import_data(export_data: dict) -> dict:
    """Validate an import bundle and return it ready for the import services.

    The one boundary step ImportService and PartialImportService share, run
    before their transaction opens, so a rejected file writes nothing.

    An agent that borrows another agent's owned surface is given its own copy
    first (see `_copy_borrowed_owned_surfaces`). The input is not modified.

    Raises:
        ValidationError: A Surface, tool or AgentDefinition entry is malformed,
            or AgentDefinition ids repeat.
    """
    errors = [
        *_lookup_value_errors(export_data),
        *_surface_tool_errors(export_data),
        *_agent_surface_errors(export_data),
    ]
    if errors:
        raise ValidationError({"detail": errors})
    return nest_owned_surface_entries(_copy_borrowed_owned_surfaces(export_data))


def _surface_tool_errors(export_data: dict) -> list[str]:
    """List the Surface entries whose tool lists the import cannot store.

    No serializer covers them: tool rows are bulk-created without model
    validation, so a mode outside ToolMode would be stored (or fail as a 500),
    and a tool listed twice would give the lookup two (id, mode) pairs against
    the one row stored -- never matching again.
    """
    tool_id_fields = {
        EntityType.PYTHON_CODE_TOOL: "python_tool_id",
        EntityType.MCP_TOOL: "mcp_tool_id",
    }
    errors = []
    for entry in export_data.get(EntityType.SURFACE, []):
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")
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


def _agent_surface_errors(export_data: dict) -> list[str]:
    """List the AgentDefinition entries the import cannot place surfaces for.

    An export always writes `owned_surfaces` and `default_surfaces` as lists and
    llm configs as ids; a null list or a malformed value would fail mid-import
    as a 500.
    """
    errors = []
    for entry in export_data.get(EntityType.AGENT_DEFINITION, []):
        agent_id = entry.get("id") if isinstance(entry, dict) else None
        if not _is_int(agent_id):
            continue
        label = f"AgentDefinition {agent_id}"
        for llm_config_field in ("llm_config", "fcm_llm_config"):
            llm_config_id = entry.get(llm_config_field)
            if llm_config_id is not None and not _is_int(llm_config_id):
                errors.append(f"{label}: {llm_config_field} must be an integer id or null.")

        owned_surface_ids = entry.get("owned_surfaces", [])
        if not isinstance(owned_surface_ids, list) or not all(
            _is_int(surface_id) for surface_id in owned_surface_ids
        ):
            errors.append(f"{label}: owned_surfaces must be a list of integer ids.")

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
    return errors


def _surface_owner_ids(agent_entries: list[dict]) -> dict[int, int]:
    """Map each owned surface id to its owner's id.

    A surface listed by several agents belongs to the first, as in
    nest_owned_surface_entries.
    """
    owner_by_surface_id = {}
    for agent_entry in agent_entries:
        for surface_id in agent_entry.get("owned_surfaces", []):
            owner_by_surface_id.setdefault(surface_id, agent_entry["id"])
    return owner_by_surface_id


def _copy_borrowed_owned_surfaces(export_data: dict) -> dict:
    """Return the bundle with every borrowed owned surface replaced by the borrower's copy.

    A surface owned by agent A is borrowed when the file points at it on behalf
    of another agent B: a row of B's `default_surfaces`, or the `surface_list` of
    an AgentNode or TaskNode whose `agent_definition` is B. The agents API
    rejects that state, and an owned surface is deleted together with its
    owner. Release 1.3.2 nonetheless wrote it when it re-imported an agent that
    owns surfaces as a renamed copy, so exports of those databases carry it.

    B gets its own copy of the Surface entry, owned by B, under an id no
    surface reference in the file uses -- one copy per (B, surface) pair, shared
    by all of B's references. That matches what an import creates for an agent
    otherwise: its owned surfaces are always fresh rows of its own. A surface
    with no Surface entry in the file is left alone. Expects the AgentDefinition
    and Surface entries to be well-formed.

    Returns:
        `export_data` itself when nothing is borrowed, otherwise a repaired copy.
    """
    agent_entries = export_data.get(EntityType.AGENT_DEFINITION, [])
    owner_by_surface_id = _surface_owner_ids(agent_entries)
    surface_entry_by_id = {entry["id"]: entry for entry in export_data.get(EntityType.SURFACE, [])}

    def is_borrowed(borrower_id: int, surface_id: object) -> bool:
        owner_id = owner_by_surface_id.get(surface_id) if _is_int(surface_id) else None
        return (
            owner_id is not None and owner_id != borrower_id and surface_id in surface_entry_by_id
        )

    agent_ids = {agent_entry["id"] for agent_entry in agent_entries}
    referenced_surface_ids = set()
    borrows = set()
    for agent_entry in agent_entries:
        for row in agent_entry.get("default_surfaces", []):
            referenced_surface_ids.add(row["surface_id"])
            if is_borrowed(agent_entry["id"], row["surface_id"]):
                borrows.add((agent_entry["id"], row["surface_id"]))
    for node_entry in _surface_listing_node_entries(export_data):
        borrower_id = node_entry.get("agent_definition")
        for surface_id in node_entry["surface_list"]:
            if _is_int(surface_id):
                referenced_surface_ids.add(surface_id)
            if (
                _is_int(borrower_id)
                and borrower_id in agent_ids
                and is_borrowed(borrower_id, surface_id)
            ):
                borrows.add((borrower_id, surface_id))
    if not borrows:
        return export_data

    repaired_data = deepcopy(export_data)
    repaired_agent_by_id = {
        agent_entry["id"]: agent_entry for agent_entry in repaired_data[EntityType.AGENT_DEFINITION]
    }
    last_used_surface_id = max(
        {*surface_entry_by_id, *owner_by_surface_id, *referenced_surface_ids}
    )
    copy_id_by_borrow = {}
    for borrower_id, surface_id in sorted(borrows):
        last_used_surface_id += 1
        copy_id_by_borrow[(borrower_id, surface_id)] = last_used_surface_id
        repaired_data[EntityType.SURFACE].append(
            {**deepcopy(surface_entry_by_id[surface_id]), "id": last_used_surface_id}
        )
        borrower = repaired_agent_by_id[borrower_id]
        borrower["owned_surfaces"] = [*borrower.get("owned_surfaces", []), last_used_surface_id]
        logger.warning(
            "Import: AgentDefinition {} uses surface {}, which AgentDefinition {} owns; "
            "it gets its own copy as surface {}.",
            borrower_id,
            surface_id,
            owner_by_surface_id[surface_id],
            last_used_surface_id,
        )

    for agent_entry in repaired_data[EntityType.AGENT_DEFINITION]:
        for row in agent_entry.get("default_surfaces", []):
            row["surface_id"] = copy_id_by_borrow.get(
                (agent_entry["id"], row["surface_id"]), row["surface_id"]
            )
    for node_entry in _surface_listing_node_entries(repaired_data):
        borrower_id = node_entry.get("agent_definition")
        if not _is_int(borrower_id):
            continue
        node_entry["surface_list"] = [
            copy_id_by_borrow.get((borrower_id, surface_id), surface_id)
            if _is_int(surface_id)
            else surface_id
            for surface_id in node_entry["surface_list"]
        ]
    return repaired_data


_SURFACE_LISTING_NODE_TYPES = (EntityType.AGENT_NODE, EntityType.TASK_NODE)


def _surface_listing_node_entries(export_data: dict) -> list[dict]:
    """Return the bundle's AgentNode and TaskNode entries that list surfaces.

    Full exports nest nodes in each Flow entry, tagged by `node_type`; partial
    bundles list them top-level by entity type. Node entries are not validated
    before import, so malformed ones are skipped here and left to the node
    strategies.
    """
    node_entries = [
        node_entry
        for flow_entry in export_data.get(EntityType.GRAPH, [])
        if isinstance(flow_entry, dict) and isinstance(flow_entry.get("nodes"), list)
        for node_entry in flow_entry["nodes"]
        if isinstance(node_entry, dict)
        and node_entry.get("node_type") in _SURFACE_LISTING_NODE_TYPES
    ]
    for node_type in _SURFACE_LISTING_NODE_TYPES:
        top_level_entries = export_data.get(node_type, [])
        if isinstance(top_level_entries, list):
            node_entries.extend(top_level_entries)
    return [
        node_entry
        for node_entry in node_entries
        if isinstance(node_entry, dict) and isinstance(node_entry.get("surface_list"), list)
    ]


def _is_int(value) -> bool:
    """Return whether `value` is an integer and not a bool."""
    return type(value) is int


# The values each reuse lookup compares, validated by the strategy's import
# serializer: the lookup compares them as create_entity would store them, so a
# value the serializer rejects is a 400 here rather than a failure mid-import.
_LOOKUP_FIELDS = {
    EntityType.PYTHON_CODE_TOOL: (
        PythonCodeToolImportSerializer,
        ("name", *PYTHON_TOOL_COMPARED_FIELDS),
    ),
    EntityType.MCP_TOOL: (McpToolImportSerializer, ("name", *MCP_COMPARED_FIELDS)),
    EntityType.SURFACE: (SurfaceImportSerializer, ("name", "instructions")),
    EntityType.AGENT_DEFINITION: (
        AgentDefinitionImportSerializer,
        ("name", *AGENT_COMPARED_FIELDS),
    ),
}


def _lookup_value_errors(export_data: dict) -> list[str]:
    """List malformed entries: not an object, no integer id, or a rejected value.

    A rejected value is one the entity's import serializer refuses for a field
    the reuse lookup compares.
    """
    errors = []
    for entity_type, (serializer_class, field_names) in _LOOKUP_FIELDS.items():
        for entry in export_data.get(entity_type, []):
            if not isinstance(entry, dict):
                errors.append(f"{entity_type} entry is not an object.")
                continue
            label = f"{entity_type} {entry.get('id')}"
            if not _is_int(entry.get("id")):
                errors.append(f"{label}: id must be an integer.")
            looked_up_entry = entry
            if entity_type == EntityType.AGENT_DEFINITION:
                # Older exports carry nulls and out-of-range limits that the
                # strategy normalises before its lookup and create.
                looked_up_entry = deepcopy(entry)
                normalize_legacy_agent_entry(looked_up_entry)
            try:
                import_values(serializer_class, looked_up_entry, field_names)
            except ValidationError as error:
                errors.append(f"{label}: {_field_messages(error.detail)}")
            if entity_type == EntityType.PYTHON_CODE_TOOL:
                python_code = PythonCodeImportSerializer(data=entry.get("python_code"))
                if not python_code.is_valid():
                    errors.append(f"{label} python_code: {_field_messages(python_code.errors)}")
    return errors


def _field_messages(errors_by_field: dict) -> str:
    return "; ".join(
        f"{field_name}: {' '.join(str(message) for message in messages)}"
        for field_name, messages in errors_by_field.items()
    )
