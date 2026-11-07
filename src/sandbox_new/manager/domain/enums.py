from enum import StrEnum

__all__ = [
    "ExecutionStatus",
    "JobStatus",
    "VenvBuildErrorKind",
    "VenvOrder",
    "VenvStatus",
    "WheelOffer",
    "WheelStatus",
]


class VenvStatus(StrEnum):
    DECLARED = "declared"
    WAITING = "waiting"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class VenvBuildErrorKind(StrEnum):
    """Why a venv build failed.

    The values are the codes of the build errors the venv build port raises. A custom
    library refused before the build starts is stored under one of them too: one that
    isn't stored as `package_not_found`, one with nothing built as
    `package_version_not_found`. A failed job reports the kind as its failure's code.

    The text stored with every kind but ``PACKAGE_INSTALL_FAILED`` names only what the
    user declared, so it is shown to them; a new kind must keep to that, or the build
    port error that has it must use ``PACKAGE_INSTALL_FAILED``.
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


class WheelStatus(StrEnum):
    DECLARED = "declared"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class WheelOffer(StrEnum):
    """What a custom library can give a venv build at this moment."""

    READY = "ready"
    WAIT = "wait"
    NOTHING_BUILT = "nothing_built"


class ExecutionStatus(StrEnum):
    """Where an accepted execution is, as the status endpoint reports it."""

    # Waiting for its venv to finish building; no queue deadline runs yet, only the hold
    # deadline after which it is failed without running.
    HELD = "held"
    # Handed to the worker queue, waiting for a slot or running.
    QUEUED = "queued"
    # Its result was handed to the publisher.
    DONE = "done"
