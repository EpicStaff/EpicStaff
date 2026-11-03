from enum import StrEnum

__all__ = [
    "JobStatus",
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
