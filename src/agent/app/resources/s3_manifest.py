"""
Builds an informational manifest of the storage files/folders an agent may
access, rendered as a single ``ContextAttachment`` injected before the first
LLM call.

Pure function, no I/O, no S3 network calls — ``S3FileSpec.metadata`` is
whatever ``base_node_payload_service._build_s3_pool`` attached on the Django
side and must be read defensively since it crosses a service boundary.
"""

from __future__ import annotations

from shared.models.agent_service import ContextAttachment, S3FileSpec

_FLAG_ORDER = ("can_list", "can_view", "can_edit", "can_delete")

_OPERATION_DESCRIPTIONS = {
    "list": "list: enumerate the entries inside this folder",
    "view": "view: read the contents",
    "edit": "edit: modify or overwrite the contents",
    "delete": "delete: remove it permanently",
}


def build_s3_manifest(
    specs: list[S3FileSpec], scratch_path: str | None = None
) -> ContextAttachment | None:
    """Render ``specs`` and an optional ``scratch_path`` into one system
    ``ContextAttachment``, or ``None`` if there is nothing to grant."""
    if not specs and scratch_path is None:
        return None

    lines = [_render_line(spec) for spec in specs]

    if scratch_path is not None:
        lines.append(_render_scratch_line(scratch_path))

    legend_lines = _render_legend(specs, scratch_path)
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


def _render_scratch_line(scratch_path: str) -> str:
    return (
        f"You may create and manage your own files under: {scratch_path} "
        "— you have full access there (list, view, edit, delete)."
    )


def _render_legend(
    specs: list[S3FileSpec], scratch_path: str | None = None
) -> list[str]:
    operations_present = _operations_present_across(specs)

    if scratch_path is not None:
        operations_present |= {"list", "view", "edit", "delete"}

    if not operations_present:
        return []

    bullets = [
        f"- {_OPERATION_DESCRIPTIONS[operation]}"
        for operation in ("list", "view", "edit", "delete")
        if operation in operations_present
    ]

    return [
        (
            "What each permission means (each is granted independently — having "
            "one does NOT imply any other):"
        ),
        *bullets,
        "",
        (
            "Any operation not listed for a path is forbidden — in particular, "
            "being able to edit a file does not let you delete it."
        ),
        "",
    ]


def _operations_present_across(specs: list[S3FileSpec]) -> set[str]:
    operations_present: set[str] = set()

    for spec in specs:
        metadata = spec.metadata or {}
        flags = metadata.get("flags")

        if not isinstance(flags, dict):
            continue

        for flag_name in _FLAG_ORDER:
            if flags.get(flag_name) == "allow":
                operations_present.add(flag_name.removeprefix("can_"))

    return operations_present


def _render_line(spec: S3FileSpec) -> str:
    metadata = spec.metadata or {}
    descriptor = _render_descriptor(metadata)
    operations = _render_operations(metadata)

    line = f"- {spec.path}"

    if descriptor:
        line += f" ({descriptor})"

    if operations:
        line += f" — may: {operations}"

    return line


def _render_descriptor(metadata: dict) -> str:
    item_type = metadata.get("item_type")

    if not item_type:
        return ""

    size = metadata.get("size")

    if item_type == "folder" or size is None:
        return item_type

    return f"{item_type}, {_format_size(size)}"


def _render_operations(metadata: dict) -> str:
    flags = metadata.get("flags")

    if not isinstance(flags, dict):
        return ""

    allowed = [
        flag_name.removeprefix("can_")
        for flag_name in _FLAG_ORDER
        if flags.get(flag_name) == "allow"
    ]

    return ", ".join(allowed)


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
