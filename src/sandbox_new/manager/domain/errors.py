__all__ = [
    "BadRequestError",
    "ConflictError",
    "CustomLibraryInUseError",
    "CustomLibraryNameNotFoundError",
    "CustomLibraryNameTakenError",
    "CustomLibraryNotFoundError",
    "CustomLibraryNotPublishedError",
    "CustomLibraryStillBuildingError",
    "ExecutionNotFoundError",
    "NotFoundError",
    "SandboxOverloadedError",
    "SecretNotDecryptableError",
    "UVBuildError",
    "UVDependencyResolutionError",
    "UVPackageNotFoundError",
    "UVVersionNotFoundError",
    "UnsupportedUploadError",
    "VenvNotFoundError",
    "WheelInUseError",
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


class CustomLibraryNameNotFoundError(NotFoundError):
    """Addressed by name rather than by id: a venv names its libraries, it does not
    hold their ids."""

    default_message: str = "Custom library '{name}' is not stored here."


class CustomLibraryNotPublishedError(BaseError):
    default_message: str = (
        "Custom library '{name}' has no built version yet. Upload a wheel, or a source "
        "archive that builds into one, before a virtual environment can install it."
    )


class CustomLibraryStillBuildingError(BaseError):
    """A version the venv needs is on its way.

    Never reaches a client: the build catches it and leaves the venv waiting rather
    than failing it, because nothing is wrong and the next tick may succeed.
    """

    default_message: str = "Custom library '{name}' is still being built."


class WheelNotFoundError(NotFoundError):
    default_message: str = "Wheel(id={wheel_id}) not found."


class CustomLibraryNameTakenError(ConflictError):
    default_message: str = "CustomLibrary(name='{name}') already exists."


class WheelVersionTakenError(ConflictError):
    default_message: str = (
        "CustomLibrary(id={custom_library_id}) already has version '{version}'. "
        "A version is published once; delete the existing wheel to replace it, which "
        "is only possible while no virtual environment has that version installed."
    )


class WheelSourceAlreadyUploadedError(ConflictError):
    default_message: str = (
        "This exact file was already uploaded to CustomLibrary(id={custom_library_id}) "
        "as Wheel(id={wheel_id})."
    )


class CustomLibraryInUseError(ConflictError):
    default_message: str = (
        "CustomLibrary(id={custom_library_id}) is used by {venv_count} virtual "
        "environment(s). Remove it from them before deleting it."
    )


class WheelInUseError(ConflictError):
    default_message: str = (
        "Version '{version}' of CustomLibrary(id={custom_library_id}) is installed in "
        "{venv_count} virtual environment(s). Remove it from them before deleting it."
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


class SecretNotDecryptableError(BadRequestError):
    """A submitted secret is not a value this sandbox's transport key opens.

    Names the secret only: its value, sealed or not, never goes into the message.
    """

    default_message: str = "Secret '{name}' could not be decrypted; the job was not run."


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


class ExecutionNotFoundError(BaseError):
    default_message: str = "Execution(id={execution_id}) not found."

    def __init__(self, execution_id: str) -> None:
        super().__init__(execution_id=execution_id)


class SandboxOverloadedError(BaseError):
    """The sandbox cannot take another execution now.

    Args:
        retry_after: Seconds the caller should wait before re-posting.
    """

    default_message: str = "The sandbox is full; retry later."

    def __init__(self, *, retry_after: int) -> None:
        super().__init__()
        self.retry_after = retry_after
