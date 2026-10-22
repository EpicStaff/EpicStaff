"""Behavior of the venv CRUD orchestrator.

The commit assertions matter as much as the return values: an operation that raises
must leave the unit of work uncommitted.
"""

import pytest

from manager.application.orchestrators import VenvCRUDOrchestrator
from manager.domain.enums import VenvStatus
from manager.domain.errors import VenvNotFoundError
from tests.builders import make_library, make_venv


async def test_create_stores_a_declared_venv_and_commits(uow):
    orchestrator = VenvCRUDOrchestrator(uow)

    venv = await orchestrator.create("data", [make_library(name="pandas")])

    assert venv.id is not None
    assert venv.status is VenvStatus.DECLARED
    assert uow.venv_repo.rows[venv.id].name == "data"
    assert uow.commits == 1


async def test_retrieve_returns_the_stored_venv(uow):
    stored = uow.venv_repo.seed(make_venv(name="data"))[0]

    assert (await VenvCRUDOrchestrator(uow).retrieve(stored.id)).name == "data"


async def test_retrieve_raises_for_a_missing_venv(uow):
    with pytest.raises(VenvNotFoundError):
        await VenvCRUDOrchestrator(uow).retrieve(404)


async def test_update_renames_without_touching_the_libraries(uow):
    stored = uow.venv_repo.seed(
        make_venv(name="old", libs=[make_library(name="pandas")], status=VenvStatus.COMPLETED)
    )[0]

    venv = await VenvCRUDOrchestrator(uow).update(stored.id, name="new", libs=None)

    assert venv.name == "new"
    assert [lib.name for lib in venv.libs] == ["pandas"]
    assert venv.status is VenvStatus.COMPLETED
    assert uow.commits == 1


async def test_update_of_libraries_returns_the_venv_to_declared(uow):
    stored = uow.venv_repo.seed(
        make_venv(status=VenvStatus.FAILED, error="uv blew up", hash="1abc")
    )[0]

    venv = await VenvCRUDOrchestrator(uow).update(
        stored.id, name=None, libs=[make_library(name="numpy")]
    )

    assert [lib.name for lib in venv.libs] == ["numpy"]
    assert venv.status is VenvStatus.DECLARED
    assert venv.error is None
    assert uow.venv_repo.rows[stored.id].status is VenvStatus.DECLARED


async def test_update_with_nothing_to_change_leaves_the_venv_alone(uow):
    stored = uow.venv_repo.seed(make_venv(name="data", status=VenvStatus.COMPLETED))[0]

    venv = await VenvCRUDOrchestrator(uow).update(stored.id, name=None, libs=None)

    assert venv.name == "data"
    assert venv.status is VenvStatus.COMPLETED


async def test_update_of_a_missing_venv_raises_and_does_not_commit(uow):
    with pytest.raises(VenvNotFoundError):
        await VenvCRUDOrchestrator(uow).update(404, name="new", libs=None)
    assert uow.commits == 0


async def test_remove_deletes_the_venv_and_commits(uow):
    stored = uow.venv_repo.seed(make_venv())[0]

    await VenvCRUDOrchestrator(uow).remove(stored.id)

    assert stored.id not in uow.venv_repo.rows
    assert uow.commits == 1


async def test_remove_of_a_missing_venv_raises_and_does_not_commit(uow):
    with pytest.raises(VenvNotFoundError):
        await VenvCRUDOrchestrator(uow).remove(404)
    assert uow.commits == 0


async def test_list_returns_every_venv_with_the_total(uow):
    uow.venv_repo.seed(make_venv(name="a"), make_venv(name="b"), make_venv(name="c"))

    venvs, total = await VenvCRUDOrchestrator(uow).list()

    assert [venv.name for venv in venvs] == ["a", "b", "c"]
    assert total == 3


async def test_list_restricted_to_ids(uow):
    first, _, third = uow.venv_repo.seed(
        make_venv(name="a"), make_venv(name="b"), make_venv(name="c")
    )

    venvs, total = await VenvCRUDOrchestrator(uow).list(ids=[first.id, third.id])

    assert [venv.name for venv in venvs] == ["a", "c"]
    assert total == 2


async def test_list_with_an_empty_id_set_matches_nothing(uow):
    uow.venv_repo.seed(make_venv(name="a"))

    assert await VenvCRUDOrchestrator(uow).list(ids=[]) == ([], 0)


async def test_list_count_is_the_total_before_paging(uow):
    uow.venv_repo.seed(make_venv(name="a"), make_venv(name="b"), make_venv(name="c"))

    venvs, total = await VenvCRUDOrchestrator(uow).list(limit=1, offset=1)

    assert [venv.name for venv in venvs] == ["b"]
    assert total == 3


async def test_retrieve_default_returns_none_when_there_is_no_default(uow):
    uow.venv_repo.seed(make_venv(name="data"))

    assert await VenvCRUDOrchestrator(uow).retrieve_default() is None


async def test_retrieve_default_finds_the_venv_named_default(uow):
    uow.venv_repo.seed(make_venv(name="default"))

    assert (await VenvCRUDOrchestrator(uow).retrieve_default()).name == "default"
