from typing import Any

from foundation.base import Schema

from manager.domain.enums import JobStatus, VenvStatus
from manager.domain.models import Library

__all__ = [
    "ExecutionAcceptedSchema",
    "ExecutionSubmitSchema",
    "VenvCreateSchema",
    "VenvListSchema",
    "VenvRetrieveSchema",
    "VenvUpdateSchema",
]


class VenvCreateSchema(Schema):
    name: str
    libs: list[Library]


class VenvListSchema(Schema):
    objects: list["VenvRetrieveSchema"]


class VenvRetrieveSchema(Schema):
    id: int
    name: str
    libs: list[Library]
    status: VenvStatus
    error: str | None = None


class VenvUpdateSchema(Schema):
    name: str | None = None
    libs: list[Library] | None = None


class ExecutionSubmitSchema(Schema):
    execution_id: str
    # Optional: tool paths at session start can submit without a session. Matches
    # ExecutionJobMessage.session_id, which is already int | None.
    session_id: int | None = None
    code: str
    entrypoint: str
    global_kwargs: dict[str, Any] = {}
    func_kwargs: dict[str, Any] = {}
    secrets: dict[str, Any] = {}
    venv_id: int | None = None
    use_storage: bool = False
    storage_allowed_paths: list[str] = []
    storage_org_prefix: str | None = None
    timeout: float | None = None


class ExecutionAcceptedSchema(Schema):
    execution_id: str
    status: JobStatus
