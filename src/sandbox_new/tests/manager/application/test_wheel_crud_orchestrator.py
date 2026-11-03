"""Behavior of the wheel CRUD orchestrator.

An upload is the one place where a file and a row are written together without a
transaction spanning both, so the order is the behavior: the row is stored first, in
``processing``, and only takes its real status once the bytes are in the object store.
Nothing ever claims to be usable before its file exists.

The name decides the rest. A ``.whl`` arrives finished and carries its version in its
name; an archive has neither until the build runs.
"""

import pytest
from litestar.datastructures import UploadFile

from manager.application.orchestrators import WheelCRUDOrchestrator
from manager.domain.enums import WheelStatus
from manager.domain.errors import (
    CustomLibraryNotFoundError,
    UnsupportedUploadError,
    WheelNameMismatchError,
    WheelInUseError,
    WheelNotBuiltError,
    WheelNotFoundError,
    WheelSourceAlreadyUploadedError,
    WheelVersionTakenError,
)
from manager.domain.models import CustomLibrary, Library, Venv, Wheel

WHEEL_NAME = "my_library-1.0.0-py3-none-any.whl"
ARCHIVE_NAME = "my-library-2.0.0.tar.gz"


def upload(filename: str, data: bytes = b"PK\x03\x04payload") -> UploadFile:
    return UploadFile(content_type="application/octet-stream", filename=filename, file_data=data)


@pytest.fixture
def library(uow) -> CustomLibrary:
    return uow.custom_library_repo.seed(CustomLibrary(name="my-library"))[0]


@pytest.fixture
def orchestrator(uow, file_storage) -> WheelCRUDOrchestrator:
    return WheelCRUDOrchestrator(uow, file_storage)


async def test_an_uploaded_wheel_is_complete_on_arrival(orchestrator, file_storage, library):
    """Nothing is left to do for it: the version is readable from the name, so the row
    goes straight to the status a download will accept."""
    wheel = await orchestrator.upload(library.id, upload(WHEEL_NAME))

    assert wheel.status is WheelStatus.COMPLETED
    assert wheel.version == "1.0.0"
    assert wheel.wheel_filename == WHEEL_NAME
    assert wheel.source_filename is None
    assert file_storage.objects[wheel.wheel_key] == b"PK\x03\x04payload"


async def test_an_uploaded_archive_waits_to_be_built(orchestrator, file_storage, library):
    wheel = await orchestrator.upload(library.id, upload(ARCHIVE_NAME))

    assert wheel.status is WheelStatus.DECLARED
    assert wheel.version is None
    assert wheel.wheel_filename is None
    assert file_storage.objects[wheel.source_key] == b"PK\x03\x04payload"


async def test_an_upload_larger_than_one_chunk_is_stored_whole(orchestrator, file_storage, library):
    """The upload is hashed in pieces before it is stored, and the two reads share one
    cursor: leaving it where the hashing stopped would store a truncated file."""
    payload = b"x" * (2 * 1024 * 1024 + 7)

    wheel = await orchestrator.upload(library.id, upload(WHEEL_NAME, payload))

    assert file_storage.objects[wheel.wheel_key] == payload


async def test_two_large_files_that_begin_alike_are_both_accepted(orchestrator, library):
    """Sameness is the whole file, not the first chunk of it: an upload is hashed in
    pieces, and stopping after one would make every large file with a common beginning
    -- the same vendored tree, the same header -- look like a re-upload."""
    shared_beginning = b"s" * (1024 * 1024)

    first = await orchestrator.upload(library.id, upload(WHEEL_NAME, shared_beginning + b"one"))
    second = await orchestrator.upload(
        library.id, upload("my_library-2.0.0-py3-none-any.whl", shared_beginning + b"two")
    )

    assert {first.version, second.version} == {"1.0.0", "2.0.0"}


async def test_download_refuses_a_wheel_whose_bytes_are_not_stored_yet(
    orchestrator, uow, library
):
    """A wheel uploaded ready-made is named on its row before its bytes are in the
    object store, so the status is what says it can be handed out -- going by the name
    alone would answer a request from the store with nothing in it."""
    wheel = uow.wheel_repo.seed(
        Wheel(
            library_id=library.id,
            wheel_filename=WHEEL_NAME,
            upload_sha256="c" * 64,
            status=WheelStatus.PROCESSING,
        )
    )[0]

    with pytest.raises(WheelNotBuiltError):
        await orchestrator.download_wheel(library.id, wheel.id)


async def test_the_same_file_under_a_different_name_is_refused(orchestrator, library):
    """Sameness is decided by content: a renamed re-upload is the same version twice."""
    await orchestrator.upload(library.id, upload(WHEEL_NAME, b"identical"))

    with pytest.raises(WheelSourceAlreadyUploadedError):
        await orchestrator.upload(library.id, upload("my-library-9.9.9.tar.gz", b"identical"))


async def test_a_different_file_claiming_a_published_version_is_refused(orchestrator, library):
    await orchestrator.upload(library.id, upload(WHEEL_NAME, b"first"))

    with pytest.raises(WheelVersionTakenError):
        await orchestrator.upload(library.id, upload(WHEEL_NAME, b"second"))


async def test_a_wheel_built_for_another_distribution_is_refused(orchestrator, library):
    with pytest.raises(WheelNameMismatchError):
        await orchestrator.upload(library.id, upload("other_lib-1.0.0-py3-none-any.whl"))


@pytest.mark.parametrize(
    "filename",
    ["notes.txt", "payload", "garbage.whl", "my_library-1.0.0.whl"],
    ids=["other suffix", "no suffix", "not a wheel name", "too few parts"],
)
async def test_a_file_that_is_neither_a_wheel_nor_an_archive_is_refused(
    orchestrator, library, filename
):
    with pytest.raises(UnsupportedUploadError):
        await orchestrator.upload(library.id, upload(filename))


async def test_uploading_to_a_library_that_is_not_there_is_refused(orchestrator):
    with pytest.raises(CustomLibraryNotFoundError):
        await orchestrator.upload(404, upload(WHEEL_NAME))


async def test_a_failed_store_leaves_the_row_saying_why(orchestrator, file_storage, uow, library):
    """The row is already committed by then, so the failure has to be recorded on it
    rather than disappearing with the request."""
    file_storage.fail_put = RuntimeError("the object store is unreachable")

    with pytest.raises(RuntimeError):
        await orchestrator.upload(library.id, upload(WHEEL_NAME))

    stored = (await uow.wheel_repo.list(library.id))[0]
    assert stored.status is WheelStatus.FAILED
    assert stored.error == "the object store is unreachable"
    assert stored.version is None


async def test_a_failed_store_leaves_the_version_unclaimed(orchestrator, file_storage, library):
    """Recorded only on completion, so the next attempt at that version is not a clash
    with a row that holds nothing."""
    file_storage.fail_put = RuntimeError("the object store is unreachable")
    with pytest.raises(RuntimeError):
        await orchestrator.upload(library.id, upload(WHEEL_NAME))
    file_storage.fail_put = None

    retried = await orchestrator.upload(library.id, upload(WHEEL_NAME, b"different bytes"))

    assert retried.status is WheelStatus.COMPLETED


async def test_download_returns_the_wheel_and_the_name_it_is_stored_under(orchestrator, library):
    wheel = await orchestrator.upload(library.id, upload(WHEEL_NAME, b"the wheel itself"))

    assert await orchestrator.download_wheel(library.id, wheel.id) == (
        b"the wheel itself",
        WHEEL_NAME,
    )


async def test_download_refuses_a_version_that_has_no_wheel_yet(orchestrator, library):
    wheel = await orchestrator.upload(library.id, upload(ARCHIVE_NAME))

    with pytest.raises(WheelNotBuiltError):
        await orchestrator.download_wheel(library.id, wheel.id)


async def test_download_refuses_a_version_whose_build_failed(orchestrator, uow, library):
    wheel = await orchestrator.upload(library.id, upload(ARCHIVE_NAME))
    wheel.mark_as_failed(RuntimeError("the build blew up"))
    await uow.wheel_repo.update(wheel)

    with pytest.raises(WheelNotBuiltError):
        await orchestrator.download_wheel(library.id, wheel.id)


@pytest.mark.parametrize("method", ["retrieve", "download_wheel"])
async def test_a_version_is_only_reachable_through_its_own_library(orchestrator, library, method):
    """The library is part of every lookup, so guessing an id from another one answers
    as if the version did not exist."""
    wheel = await orchestrator.upload(library.id, upload(WHEEL_NAME))

    with pytest.raises(WheelNotFoundError):
        await getattr(orchestrator, method)(library.id + 1, wheel.id)


async def test_remove_marks_the_version_and_leaves_its_files(orchestrator, file_storage, uow, library):
    wheel = await orchestrator.upload(library.id, upload(WHEEL_NAME))

    await orchestrator.remove(library.id, wheel.id)

    assert await orchestrator.list(library.id) == []
    assert await uow.wheel_repo.count_by_library(library.id) == 1
    assert wheel.wheel_key in file_storage.objects


async def test_removing_a_version_frees_its_number_and_its_file(orchestrator, library):
    """What the refusal above promises: replacing a published version is a delete and
    an upload, and neither the version nor the file blocks the second one."""
    wheel = await orchestrator.upload(library.id, upload(WHEEL_NAME, b"identical"))
    await orchestrator.remove(library.id, wheel.id)

    again = await orchestrator.upload(library.id, upload(WHEEL_NAME, b"identical"))

    assert again.id != wheel.id
    assert again.version == "1.0.0"


async def test_removing_a_version_that_is_not_there_is_refused(orchestrator, library):
    with pytest.raises(WheelNotFoundError):
        await orchestrator.remove(library.id, 404)


async def test_a_version_a_venv_installed_cannot_be_removed(orchestrator, uow, library):
    """The library is already unpacked inside that venv's directory. Letting the wheel
    go would leave the venv holding a version nothing can account for."""
    wheel = await orchestrator.upload(library.id, upload(WHEEL_NAME))
    uow.venv_repo.seed(
        Venv(
            name="data",
            libs=[Library(name="my-library", specification=">=1", version="1.0.0", is_custom=True)],
        )
    )

    with pytest.raises(WheelInUseError):
        await orchestrator.remove(library.id, wheel.id)

    assert [stored.id for stored in await orchestrator.list(library.id)] == [wheel.id]


async def test_a_version_only_a_specification_points_at_can_be_removed(orchestrator, uow, library):
    """A specification is a range the build has not chosen from, so it claims nothing.
    This is the hole the version-level guard deliberately leaves open."""
    wheel = await orchestrator.upload(library.id, upload(WHEEL_NAME))
    uow.venv_repo.seed(
        Venv(
            name="data",
            libs=[Library(name="my-library", specification=">=1", is_custom=True)],
        )
    )

    await orchestrator.remove(library.id, wheel.id)

    assert await orchestrator.list(library.id) == []


async def test_another_version_of_the_same_library_does_not_block_removal(
    orchestrator, uow, library
):
    wheel = await orchestrator.upload(library.id, upload(WHEEL_NAME))
    uow.venv_repo.seed(
        Venv(
            name="data",
            libs=[Library(name="my-library", specification=">=1", version="9.9.9", is_custom=True)],
        )
    )

    await orchestrator.remove(library.id, wheel.id)

    assert await orchestrator.list(library.id) == []


async def test_an_unbuilt_version_is_removed_even_while_a_venv_names_the_library(
    orchestrator, uow, library
):
    """It carries no version yet, so nothing can be holding it. Checked with a venv
    that also carries no version, because comparing one absent version with another
    would match and refuse a deletion nobody has a claim on."""
    wheel = await orchestrator.upload(library.id, upload(ARCHIVE_NAME))
    uow.venv_repo.seed(
        Venv(
            name="data",
            libs=[Library(name="my-library", specification=">=1", is_custom=True)],
        )
    )

    await orchestrator.remove(library.id, wheel.id)

    assert await orchestrator.list(library.id) == []
