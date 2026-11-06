from enum import StrEnum

__all__ = ["ExecutionStatus", "JobStatus", "VenvBuildErrorKind", "VenvOrder", "VenvStatus"]


class VenvStatus(StrEnum):
    DECLARED = "declared"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class VenvBuildErrorKind(StrEnum):
    """Why a venv build failed.

    The values are the codes of the build errors the venv build port raises, so the
    stored kind and the error code are one vocabulary.

    NOTE: The user-facing kinds are listed twice: in `_DECLARED_PACKAGE_ERROR_KINDS`
    (`manager.application.orchestrators`), which decides whose text is stored, and in
    `_USER_FACING_BUILD_ERROR_KINDS` (`manager.domain.models`), which decides whose text
    is shown. A new kind must be added to both.
    """

    PACKAGE_NOT_FOUND = "package_not_found"
    PACKAGE_VERSION_NOT_FOUND = "package_version_not_found"
    PACKAGE_DEPENDENCY_CONFLICT = "package_dependency_conflict"
    # Any other failure, including one whose cause was not recognised.
    PACKAGE_INSTALL_FAILED = "package_install_failed"


class VenvOrder(StrEnum):
    DEFAULT = "default"
    NAME_ASC = "name_asc"
    NAME_DESC = "name_desc"


class JobStatus(StrEnum):
    ACCEPTED = "accepted"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionStatus(StrEnum):
    """Where an accepted execution is, as the status endpoint reports it."""

    # Waiting for its venv to finish building; no queue deadline runs yet, only the hold
    # deadline after which it is failed without running.
    HELD = "held"
    # Handed to the worker queue, waiting for a slot or running.
    QUEUED = "queued"
    # Its result was handed to the publisher.
    DONE = "done"
