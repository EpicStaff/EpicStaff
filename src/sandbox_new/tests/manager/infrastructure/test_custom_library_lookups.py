"""The bulk lookups a venv build and the delete guards need.

Each one answers for a whole venv in a single call. The build resolves every custom
entry at once rather than one library at a time, because it runs on a five second tick
and a venv may name several.

These run against the in-memory repositories. The Piccolo versions speak to Postgres,
and the one that cannot be checked here -- the JSONB containment query -- is verified
against a real database as part of finishing this work.
"""

import pytest

from manager.domain.enums import WheelStatus
from manager.domain.models import CustomLibrary, Library, Venv, Wheel
from tests.builders import make_library, make_venv
from tests.fakes.repositories import (
    FakeCustomLibraryRepository,
    FakeVenvRepository,
    FakeWheelRepository,
)


def make_wheel(library_id: int, version: str) -> Wheel:
    return Wheel(
        library_id=library_id,
        wheel_filename=f"lib-{version}-py3-none-any.whl",
        upload_sha256=f"{library_id}{version}".ljust(64, "0"),
        version=version,
        status=WheelStatus.COMPLETED,
    )


@pytest.fixture
def libraries() -> FakeCustomLibraryRepository:
    return FakeCustomLibraryRepository()


@pytest.fixture
def wheels() -> FakeWheelRepository:
    return FakeWheelRepository()


@pytest.fixture
def venvs() -> FakeVenvRepository:
    return FakeVenvRepository()


async def test_libraries_are_fetched_for_a_whole_venv_at_once(libraries):
    libraries.seed(
        CustomLibrary(name="acme-core"),
        CustomLibrary(name="acme-tools"),
        CustomLibrary(name="unrelated"),
    )

    found = await libraries.list_by_names(["acme-core", "acme-tools"])

    assert {library.name for library in found} == {"acme-core", "acme-tools"}


async def test_a_name_nobody_stored_is_simply_absent_from_the_result(libraries):
    """The caller compares what it asked for with what came back, and names the ones
    that are missing. Raising here would lose the other libraries of the same venv."""
    libraries.seed(CustomLibrary(name="acme-core"))

    found = await libraries.list_by_names(["acme-core", "never-uploaded"])

    assert [library.name for library in found] == ["acme-core"]


async def test_asking_for_no_library_returns_none_rather_than_every_one(libraries):
    """A venv with no custom entries asks for an empty list, and must not be handed
    the whole table."""
    libraries.seed(CustomLibrary(name="acme-core"))

    assert await libraries.list_by_names([]) == []


async def test_a_removed_library_is_not_offered_by_name(libraries):
    """Marked deleted means it stops answering reads, and a venv naming it has to
    fail rather than quietly install what is on its way out."""
    stored = libraries.seed(CustomLibrary(name="acme-core"))[0]
    stored.mark_as_deleted()
    await libraries.update(stored)

    assert await libraries.list_by_names(["acme-core"]) == []


async def test_wheels_are_fetched_for_every_library_of_a_venv_at_once(wheels):
    wheels.seed(
        make_wheel(library_id=1, version="1.0.0"),
        make_wheel(library_id=1, version="2.0.0"),
        make_wheel(library_id=2, version="3.0.0"),
        make_wheel(library_id=9, version="4.0.0"),
    )

    found = await wheels.list_by_library_ids([1, 2])

    assert sorted(wheel.version for wheel in found) == ["1.0.0", "2.0.0", "3.0.0"]


async def test_asking_for_no_library_returns_no_wheels(wheels):
    wheels.seed(make_wheel(library_id=1, version="1.0.0"))

    assert await wheels.list_by_library_ids([]) == []


async def test_a_removed_wheel_is_not_offered_to_a_build(wheels):
    """It is on its way out of the object store, so a build must not install it."""
    stored = wheels.seed(make_wheel(library_id=1, version="1.0.0"))[0]
    stored.mark_as_deleted()
    await wheels.update(stored)

    assert await wheels.list_by_library_ids([1]) == []


async def test_the_venvs_using_a_library_are_the_ones_that_marked_it_custom(venvs):
    venvs.seed(
        make_venv(
            name="uses it",
            libs=[make_library(name="acme-core", specification=">=1", is_custom=True)],
        ),
        make_venv(
            name="names it as an index package",
            libs=[make_library(name="acme-core", specification=">=1")],
        ),
        make_venv(name="unrelated", libs=[make_library(name="requests")]),
    )

    found = await venvs.list_using_custom_library("acme-core")

    assert [venv.name for venv in found] == ["uses it"]


async def test_a_library_nothing_uses_has_no_venvs(venvs):
    venvs.seed(make_venv(name="data", libs=[make_library(name="requests")]))

    assert await venvs.list_using_custom_library("acme-core") == []


async def test_a_venv_is_found_whatever_state_its_build_is_in(venvs):
    """A venv that failed to build still names the library, and deleting it under the
    venv would change why the next attempt fails."""
    venvs.seed(
        Venv(
            name="failed one",
            libs=[Library(name="acme-core", specification=">=1", is_custom=True)],
            status="failed",
            error="uv blew up",
        )
    )

    assert [venv.name for venv in await venvs.list_using_custom_library("acme-core")] == [
        "failed one"
    ]
