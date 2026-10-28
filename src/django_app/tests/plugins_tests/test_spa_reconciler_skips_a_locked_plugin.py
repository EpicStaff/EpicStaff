"""The frontend repair never waits for a plugin another transaction holds, as an approval writing
its files does: it skips the plugin, and a later pass repairs it."""

import threading
import time

import pytest
from django.db import transaction
from plugins.lifecycle.lifecycle_locks import lock_plugin
from plugins.packages.spa_publisher import SpaPublisher
from plugins.packages.spa_state_reconciler import SpaStateReconciler

from tests.plugins_tests.lock_concurrency import Side

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures("plugins_enabled", "package_store")]


def test_a_plugin_held_by_another_transaction_is_skipped_then_repaired_by_the_next_pass(running_plugin, spa_root):
    running_plugin(version="0.6.0")
    publisher = SpaPublisher(spa_root)
    # A wrong flag: the plugin runs, so no maintenance page should be served.
    publisher.set_maintenance("weather", True)
    holding = threading.Event()
    release = threading.Event()

    def hold_the_plugin():
        with transaction.atomic():
            lock_plugin("weather")
            holding.set()
            release.wait(20)

    holder = Side("approval", hold_the_plugin)
    holder.start()
    try:
        assert holding.wait(15)
        started = time.monotonic()
        skipped = SpaStateReconciler(publisher).run()
        seconds = time.monotonic() - started
        flag_while_held = publisher.maintenance_flag_set("weather")
    finally:
        release.set()
        holder.join(20)

    assert holder.error is None
    assert (skipped, flag_while_held) == (0, True)
    assert seconds < 5
    assert SpaStateReconciler(publisher).run() == 1
    assert not publisher.maintenance_flag_set("weather")
