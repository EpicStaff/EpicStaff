from enum import StrEnum

__all__ = ["ExecutionStatus", "JobStatus", "VenvStatus"]


class VenvStatus(StrEnum):
    DECLARED = "declared"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


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
