"""The store measurement keeps counting what run code writes past the StorageFile index.

Every mint of temporary storage credentials moves the organization's `measure_until` to at
least mint time + credential TTL + 5 minutes + 1 hour, never earlier; credentials that never
expire (TTL <= 0) keep the organization measured indefinitely. The deadline is set before the
mint, so an account whose mint response was lost is measured too.

A measurement stores `max(0, stored bytes - min(indexed bytes before, after listing))` as
`unindexed_bytes`: a row without a size counts as unindexed, a file deleted or uploaded while
the store is listed errs toward an over-count that the next measurement heals, and rows
claiming more than is stored never make it negative. The hourly run measures every
organization whose deadline has not passed and every one still holding unindexed bytes; one
organization failing does not stop the others.

The object store is the in-memory backend, one per organization prefix, as
`get_storage_backend` scopes the real one.
"""

from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from storage_credentials.exceptions import TemporaryCredentialIssueError
from storage_credentials.services.session_credential_service import session_credential_service
from tables.models import OrganizationStorageUsage, PythonCodeResult, StorageFile
from tables.services.storage_service import usage_measurement
from tables.services.storage_service.path_utils import storage_key
from tables.services.storage_service.usage_measurement import (
    measure_due_organizations,
    measure_organization,
    request_measurement,
)
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.services_tests.test_run_code_storage_credentials import gateway  # noqa: F401
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend

pytestmark = pytest.mark.django_db

TTL_HOURS = 6
# TTL + the mint allowance (5 minutes) + one measurement interval (1 hour).
DEADLINE_AFTER_MINT = timedelta(hours=TTL_HOURS + 1, minutes=5)
NEVER = datetime.max.replace(tzinfo=UTC)


@pytest.fixture(autouse=True)
def credential_ttl(settings):
    settings.STORAGE_TEMP_CREDENTIALS_TTL_HOURS = TTL_HOURS


class StoreByPrefix:
    """One in-memory backend per organization prefix."""

    def __init__(self):
        self.backends: dict[str, InMemoryStorageBackend] = {}

    def backend_for(self, organization_prefix: str = "org_1/") -> InMemoryStorageBackend:
        return self.backends.setdefault(
            organization_prefix, InMemoryStorageBackend(organization_prefix=organization_prefix)
        )

    def of(self, org) -> InMemoryStorageBackend:
        return self.backend_for(storage_key(org.pk, ""))


@pytest.fixture
def store(monkeypatch):
    by_prefix = StoreByPrefix()
    monkeypatch.setattr(usage_measurement, "get_storage_backend", by_prefix.backend_for)
    return by_prefix


def _usage(org, **fields) -> OrganizationStorageUsage:
    return OrganizationStorageUsage.objects.create(organization=org, **fields)


def _file_row(org, path: str, size: int | None) -> None:
    StorageFile.objects.create(org=org, path=path, name=path, item_type="file", size=size)


def _deadline_window(call) -> tuple[datetime, datetime]:
    before = timezone.now()
    call()
    after = timezone.now()
    return before + DEADLINE_AFTER_MINT, after + DEADLINE_AFTER_MINT


# --- request_measurement ------------------------------------------------------------------


def test_a_first_request_creates_the_row_with_the_deadline(acme):
    earliest, latest = _deadline_window(lambda: request_measurement(acme.pk))

    usage = OrganizationStorageUsage.objects.get(organization=acme)
    assert earliest <= usage.measure_until <= latest
    assert (usage.unindexed_bytes, usage.measured_at) == (0, None)


@pytest.mark.parametrize(
    "current_deadline", [None, timedelta(hours=-2), timedelta(hours=1)], ids=["none", "passed", "sooner"]
)
def test_a_request_extends_a_sooner_deadline_and_keeps_the_measured_bytes(acme, current_deadline):
    measured_at = timezone.now() - timedelta(minutes=30)
    _usage(
        acme,
        unindexed_bytes=42,
        measured_at=measured_at,
        measure_until=None if current_deadline is None else timezone.now() + current_deadline,
    )

    earliest, latest = _deadline_window(lambda: request_measurement(acme.pk))

    usage = OrganizationStorageUsage.objects.get(organization=acme)
    assert earliest <= usage.measure_until <= latest
    assert (usage.unindexed_bytes, usage.measured_at) == (42, measured_at)


def test_a_request_never_moves_a_later_deadline_earlier(acme):
    later = timezone.now() + timedelta(days=30)
    _usage(acme, measure_until=later)

    request_measurement(acme.pk)

    assert OrganizationStorageUsage.objects.get(organization=acme).measure_until == later


@pytest.mark.parametrize("ttl_hours", [0, -1])
def test_credentials_that_never_expire_are_measured_indefinitely(acme, settings, ttl_hours):
    settings.STORAGE_TEMP_CREDENTIALS_TTL_HOURS = ttl_hours

    request_measurement(acme.pk)
    settings.STORAGE_TEMP_CREDENTIALS_TTL_HOURS = TTL_HOURS
    request_measurement(acme.pk)

    assert OrganizationStorageUsage.objects.get(organization=acme).measure_until == NEVER


def test_a_request_touches_only_its_own_organization(acme, beta):
    beta_deadline = timezone.now() + timedelta(minutes=10)
    _usage(beta, measure_until=beta_deadline)

    request_measurement(acme.pk)

    assert OrganizationStorageUsage.objects.get(organization=beta).measure_until == beta_deadline


# --- minting requests the measurement -------------------------------------------------------


def _issue_for_test_run(org):
    result = PythonCodeResult.objects.create(execution_id=f"exec-{org.pk}", org=org)
    return session_credential_service.issue_for_test_run(
        python_code_result=result, storage_allowed_paths=["test-runs/x/"], org_id=org.pk
    )


def test_every_mint_keeps_the_organization_measured_past_its_credentials(gateway, acme):  # noqa: F811
    earliest, latest = _deadline_window(lambda: _issue_for_test_run(acme))

    assert len(gateway.created) == 1
    assert earliest <= OrganizationStorageUsage.objects.get(organization=acme).measure_until <= latest


def test_an_account_whose_mint_response_was_lost_is_still_measured(gateway, acme):  # noqa: F811
    async def created_then_lost(**kwargs):
        gateway.created.append(kwargs)
        raise TimeoutError("the response never arrived")

    gateway.create_service_account = created_then_lost

    with pytest.raises(TemporaryCredentialIssueError):
        _issue_for_test_run(acme)

    assert len(gateway.created) == 1
    assert OrganizationStorageUsage.objects.get(organization=acme).measure_until > timezone.now()


# --- measure_organization --------------------------------------------------------------------


def test_bytes_without_a_row_or_without_a_size_are_unindexed(store, acme):
    backend = store.of(acme)
    backend.put_bytes("indexed.txt", b"x" * 100)
    _file_row(acme, "indexed.txt", 100)
    backend.put_bytes("unread-size.txt", b"x" * 40)
    _file_row(acme, "unread-size.txt", None)
    backend.put_bytes("written-by-code/out.bin", b"x" * 250)
    _usage(acme)

    before = timezone.now()
    measure_organization(acme.pk)

    usage = OrganizationStorageUsage.objects.get(organization=acme)
    assert usage.unindexed_bytes == 290
    assert before <= usage.measured_at <= timezone.now()


def test_rows_claiming_more_than_is_stored_leave_zero_unindexed(store, acme):
    store.of(acme).put_bytes("small.txt", b"x" * 100)
    _file_row(acme, "small.txt", 500)
    _usage(acme, unindexed_bytes=77)

    measure_organization(acme.pk)

    assert OrganizationStorageUsage.objects.get(organization=acme).unindexed_bytes == 0


def test_only_the_organization_s_own_prefix_is_measured(store, acme, beta):
    store.of(beta).put_bytes("beta.bin", b"x" * 900)
    store.of(acme).put_bytes("acme.bin", b"x" * 10)
    _usage(acme)

    measure_organization(acme.pk)

    assert OrganizationStorageUsage.objects.get(organization=acme).unindexed_bytes == 10


def test_an_organization_that_never_minted_gets_no_row(store, acme):
    store.of(acme).put_bytes("a.bin", b"x" * 10)

    measure_organization(acme.pk)

    assert not OrganizationStorageUsage.objects.filter(organization=acme).exists()


def test_an_upload_landing_while_listing_is_over_counted_until_the_next_measurement(
    store, acme, monkeypatch
):
    backend = store.of(acme)
    _usage(acme)
    list_store = backend.total_size

    def listing_while_an_upload_lands(prefix):
        backend.put_bytes("landed.bin", b"x" * 300)
        _file_row(acme, "landed.bin", 300)
        return list_store(prefix)

    monkeypatch.setattr(backend, "total_size", listing_while_an_upload_lands)
    measure_organization(acme.pk)
    assert OrganizationStorageUsage.objects.get(organization=acme).unindexed_bytes == 300

    monkeypatch.setattr(backend, "total_size", list_store)
    measure_organization(acme.pk)
    assert OrganizationStorageUsage.objects.get(organization=acme).unindexed_bytes == 0


def test_a_delete_landing_after_listing_is_over_counted_until_the_next_measurement(
    store, acme, monkeypatch
):
    backend = store.of(acme)
    backend.put_bytes("doomed.bin", b"x" * 300)
    _file_row(acme, "doomed.bin", 300)
    _usage(acme)
    list_store = backend.total_size

    def listing_then_a_delete_lands(prefix):
        listed = list_store(prefix)
        backend.delete("doomed.bin")
        StorageFile.objects.filter(org=acme, path="doomed.bin").delete()
        return listed

    monkeypatch.setattr(backend, "total_size", listing_then_a_delete_lands)
    measure_organization(acme.pk)
    assert OrganizationStorageUsage.objects.get(organization=acme).unindexed_bytes == 300

    monkeypatch.setattr(backend, "total_size", list_store)
    measure_organization(acme.pk)
    assert OrganizationStorageUsage.objects.get(organization=acme).unindexed_bytes == 0


# --- measure_due_organizations ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("measure_until", "unindexed_bytes", "measured"),
    [
        (timedelta(minutes=5), 0, True),
        ("never", 0, True),
        (timedelta(minutes=-5), 50, True),
        (timedelta(minutes=-5), 0, False),
        (None, 0, False),
    ],
    ids=[
        "deadline-ahead",
        "credentials-never-expire",
        "deadline-passed-bytes-left",
        "deadline-passed-nothing-left",
        "never-minted",
    ],
)
def test_the_hourly_run_measures_organizations_within_their_deadline_or_holding_bytes(
    store, acme, measure_until, unindexed_bytes, measured
):
    if measure_until == "never":
        deadline = NEVER
    elif measure_until is None:
        deadline = None
    else:
        deadline = timezone.now() + measure_until
    _usage(acme, measure_until=deadline, unindexed_bytes=unindexed_bytes)
    store.of(acme).put_bytes("direct.bin", b"x" * 70)

    measure_due_organizations()

    usage = OrganizationStorageUsage.objects.get(organization=acme)
    if measured:
        assert (usage.unindexed_bytes, usage.measured_at is not None) == (70, True)
    else:
        assert (usage.unindexed_bytes, usage.measured_at) == (unindexed_bytes, None)


def test_one_organization_failing_does_not_stop_the_others(store, acme, beta, monkeypatch):
    soon = timezone.now() + timedelta(hours=1)
    _usage(acme, measure_until=soon, unindexed_bytes=5)
    _usage(beta, measure_until=soon)
    store.of(beta).put_bytes("direct.bin", b"x" * 70)

    def store_is_down(prefix):
        raise ConnectionError("store is down")

    monkeypatch.setattr(store.of(acme), "total_size", store_is_down)

    measure_due_organizations()

    acme_usage = OrganizationStorageUsage.objects.get(organization=acme)
    assert (acme_usage.unindexed_bytes, acme_usage.measured_at) == (5, None)
    assert OrganizationStorageUsage.objects.get(organization=beta).unindexed_bytes == 70
