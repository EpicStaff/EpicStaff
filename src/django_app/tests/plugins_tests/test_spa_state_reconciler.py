"""The frontend repair: the maintenance flag and `current` put back in line with each plugin."""

import pytest
from plugins.models import Plugin, PluginState
from plugins.packages.spa_publisher import SpaPublisher
from plugins.packages.spa_state_reconciler import SpaStateReconciler

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store")]


@pytest.fixture
def plugin(running_plugin, spa_root):
    return running_plugin(version="0.6.0")


def _set_state(plugin, state):
    Plugin.objects.filter(pk=plugin.pk).update(state=state)


def test_the_flag_exists_exactly_for_plugins_in_maintenance(plugin, spa_root, log_messages):
    publisher = SpaPublisher(spa_root)
    _set_state(plugin, PluginState.MAINTENANCE)

    assert SpaStateReconciler(publisher).run() == 1
    assert publisher.maintenance_flag_set("weather")

    _set_state(plugin, PluginState.RUNNING)
    assert SpaStateReconciler(publisher).run() == 1
    assert not publisher.maintenance_flag_set("weather")
    assert sum(message.startswith("plugins.spa.repaired ") for message in log_messages) == 2


def test_a_current_link_that_names_another_version_is_switched_back(plugin, spa_root, installation):
    publisher = SpaPublisher(spa_root)
    (spa_root / "weather" / "0.5.0").mkdir()
    publisher.switch_current("weather", "0.5.0")

    assert SpaStateReconciler(publisher).run() == 1

    assert publisher.current_version("weather") == "0.6.0"


def test_a_missing_version_directory_is_left_alone(plugin, spa_root):
    publisher = SpaPublisher(spa_root)
    (spa_root / "weather" / "0.5.0").mkdir()
    publisher.switch_current("weather", "0.5.0")
    (spa_root / "weather" / "0.6.0").rename(spa_root / "weather" / "0.6.0-gone")

    assert SpaStateReconciler(publisher).run() == 0

    assert publisher.current_version("weather") == "0.5.0"


def test_a_plugin_without_a_frontend_gets_no_link(plugin, spa_root):
    from plugins.models import PluginPackage

    PluginPackage.objects.filter(pk=plugin.current_package_id).update(spa_file_count=0)
    (spa_root / "weather" / "current").unlink()

    assert SpaStateReconciler(SpaPublisher(spa_root)).run() == 0
    assert not (spa_root / "weather" / "current").exists()


def test_nothing_happens_while_the_spa_volume_is_not_mounted(plugin, settings, tmp_path):
    settings.PLUGINS_SPA_ROOT = tmp_path / "not-mounted"
    _set_state(plugin, PluginState.MAINTENANCE)

    assert SpaStateReconciler().run() == 0
    assert not (tmp_path / "not-mounted").exists()


def test_nothing_is_removed(plugin, spa_root):
    (spa_root / "weather" / "0.5.0").mkdir()
    _set_state(plugin, PluginState.MAINTENANCE)

    SpaStateReconciler(SpaPublisher(spa_root)).run()

    assert (spa_root / "weather" / "0.5.0").is_dir() and (spa_root / "weather" / "0.6.0").is_dir()
