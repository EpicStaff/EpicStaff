"""Builders for the domain objects the tests drive.

Each builder fills in a plausible default for every required field and takes keyword
overrides, so a test states only the field it is about.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from manager.domain.enums import VenvStatus
from manager.domain.models import Job as ManagerJob, Library, Venv
from worker.application.context import ExecutionContext
from worker.domain.enums import NetworkPolicy
from worker.domain.models import IsolationPlan, Job as WorkerJob, NetworkDecision

__all__ = [
    "make_context",
    "make_isolation_plan",
    "make_library",
    "make_manager_job",
    "make_venv",
    "make_worker_job",
    "write_executable",
]


def make_library(name: str = "requests", specification: str = ">=2.0", **overrides) -> Library:
    return Library(name=name, specification=specification, **overrides)


def make_venv(
    *,
    id: int | None = None,
    name: str = "default",
    libs: list[Library] | None = None,
    hash: str | None = None,
    status: VenvStatus = VenvStatus.DECLARED,
    error: str | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> Venv:
    return Venv(
        id=id,
        name=name,
        libs=libs if libs is not None else [],
        hash=hash,
        status=status,
        error=error,
        created_at=created_at,
        updated_at=updated_at,
    )


def make_manager_job(**overrides: Any) -> ManagerJob:
    fields: dict[str, Any] = {
        "session_id": 7,
        "execution_id": "exec-1",
        "venv_id": 1,
        "venv_hash": "1abc",
        "code": "def main():\n    return 1",
        "result": "",
        "entrypoint": "main",
        "secrets": {},
        "global_kwargs": {},
        "func_kwargs": {},
        "use_storage": False,
        "storage_allowed_paths": [],
        "storage_org_prefix": None,
        "storage_credentials": None,
        "timeout": None,
        "error": None,
    }
    fields.update(overrides)
    return ManagerJob(**fields)


def make_worker_job(**overrides: Any) -> WorkerJob:
    fields: dict[str, Any] = {
        "execution_id": "exec-1",
        "venv_hash": "1abc",
        "code": "def main():\n    return 1",
        "entrypoint": "main",
        "func_kwargs": {},
        "global_kwargs": {},
        "secrets": {},
        "use_storage": False,
        "storage_allowed_paths": [],
        "storage_org_prefix": None,
        "storage_credentials": None,
        "session_id": 7,
        "timeout": None,
    }
    fields.update(overrides)
    return WorkerJob(**fields)


def make_isolation_plan(
    *,
    landlock_abi: int = 0,
    policy: NetworkPolicy = NetworkPolicy.UNRESTRICTED,
    allowed_tcp_ports: tuple[int, ...] = (),
    isolate_signals: bool = False,
    jail=None,
) -> IsolationPlan:
    return IsolationPlan(
        landlock_abi=landlock_abi,
        network=NetworkDecision(policy=policy, allowed_tcp_ports=allowed_tcp_ports),
        isolate_signals=isolate_signals,
        jail=jail,
    )


def make_context(job: WorkerJob | None = None, **fields: Any) -> ExecutionContext:
    """An ``ExecutionContext`` with the given fields already assigned.

    ``ExecutionContext`` validates on assignment, so ``Path`` fields must be given as
    ``Path`` objects, not strings.
    """
    context = ExecutionContext(job=job if job is not None else make_worker_job())
    for name, value in fields.items():
        setattr(context, name, value)
    return context


def write_executable(path: Path) -> Path:
    """Create a file that looks like a venv's python binary, parents included."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    return path
