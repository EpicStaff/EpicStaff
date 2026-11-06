"""Behavior of the venv build orchestrator.

The hash is a sha256 of the lock file the provider writes, so ``FakeUVProvider`` writes
a real one -- a canned hash would leave that derivation untested.
"""

import hashlib

import pytest

from manager.application.errors import VenvNotFoundError
from manager.application.orchestrators import VenvBuildOrchestrator
from manager.application.ports.errors import (
    DependencyConflictError,
    EnvironmentBuildError,
    PackageNotFoundError,
    PackageVersionNotFoundError,
)
from manager.domain.enums import VenvBuildErrorKind, VenvStatus
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


GENERIC_BUILD_ERROR = "Couldn't install the libraries. Check the library names and versions."


@pytest.mark.parametrize(
    ("error", "kind", "stored_error"),
    [
        (
            PackageNotFoundError(package="requests2"),
            VenvBuildErrorKind.PACKAGE_NOT_FOUND,
            "Package 'requests2' does not exist.",
        ),
        (
            PackageVersionNotFoundError(package="requests", specification="==99"),
            VenvBuildErrorKind.PACKAGE_VERSION_NOT_FOUND,
            "Package 'requests' has no version matching '==99'.",
        ),
        (
            DependencyConflictError(package="pandas"),
            VenvBuildErrorKind.PACKAGE_DEPENDENCY_CONFLICT,
            "Package 'pandas' requires versions of its dependencies "
            "that conflict with the other requested packages.",
        ),
        (EnvironmentBuildError(), VenvBuildErrorKind.PACKAGE_INSTALL_FAILED, GENERIC_BUILD_ERROR),
        (
            RuntimeError("uv crashed in /var/lib/sandbox/venvs/builds"),
            VenvBuildErrorKind.PACKAGE_INSTALL_FAILED,
            GENERIC_BUILD_ERROR,
        ),
    ],
    ids=["package-not-found", "version-not-found", "conflict", "unrecognised-cause", "unexpected"],
)
async def test_a_failed_build_stores_its_kind_and_only_a_text_that_is_safe_to_show(
    uow, uv_provider, venvs_dir, error, kind, stored_error
):
    stored = uow.venv_repo.seed(make_venv())[0]
    uv_provider.fail_apply = error

    await VenvBuildOrchestrator(uow, uv_provider).build(stored)

    failed = uow.venv_repo.rows[stored.id]
    assert (failed.status, failed.error_kind, failed.error) == (
        VenvStatus.FAILED,
        kind,
        stored_error,
    )
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


async def test_build_pins_a_library_that_carries_an_explicit_version(uow, uv_provider, venvs_dir):
    stored = uow.venv_repo.seed(
        make_venv(libs=[make_library(name="pandas", specification=">=2.0", version="2.1.0")])
    )[0]

    await VenvBuildOrchestrator(uow, uv_provider).build(stored)

    _, libs = uv_provider.apply_calls[0]
    assert libs == ("pandas==2.1.0",)


async def test_build_records_the_version_the_resolver_installed(uow, uv_provider, venvs_dir):
    stored = uow.venv_repo.seed(
        make_venv(libs=[make_library(name="pandas", specification=">=2.0")])
    )[0]
    uv_provider.resolved_versions = {"pandas": "2.2.3"}

    await VenvBuildOrchestrator(uow, uv_provider).build(stored)

    built = uow.venv_repo.rows[stored.id]
    assert built.libs[0].version == "2.2.3"
    assert built.status is VenvStatus.COMPLETED


async def test_build_reads_the_resolved_versions_from_the_staging_lock_file(
    uow, uv_provider, venvs_dir
):
    stored = uow.venv_repo.seed(make_venv(libs=[make_library(name="pandas")]))[0]
    seen: list = []
    uv_provider.read_resolved_versions = lambda venv_path: seen.append(venv_path) or {}

    await VenvBuildOrchestrator(uow, uv_provider).build(stored)

    assert seen == [venvs_dir / "builds" / f"venv-{stored.id}"]


async def test_build_failure_leaves_the_declared_versions_alone(uow, uv_provider, venvs_dir):
    stored = uow.venv_repo.seed(
        make_venv(libs=[make_library(name="pandas", specification=">=2.0")])
    )[0]
    uv_provider.resolved_versions = {"pandas": "2.2.3"}
    uv_provider.fail_apply = RuntimeError("uv pip compile failed")

    await VenvBuildOrchestrator(uow, uv_provider).build(stored)

    assert uow.venv_repo.rows[stored.id].libs[0].version is None


async def test_a_failure_after_the_resolve_leaves_the_declared_libraries_alone(
    uow, uv_provider, venvs_dir
):
    """The resolve succeeded but the venv did not: a stamped version and the `>=`
    specification derived from it would describe an environment that was never built."""
    stored = uow.venv_repo.seed(make_venv(libs=[make_library(name="pandas", specification="")]))[0]
    uv_provider.resolved_versions = {"pandas": "2.2.3"}
    uv_provider.fail_install_local = RuntimeError("pip install of the shared packages failed")

    await VenvBuildOrchestrator(uow, uv_provider).build(stored)

    built = uow.venv_repo.rows[stored.id]
    assert built.status is VenvStatus.FAILED
    assert (built.libs[0].version, built.libs[0].specification) == (None, "")


async def test_build_stamps_a_specification_when_the_library_declared_none(
    uow, uv_provider, venvs_dir
):
    stored = uow.venv_repo.seed(make_venv(libs=[make_library(name="pandas", specification="")]))[0]
    uv_provider.resolved_versions = {"pandas": "2.2.3"}

    await VenvBuildOrchestrator(uow, uv_provider).build(stored)

    built = uow.venv_repo.rows[stored.id]
    assert (built.libs[0].version, built.libs[0].specification) == ("2.2.3", ">=2.2.3")
