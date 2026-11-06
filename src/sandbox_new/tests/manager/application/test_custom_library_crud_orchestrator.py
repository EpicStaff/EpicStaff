"""Behavior of the custom library CRUD orchestrator.

Two rules live here and nowhere else: a name belongs to one library at a time, judged
by the canonical spelling rather than the one that was sent, and a delete is a mark
that takes the library's versions with it, because a background task is what actually
removes files from the object store.

The commit assertions matter as much as the return values: an operation that raises
must leave the unit of work uncommitted.
"""

import pytest

from manager.application.orchestrators import CustomLibraryCRUDOrchestrator
from manager.domain.errors import (
    CustomLibraryInUseError,
    CustomLibraryNameTakenError,
    CustomLibraryNotFoundError,
    UnsupportedUploadError,
)
from manager.domain.models import CustomLibrary, Library, Venv, Wheel

SHA256 = "a" * 64


def make_wheel(library_id: int, suffix: str) -> Wheel:
    return Wheel(
        library_id=library_id,
        source_filename=f"lib-{suffix}.tar.gz",
        upload_sha256=suffix * 64,
    )


async def test_create_stores_the_library_and_commits(uow):
    library = await CustomLibraryCRUDOrchestrator(uow).create("My_Library")

    assert library.id is not None
    assert uow.custom_library_repo.rows[library.id].name == "my-library"
    assert uow.commits == 1


@pytest.mark.parametrize("spelling", ["my-library", "My.Library", "MY_LIBRARY"])
async def test_create_refuses_a_name_another_library_already_answers_to(uow, spelling):
    """Judged on the canonical spelling: a package index treats these as one name, so
    allowing a second row would make two libraries no upload could tell apart."""
    orchestrator = CustomLibraryCRUDOrchestrator(uow)
    await orchestrator.create("my-library")

    with pytest.raises(CustomLibraryNameTakenError):
        await orchestrator.create(spelling)

    assert len(uow.custom_library_repo.rows) == 1
    assert uow.commits == 1


async def test_retrieve_raises_for_a_library_that_is_not_there(uow):
    with pytest.raises(CustomLibraryNotFoundError):
        await CustomLibraryCRUDOrchestrator(uow).retrieve(404)


async def test_retrieve_carries_the_library_versions(uow):
    orchestrator = CustomLibraryCRUDOrchestrator(uow)
    library = await orchestrator.create("acme-core")
    uow.wheel_repo.seed(make_wheel(library.id, "a"), make_wheel(library.id, "b"))

    obj, wheels = await orchestrator.retrieve(library.id)

    assert obj.name == "acme-core"
    assert len(wheels) == 2


async def test_a_page_pairs_every_library_with_its_own_versions(uow):
    orchestrator = CustomLibraryCRUDOrchestrator(uow)
    first = await orchestrator.create("acme-core")
    second = await orchestrator.create("acme-ml")
    empty = await orchestrator.create("acme-cli")
    uow.wheel_repo.seed(make_wheel(first.id, "a"), make_wheel(second.id, "b"))

    pairs, total = await orchestrator.list(None, None, None)

    assert total == 3
    assert {obj.id: [wheel.library_id for wheel in wheels] for obj, wheels in pairs} == {
        first.id: [first.id],
        second.id: [second.id],
        empty.id: [],
    }


async def test_a_page_reads_the_versions_of_every_library_at_once(uow):
    """One query for the page, not one per row: the state of a library's builds is
    shown on every row of the list, and that must not cost a round trip each."""
    orchestrator = CustomLibraryCRUDOrchestrator(uow)
    library = await orchestrator.create("acme-core")
    uow.wheel_repo.seed(make_wheel(library.id, "a"))

    async def refuse(*_args, **_kwargs):
        raise AssertionError("a page must not read one library's versions at a time")

    uow.wheel_repo.list = refuse

    pairs, _total = await orchestrator.list(None, None, None)

    assert len(pairs) == 1


async def test_create_for_names_the_library_after_a_wheels_distribution(uow):
    library = await CustomLibraryCRUDOrchestrator(uow).create_for("My_Library-1.0.0-py3-none-any.whl")

    assert library.name == "my-library"
    assert uow.custom_library_repo.rows[library.id].name == "my-library"


async def test_create_for_refuses_a_wheel_named_after_another_library(uow):
    orchestrator = CustomLibraryCRUDOrchestrator(uow)
    await orchestrator.create("my-library")

    with pytest.raises(CustomLibraryNameTakenError):
        await orchestrator.create_for("my_library-2.0.0-py3-none-any.whl")


async def test_create_for_refuses_a_wheel_filename_that_does_not_parse(uow):
    with pytest.raises(UnsupportedUploadError):
        await CustomLibraryCRUDOrchestrator(uow).create_for("not-a-wheel.whl")


async def test_create_for_a_source_archive_creates_an_unnamed_library(uow):
    """The distribution a source archive builds is not known until it does, so there is
    nothing to name the library by yet."""
    library = await CustomLibraryCRUDOrchestrator(uow).create_for("my-library-1.0.0.tar.gz")

    assert library.name is None
    assert uow.custom_library_repo.rows[library.id].name is None


async def test_remove_marks_the_library_and_every_version_of_it(uow):
    """Marked, not deleted: the files are in the object store, which this transaction
    cannot roll back, so the rows stay until the reaper has removed the files."""
    orchestrator = CustomLibraryCRUDOrchestrator(uow)
    library = await orchestrator.create("doomed")
    uow.wheel_repo.seed(make_wheel(library.id, "a"), make_wheel(library.id, "b"))

    await orchestrator.remove(library.id)

    assert await uow.wheel_repo.list(library.id) == []
    assert await uow.wheel_repo.count_by_library(library.id) == 2
    assert [row.name for row in await uow.custom_library_repo.list_deleted()] == ["doomed"]
    assert len(await uow.wheel_repo.list_deleted()) == 2


async def test_a_removed_library_answers_no_read(uow):
    orchestrator = CustomLibraryCRUDOrchestrator(uow)
    library = await orchestrator.create("doomed")

    await orchestrator.remove(library.id)

    with pytest.raises(CustomLibraryNotFoundError):
        await orchestrator.retrieve(library.id)


async def test_remove_leaves_another_library_and_its_versions_alone(uow):
    orchestrator = CustomLibraryCRUDOrchestrator(uow)
    doomed = await orchestrator.create("doomed")
    spared = await orchestrator.create("spared")
    uow.wheel_repo.seed(make_wheel(doomed.id, "a"), make_wheel(spared.id, "b"))

    await orchestrator.remove(doomed.id)

    assert len(await uow.wheel_repo.list(spared.id)) == 1
    assert (await orchestrator.retrieve(spared.id))[0].name == "spared"


async def test_remove_raises_for_a_library_that_is_not_there(uow):
    with pytest.raises(CustomLibraryNotFoundError):
        await CustomLibraryCRUDOrchestrator(uow).remove(404)


async def test_the_name_of_a_removed_library_can_be_taken_again_at_once(uow):
    """What makes a delete usable: the name is free before the reaper has run, which is
    how a library is replaced rather than renamed around."""
    orchestrator = CustomLibraryCRUDOrchestrator(uow)
    first = await orchestrator.create("my-library")
    await orchestrator.remove(first.id)

    second = await orchestrator.create("my-library")

    assert second.id != first.id
    assert isinstance(second, CustomLibrary)


def declare(uow, name: str, *, custom: bool = True, version: str | None = None):
    """A venv naming `name`, as a stored library or as an ordinary package."""
    return uow.venv_repo.seed(
        Venv(
            name=f"uses {name}",
            libs=[
                Library(
                    name=name, specification=">=1", version=version, is_custom=custom
                )
            ],
        )
    )[0]


async def test_a_library_a_venv_uses_cannot_be_removed(uow):
    """Removing it would leave the venv naming a library that is gone, and its next
    build would fail over a change its author never made."""
    orchestrator = CustomLibraryCRUDOrchestrator(uow)
    library = await orchestrator.create("acme-core")
    declare(uow, "acme-core")

    with pytest.raises(CustomLibraryInUseError):
        await orchestrator.remove(library.id)

    assert (await orchestrator.retrieve(library.id))[0].name == "acme-core"


async def test_the_refusal_says_how_many_environments_are_in_the_way(uow):
    orchestrator = CustomLibraryCRUDOrchestrator(uow)
    library = await orchestrator.create("acme-core")
    declare(uow, "acme-core")
    declare(uow, "acme-core")

    with pytest.raises(CustomLibraryInUseError, match="2"):
        await orchestrator.remove(library.id)


async def test_an_ordinary_package_of_the_same_name_does_not_block_removal(uow):
    """A venv asking the package index for `acme-core` has nothing to do with the
    library stored here, however the two names happen to coincide."""
    orchestrator = CustomLibraryCRUDOrchestrator(uow)
    library = await orchestrator.create("acme-core")
    declare(uow, "acme-core", custom=False)

    await orchestrator.remove(library.id)

    assert [row.name for row in await uow.custom_library_repo.list_deleted()] == ["acme-core"]


async def test_a_library_nothing_uses_is_still_removed_with_its_wheels(uow):
    orchestrator = CustomLibraryCRUDOrchestrator(uow)
    library = await orchestrator.create("acme-core")
    uow.wheel_repo.seed(make_wheel(library.id, "a"))

    await orchestrator.remove(library.id)

    assert await uow.wheel_repo.list(library.id) == []
