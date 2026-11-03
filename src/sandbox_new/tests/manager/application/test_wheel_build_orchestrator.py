"""Behavior of the wheel build orchestrator.

A build never raises: it runs a client's source, so failing is an outcome and belongs
on the row, where the client reads it. What the build produces is only trusted after it
is checked -- an archive may declare any distribution, and the version it carries is
unknown until it has been built.

The uv provider is faked; what it does with a directory is its own suite. What is real
here are the archives, because unpacking one is this orchestrator's own work.
"""

import io
import tarfile
import zipfile

import pytest

from manager.application.orchestrators import WheelBuildOrchestrator
from manager.domain.enums import WheelStatus
from manager.domain.models import CustomLibrary, Wheel

BUILT_WHEEL = "my_library-1.4.2-py3-none-any.whl"
PYPROJECT = '[project]\nname = "my-library"\nversion = "1.4.2"\n'


def tar_archive(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def zip_archive(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, content in files.items():
            bundle.writestr(name, content)
    return buffer.getvalue()


@pytest.fixture
def library(uow) -> CustomLibrary:
    return uow.custom_library_repo.seed(CustomLibrary(name="my-library"))[0]


@pytest.fixture
def orchestrator(uow, file_storage, uv_provider) -> WheelBuildOrchestrator:
    uv_provider.built_wheel_name = BUILT_WHEEL
    return WheelBuildOrchestrator(uow, file_storage, uv_provider)


@pytest.fixture
def declared(uow, file_storage, library):
    """A version waiting to be built, with its archive already in the object store."""

    def declare(archive: bytes, filename: str = "my-library-1.4.2.tar.gz") -> Wheel:
        wheel = uow.wheel_repo.seed(
            Wheel(library_id=library.id, source_filename=filename, upload_sha256="a" * 64)
        )[0]
        file_storage.objects[wheel.source_key] = archive
        return wheel

    return declare


async def test_a_built_version_carries_the_wheel_the_build_produced(
    orchestrator, file_storage, uow, declared, library
):
    wheel = declared(tar_archive({"my-library-1.4.2/pyproject.toml": PYPROJECT}))

    await orchestrator.build(wheel)

    stored = await uow.wheel_repo.retrieve(library.id, wheel.id)
    assert stored.status is WheelStatus.COMPLETED
    assert stored.version == "1.4.2"
    assert stored.wheel_filename == BUILT_WHEEL
    assert stored.wheel_key in file_storage.objects


async def test_the_archive_is_kept_next_to_the_wheel_it_produced(
    orchestrator, file_storage, uow, declared, library
):
    """Both keys stay reachable: the reaper deletes each of them when the version goes."""
    wheel = declared(tar_archive({"my-library-1.4.2/pyproject.toml": PYPROJECT}))

    await orchestrator.build(wheel)

    stored = await uow.wheel_repo.retrieve(library.id, wheel.id)
    assert stored.source_key in file_storage.objects
    assert stored.wheel_key in file_storage.objects


@pytest.mark.parametrize(
    "members",
    [
        {"pyproject.toml": PYPROJECT, "src/my_library/__init__.py": "V = 1"},
        {"my-library-1.4.2/pyproject.toml": PYPROJECT},
        {"my-library-1.4.2/setup.py": "from setuptools import setup\n\nsetup()\n"},
        {"my-library-1.4.2/pyproject.toml": PYPROJECT, "README.md": "hi"},
    ],
    ids=["project at the root", "wrapped as an sdist", "legacy setup.py", "wrapper and loose files"],
)
async def test_the_build_is_run_where_the_project_actually_is(
    orchestrator, uow, declared, library, members
):
    """uv refuses a directory holding neither pyproject.toml nor setup.py, so pointing
    it at the archive root would fail every source packed the way sdists are."""
    wheel = declared(tar_archive(members))

    await orchestrator.build(wheel)

    assert (await uow.wheel_repo.retrieve(library.id, wheel.id)).status is WheelStatus.COMPLETED


async def test_an_archive_holding_no_python_project_fails_the_build(
    orchestrator, uow, declared, library
):
    wheel = declared(tar_archive({"my_library/__init__.py": "V = 1"}))

    await orchestrator.build(wheel)

    assert (await uow.wheel_repo.retrieve(library.id, wheel.id)).status is WheelStatus.FAILED


async def test_a_zip_archive_is_unpacked_too(orchestrator, uow, declared, library):
    wheel = declared(
        zip_archive({"my-library-1.4.2/pyproject.toml": PYPROJECT}), "my-library-1.4.2.zip"
    )

    await orchestrator.build(wheel)

    assert (await uow.wheel_repo.retrieve(library.id, wheel.id)).status is WheelStatus.COMPLETED


async def test_a_build_that_fails_says_why_on_the_row_instead_of_raising(
    orchestrator, uv_provider, uow, declared, library
):
    uv_provider.fail_build_wheel = RuntimeError("the build backend returned an error")
    wheel = declared(tar_archive({"my-library-1.4.2/pyproject.toml": PYPROJECT}))

    await orchestrator.build(wheel)

    stored = await uow.wheel_repo.retrieve(library.id, wheel.id)
    assert stored.status is WheelStatus.FAILED
    assert stored.error == "the build backend returned an error"


async def test_an_archive_that_cannot_be_unpacked_fails_the_build(
    orchestrator, uow, declared, library
):
    wheel = declared(b"not an archive at all")

    await orchestrator.build(wheel)

    assert (await uow.wheel_repo.retrieve(library.id, wheel.id)).status is WheelStatus.FAILED


async def test_an_archive_member_pointing_outside_its_directory_fails_the_build(
    orchestrator, uow, declared, library
):
    """The archive is a client's file and unpacking it writes to the manager's own
    filesystem, so a member naming a path above the directory is refused outright."""
    wheel = declared(
        tar_archive({"my-library-1.4.2/pyproject.toml": PYPROJECT, "../escaped.txt": "pwned"})
    )

    await orchestrator.build(wheel)

    assert (await uow.wheel_repo.retrieve(library.id, wheel.id)).status is WheelStatus.FAILED


async def test_a_version_with_no_archive_to_build_says_so(orchestrator, uow, library):
    """Refused by name rather than by trying: asking the object store for a key that
    was never built would blame it for what the row says plainly."""
    wheel = uow.wheel_repo.seed(
        Wheel(library_id=library.id, wheel_filename=BUILT_WHEEL, upload_sha256="b" * 64)
    )[0]

    await orchestrator.build(wheel)

    stored = await uow.wheel_repo.retrieve(library.id, wheel.id)
    assert stored.status is WheelStatus.FAILED
    assert "no source archive" in stored.error


async def test_a_source_that_builds_another_distribution_is_refused(
    orchestrator, uv_provider, uow, declared, library
):
    """Nothing checks this before the build: the archive's own metadata decides the
    name, and it only becomes known once a wheel exists."""
    uv_provider.built_wheel_name = "other_lib-1.0.0-py3-none-any.whl"
    wheel = declared(tar_archive({"my-library-1.4.2/pyproject.toml": PYPROJECT}))

    await orchestrator.build(wheel)

    stored = await uow.wheel_repo.retrieve(library.id, wheel.id)
    assert stored.status is WheelStatus.FAILED
    assert "other-lib" in stored.error


async def test_a_source_that_builds_a_published_version_is_refused(
    orchestrator, uow, declared, library
):
    uow.wheel_repo.seed(
        Wheel(
            library_id=library.id,
            wheel_filename=BUILT_WHEEL,
            upload_sha256="c" * 64,
            version="1.4.2",
            status=WheelStatus.COMPLETED,
        )
    )
    wheel = declared(tar_archive({"my-library-1.4.2/pyproject.toml": PYPROJECT}))

    await orchestrator.build(wheel)

    stored = await uow.wheel_repo.retrieve(library.id, wheel.id)
    assert stored.status is WheelStatus.FAILED
    assert "1.4.2" in stored.error


async def test_a_failed_build_leaves_its_version_for_the_next_attempt(
    orchestrator, uv_provider, uow, declared, library
):
    """The version is recorded on completion and not before, so a source fixed and
    uploaded again is not refused by the row that failed to build it."""
    uv_provider.fail_build_wheel = RuntimeError("the build backend returned an error")
    wheel = declared(tar_archive({"my-library-1.4.2/pyproject.toml": PYPROJECT}))
    await orchestrator.build(wheel)

    assert (await uow.wheel_repo.retrieve(library.id, wheel.id)).version is None
    assert await uow.wheel_repo.retrieve_by_version(library.id, "1.4.2") is None


async def test_a_wheel_that_cannot_be_stored_leaves_its_version_unclaimed(
    orchestrator, file_storage, uow, declared, library
):
    """The build got as far as a version, and storing it is what failed. Recording the
    version anyway would have a row that holds no wheel occupy the number for good."""
    file_storage.fail_put = RuntimeError("the object store is unreachable")
    wheel = declared(tar_archive({"my-library-1.4.2/pyproject.toml": PYPROJECT}))

    await orchestrator.build(wheel)

    stored = await uow.wheel_repo.retrieve(library.id, wheel.id)
    assert stored.status is WheelStatus.FAILED
    assert stored.version is None
    assert await uow.wheel_repo.retrieve_by_version(library.id, "1.4.2") is None
