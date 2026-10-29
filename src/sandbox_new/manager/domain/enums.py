from enum import StrEnum

__all__ = ["JobStatus", "VenvOrder", "VenvStatus"]


class VenvStatus(StrEnum):
    DECLARED = "declared"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class VenvOrder(StrEnum):
    DEFAULT = "default"
    NAME_ASC = "name_asc"
    NAME_DESC = "name_desc"


class JobStatus(StrEnum):
    ACCEPTED = "accepted"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
