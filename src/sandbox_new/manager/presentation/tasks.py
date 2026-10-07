import asyncio
import shutil
from pathlib import Path
from typing import cast

import settings
from foundation.utils import task_scheduler

from manager.application.orchestrators import VenvBuildOrchestrator
from manager.domain.enums import VenvStatus
from manager.infrastructure.database.unit_of_work import PiccoloUnitOfWork
from manager.infrastructure.providers import UVProvider


@task_scheduler.schedule(interval=5)
async def build_declared_venv():
    uow = PiccoloUnitOfWork()
    uv_provider = UVProvider()

    async with uow:
        venvs = await uow.venv_repo.list_by_status(status=VenvStatus.DECLARED)

    for venv in venvs:
        await VenvBuildOrchestrator(uow, uv_provider).build(venv)


# TODO: don't delete venvs that are at working.
@task_scheduler.schedule(interval=60)
async def remove_orphaned_venv():
    uow = PiccoloUnitOfWork()
    venvs_dir = cast(Path, settings.VENVS_DIR)

    hash_to_venv_path_map: dict[str, Path] = {
        p.name.split("-")[-1]: p
        for p in venvs_dir.iterdir()
        if p.is_dir() and p.name.startswith("venv-")
    }
    hashes = set(hash_to_venv_path_map.keys())

    async with uow:
        venvs = await uow.venv_repo.list_by_hashes(hashes=hashes)
    db_hashes = {v.hash for v in venvs}

    orphaned_hashes = hashes - db_hashes
    for hash in orphaned_hashes:
        path = hash_to_venv_path_map[hash]
        await asyncio.to_thread(shutil.rmtree, path)
