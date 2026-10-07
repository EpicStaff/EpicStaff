__all__ = [
    "VenvNotFoundError",
]


class BaseError(Exception):
    """Base class for domain errors"""

    default_message: str = ""

    def __init__(self, message: str = "", *args, **format_kwargs) -> None:
        if not message and self.default_message:
            message = self.default_message.format(**format_kwargs)
        super().__init__(message, *args)


class VenvNotFoundError(BaseError):
    default_message: str = "Venv(id={venv_id}) not found."
