import re

from rest_framework import serializers

# Mirrors the MCP description sanitization in
# src/agent/app/tools/mcp/gateway.py (_C0_CONTROL_CHARS_RE / _MAX_MCP_DESCRIPTION_CHARS).
# Kept in sync by convention rather than a shared import: django_app and the
# agent service are deployed independently and do not share a dependency tree.
# The result is also trimmed: it is stored, and the serializer field trims what an
# import reads, so an untrimmed stored value would never match its own export again.
MAX_DESCRIPTION_CHARS = 1024
_C0_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_description(description: str) -> str:
    """Strip C0 control characters, cap length and trim a user-authored tool description.

    `PythonCodeTool.description` reaches the LLM tool schema verbatim, so a
    user can smuggle prompt-injection payloads (e.g. escape sequences) into
    it with no external content required. Apply it on every write of a
    user-authored description. Built-in tools loaded by the upload_tools command
    are repository content and are stored as written, so a built-in description
    can exceed the cap.
    """
    cleaned = _C0_CONTROL_CHARS_RE.sub("", description)
    return cleaned[:MAX_DESCRIPTION_CHARS].strip()


def validate_tool_description(description: str) -> str:
    """Return the description sanitized for storage, rejecting one that is left without visible text.

    The field's own blank check runs before this and does not count control
    characters as blank, so a description made only of them would otherwise be
    stored as "", which a later import of the tool rejects.
    """
    cleaned = sanitize_description(description)
    if not cleaned:
        raise serializers.ValidationError("Description must contain visible text.")
    return cleaned
