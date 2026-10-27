from enum import StrEnum

__all__ = ["JobStatus", "VenvStatus"]


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
