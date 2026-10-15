from enum import StrEnum


class RecycleBinSource(StrEnum):
    """A recycle bin, one per tab: every key of `bin_resources()`, plus storage.

    The values are API strings (the empty endpoint's `source`, the frontend's
    RecycleBinSourceKey), so they never change.
    """

    FLOW = "flow"
    AGENT = "agent"
    SURFACE = "surface"
    PYTHON_TOOL = "python_tool"
    MCP_TOOL = "mcp_tool"
    STORAGE = "storage"
    COLLECTION = "collection"
    KEY_VALUE_TABLE = "key_value_table"
    SECRET = "secret"
    REALTIME_CHANNEL = "realtime_channel"
    WEBHOOK_TRIGGER = "webhook_trigger"
