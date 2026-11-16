"""Behavior of the venv build orchestrator.

The hash is a sha256 of the lock file the provider writes, so ``FakeUVProvider`` writes
a real one -- a canned hash would leave that derivation untested.
"""

import hashlib

import pytest

from manager.application.orchestrators import VenvBuildOrchestrator
from manager.domain.enums import VenvStatus, WheelStatus
from manager.domain.errors import VenvNotFoundError
from manager.domain.models import CustomLibrary, Wheel
from tests.builders import make_library, make_venv
from tests.fakes import FakeUnitOfWork
from tests.fakes.repositories import FakeCustomLibraryRepository, FakeWheelRepository


def expected_hash(venv_id: int, libs: list[str]) -> str:
    return f"{venv_id}{hashlib.sha256('\n'.join(libs).encode('utf-8')).hexdigest()}"


async def test_build_completes_the_venv_and_moves_it_into_place(uow, uv_provider, venvs_dir, file_storage):
    stored = uow.venv_repo.seed(
        make_venv(libs=[make_library(name="pandas", specification=">=2.0")])
    )[0]

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    built = uow.venv_repo.rows[stored.id]
    assert built.status is VenvStatus.COMPLETED
    assert built.error is None
    assert built.hash == expected_hash(stored.id, ["pandas>=2.0"])
    assert (venvs_dir / f"venv-{built.hash}").is_dir()
    assert not (venvs_dir / "builds" / f"venv-{stored.id}").exists()


async def test_build_passes_the_library_strings_to_the_provider(uow, uv_provider, venvs_dir, file_storage):
    stored = uow.venv_repo.seed(
        make_venv(
            libs=[
                make_library(name="pandas", specification=">=2.0"),
                make_library(name="numpy", specification=""),
            ]
        )
    )[0]

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    _, libs = uv_provider.apply_calls[0]
    assert libs == ("pandas>=2.0", "numpy")


async def test_build_installs_the_predefined_packages_into_the_final_venv(
    uow, uv_provider, venvs_dir
, file_storage):
    import settings

    stored = uow.venv_repo.seed(make_venv())[0]

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    built = uow.venv_repo.rows[stored.id]
    venv_path, packages = uv_provider.install_local_calls[0]
    assert venv_path == venvs_dir / f"venv-{built.hash}"
    assert packages == settings.PREDEFINED_VENV_PACKAGES


async def test_build_marks_the_venv_processing_before_it_starts(uow, uv_provider, venvs_dir, file_storage):
    stored = uow.venv_repo.seed(make_venv())[0]
    seen: list[VenvStatus] = []

    original_init_venv = uv_provider.init_venv

    async def record_then_init(venv_path):
        seen.append(uow.venv_repo.rows[stored.id].status)
        await original_init_venv(venv_path)

    uv_provider.init_venv = record_then_init

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    assert seen == [VenvStatus.PROCESSING]


async def test_build_failure_marks_the_venv_failed_with_the_error_text(
    uow, uv_provider, venvs_dir
, file_storage):
    stored = uow.venv_repo.seed(make_venv())[0]
    uv_provider.fail_apply = RuntimeError("uv pip compile failed")

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    failed = uow.venv_repo.rows[stored.id]
    assert failed.status is VenvStatus.FAILED
    assert failed.error == "uv pip compile failed"
    assert uv_provider.install_local_calls == []


def install_target(uv_provider):
    venv_path, _ = uv_provider.install_local_calls[0]
    return venv_path


async def test_build_reuses_an_existing_venv_directory_and_removes_the_staging_copy(
    uow, uv_provider, venvs_dir
, file_storage):
    stored = uow.venv_repo.seed(make_venv(libs=[make_library(name="pandas")]))[0]
    existing = venvs_dir / f"venv-{expected_hash(stored.id, ['pandas>=2.0'])}"
    existing.mkdir()
    (existing / "marker").write_text("kept")

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    assert (existing / "marker").read_text() == "kept"
    assert not (venvs_dir / "builds" / f"venv-{stored.id}").exists()
    assert install_target(uv_provider) == existing


async def test_build_removes_a_stale_staging_directory_first(uow, uv_provider, venvs_dir, file_storage):
    stored = uow.venv_repo.seed(make_venv())[0]
    stale = venvs_dir / "builds" / f"venv-{stored.id}"
    stale.mkdir()
    (stale / "junk").write_text("from a crashed build")

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    assert uow.venv_repo.rows[stored.id].status is VenvStatus.COMPLETED
    built = uow.venv_repo.rows[stored.id]
    assert not (venvs_dir / f"venv-{built.hash}" / "junk").exists()


async def test_build_by_id_resolves_the_venv(uow, uv_provider, venvs_dir, file_storage):
    stored = uow.venv_repo.seed(make_venv())[0]

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored.id)

    assert uow.venv_repo.rows[stored.id].status is VenvStatus.COMPLETED


async def test_build_by_id_raises_for_a_missing_venv(uow, uv_provider, venvs_dir, file_storage):
    with pytest.raises(VenvNotFoundError):
        await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(404)


async def test_build_pins_a_library_that_carries_an_explicit_version(uow, uv_provider, venvs_dir, file_storage):
    stored = uow.venv_repo.seed(
        make_venv(libs=[make_library(name="pandas", specification=">=2.0", version="2.1.0")])
    )[0]

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    _, libs = uv_provider.apply_calls[0]
    assert libs == ("pandas==2.1.0",)


async def test_build_records_the_version_the_resolver_installed(uow, uv_provider, venvs_dir, file_storage):
    stored = uow.venv_repo.seed(
        make_venv(libs=[make_library(name="pandas", specification=">=2.0")])
    )[0]
    uv_provider.resolved_versions = {"pandas": "2.2.3"}

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    built = uow.venv_repo.rows[stored.id]
    assert built.libs[0].version == "2.2.3"
    assert built.status is VenvStatus.COMPLETED


async def test_build_reads_the_resolved_versions_from_the_staging_lock_file(
    uow, uv_provider, venvs_dir
, file_storage):
    stored = uow.venv_repo.seed(make_venv(libs=[make_library(name="pandas")]))[0]
    seen: list = []
    uv_provider.read_resolved_versions = lambda venv_path: seen.append(venv_path) or {}

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    assert seen == [venvs_dir / "builds" / f"venv-{stored.id}"]


async def test_build_failure_leaves_the_declared_versions_alone(uow, uv_provider, venvs_dir, file_storage):
    stored = uow.venv_repo.seed(
        make_venv(libs=[make_library(name="pandas", specification=">=2.0")])
    )[0]
    uv_provider.resolved_versions = {"pandas": "2.2.3"}
    uv_provider.fail_apply = RuntimeError("uv pip compile failed")

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    assert uow.venv_repo.rows[stored.id].libs[0].version is None


async def test_a_failure_after_the_resolve_leaves_the_declared_libraries_alone(
    uow, uv_provider, venvs_dir
, file_storage):
    """The resolve succeeded but the venv did not: a stamped version and the `>=`
    specification derived from it would describe an environment that was never built."""
    stored = uow.venv_repo.seed(make_venv(libs=[make_library(name="pandas", specification="")]))[0]
    uv_provider.resolved_versions = {"pandas": "2.2.3"}
    uv_provider.fail_install_local = RuntimeError("pip install of the shared packages failed")

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    built = uow.venv_repo.rows[stored.id]
    assert built.status is VenvStatus.FAILED
    assert (built.libs[0].version, built.libs[0].specification) == (None, "")


async def test_build_stamps_a_specification_when_the_library_declared_none(
    uow, uv_provider, venvs_dir
, file_storage):
    stored = uow.venv_repo.seed(make_venv(libs=[make_library(name="pandas", specification="")]))[0]
    uv_provider.resolved_versions = {"pandas": "2.2.3"}

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    built = uow.venv_repo.rows[stored.id]
    assert (built.libs[0].version, built.libs[0].specification) == ("2.2.3", ">=2.2.3")


class CountingCustomLibraryRepository(FakeCustomLibraryRepository):
    """Counts the calls, so a return to one query per entry is visible."""

    def __init__(self) -> None:
        super().__init__()
        self.list_by_names_calls = 0

    async def list_by_names(self, names):
        self.list_by_names_calls += 1
        return await super().list_by_names(names)


class CountingWheelRepository(FakeWheelRepository):
    def __init__(self) -> None:
        super().__init__()
        self.list_by_library_ids_calls = 0

    async def list_by_library_ids(self, ids):
        self.list_by_library_ids_calls += 1
        return await super().list_by_library_ids(ids)


def publish(uow, file_storage, name: str, versions: dict[str, WheelStatus]) -> CustomLibrary:
    """A stored library whose versions are in the given states, with files to download."""
    library = uow.custom_library_repo.seed(CustomLibrary(name=name))[0]
    for index, (version, status) in enumerate(versions.items()):
        built = status is WheelStatus.COMPLETED
        wheel = uow.wheel_repo.seed(
            Wheel(
                library_id=library.id,
                source_filename=f"{name}-{version}.tar.gz",
                wheel_filename=(
                    f"{name.replace('-', '_')}-{version}-py3-none-any.whl" if built else None
                ),
                upload_sha256=f"{library.id}{index}".ljust(64, "0"),
                version=version if built else None,
                status=status,
            )
        )[0]
        if wheel.wheel_key is not None:
            file_storage.objects[wheel.wheel_key] = f"the {name} {version} wheel".encode()
    return library


def custom(name: str, specification: str = ""):
    return make_library(name=name, specification=specification, is_custom=True)


async def test_a_stored_library_is_downloaded_and_handed_to_the_resolver(
    uow, uv_provider, venvs_dir, file_storage
):
    publish(uow, file_storage, "acme-core", {"1.4.2": WheelStatus.COMPLETED})
    stored = uow.venv_repo.seed(make_venv(libs=[custom("acme-core", ">=1")]))[0]

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    assert uv_provider.wheelhouses[0] is not None
    assert uv_provider.wheelhouse_contents[0] == ["acme_core-1.4.2-py3-none-any.whl"]
    assert uow.venv_repo.rows[stored.id].status is VenvStatus.COMPLETED


async def test_every_built_version_reaches_the_wheelhouse(
    uow, uv_provider, venvs_dir, file_storage
):
    """The resolver applies the specification, so it is given the candidates."""
    publish(
        uow,
        file_storage,
        "acme-core",
        {"1.0.0": WheelStatus.COMPLETED, "2.0.0": WheelStatus.COMPLETED},
    )
    stored = uow.venv_repo.seed(make_venv(libs=[custom("acme-core", ">=1")]))[0]

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    assert uv_provider.wheelhouse_contents[0] == [
        "acme_core-1.0.0-py3-none-any.whl",
        "acme_core-2.0.0-py3-none-any.whl",
    ]


async def test_a_venv_of_ordinary_packages_is_given_no_wheelhouse(
    uow, uv_provider, venvs_dir, file_storage
):
    """Nothing is downloaded, and the resolver is not pointed at a directory that
    holds nothing."""
    stored = uow.venv_repo.seed(make_venv(libs=[make_library(name="requests")]))[0]

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    assert uv_provider.wheelhouses == [None]
    assert file_storage.objects == {}


async def test_the_wheelhouse_does_not_outlive_the_build(
    uow, uv_provider, venvs_dir, file_storage
):
    """It is a temporary directory and not a cache: a cache is another place a deleted
    wheel could still be installed from."""
    publish(uow, file_storage, "acme-core", {"1.4.2": WheelStatus.COMPLETED})
    stored = uow.venv_repo.seed(make_venv(libs=[custom("acme-core")]))[0]

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    assert not uv_provider.wheelhouses[0].exists()


async def test_every_library_of_a_venv_is_resolved_in_two_queries(
    uv_provider, venvs_dir, file_storage
):
    """One query per entry would be four here, on a tick that runs every five seconds."""
    libraries = CountingCustomLibraryRepository()
    wheels = CountingWheelRepository()
    uow = FakeUnitOfWork(custom_library_repo=libraries, wheel_repo=wheels)
    for name in ("acme-core", "acme-tools", "acme-extra"):
        publish(uow, file_storage, name, {"1.0.0": WheelStatus.COMPLETED})
    stored = uow.venv_repo.seed(
        make_venv(
            libs=[custom("acme-core"), custom("acme-tools"), custom("acme-extra"),
                  make_library(name="requests")]
        )
    )[0]

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    assert libraries.list_by_names_calls == 1
    assert wheels.list_by_library_ids_calls == 1


async def test_a_venv_waits_while_a_version_it_needs_is_still_being_built(
    uow, uv_provider, venvs_dir, file_storage
):
    publish(uow, file_storage, "acme-core", {"1.4.2": WheelStatus.PROCESSING})
    stored = uow.venv_repo.seed(make_venv(libs=[custom("acme-core")]))[0]

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    waiting = uow.venv_repo.rows[stored.id]
    assert waiting.status is VenvStatus.WAITING
    assert waiting.error is None
    assert uv_provider.apply_calls == []
    # Written once, not marked `processing` first and corrected after: a venv that is
    # only waiting would otherwise be rewritten twice on every five second tick.
    assert uow.commits == 1


async def test_a_waiting_venv_builds_once_the_version_is_there(
    uow, uv_provider, venvs_dir, file_storage
):
    """What makes waiting worth having: the next tick finishes it with no user action."""
    library = publish(uow, file_storage, "acme-core", {"1.4.2": WheelStatus.PROCESSING})
    stored = uow.venv_repo.seed(make_venv(libs=[custom("acme-core")]))[0]
    orchestrator = VenvBuildOrchestrator(uow, uv_provider, file_storage)
    await orchestrator.build(stored)

    wheel = (await uow.wheel_repo.list(library.id))[0]
    wheel.mark_as_completed("1.4.2", "acme_core-1.4.2-py3-none-any.whl")
    await uow.wheel_repo.update(wheel)
    file_storage.objects[wheel.wheel_key] = b"the wheel"
    await orchestrator.build(uow.venv_repo.rows[stored.id])

    assert uow.venv_repo.rows[stored.id].status is VenvStatus.COMPLETED


async def test_a_venv_fails_when_the_library_has_no_built_version_and_none_coming(
    uow, uv_provider, venvs_dir, file_storage
):
    publish(uow, file_storage, "acme-core", {"1.4.2": WheelStatus.FAILED})
    stored = uow.venv_repo.seed(make_venv(libs=[custom("acme-core")]))[0]

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    failed = uow.venv_repo.rows[stored.id]
    assert failed.status is VenvStatus.FAILED
    assert "acme-core" in failed.error


async def test_a_venv_fails_when_it_names_a_library_nobody_stored(
    uow, uv_provider, venvs_dir, file_storage
):
    stored = uow.venv_repo.seed(make_venv(libs=[custom("never-uploaded")]))[0]

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    failed = uow.venv_repo.rows[stored.id]
    assert failed.status is VenvStatus.FAILED
    assert "never-uploaded" in failed.error


async def test_a_venv_refused_before_the_build_is_never_marked_processing(
    uow, uv_provider, venvs_dir, file_storage
):
    """Nothing was started, so nothing claims to be in progress."""
    stored = uow.venv_repo.seed(make_venv(libs=[custom("never-uploaded")]))[0]

    await VenvBuildOrchestrator(uow, uv_provider, file_storage).build(stored)

    assert uv_provider.init_venv_calls == []
