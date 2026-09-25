import asyncio

import pytest

from tables.exceptions import OrgUploadLimitReached, UploadSlotsBusy
from tables.services.storage_service.upload_admission import UploadAdmission

ORG_A = 1
ORG_B = 2


def _admission(*, max_concurrency=4, per_org_limit=2, slot_timeout=0.05) -> UploadAdmission:
    return UploadAdmission(
        max_concurrency=max_concurrency, per_org_limit=per_org_limit, slot_timeout=slot_timeout
    )


@pytest.mark.asyncio
async def test_a_full_worker_answers_503_with_retry_after_once_the_wait_runs_out():
    admission = _admission(max_concurrency=1, slot_timeout=0.05)

    async with admission.admit(ORG_A):
        with pytest.raises(UploadSlotsBusy) as caught:
            async with admission.admit(ORG_B):
                pytest.fail("admitted without a free slot")

    assert caught.value.status_code == 503
    assert caught.value.headers == {"Retry-After": "1"}
    assert admission.uploads_of(ORG_B) == 0


@pytest.mark.asyncio
async def test_a_waiter_gets_the_slot_as_soon_as_it_frees_up():
    admission = _admission(max_concurrency=1, slot_timeout=5)
    release = asyncio.Event()

    async def _hold():
        async with admission.admit(ORG_A):
            await release.wait()

    holder = asyncio.create_task(_hold())
    await asyncio.sleep(0)
    asyncio.get_running_loop().call_later(0.02, release.set)

    async with admission.admit(ORG_B):
        assert admission.uploads_of(ORG_B) == 1
    await holder


@pytest.mark.asyncio
async def test_the_per_org_limit_answers_429_but_other_orgs_still_get_in():
    admission = _admission(per_org_limit=2, slot_timeout=7)

    async with admission.admit(ORG_A), admission.admit(ORG_A):
        with pytest.raises(OrgUploadLimitReached) as caught:
            async with admission.admit(ORG_A):
                pytest.fail("third upload of one org admitted")
        async with admission.admit(ORG_B):
            assert admission.uploads_of(ORG_B) == 1

    assert caught.value.status_code == 429
    assert caught.value.wait == 7
    assert admission.uploads_of(ORG_A) == 0


@pytest.mark.asyncio
async def test_uploads_waiting_for_a_slot_count_against_their_org():
    # otherwise one org could line up every waiter and take each slot as it frees
    admission = _admission(max_concurrency=1, per_org_limit=2, slot_timeout=5)
    release = asyncio.Event()

    async def _hold(org_id):
        async with admission.admit(org_id):
            await release.wait()

    running = asyncio.create_task(_hold(ORG_B))
    await asyncio.sleep(0)
    waiting = [asyncio.create_task(_hold(ORG_A)) for _ in range(2)]
    await asyncio.sleep(0.01)

    with pytest.raises(OrgUploadLimitReached):
        async with admission.admit(ORG_A):
            pass

    release.set()
    await asyncio.gather(running, *waiting)
    assert admission.uploads_of(ORG_A) == admission.uploads_of(ORG_B) == 0


@pytest.mark.asyncio
async def test_bookkeeping_is_released_when_the_upload_fails():
    admission = _admission(max_concurrency=1, per_org_limit=1)

    with pytest.raises(RuntimeError):
        async with admission.admit(ORG_A):
            raise RuntimeError("upload failed")

    assert admission.uploads_of(ORG_A) == 0
    async with admission.admit(ORG_A):  # both the org share and the slot came back
        pass


@pytest.mark.asyncio
async def test_bookkeeping_is_released_when_the_upload_is_cancelled():
    admission = _admission(max_concurrency=1, per_org_limit=1)
    entered = asyncio.Event()

    async def _upload():
        async with admission.admit(ORG_A):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(_upload())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert admission.uploads_of(ORG_A) == 0
    async with admission.admit(ORG_A):
        pass


@pytest.mark.asyncio
async def test_a_waiter_cancelled_before_it_got_a_slot_leaves_nothing_behind():
    admission = _admission(max_concurrency=1, per_org_limit=1, slot_timeout=5)

    async with admission.admit(ORG_B):
        waiter = asyncio.create_task(admission.admit(ORG_A).__aenter__())
        await asyncio.sleep(0.01)
        assert admission.uploads_of(ORG_A) == 1
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

    assert admission.uploads_of(ORG_A) == 0
    async with admission.admit(ORG_A):
        pass


@pytest.mark.asyncio
async def test_no_slot_timeout_waits_for_a_slot_however_long_it_takes():
    admission = _admission(max_concurrency=1, slot_timeout=None)
    release = asyncio.Event()

    async def _hold():
        async with admission.admit(ORG_A):
            await release.wait()

    holder = asyncio.create_task(_hold())
    await asyncio.sleep(0)
    asyncio.get_running_loop().call_later(0.05, release.set)

    async with admission.admit(ORG_B):
        assert admission.uploads_of(ORG_B) == 1
    await holder


@pytest.mark.asyncio
async def test_an_over_the_limit_org_without_a_slot_timeout_gets_429_without_retry_after():
    admission = _admission(per_org_limit=1, slot_timeout=None)

    async with admission.admit(ORG_A):
        with pytest.raises(OrgUploadLimitReached) as caught:
            async with admission.admit(ORG_A):
                pytest.fail("second upload of one org admitted")

    assert caught.value.wait is None
