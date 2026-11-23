# Codes of the error item a session streams on an error card or stores in its status. They
# are a contract with every reader of a session's errors: never rename one, add a new one.
NODE_FAILED_CODE = "node_failed"
SUBFLOW_FAILED_CODE = "subflow_failed"
FLOW_FAILED_CODE = "flow_failed"


class ReturnCodeError(Exception):
    code = "python_code_failed"


class KnowledgeSearchError(Exception):
    code = "knowledge_search_failed"


class KeyValueNodeError(Exception):
    code = "key_value_failed"


class NodeConfigurationError(Exception):
    """A node can't run with the settings the flow author gave it.

    The message names only the node and the missing or wrong setting, so it is safe to
    show to the user.
    """

    code = "node_not_configured"


class InvalidStatePathError(Exception):
    """A flow state path the flow author wrote cannot be read or written.

    The message names only the author's own path, so it is safe to show to the user.
    """

    code = "invalid_state_path"


class StopSession(Exception):  # noqa: N818
    code = "session_stopped"

    def __init__(self, *args, status: str | None = None, reason: str | None = None):
        self.status = status
        # Optional human-readable reason surfaced via Session.status_data.
        # None for the existing manual-stop/timeout paths, so their
        # behavior is unchanged.
        self.reason = reason

        super().__init__(*args)
