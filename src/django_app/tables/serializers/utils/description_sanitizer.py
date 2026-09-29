import re

# Mirrors the MCP description sanitization in
# src/agent/app/tools/mcp/gateway.py (_C0_CONTROL_CHARS_RE / _MAX_MCP_DESCRIPTION_CHARS).
# Kept in sync by convention rather than a shared import: django_app and the
# agent service are deployed independently and do not share a dependency tree.
MAX_DESCRIPTION_CHARS = 1024
_C0_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_description(description: str) -> str:
    """Strip C0 control characters and cap length on a user-authored tool description.

    `PythonCodeTool.description` reaches the LLM tool schema verbatim, so a
    user can smuggle prompt-injection payloads (e.g. escape sequences) into
    it with no external content required. Applied on write so every persisted
    description is already clean.
    """
    cleaned = _C0_CONTROL_CHARS_RE.sub("", description)
    return cleaned[:MAX_DESCRIPTION_CHARS]
