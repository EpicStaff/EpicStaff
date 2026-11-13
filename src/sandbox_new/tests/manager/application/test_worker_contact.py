"""What the manager knows about the worker: boot identity, contact, parked polls.

Liveness is judged from contact alone, never from job duration. A new boot id
supersedes the old one; a superseded id is a zombie and is refused by AGE, so a crash
loop of any length cannot push a live zombie out of memory. Waiting pollers are the
intake's free-slot probe and must never go negative or leak.
"""

import pytest

from manager.application.worker_contact import WorkerContact


@pytest.fixture
def contact(clock) -> WorkerContact:
    return WorkerContact(clock=clock)


def test_the_first_boot_is_accepted_and_stays_accepted(contact):
    assert contact.accept_boot("boot-1") is True
    assert contact.accept_boot("boot-1") is True


def test_a_new_boot_supersedes_the_current_one(contact):
    contact.accept_boot("boot-1")

    assert contact.accept_boot("boot-2") is True
    assert contact.accept_boot("boot-1") is False
    assert contact.accept_boot("boot-2") is True


def test_a_superseded_boot_stays_refused_through_a_crash_loop(contact):
    """Superseded ids are remembered by age, so any number of newer boots cannot push a
    recent zombie out of memory."""
    contact.accept_boot("boot-1")
    for index in range(2, 20):
        contact.accept_boot(f"boot-{index}")

    assert contact.accept_boot("boot-1") is False


def test_a_superseded_boot_is_forgotten_after_the_memory_window(contact, clock):
    contact.accept_boot("boot-1")
    contact.accept_boot("boot-2")

    clock.advance(60.1)

    assert contact.accept_boot("boot-1") is True


def test_a_boot_heard_from_recently_is_not_silent(contact, clock):
    contact.record_seen("boot-1")

    clock.advance(59.9)

    assert contact.boot_is_silent("boot-1", 60.0) is False


def test_a_boot_not_heard_from_for_too_long_is_silent(contact, clock):
    contact.record_seen("boot-1")

    clock.advance(60.1)

    assert contact.boot_is_silent("boot-1", 60.0) is True


def test_a_boot_never_heard_from_counts_as_silent(contact, clock):
    clock.advance(60.1)

    assert contact.boot_is_silent("boot-never", 60.0) is True


def test_a_fresh_manager_does_not_call_the_worker_silent(contact, clock):
    clock.advance(59.9)

    assert contact.worker_is_silent(60.0) is False


def test_a_worker_with_no_contact_for_too_long_is_silent(contact, clock):
    clock.advance(60.1)

    assert contact.worker_is_silent(60.0) is True


def test_any_contact_resets_the_workers_silence(contact, clock):
    clock.advance(59.0)
    contact.record_seen("boot-1")
    clock.advance(59.0)

    assert contact.worker_is_silent(60.0) is False


def test_waiting_pollers_are_counted_and_never_go_negative(contact):
    contact.add_waiting_poller()
    contact.add_waiting_poller()
    assert contact.waiting_pollers == 2

    contact.remove_waiting_poller()
    contact.remove_waiting_poller()
    contact.remove_waiting_poller()
    assert contact.waiting_pollers == 0
