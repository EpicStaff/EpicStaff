__all__ = [
    "BadRequestError",
    "ConflictError",
    "CustomLibraryNameTakenError",
    "CustomLibraryNotFoundError",
    "NotFoundError",
    "UVBuildError",
    "UVDependencyResolutionError",
    "UVPackageNotFoundError",
    "UVVersionNotFoundError",
    "UnsupportedUploadError",
    "VenvNotFoundError",
    "WheelNameMismatchError",
    "WheelNotBuiltError",
    "WheelNotFoundError",
    "WheelSourceAlreadyUploadedError",
    "WheelVersionTakenError",
]


class BaseError(Exception):
    """Base class for domain errors"""

    default_message: str = ""

    def __init__(self, message: str = "", *args, **format_kwargs) -> None:
        if not message and self.default_message:
            message = self.default_message.format(**format_kwargs)
        super().__init__(message, *args)


class NotFoundError(BaseError):
    """The addressed resource does not exist. Rendered as 404."""


class ConflictError(BaseError):
    """The request clashes with what is already stored. Rendered as 409."""


class BadRequestError(BaseError):
    """The request itself is wrong, whatever is stored. Rendered as 400.

    For what the schemas cannot check on their own: a rule that needs the stored
    state, such as an uploaded wheel belonging to a different library.
    """


class VenvNotFoundError(NotFoundError):
    default_message: str = "Venv(id={venv_id}) not found."


class CustomLibraryNotFoundError(NotFoundError):
    default_message: str = "CustomLibrary(id={custom_library_id}) not found."


class WheelNotFoundError(NotFoundError):
    default_message: str = "Wheel(id={wheel_id}) not found."


class CustomLibraryNameTakenError(ConflictError):
    default_message: str = "CustomLibrary(name='{name}') already exists."


class WheelVersionTakenError(ConflictError):
    default_message: str = (
        "CustomLibrary(id={custom_library_id}) already has version '{version}'. "
        "A version is published once; delete the existing wheel to replace it."
    )


class WheelSourceAlreadyUploadedError(ConflictError):
    default_message: str = (
        "This exact file was already uploaded to CustomLibrary(id={custom_library_id}) "
        "as Wheel(id={wheel_id})."
    )


class WheelNotBuiltError(ConflictError):
    default_message: str = "Wheel(id={wheel_id}) has no wheel file: its status is '{status}'."


class UnsupportedUploadError(BadRequestError):
    default_message: str = (
        "'{filename}' is neither a wheel (.whl) nor a source archive (.tar.gz, .tgz, .zip)."
    )


class WheelNameMismatchError(BadRequestError):
    default_message: str = (
        "CustomLibrary(id={custom_library_id}) is '{library_name}', but this is a "
        "distribution named '{wheel_name}'."
    )


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
