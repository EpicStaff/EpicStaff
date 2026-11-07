from typing import ClassVar

__all__ = [
    "BadRequestError",
    "BaseError",
    "ConflictError",
    "CustomLibraryInUseError",
    "CustomLibraryNameNotFoundError",
    "CustomLibraryNameTakenError",
    "CustomLibraryNotFoundError",
    "CustomLibraryNotPublishedError",
    "CustomLibraryStillBuildingError",
    "NotFoundError",
    "UnsupportedUploadError",
    "WheelInUseError",
    "WheelNameMismatchError",
    "WheelNotBuiltError",
    "WheelNotFoundError",
    "WheelSourceAlreadyUploadedError",
    "WheelVersionTakenError",
]


class BaseError(Exception):
    """Base class for this service's errors.

    Every subclass sets ``code``, a stable snake_case name that stays the same across
    releases even when the wording of the message changes. For an error rendered to a
    client it is what the client branches on; for a venv build error, which never
    reaches a client, it is the kind stored on the failed venv. The subclasses live
    with the contract they belong to: the domain's own rules here, under the group
    that sets their HTTP status; the application's refusals; and the application's
    ports.
    """

    code: ClassVar[str]
    default_message: str = ""

    def __init__(self, message: str = "", *args, **format_kwargs) -> None:
        if not message and self.default_message:
            message = self.default_message.format(**format_kwargs)
        super().__init__(message, *args)


class NotFoundError(BaseError):
    """The addressed resource does not exist. Rendered as 404."""

    code = "not_found"


class ConflictError(BaseError):
    """The request clashes with what is already stored. Rendered as 409."""

    code = "conflict"


class BadRequestError(BaseError):
    """The request itself is wrong, whatever is stored. Rendered as 400.

    For what the schemas cannot check on their own: a rule that needs the stored
    state, such as an uploaded wheel belonging to a different library.
    """

    code = "bad_request"


class CustomLibraryNotFoundError(NotFoundError):
    code = "custom_library_not_found"
    default_message: str = "CustomLibrary(id={custom_library_id}) not found."


class CustomLibraryNameNotFoundError(NotFoundError):
    """Addressed by name rather than by id: a venv names its libraries, it does not
    hold their ids."""

    code = "custom_library_name_not_found"
    default_message: str = "Custom library '{name}' is not stored here."


class CustomLibraryNotPublishedError(BaseError):
    code = "custom_library_not_published"
    default_message: str = (
        "Custom library '{name}' has no built version yet. Upload a wheel, or a source "
        "archive that builds into one, before a virtual environment can install it."
    )


class CustomLibraryStillBuildingError(BaseError):
    """A version the venv needs is on its way.

    Never reaches a client: the build catches it and leaves the venv waiting rather
    than failing it, because nothing is wrong and the next tick may succeed.
    """

    code = "custom_library_still_building"
    default_message: str = "Custom library '{name}' is still being built."


class WheelNotFoundError(NotFoundError):
    code = "wheel_not_found"
    default_message: str = "Wheel(id={wheel_id}) not found."


class CustomLibraryNameTakenError(ConflictError):
    code = "custom_library_name_taken"
    default_message: str = "CustomLibrary(name='{name}') already exists."


class WheelVersionTakenError(ConflictError):
    code = "wheel_version_taken"
    default_message: str = (
        "CustomLibrary(id={custom_library_id}) already has version '{version}'. "
        "A version is published once; delete the existing wheel to replace it, which "
        "is only possible while no virtual environment has that version installed."
    )


class WheelSourceAlreadyUploadedError(ConflictError):
    code = "wheel_source_already_uploaded"
    default_message: str = (
        "This exact file was already uploaded to CustomLibrary(id={custom_library_id}) "
        "as Wheel(id={wheel_id})."
    )


class CustomLibraryInUseError(ConflictError):
    code = "custom_library_in_use"
    default_message: str = (
        "CustomLibrary(id={custom_library_id}) is used by {venv_count} virtual "
        "environment(s). Remove it from them before deleting it."
    )


class WheelInUseError(ConflictError):
    code = "wheel_in_use"
    default_message: str = (
        "Version '{version}' of CustomLibrary(id={custom_library_id}) is installed in "
        "{venv_count} virtual environment(s). Remove it from them before deleting it."
    )


class WheelNotBuiltError(ConflictError):
    code = "wheel_not_built"
    default_message: str = "Wheel(id={wheel_id}) has no wheel file: its status is '{status}'."


class UnsupportedUploadError(BadRequestError):
    code = "unsupported_upload"
    default_message: str = (
        "'{filename}' is neither a wheel (.whl) nor a source archive (.tar.gz, .tgz, .zip)."
    )


class WheelNameMismatchError(BadRequestError):
    code = "wheel_name_mismatch"
    default_message: str = (
        "CustomLibrary(id={custom_library_id}) is '{library_name}', but this is a "
        "distribution named '{wheel_name}'."
    )
