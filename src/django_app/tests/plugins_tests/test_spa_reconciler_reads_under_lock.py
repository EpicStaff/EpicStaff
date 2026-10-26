"""The frontend repair decides from the plugin's row as it is once locked, so it never undoes a
flag or a `current` link that a lifecycle change wrote just after the repair first read the row."""

import pytest
from plugins.models import Plugin, PluginState
from plugins.packages.spa_publisher import SpaPublisher
from plugins.packages.spa_state_reconciler import SpaStateReconciler

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store")]


@pytest.fixture
def plugin(running_plugin, spa_root):
    return running_plugin(version="0.6.0")


def _commits_meanwhile(monkeypatch, change):
    """Run `change` (another transaction's commit and its file write) right after the repair
    found a mismatch on the row it read first."""
    original = SpaStateReconciler._repairs_needed

    def found_then_changed(self, plugin):
        needed = original(self, plugin)
        change()
        return needed

    monkeypatch.setattr(SpaStateReconciler, "_repairs_needed", found_then_changed)


def test_a_maintenance_flag_written_by_an_advance_that_committed_meanwhile_is_kept(plugin, spa_root, monkeypatch):
    publisher = SpaPublisher(spa_root)
    # The advance's flag is on disk; its state change commits after the repair's first read.
    publisher.set_maintenance("weather", True)
    _commits_meanwhile(monkeypatch, lambda: Plugin.objects.filter(pk=plugin.pk).update(state=PluginState.MAINTENANCE))

    assert SpaStateReconciler(publisher).run() == 0

    assert publisher.maintenance_flag_set("weather")


def test_a_current_link_switched_by_a_completion_that_committed_meanwhile_is_kept(
    plugin, spa_root, installation, monkeypatch
):
    publisher = SpaPublisher(spa_root)
    newer = plugin.current_package
    newer.pk = None
    newer.version = "0.7.0"
    newer.storage_key = "newer-key"
    newer.save()
    (spa_root / "weather" / "0.7.0").mkdir()
    publisher.switch_current("weather", "0.7.0")
    _commits_meanwhile(monkeypatch, lambda: Plugin.objects.filter(pk=plugin.pk).update(current_package=newer))

    assert SpaStateReconciler(publisher).run() == 0

    assert publisher.current_version("weather") == "0.7.0"


def test_a_mismatch_still_there_under_the_lock_is_repaired(plugin, spa_root):
    publisher = SpaPublisher(spa_root)
    publisher.set_maintenance("weather", True)

    assert SpaStateReconciler(publisher).run() == 1

    assert not publisher.maintenance_flag_set("weather")
