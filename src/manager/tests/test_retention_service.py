from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from helpers.logger import logger

from repositories.retention_repository import OrgRetentionRow, RetentionInterruptedError
from services.retention_service import RetentionService
from src.shared.retention import DataType, RetentionPolicy, RetentionRule

NOW = datetime(2026, 10, 20, 3, 30, tzinfo=UTC)
THIRTY_DAYS_AGO = datetime(2026, 9, 20, 3, 30, tzinfo=UTC)
NINETY_DAYS_AGO = datetime(2026, 7, 22, 3, 30, tzinfo=UTC)
ONE_HUNDRED_EIGHTY_DAYS_AGO = datetime(2026, 4, 23, 3, 30, tzinfo=UTC)


class FakeRetentionRepository:
    """In-memory stand-in: records each purge and returns or raises what the test configured."""

    def __init__(self, orgs, deleted_by_org=None, errors_by_org=None, list_error=None):
        self.orgs = orgs
        self.deleted_by_org = deleted_by_org or {}
        self.errors_by_org = errors_by_org or {}
        self.list_error = list_error
        self.calls: list[tuple[int | None, datetime]] = []

    async def list_org_retention(self):
        if self.list_error:
            raise self.list_error
        return self.orgs

    async def delete_expired_sessions(self, org_id, cutoff, batch_size=200):
        self.calls.append((org_id, cutoff))
        if org_id in self.errors_by_org:
            raise self.errors_by_org[org_id]
        return self.deleted_by_org.get(org_id, 0)


class FakeChatClient:
    def __init__(self, deleted_by_org=None, errors_by_org=None):
        self.deleted_by_org = deleted_by_org or {}
        self.errors_by_org = errors_by_org or {}
        self.calls: list[tuple[int, datetime]] = []

    async def purge(self, org_id, older_than):
        self.calls.append((org_id, older_than))
        if org_id in self.errors_by_org:
            raise self.errors_by_org[org_id]
        return self.deleted_by_org.get(org_id, 0)


def _interrupted(deleted: int, cause: Exception) -> RetentionInterruptedError:
    try:
        raise RetentionInterruptedError(deleted) from cause
    except RetentionInterruptedError as error:
        return error


def _policy(
    sessions_default=30, sessions_max=None, conversations_default=180, conversations_max=None
):
    return RetentionPolicy(
        rules={
            DataType.SESSIONS: RetentionRule(sessions_default, sessions_max),
            DataType.CONVERSATIONS: RetentionRule(conversations_default, conversations_max),
            DataType.AUDIT: RetentionRule(0, None),
        }
    )


def _service(repository, chat_client=None, policy=None):
    return RetentionService(
        repository=repository,
        chat_client=chat_client,
        policy=policy or _policy(),
        timezone=ZoneInfo("UTC"),
        clock=lambda: NOW,
    )


@pytest.fixture
def log_messages():
    messages: list[str] = []
    handler_id = logger.add(lambda message: messages.append(message.record["message"]))
    yield messages
    logger.remove(handler_id)


@pytest.mark.asyncio
async def test_uses_org_override_and_default():
    repository = FakeRetentionRepository(
        orgs=[
            OrgRetentionRow(org_id=1, sessions_days=None, conversations_days=None),
            OrgRetentionRow(org_id=2, sessions_days=90, conversations_days=None),
            OrgRetentionRow(org_id=3, sessions_days=0, conversations_days=None),
        ]
    )

    await _service(repository).run_retention()

    assert repository.calls == [(1, THIRTY_DAYS_AGO), (2, NINETY_DAYS_AGO), (None, THIRTY_DAYS_AGO)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("org_days", "expected_cutoff"),
    [
        (365, NINETY_DAYS_AGO),
        (0, NINETY_DAYS_AGO),
        (90, NINETY_DAYS_AGO),
        (30, THIRTY_DAYS_AGO),
        (None, THIRTY_DAYS_AGO),
    ],
)
async def test_effective_value_clamped_by_cap(org_days, expected_cutoff):
    repository = FakeRetentionRepository(
        orgs=[OrgRetentionRow(org_id=7, sessions_days=org_days, conversations_days=None)]
    )

    await _service(repository, policy=_policy(sessions_default=30, sessions_max=90)).run_retention()

    assert repository.calls[0] == (7, expected_cutoff)


@pytest.mark.asyncio
async def test_operator_default_of_zero_deletes_nothing():
    repository = FakeRetentionRepository(
        orgs=[OrgRetentionRow(org_id=1, sessions_days=None, conversations_days=None)]
    )
    chat_client = FakeChatClient()

    result = await _service(
        repository, chat_client, _policy(sessions_default=0, conversations_default=0)
    ).run_retention()

    assert repository.calls == []
    assert chat_client.calls == []
    assert result == {"sessions": 0, "conversations": 0}


@pytest.mark.asyncio
async def test_calls_chat_only_when_enabled():
    orgs = [
        OrgRetentionRow(org_id=1, sessions_days=None, conversations_days=None),
        OrgRetentionRow(org_id=2, sessions_days=None, conversations_days=30),
        OrgRetentionRow(org_id=3, sessions_days=None, conversations_days=0),
    ]
    chat_client = FakeChatClient(deleted_by_org={1: 4, 2: 6})

    enabled = await _service(FakeRetentionRepository(orgs), chat_client).run_retention()
    disabled = await _service(FakeRetentionRepository(orgs), chat_client=None).run_retention()

    # Conversations always belong to an organization: there is no org-less chat purge.
    assert chat_client.calls == [(1, ONE_HUNDRED_EIGHTY_DAYS_AGO), (2, THIRTY_DAYS_AGO)]
    assert enabled["conversations"] == 10
    assert disabled["conversations"] == 0


@pytest.mark.asyncio
async def test_one_org_failure_does_not_stop_others(log_messages):
    repository = FakeRetentionRepository(
        orgs=[
            OrgRetentionRow(org_id=1, sessions_days=None, conversations_days=None),
            OrgRetentionRow(org_id=2, sessions_days=None, conversations_days=None),
        ],
        deleted_by_org={2: 5, None: 1},
        errors_by_org={1: RuntimeError("database went away")},
    )
    chat_client = FakeChatClient(
        deleted_by_org={1: 3}, errors_by_org={2: RuntimeError("chat unreachable")}
    )

    result = await _service(repository, chat_client).run_retention()

    assert [org_id for org_id, _ in repository.calls] == [1, 2, None]
    assert [org_id for org_id, _ in chat_client.calls] == [1, 2]
    assert result == {"sessions": 6, "conversations": 3}
    assert any("sessions org=1" in line and "database went away" in line for line in log_messages)
    assert any("conversations org=2" in line and "chat unreachable" in line for line in log_messages)


@pytest.mark.asyncio
async def test_logs_one_line_per_org_and_type(log_messages):
    repository = FakeRetentionRepository(
        orgs=[
            OrgRetentionRow(org_id=1, sessions_days=None, conversations_days=None),
            OrgRetentionRow(org_id=2, sessions_days=0, conversations_days=0),
        ],
        deleted_by_org={1: 12, None: 0},
    )
    chat_client = FakeChatClient(deleted_by_org={1: 7})

    await _service(repository, chat_client).run_retention()

    retention_lines = [line for line in log_messages if line.startswith("Retention ")]
    assert len(retention_lines) == 5
    assert any("sessions org=1 " in line and "deleted 12" in line for line in retention_lines)
    assert any("conversations org=1 " in line and "deleted 7" in line for line in retention_lines)
    assert any("sessions org=2 " in line and "kept forever" in line for line in retention_lines)
    assert any("conversations org=2 " in line and "kept forever" in line for line in retention_lines)
    assert any("sessions org=None " in line and "deleted 0" in line for line in retention_lines)


@pytest.mark.asyncio
async def test_partial_failure_logs_and_counts_what_was_deleted(log_messages):
    repository = FakeRetentionRepository(
        orgs=[OrgRetentionRow(org_id=4, sessions_days=None, conversations_days=None)],
        errors_by_org={4: _interrupted(400, RuntimeError("lock timeout"))},
    )

    result = await _service(repository).run_retention()

    assert result["sessions"] == 400
    assert any(
        "sessions org=4 " in line and "deleted 400" in line and "lock timeout" in line
        for line in log_messages
    )


@pytest.mark.asyncio
async def test_failure_to_list_orgs_still_purges_sessions_without_a_flow(log_messages):
    repository = FakeRetentionRepository(
        orgs=[], deleted_by_org={None: 2}, list_error=RuntimeError("connection refused")
    )

    result = await _service(repository, FakeChatClient()).run_retention()

    assert repository.calls == [(None, THIRTY_DAYS_AGO)]
    assert result == {"sessions": 2, "conversations": 0}
    assert any("connection refused" in line for line in log_messages)


@pytest.mark.asyncio
async def test_start_schedules_the_nightly_job():
    service = _service(FakeRetentionRepository(orgs=[]))

    await service.start()
    job = service.scheduler.get_job("data_retention")
    fields = {field.name: str(field) for field in job.trigger.fields}
    service.stop()

    assert (fields["hour"], fields["minute"]) == ("3", "30")
    assert job.misfire_grace_time == 3600
    assert job.coalesce is True
