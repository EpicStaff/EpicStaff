from typing import ClassVar

__all__ = ["BaseError"]


class BaseError(Exception):
    """Base class for this service's errors.

    Every subclass sets ``code``, a stable snake_case name that stays the same across
    releases even when the wording of the message changes. For an error rendered to a
    client it is what the client branches on; for a venv build error, which never
    reaches a client, it is the kind stored on the failed venv. The subclasses live
    with the contract they belong to: the application, and the application's ports.
    """

    code: ClassVar[str]
    default_message: str = ""

    def __init__(self, message: str = "", *args, **format_kwargs) -> None:
        if not message and self.default_message:
            message = self.default_message.format(**format_kwargs)
        super().__init__(message, *args)
