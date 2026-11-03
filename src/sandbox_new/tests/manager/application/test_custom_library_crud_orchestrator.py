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


async def test_update_renames_the_library_and_commits(uow):
    orchestrator = CustomLibraryCRUDOrchestrator(uow)
    stored = await orchestrator.create("before")

    library = await orchestrator.update(stored.id, name="After_Rename")

    assert library.name == "after-rename"
    assert uow.custom_library_repo.rows[stored.id].name == "after-rename"


async def test_update_without_a_name_leaves_the_library_as_it_is(uow):
    orchestrator = CustomLibraryCRUDOrchestrator(uow)
    stored = await orchestrator.create("unchanged")

    assert (await orchestrator.update(stored.id, name=None)).name == "unchanged"


async def test_update_to_another_spelling_of_the_name_it_already_has_is_not_a_clash(uow):
    """The library would otherwise be found as the holder of the name and clash with
    itself, which would make the stored spelling impossible to re-send."""
    orchestrator = CustomLibraryCRUDOrchestrator(uow)
    stored = await orchestrator.create("my-library")

    assert (await orchestrator.update(stored.id, name="My.Library")).name == "my-library"


async def test_update_refuses_a_name_another_library_answers_to(uow):
    orchestrator = CustomLibraryCRUDOrchestrator(uow)
    first = await orchestrator.create("first")
    second = await orchestrator.create("second")

    with pytest.raises(CustomLibraryNameTakenError):
        await orchestrator.update(second.id, name="FIRST")

    assert uow.custom_library_repo.rows[second.id].name == "second"
    assert uow.custom_library_repo.rows[first.id].name == "first"


async def test_update_raises_for_a_library_that_is_not_there(uow):
    with pytest.raises(CustomLibraryNotFoundError):
        await CustomLibraryCRUDOrchestrator(uow).update(404, name="whatever")


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
    assert (await orchestrator.retrieve(spared.id)).name == "spared"


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

    assert (await orchestrator.retrieve(library.id)).name == "acme-core"


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
