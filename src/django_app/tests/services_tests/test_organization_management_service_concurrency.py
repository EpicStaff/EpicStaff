"""Concurrency tests for OrganizationManagementService.deactivate_organization.

These tests verify the SELECT FOR UPDATE locking fix that prevents two
concurrent callers from simultaneously deactivating the last two active
organizations, leaving the system with zero active organizations.

The fix under test replaced an unlocked .count() with a single
select_for_update().order_by("pk") that locks the entire active-organization
set. The second concurrent caller blocks on that lock, re-evaluates the set
after the first caller commits, and correctly raises LastActiveOrganizationError.

IMPORTANT: These tests require `transaction=True` because:
  - The default django_db marker wraps tests in a rolled-back transaction,
    which makes SELECT FOR UPDATE a no-op (no real serialization).
  - Cross-thread visibility requires committed rows; transaction=True uses
    actual DB commits and truncates tables at teardown instead.
  - As a consequence, `heal_builtin_roles` (conftest autouse) re-seeds
    built-in Roles at the start of the next database test after teardown.

Requires a real Postgres backend. Do not run against SQLite.
"""

import threading
import time

import pytest
from django.db import connection

from tables.models.rbac_models import Organization
from tables.services.rbac.organization_management_service import (
    OrganizationManagementService,
)
from tables.services.rbac.rbac_exceptions import LastActiveOrganizationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _call_in_thread(fn, results, key):
    """Run fn() in the current thread, store result or exception in results[key].
    Always closes the DB connection on exit so the test DB can be torn down.
    """
    try:
        results[key] = fn()
    except Exception as exc:  # noqa: BLE001
        results[key] = exc
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Test 1: concurrent deactivate_organization on the last two active orgs
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_deactivate_organization_preserves_invariant():
    """Two concurrent callers each try to deactivate one of the last two
    active organizations. Exactly one must succeed; the other must raise
    LastActiveOrganizationError. The system must end with exactly one active
    organization.

    With the old racy .count() both callers see count == 2, both proceed, and
    the system ends with zero active organizations. The SELECT FOR UPDATE fix
    serializes them: the second caller re-evaluates the set after the first
    commits and sees count == 1, then raises.

    Setup: zero out any pre-existing active orgs so the guard fires at the true
    boundary. Create exactly two new active orgs -- org_a (lower pk) and org_b
    (higher pk). The select_for_update().order_by("pk") in the service acquires
    locks in pk order, so Thread A (targeting org_a) holds the lock while
    Thread B (targeting org_b) blocks waiting to acquire that same row set.
    """
    # Eliminate any active orgs that would prevent the guard from firing.
    Organization.objects.filter(is_active=True).update(is_active=False)

    org_a = Organization.objects.create(name="ConcurrencyOrgA", is_active=True)
    org_b = Organization.objects.create(name="ConcurrencyOrgB", is_active=True)

    # org_a has the lower pk (created first), so select_for_update().order_by("pk")
    # acquires the lock on org_a first. Thread A targets org_a and holds the
    # lock while saving; Thread B targets org_b and blocks acquiring that same
    # lock row set.

    a_reached_save = threading.Event()
    release_a = threading.Event()

    original_save = Organization.save

    def patched_save(self, *args, **kwargs):
        if self.pk == org_a.pk and not self.is_active:
            # Thread A has evaluated the guard and is about to persist the
            # deactivation. Signal the main thread and wait before committing.
            a_reached_save.set()
            released = release_a.wait(timeout=10)
            if not released:
                raise RuntimeError("Test timed out waiting for release_a signal")
        original_save(self, *args, **kwargs)

    results = {}

    def thread_a_fn():
        Organization.save = patched_save
        try:
            return OrganizationManagementService().deactivate_organization(
                org_id=org_a.pk
            )
        finally:
            Organization.save = original_save

    def thread_b_fn():
        return OrganizationManagementService().deactivate_organization(org_id=org_b.pk)

    thread_a = threading.Thread(
        target=_call_in_thread, args=(thread_a_fn, results, "a")
    )
    thread_b = threading.Thread(
        target=_call_in_thread, args=(thread_b_fn, results, "b")
    )

    thread_a.start()

    # Wait until Thread A has acquired the FOR UPDATE lock and reached the
    # patched save hook (it holds the lock inside the atomic block).
    reached = a_reached_save.wait(timeout=10)
    assert reached, "Thread A did not reach the save hook within 10s"

    # Now start Thread B. B will issue select_for_update() and block because A
    # holds the lock on the same rows.
    thread_b.start()

    # Give Thread B a moment to actually park inside the DB waiting for the
    # lock. 0.3s is enough for the DB round-trip to reach the lock wait queue.
    time.sleep(0.3)

    # Release Thread A to commit.
    release_a.set()

    thread_a.join(timeout=15)
    thread_b.join(timeout=15)

    assert not thread_a.is_alive(), "Thread A did not finish within 15s"
    assert not thread_b.is_alive(), "Thread B did not finish within 15s"

    result_a = results.get("a")
    result_b = results.get("b")

    errors = [
        r for r in (result_a, result_b) if isinstance(r, LastActiveOrganizationError)
    ]
    successes = [r for r in (result_a, result_b) if not isinstance(r, Exception)]

    assert len(errors) == 1, (
        f"Expected exactly 1 LastActiveOrganizationError; got result_a={result_a!r}, "
        f"result_b={result_b!r}"
    )
    assert (
        len(successes) == 1
    ), f"Expected exactly 1 success; got result_a={result_a!r}, result_b={result_b!r}"

    remaining = Organization.objects.filter(is_active=True).count()
    assert remaining == 1, (
        f"Invariant violated: {remaining} active organizations remain "
        f"(expected 1). Old racy code would leave 0."
    )


# ---------------------------------------------------------------------------
# Test 2: concurrent deactivations with three active orgs -- both must succeed
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_deactivate_organization_both_succeed_with_three_active():
    """Two concurrent callers each deactivate one of three active organizations.
    Both must succeed (count ends at 1), proving the guard only blocks at the
    true last-active boundary and does not over-reject when a spare org exists.

    Thread A (targeting org_a) holds the FOR UPDATE lock while saving.
    Thread B (targeting org_b) blocks, then re-evaluates: it sees org_c still
    active, so the guard allows it through. Both commits land; one org remains.
    """
    Organization.objects.filter(is_active=True).update(is_active=False)

    org_a = Organization.objects.create(name="ThreeOrgA", is_active=True)
    org_b = Organization.objects.create(name="ThreeOrgB", is_active=True)
    Organization.objects.create(name="ThreeOrgC", is_active=True)

    a_reached_save = threading.Event()
    release_a = threading.Event()

    original_save = Organization.save

    def patched_save(self, *args, **kwargs):
        if self.pk == org_a.pk and not self.is_active:
            a_reached_save.set()
            released = release_a.wait(timeout=10)
            if not released:
                raise RuntimeError("Test timed out waiting for release_a signal")
        original_save(self, *args, **kwargs)

    results = {}

    def thread_a_fn():
        Organization.save = patched_save
        try:
            return OrganizationManagementService().deactivate_organization(
                org_id=org_a.pk
            )
        finally:
            Organization.save = original_save

    def thread_b_fn():
        return OrganizationManagementService().deactivate_organization(org_id=org_b.pk)

    thread_a = threading.Thread(
        target=_call_in_thread, args=(thread_a_fn, results, "a")
    )
    thread_b = threading.Thread(
        target=_call_in_thread, args=(thread_b_fn, results, "b")
    )

    thread_a.start()

    reached = a_reached_save.wait(timeout=10)
    assert reached, "Thread A did not reach the save hook within 10s"

    thread_b.start()
    time.sleep(0.3)
    release_a.set()

    thread_a.join(timeout=15)
    thread_b.join(timeout=15)

    assert not thread_a.is_alive(), "Thread A did not finish within 15s"
    assert not thread_b.is_alive(), "Thread B did not finish within 15s"

    result_a = results.get("a")
    result_b = results.get("b")

    errors = [r for r in (result_a, result_b) if isinstance(r, Exception)]
    successes = [r for r in (result_a, result_b) if not isinstance(r, Exception)]

    assert len(errors) == 0, (
        f"Expected both deactivations to succeed; got result_a={result_a!r}, "
        f"result_b={result_b!r}"
    )
    assert (
        len(successes) == 2
    ), f"Expected 2 successes; got result_a={result_a!r}, result_b={result_b!r}"

    remaining = Organization.objects.filter(is_active=True).count()
    assert remaining == 1, (
        f"Expected exactly 1 active organization after both deactivations; "
        f"got {remaining}."
    )
