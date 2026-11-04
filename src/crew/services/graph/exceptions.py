class PublicNodeError(Exception):
    """A node failure whose message is written for the user, so it is shown as it is.

    The message is crew's own text about the node's configuration or the flow state, a
    message another service wrote for the user (Django's 400/404/409 Key-Value messages), or
    the stderr of the user's own code. Raw failure text of a service is never in it: such a
    failure is logged under `correlation_id` and the message cites that reference.
    """

    def __init__(self, message: str, *, correlation_id: str | None = None):
        super().__init__(message)
        self.correlation_id = correlation_id


class ReturnCodeError(PublicNodeError):
    """The user's code failed or timed out; the message is its stderr or the timeout text.

    A sandbox that couldn't run the code at all is a `CodeExecutionUnavailableError`.
    """


class CodeExecutionUnavailableError(PublicNodeError):
    """The sandbox couldn't run a node's code; the raw cause is logged under `correlation_id`."""


class KnowledgeSearchError(PublicNodeError): ...


class EmptyKnowledgeQueryError(PublicNodeError): ...


class KeyValueNodeError(PublicNodeError): ...


class OutputPathError(PublicNodeError):
    """A code node's result couldn't be stored at its output variable path."""


class NodeFileError(PublicNodeError):
    """A File Extractor or Audio to text node couldn't use one of its files."""


class TelegramFieldError(PublicNodeError):
    """A Telegram Trigger field couldn't be read from the update or stored."""


class SubflowPathError(PublicNodeError):
    """A Subflow node's input path isn't a flow variable, or its output path doesn't exist."""


class NodeExecutionError(Exception):
    """A node failed and has already shown the user an error message.

    Raised by `BaseNode.run` in place of the node's own error, which is kept as
    `__cause__`. It carries what the user was told, so the failed session repeats it
    instead of reporting the failure under a second reference.
    """

    def __init__(self, public_message: str, *, correlation_id: str | None = None):
        super().__init__(public_message)
        self.public_message = public_message
        self.correlation_id = correlation_id


class StopSession(Exception):  # noqa: N818
    def __init__(
        self,
        *args,
        status: str | None = None,
        reason: str | None = None,
        public_message: str | None = None,
    ):
        self.status = status
        # Optional reason surfaced via Session.status_data and the session audit.
        # None for the manual-stop/timeout paths.
        self.reason = reason
        # Shown to the user as the session's `status_data.error`; None for a manual stop.
        self.public_message = public_message

        super().__init__(*args)
