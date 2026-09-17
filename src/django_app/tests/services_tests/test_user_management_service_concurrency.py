"""Concurrency tests for UserManagementService.revoke_superadmin and
UserManagementService.set_user_active.

These tests verify the SELECT FOR UPDATE locking fix that prevents two
concurrent callers from simultaneously demoting/deactivating the last two
active superadmins, leaving the system with zero active superadmins.

The fix under test replaced an unlocked .count() with a single
select_for_update() that locks the entire active-superadmin set in pk order.
The second concurrent caller blocks on that lock, re-evaluates the set after
the first caller commits, and correctly raises LastSuperadminError.

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
from django.contrib.auth import get_user_model
from django.db import connection

from tables.services.rbac.rbac_exceptions import LastSuperadminError
from tables.services.rbac.user_management_service import UserManagementService

UserModel = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_active_superadmin(email):
    """Create an active superadmin directly (no fixtures: we need pk control)."""
    user = UserModel.objects.create_user(
        email=email,
        password="StrongPass123!",
        is_superadmin=True,
        is_active=True,
    )
    return user


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
# Test 1: concurrent revoke_superadmin on the last two active superadmins
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_revoke_superadmin_preserves_invariant():
    """Two concurrent callers each try to revoke superadmin from one of the
    last two active superadmins. Exactly one must succeed; the other must
    raise LastSuperadminError. The system must end with exactly one active
    superadmin.

    With the old racy .count() both callers see count == 2, both proceed, and
    the system ends with zero active superadmins. The SELECT FOR UPDATE fix
    serializes them: the second caller re-evaluates the set after the first
    commits and sees count == 1, then raises.
    """
    sa_a = _make_active_superadmin("sa-a-revoke@example.com")
    sa_b = _make_active_superadmin("sa-b-revoke@example.com")

    # sa_a has the lower pk (created first), so select_for_update().order_by("pk")
    # acquires the lock on sa_a first. Thread A targets sa_a and holds the
    # lock while saving; Thread B targets sa_b and blocks acquiring that same
    # lock row set.

    a_reached_save = threading.Event()
    release_a = threading.Event()

    original_save = UserModel.save

    def patched_save(self, *args, **kwargs):
        if self.pk == sa_a.pk and not self.is_superadmin:
            # Thread A has evaluated the guard and is about to persist the
            # demotion. Signal the main thread and wait before committing.
            a_reached_save.set()
            released = release_a.wait(timeout=10)
            if not released:
                raise RuntimeError("Test timed out waiting for release_a signal")
        original_save(self, *args, **kwargs)

    results = {}

    def thread_a_fn():
        UserModel.save = patched_save
        try:
            return UserManagementService().revoke_superadmin(
                actor=None, target_user_id=sa_a.pk
            )
        finally:
            UserModel.save = original_save

    def thread_b_fn():
        return UserManagementService().revoke_superadmin(
            actor=None, target_user_id=sa_b.pk
        )

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

    errors = [r for r in (result_a, result_b) if isinstance(r, LastSuperadminError)]
    successes = [r for r in (result_a, result_b) if not isinstance(r, Exception)]

    assert len(errors) == 1, (
        f"Expected exactly 1 LastSuperadminError; got result_a={result_a!r}, "
        f"result_b={result_b!r}"
    )
    assert len(successes) == 1, (
        f"Expected exactly 1 success; got result_a={result_a!r}, result_b={result_b!r}"
    )

    remaining = UserModel.objects.filter(is_superadmin=True, is_active=True).count()
    assert remaining == 1, (
        f"Invariant violated: {remaining} active superadmins remain "
        f"(expected 1). Old racy code would leave 0."
    )


# ---------------------------------------------------------------------------
# Test 2: concurrent set_user_active(value=False) on the last two active
#          superadmins
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_set_user_active_false_preserves_invariant():
    """Two concurrent callers each try to deactivate one of the last two
    active superadmins. Exactly one must succeed; the other must raise
    LastSuperadminError. The system must end with exactly one active
    superadmin.
    """
    sa_a = _make_active_superadmin("sa-a-deact@example.com")
    sa_b = _make_active_superadmin("sa-b-deact@example.com")

    a_reached_save = threading.Event()
    release_a = threading.Event()

    original_save = UserModel.save

    def patched_save(self, *args, **kwargs):
        if self.pk == sa_a.pk and not self.is_active:
            a_reached_save.set()
            released = release_a.wait(timeout=10)
            if not released:
                raise RuntimeError("Test timed out waiting for release_a signal")
        original_save(self, *args, **kwargs)

    results = {}

    def thread_a_fn():
        UserModel.save = patched_save
        try:
            return UserManagementService().set_user_active(
                actor=None, target_user_id=sa_a.pk, value=False
            )
        finally:
            UserModel.save = original_save

    def thread_b_fn():
        return UserManagementService().set_user_active(
            actor=None, target_user_id=sa_b.pk, value=False
        )

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

    errors = [r for r in (result_a, result_b) if isinstance(r, LastSuperadminError)]
    successes = [r for r in (result_a, result_b) if not isinstance(r, Exception)]

    assert len(errors) == 1, (
        f"Expected exactly 1 LastSuperadminError; got result_a={result_a!r}, "
        f"result_b={result_b!r}"
    )
    assert len(successes) == 1, (
        f"Expected exactly 1 success; got result_a={result_a!r}, result_b={result_b!r}"
    )

    remaining = UserModel.objects.filter(is_superadmin=True, is_active=True).count()
    assert remaining == 1, (
        f"Invariant violated: {remaining} active superadmins remain "
        f"(expected 1). Old racy code would leave 0."
    )


# ---------------------------------------------------------------------------
# Test 3: mixed concurrency -- revoke_superadmin vs set_user_active(False)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_mixed_revoke_and_deactivate_preserves_invariant():
    """Thread A calls revoke_superadmin(sa_a); Thread B calls
    set_user_active(sa_b, value=False). Both operations lock the full
    active-superadmin row set in pk order. Exactly one must succeed.
    """
    sa_a = _make_active_superadmin("sa-a-mixed@example.com")
    sa_b = _make_active_superadmin("sa-b-mixed@example.com")

    a_reached_save = threading.Event()
    release_a = threading.Event()

    original_save = UserModel.save

    def patched_save(self, *args, **kwargs):
        # Thread A is revoking sa_a's superadmin flag.
        if self.pk == sa_a.pk and not self.is_superadmin:
            a_reached_save.set()
            released = release_a.wait(timeout=10)
            if not released:
                raise RuntimeError("Test timed out waiting for release_a signal")
        original_save(self, *args, **kwargs)

    results = {}

    def thread_a_fn():
        UserModel.save = patched_save
        try:
            return UserManagementService().revoke_superadmin(
                actor=None, target_user_id=sa_a.pk
            )
        finally:
            UserModel.save = original_save

    def thread_b_fn():
        return UserManagementService().set_user_active(
            actor=None, target_user_id=sa_b.pk, value=False
        )

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

    errors = [r for r in (result_a, result_b) if isinstance(r, LastSuperadminError)]
    successes = [r for r in (result_a, result_b) if not isinstance(r, Exception)]

    assert len(errors) == 1, (
        f"Expected exactly 1 LastSuperadminError; got result_a={result_a!r}, "
        f"result_b={result_b!r}"
    )
    assert len(successes) == 1, (
        f"Expected exactly 1 success; got result_a={result_a!r}, result_b={result_b!r}"
    )

    remaining = UserModel.objects.filter(is_superadmin=True, is_active=True).count()
    assert remaining == 1, (
        f"Invariant violated: {remaining} active superadmins remain "
        f"(expected 1). Old racy code would leave 0."
    )
