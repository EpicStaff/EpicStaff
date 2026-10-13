"""Behavior of the venv build orchestrator.

The hash is a sha256 of the lock file the provider writes, so ``FakeUVProvider`` writes
a real one -- a canned hash would leave that derivation untested.
"""

import hashlib

import pytest

from manager.application.orchestrators import VenvBuildOrchestrator
from manager.domain.enums import VenvStatus
from manager.domain.errors import VenvNotFoundError
from tests.builders import make_library, make_venv


def expected_hash(venv_id: int, libs: list[str]) -> str:
    return f"{venv_id}{hashlib.sha256('\n'.join(libs).encode('utf-8')).hexdigest()}"


async def test_build_completes_the_venv_and_moves_it_into_place(uow, uv_provider, venvs_dir):
    stored = uow.venv_repo.seed(
        make_venv(libs=[make_library(name="pandas", specification=">=2.0")])
    )[0]

    await VenvBuildOrchestrator(uow, uv_provider).build(stored)

    built = uow.venv_repo.rows[stored.id]
    assert built.status is VenvStatus.COMPLETED
    assert built.error is None
    assert built.hash == expected_hash(stored.id, ["pandas>=2.0"])
    assert (venvs_dir / f"venv-{built.hash}").is_dir()
    assert not (venvs_dir / "builds" / f"venv-{stored.id}").exists()


async def test_build_passes_the_library_strings_to_the_provider(uow, uv_provider, venvs_dir):
    stored = uow.venv_repo.seed(
        make_venv(
            libs=[
                make_library(name="pandas", specification=">=2.0"),
                make_library(name="numpy", specification=""),
            ]
        )
    )[0]

    await VenvBuildOrchestrator(uow, uv_provider).build(stored)

    _, libs = uv_provider.apply_calls[0]
    assert libs == ("pandas>=2.0", "numpy")


async def test_build_installs_the_predefined_packages_into_the_final_venv(
    uow, uv_provider, venvs_dir
):
    import settings

    stored = uow.venv_repo.seed(make_venv())[0]

    await VenvBuildOrchestrator(uow, uv_provider).build(stored)

    built = uow.venv_repo.rows[stored.id]
    venv_path, packages = uv_provider.install_local_calls[0]
    assert venv_path == venvs_dir / f"venv-{built.hash}"
    assert packages == settings.PREDEFINED_VENV_PACKAGES


async def test_build_marks_the_venv_processing_before_it_starts(uow, uv_provider, venvs_dir):
    stored = uow.venv_repo.seed(make_venv())[0]
    seen: list[VenvStatus] = []

    original_init_venv = uv_provider.init_venv

    async def record_then_init(venv_path):
        seen.append(uow.venv_repo.rows[stored.id].status)
        await original_init_venv(venv_path)

    uv_provider.init_venv = record_then_init

    await VenvBuildOrchestrator(uow, uv_provider).build(stored)

    assert seen == [VenvStatus.PROCESSING]


async def test_build_failure_marks_the_venv_failed_with_the_error_text(
    uow, uv_provider, venvs_dir
):
    stored = uow.venv_repo.seed(make_venv())[0]
    uv_provider.fail_apply = RuntimeError("uv pip compile failed")

    await VenvBuildOrchestrator(uow, uv_provider).build(stored)

    failed = uow.venv_repo.rows[stored.id]
    assert failed.status is VenvStatus.FAILED
    assert failed.error == "uv pip compile failed"
    assert uv_provider.install_local_calls == []


def install_target(uv_provider):
    venv_path, _ = uv_provider.install_local_calls[0]
    return venv_path


async def test_build_reuses_an_existing_venv_directory_and_removes_the_staging_copy(
    uow, uv_provider, venvs_dir
):
    stored = uow.venv_repo.seed(make_venv(libs=[make_library(name="pandas")]))[0]
    existing = venvs_dir / f"venv-{expected_hash(stored.id, ['pandas>=2.0'])}"
    existing.mkdir()
    (existing / "marker").write_text("kept")

    await VenvBuildOrchestrator(uow, uv_provider).build(stored)

    assert (existing / "marker").read_text() == "kept"
    assert not (venvs_dir / "builds" / f"venv-{stored.id}").exists()
    assert install_target(uv_provider) == existing


async def test_build_removes_a_stale_staging_directory_first(uow, uv_provider, venvs_dir):
    stored = uow.venv_repo.seed(make_venv())[0]
    stale = venvs_dir / "builds" / f"venv-{stored.id}"
    stale.mkdir()
    (stale / "junk").write_text("from a crashed build")

    await VenvBuildOrchestrator(uow, uv_provider).build(stored)

    assert uow.venv_repo.rows[stored.id].status is VenvStatus.COMPLETED
    built = uow.venv_repo.rows[stored.id]
    assert not (venvs_dir / f"venv-{built.hash}" / "junk").exists()


async def test_build_by_id_resolves_the_venv(uow, uv_provider, venvs_dir):
    stored = uow.venv_repo.seed(make_venv())[0]

    await VenvBuildOrchestrator(uow, uv_provider).build(stored.id)

    assert uow.venv_repo.rows[stored.id].status is VenvStatus.COMPLETED


async def test_build_by_id_raises_for_a_missing_venv(uow, uv_provider, venvs_dir):
    with pytest.raises(VenvNotFoundError):
        await VenvBuildOrchestrator(uow, uv_provider).build(404)
