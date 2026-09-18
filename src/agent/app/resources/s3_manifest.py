"""
Builds an informational manifest of the storage files/folders an agent may
access, rendered as a single ``ContextAttachment`` injected before the first
LLM call.

Each path line states both what is allowed ("may: ...") and what is denied
("may not: ...") for that path explicitly, so the model never has to infer
a denial from an unrelated example — leaving denials implicit previously
caused the model to over-generalise a single denial example to unrelated
paths and operations.

Permission verbs mean different things for a folder than for a file (e.g.
"edit" on a folder means creating new entries inside it, not overwriting an
existing one), so the legend renders a separate section per kind, each
listing only the verbs actually present among specs of that kind.

Pure function, no I/O, no S3 network calls — ``S3FileSpec.metadata`` is
whatever ``base_node_payload_service._build_s3_pool`` attached on the Django
side and must be read defensively since it crosses a service boundary.
"""

from __future__ import annotations

from shared.models.agent_service import ContextAttachment, S3FileSpec

_FLAG_ORDER = ("can_list", "can_view", "can_edit", "can_delete")

_FILE_OPERATION_DESCRIPTIONS = {
    "list": "list: see this file in directory listings",
    "view": "view: read the contents",
    "edit": "edit: modify or overwrite the contents",
    "delete": "delete: remove it permanently",
}

_FOLDER_OPERATION_DESCRIPTIONS = {
    "list": "list: enumerate the entries inside this folder",
    "view": "view: read the contents of entries inside it",
    "edit": (
        "edit: create new entries inside it (modifying an existing entry "
        "requires that entry's own edit permission)"
    ),
    "delete": "delete: remove the folder itself once empty",
}


def build_s3_manifest(specs: list[S3FileSpec]) -> ContextAttachment | None:
    """Render ``specs`` into one system ``ContextAttachment``, or ``None`` if empty."""
    if not specs:
        return None

    lines = [_render_line(spec) for spec in specs]
    legend_lines = _render_legend(specs)
    content = "\n".join(
        [
            "Files and folders you have access to:",
            *lines,
            "",
            *legend_lines,
            "You have no access to any other path in storage.",
        ]
    )

    return ContextAttachment(role="system", source="s3", content=content)


def _render_legend(specs: list[S3FileSpec]) -> list[str]:
    folder_operations, file_operations = _operations_present_by_kind(specs)

    if not folder_operations and not file_operations:
        return []

    lines = [
        (
            "What each permission means (each is granted independently — having "
            "one does NOT imply any other):"
        )
    ]

    if folder_operations:
        lines.append("Folders:")
        lines.extend(
            _render_legend_bullets(folder_operations, _FOLDER_OPERATION_DESCRIPTIONS)
        )

    if file_operations:
        if folder_operations:
            lines.append("")

        lines.append("Files:")
        lines.extend(
            _render_legend_bullets(file_operations, _FILE_OPERATION_DESCRIPTIONS)
        )

    lines.append("")
    lines.append(
        (
            "Each path above lists exactly what you may and may not do with "
            "it. Treat that per-path list as authoritative — do not "
            "generalise a restriction on one path to another path, or from "
            "one operation to another. If an operation is listed as allowed "
            "for a path, perform it with your tools when asked; do not "
            "refuse it or ask for confirmation first."
        )
    )
    lines.append("")

    return lines


def _render_legend_bullets(
    operations_present: set[str], descriptions: dict[str, str]
) -> list[str]:
    return [
        f"- {descriptions[operation]}"
        for operation in ("list", "view", "edit", "delete")
        if operation in operations_present
    ]


def _operations_present_by_kind(specs: list[S3FileSpec]) -> tuple[set[str], set[str]]:
    folder_operations: set[str] = set()
    file_operations: set[str] = set()

    for spec in specs:
        metadata = spec.metadata or {}
        flags = metadata.get("flags")

        if not isinstance(flags, dict):
            continue

        allowed_operations = {
            flag_name.removeprefix("can_")
            for flag_name in _FLAG_ORDER
            if flags.get(flag_name) == "allow"
        }

        if not allowed_operations:
            continue

        if _is_folder(spec):
            folder_operations |= allowed_operations
        else:
            file_operations |= allowed_operations

    return folder_operations, file_operations


def _is_folder(spec: S3FileSpec) -> bool:
    metadata = spec.metadata or {}
    item_type = metadata.get("item_type")

    if item_type == "folder":
        return True

    if item_type == "file":
        return False

    return spec.path.endswith("/")


def _render_line(spec: S3FileSpec) -> str:
    metadata = spec.metadata or {}
    descriptor = _render_descriptor(metadata)
    allowed_operations, denied_operations = _render_operations(metadata)

    line = f"- {spec.path}"

    if descriptor:
        line += f" ({descriptor})"

    if allowed_operations:
        line += f" — may: {', '.join(allowed_operations)}"

    if denied_operations:
        line += f" — may not: {', '.join(denied_operations)}"

    return line


def _render_descriptor(metadata: dict) -> str:
    item_type = metadata.get("item_type")

    if not item_type:
        return ""

    size = metadata.get("size")

    if item_type == "folder" or size is None:
        return item_type

    return f"{item_type}, {_format_size(size)}"


def _render_operations(metadata: dict) -> tuple[list[str], list[str]]:
    flags = metadata.get("flags")

    if not isinstance(flags, dict):
        return [], []

    allowed = []
    denied = []

    for flag_name in _FLAG_ORDER:
        operation = flag_name.removeprefix("can_")

        if flags.get(flag_name) == "allow":
            allowed.append(operation)
        else:
            denied.append(operation)

    return allowed, denied


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"

    if size_bytes < 1024 * 1024:
        return f"{_round(size_bytes / 1024)} KB"

    return f"{_round(size_bytes / (1024 * 1024))} MB"


def _round(value: float) -> str:
    rounded = round(value, 1)

    if rounded == int(rounded):
        return str(int(rounded))

    return str(rounded)
