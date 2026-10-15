__all__ = [
    "UVBuildError",
    "UVDependencyResolutionError",
    "UVPackageNotFoundError",
    "UVVersionNotFoundError",
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


class UVBuildError(BaseError):
    default_message: str = (
        "Could not build the environment. Check the library names and version specifications."
    )


class UVPackageNotFoundError(BaseError):
    default_message: str = "Package '{package}' does not exist."


class UVVersionNotFoundError(BaseError):
    default_message: str = "Package '{package}' has no version matching '{specification}'."


class UVDependencyResolutionError(BaseError):
    default_message: str = (
        "Package '{package}' requires versions of its dependencies "
        "that conflict with the other requested packages."
    )
