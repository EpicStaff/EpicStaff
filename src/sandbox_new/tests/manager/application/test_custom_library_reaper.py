"""Behavior of the custom library reaper.

A delete marks; this is what removes. The object store and the database cannot be
committed together, so the pass is deliberately two steps in a fixed order -- files
first, then the row -- and every test here is about what the next pass does when it
stopped somewhere in the middle. Both steps are idempotent, which is the whole reason
the order is safe.
"""

import pytest

from manager.application.orchestrators import CustomLibraryReapOrchestrator
from manager.domain.models import CustomLibrary, Wheel
from tests.fakes import FakeUnitOfWork
from tests.fakes.repositories import FakeWheelRepository


class WheelRepositoryThatFailsOneRemoval(FakeWheelRepository):
    """Refuses the first row deletion, which is the step after the files are gone."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_remove = True

    async def remove(self, obj: Wheel) -> None:
        if self.fail_remove:
            self.fail_remove = False
            raise RuntimeError("the database went away")
        await super().remove(obj)


async def store_a_removed_library(uow, file_storage, name: str = "doomed"):
    """A library and two versions of it, marked deleted, with their files in the store.

    One version was built and holds two files; the other is still an archive and holds
    one, so a pass has to cope with a key that is not there.
    """
    library = uow.custom_library_repo.seed(CustomLibrary(name=name))[0]
    wheels = uow.wheel_repo.seed(
        Wheel(
            library_id=library.id,
            source_filename=f"{name}-1.0.0.tar.gz",
            wheel_filename=f"{name}-1.0.0-py3-none-any.whl",
            upload_sha256="a" * 64,
        ),
        Wheel(
            library_id=library.id,
            source_filename=f"{name}-2.0.0.tar.gz",
            upload_sha256="b" * 64,
        ),
    )
    for wheel in wheels:
        file_storage.objects[wheel.source_key] = b"the archive"
        if wheel.wheel_key is not None:
            file_storage.objects[wheel.wheel_key] = b"the wheel"
        wheel.mark_as_deleted()
        await uow.wheel_repo.update(wheel)

    library.mark_as_deleted()
    await uow.custom_library_repo.update(library)
    return library, wheels


@pytest.fixture
def reaper(uow, file_storage) -> CustomLibraryReapOrchestrator:
    return CustomLibraryReapOrchestrator(uow, file_storage)


@pytest.fixture
async def library_and_wheels(uow, file_storage):
    return await store_a_removed_library(uow, file_storage)


async def test_a_pass_removes_every_file_and_row_that_was_marked(
    reaper, uow, file_storage, library_and_wheels
):
    library, _ = library_and_wheels

    await reaper.reap()

    assert file_storage.objects == {}
    assert await uow.wheel_repo.count_by_library(library.id) == 0
    assert await uow.custom_library_repo.list_deleted() == []


async def test_a_pass_with_nothing_marked_does_nothing(reaper, uow, file_storage):
    library = uow.custom_library_repo.seed(CustomLibrary(name="live"))[0]
    wheel = uow.wheel_repo.seed(
        Wheel(library_id=library.id, source_filename="live-1.0.0.tar.gz", upload_sha256="c" * 64)
    )[0]
    file_storage.objects[wheel.source_key] = b"the archive"

    await reaper.reap()

    assert file_storage.objects != {}
    assert await uow.wheel_repo.count_by_library(library.id) == 1


async def test_a_pass_leaves_a_library_nobody_removed_alone(reaper, uow, file_storage):
    await store_a_removed_library(uow, file_storage, name="doomed")
    spared = uow.custom_library_repo.seed(CustomLibrary(name="spared"))[0]
    wheel = uow.wheel_repo.seed(
        Wheel(library_id=spared.id, source_filename="spared-1.0.0.tar.gz", upload_sha256="d" * 64)
    )[0]
    file_storage.objects[wheel.source_key] = b"the archive"

    await reaper.reap()

    assert await uow.custom_library_repo.retrieve(spared.id) is not None
    assert list(file_storage.objects) == [wheel.source_key]


async def test_a_file_that_cannot_be_deleted_keeps_its_row_for_the_next_pass(
    reaper, uow, file_storage, library_and_wheels
):
    """The row is the only record of what is still in the store, so it outlives a
    failed deletion rather than being dropped on the assumption the file went."""
    library, wheels = library_and_wheels
    file_storage.fail_delete = RuntimeError("the object store is unreachable")
    file_storage.fail_key = wheels[0].wheel_key

    await reaper.reap()

    assert await uow.wheel_repo.count_by_library(library.id) == 1
    assert wheels[0].wheel_key in file_storage.objects


async def test_the_next_pass_finishes_what_an_unreachable_store_interrupted(
    reaper, uow, file_storage, library_and_wheels
):
    library, wheels = library_and_wheels
    file_storage.fail_delete = RuntimeError("the object store is unreachable")
    file_storage.fail_key = wheels[0].wheel_key
    await reaper.reap()

    file_storage.fail_delete = None
    await reaper.reap()

    assert file_storage.objects == {}
    assert await uow.wheel_repo.count_by_library(library.id) == 0
    assert await uow.custom_library_repo.list_deleted() == []


async def test_the_next_pass_finishes_what_a_failed_row_deletion_interrupted(file_storage):
    """The files are already gone by then, and deleting a key that is not there is not
    an error -- which is what makes repeating the whole step safe."""
    uow = FakeUnitOfWork(wheel_repo=WheelRepositoryThatFailsOneRemoval())
    library, _ = await store_a_removed_library(uow, file_storage)
    reaper = CustomLibraryReapOrchestrator(uow, file_storage)

    await reaper.reap()
    assert await uow.wheel_repo.count_by_library(library.id) == 1

    await reaper.reap()

    assert file_storage.objects == {}
    assert await uow.wheel_repo.count_by_library(library.id) == 0
    assert await uow.custom_library_repo.list_deleted() == []


async def test_a_library_is_not_dropped_while_a_version_of_it_is_still_stored(
    reaper, uow, file_storage, library_and_wheels
):
    """The foreign key cascades. Dropping the library first would take the row that
    still points at stored files with it, and nothing would ever find them again."""
    library, wheels = library_and_wheels
    file_storage.fail_delete = RuntimeError("the object store is unreachable")
    file_storage.fail_key = wheels[0].wheel_key

    await reaper.reap()

    assert [row.name for row in await uow.custom_library_repo.list_deleted()] == ["doomed"]
