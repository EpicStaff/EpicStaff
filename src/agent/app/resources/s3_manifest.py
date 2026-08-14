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


def build_s3_manifest(specs: list[S3FileSpec]) -> ContextAttachment | None:
    """Render ``specs`` into one system ``ContextAttachment``, or ``None`` if empty."""
    if not specs:
        return None

    lines = [_render_line(spec) for spec in specs]
    content = "\n".join(
        [
            "Files and folders you have access to:",
            *lines,
            "",
            "You have no access to any other path in storage.",
        ]
    )

    return ContextAttachment(role="system", source="s3", content=content)


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
