import json
import os
import stat
import threading

import pytest

from es_plugins.launcher import directory_setup
from es_plugins.launcher.directory_setup import DirectorySetup, DirectorySetupError, Ownership
from es_plugins.layout import AGENT_UID

PLUGIN = "weather"
PLUGIN_UID = 20001


def mode_of(path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


def node_wide_modes(layout):
    return {
        layout.data_root: 0o755,
        layout.agent_directory: 0o750,
        layout.plugin_data_root: 0o711,
        layout.plugins_root: 0o711,
        layout.venvs_root: 0o711,
        layout.logs_root: 0o700,
        layout.backups_root: 0o700,
        layout.run_root: 0o711,
        layout.launcher_socket_directory: 0o750,
        layout.heartbeat_file: 0o644,
        layout.egress_policy_directory: 0o755,
    }


def plugin_modes(layout):
    return {
        layout.plugin_home(PLUGIN): 0o700,
        layout.plugin_temporary_directory(PLUGIN): 0o700,
        layout.plugin_code_root(PLUGIN): 0o750,
        layout.plugin_venvs(PLUGIN): 0o750,
        layout.plugin_run_directory(PLUGIN): 0o711,
    }


def test_the_node_tree_gets_its_modes(layout, unprivileged_setup):
    assert {path: mode_of(path) for path in node_wide_modes(layout)} == node_wide_modes(layout)


def test_the_egress_policy_directory_is_left_to_the_volume_and_never_created(layout, own_ownership):
    layout.egress_policy_directory.rmdir()
    setup = DirectorySetup(layout, launcher=own_ownership, agent=own_ownership, plugin_gid=os.getgid())

    setup.prepare_tree()

    assert not layout.egress_policy_directory.exists()


def test_setup_repairs_an_existing_tree_whatever_modes_it_has(layout, unprivileged_setup):
    # Deepest first: a directory set to 0000 cannot be entered to change what is below it.
    for path in sorted(node_wide_modes(layout), key=lambda path: len(path.parts), reverse=True):
        os.chmod(path, 0o000 if path.is_dir() else 0o600)

    unprivileged_setup.prepare_tree()
    unprivileged_setup.prepare_tree()

    assert {path: mode_of(path) for path in node_wide_modes(layout)} == node_wide_modes(layout)


def test_a_plugins_directories_get_their_modes_and_setup_is_idempotent(
    layout, unprivileged_setup
):
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())
    (layout.plugin_temporary_directory(PLUGIN) / "cache").write_text("kept")
    os.chmod(layout.plugin_temporary_directory(PLUGIN), 0o000)
    os.chmod(layout.plugin_home(PLUGIN), 0o500)

    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())

    assert {path: mode_of(path) for path in plugin_modes(layout)} == plugin_modes(layout)
    assert (layout.plugin_temporary_directory(PLUGIN) / "cache").read_text() == "kept"


def change_times(paths) -> dict:
    """Inode and change time: a chmod or chown, even to the same values, moves the change time."""
    return {path: (os.lstat(path).st_ino, os.lstat(path).st_ctime_ns) for path in paths}


def test_preparing_a_correct_tree_and_plugin_again_touches_nothing(layout, unprivileged_setup):
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())
    paths = [path for path in node_wide_modes(layout) if path.is_dir()] + list(plugin_modes(layout))
    before = change_times(paths)

    unprivileged_setup.prepare_tree()
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())

    # A running plugin's HOME is never taken back to root and handed over again.
    assert change_times(paths) == before


def test_a_link_planted_as_the_plugins_tmp_is_replaced_not_followed(
    tmp_path, layout, unprivileged_setup
):
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())
    target = tmp_path / "elsewhere"
    target.mkdir(mode=0o755)
    temporary = layout.plugin_temporary_directory(PLUGIN)
    temporary.rmdir()
    temporary.symlink_to(target)

    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())

    assert temporary.is_dir() and not temporary.is_symlink()
    assert mode_of(target) == 0o755


def test_a_link_in_place_of_a_node_directory_is_refused(tmp_path, layout, unprivileged_setup):
    target = tmp_path / "elsewhere"
    target.mkdir()
    layout.plugins_root.rmdir()
    layout.plugins_root.symlink_to(target)

    with pytest.raises(DirectorySetupError):
        unprivileged_setup.prepare_tree()


def unpack_source(layout, version="0.2.0"):
    source = layout.unpacked_source(PLUGIN, version)
    (source / "weather_plugin").mkdir(parents=True)
    (source / "weather_plugin" / "__init__.py").write_text("")
    (source / "weather_plugin" / "app.py").write_text("app = None\n")
    return source


def test_code_is_installed_as_read_only_files_and_directories(layout, unprivileged_setup):
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())
    unpack_source(layout)

    unprivileged_setup.install_code(PLUGIN, "0.2.0")

    installed = layout.plugin_source(PLUGIN, "0.2.0")
    assert (installed / "weather_plugin" / "app.py").read_text() == "app = None\n"
    assert mode_of(installed / "weather_plugin" / "app.py") == 0o644
    assert mode_of(installed / "weather_plugin") == 0o755
    assert mode_of(layout.plugin_code(PLUGIN, "0.2.0")) == 0o755
    assert sorted(entry.name for entry in layout.plugin_code_root(PLUGIN).iterdir()) == ["0.2.0"]


def test_installing_a_version_again_replaces_it(layout, unprivileged_setup):
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())
    source = unpack_source(layout)
    unprivileged_setup.install_code(PLUGIN, "0.2.0")
    (source / "weather_plugin" / "app.py").write_text("app = 'new'\n")
    (source / "weather_plugin" / "__init__.py").unlink()

    unprivileged_setup.install_code(PLUGIN, "0.2.0")

    installed = layout.plugin_source(PLUGIN, "0.2.0") / "weather_plugin"
    assert sorted(entry.name for entry in installed.iterdir()) == ["app.py"]
    assert (installed / "app.py").read_text() == "app = 'new'\n"
    assert sorted(entry.name for entry in layout.plugin_code_root(PLUGIN).iterdir()) == ["0.2.0"]


def test_a_link_inside_the_unpacked_code_is_refused(tmp_path, layout, unprivileged_setup):
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())
    source = unpack_source(layout)
    secret = tmp_path / "another-plugins-secret"
    secret.write_text("secret")
    (source / "weather_plugin" / "stolen.py").symlink_to(secret)

    with pytest.raises(DirectorySetupError, match="stolen.py"):
        unprivileged_setup.install_code(PLUGIN, "0.2.0")

    assert not layout.plugin_code(PLUGIN, "0.2.0").exists()


def test_a_fifo_in_the_unpacked_code_is_refused(layout, unprivileged_setup):
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())
    source = unpack_source(layout)
    os.mkfifo(source / "weather_plugin" / "pipe.py")

    with pytest.raises(DirectorySetupError, match="pipe.py is neither a regular file"):
        unprivileged_setup.install_code(PLUGIN, "0.2.0")


def test_a_fifo_swapped_in_after_the_check_is_refused_without_blocking(
    layout, unprivileged_setup, monkeypatch
):
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())
    source = unpack_source(layout)
    os.mkfifo(source / "weather_plugin" / "pipe.py")
    real_lstat = os.lstat

    def lstat_seeing_a_file(name, *arguments, **options):
        # The agent replaced a regular file by a FIFO between the launcher's lstat and open.
        if name == "pipe.py":
            regular = list(real_lstat(source / "weather_plugin" / "app.py"))
            return os.stat_result(regular)
        return real_lstat(name, *arguments, **options)

    monkeypatch.setattr(directory_setup.os, "lstat", lstat_seeing_a_file)
    outcome = []

    def install():
        try:
            unprivileged_setup.install_code(PLUGIN, "0.2.0")
        except DirectorySetupError as error:
            outcome.append(str(error))

    # A blocking open of a FIFO with no writer would never return: run it where it can hang.
    installing = threading.Thread(target=install, daemon=True)
    installing.start()
    installing.join(5)

    assert not installing.is_alive(), "the launcher blocked opening a FIFO"
    assert outcome and "pipe.py is not a regular file" in outcome[0]


def test_a_link_in_the_path_to_the_unpacked_code_is_refused(tmp_path, layout, unprivileged_setup):
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "0.2.0" / "backend" / "src").mkdir(parents=True)
    (elsewhere / "0.2.0" / "backend" / "src" / "other.py").write_text("other plugin code")
    layout.unpack_directory.mkdir(parents=True)
    (layout.unpack_directory / PLUGIN).symlink_to(elsewhere)

    with pytest.raises(DirectorySetupError):
        unprivileged_setup.install_code(PLUGIN, "0.2.0")


@pytest.mark.parametrize("version", ["..", "../other", "0.2.0/../x", ".hidden"])
def test_a_version_that_is_not_one_path_segment_is_refused(layout, unprivileged_setup, version):
    with pytest.raises(ValueError):
        unprivileged_setup.install_code(PLUGIN, version)


@pytest.mark.root
def test_root_gives_every_directory_its_owner(layout):
    setup = DirectorySetup(layout)
    setup.prepare_tree()
    setup.prepare_plugin(PLUGIN, PLUGIN_UID)

    owners = {
        layout.data_root: (0, 0),
        layout.agent_directory: (AGENT_UID, 0),
        layout.logs_root: (AGENT_UID, AGENT_UID),
        layout.backups_root: (AGENT_UID, AGENT_UID),
        layout.launcher_socket_directory: (0, AGENT_UID),
        layout.heartbeat_file: (AGENT_UID, AGENT_UID),
        layout.plugin_home(PLUGIN): (PLUGIN_UID, PLUGIN_UID),
        layout.plugin_temporary_directory(PLUGIN): (PLUGIN_UID, PLUGIN_UID),
        layout.plugin_code_root(PLUGIN): (0, PLUGIN_UID),
        layout.plugin_venvs(PLUGIN): (AGENT_UID, PLUGIN_UID),
        layout.plugin_run_directory(PLUGIN): (0, 0),
        layout.egress_policy_directory: (AGENT_UID, AGENT_UID),
    }
    assert {path: (os.lstat(path).st_uid, os.lstat(path).st_gid) for path in owners} == owners


@pytest.mark.root
def test_purging_empties_the_home_as_the_plugin_and_removes_it(layout):
    setup = DirectorySetup(layout)
    setup.prepare_tree()
    setup.prepare_plugin(PLUGIN, PLUGIN_UID)
    nested = layout.plugin_home(PLUGIN) / "state" / "deep"
    nested.mkdir(parents=True)
    (nested / "data.db").write_text("x")
    for path in (layout.plugin_home(PLUGIN) / "state", nested, nested / "data.db"):
        os.chown(path, PLUGIN_UID, PLUGIN_UID)
    os.chmod(nested, 0o500)

    setup.purge_plugin_data(PLUGIN, PLUGIN_UID)

    assert not layout.plugin_home(PLUGIN).exists()


def test_a_test_setup_owns_everything_itself(own_ownership):
    assert own_ownership == Ownership(os.getuid(), os.getgid())


def _plugin_trees(layout, plugin: str) -> None:
    """What the node keeps for a plugin outside its HOME, as a test without root can make it."""
    code = layout.plugin_code(plugin, "0.2.0") / "backend" / "src"
    code.mkdir(parents=True)
    (code / "app.py").write_text("app = None\n")
    staging = layout.plugin_code_root(plugin) / ".install-0.3.0"
    staging.mkdir()
    layout.plugin_run_directory(plugin).mkdir(parents=True, exist_ok=True)
    (layout.plugin_run_directory(plugin) / "runtime.json").write_text("{}")
    layout.plugin_venvs(plugin).mkdir(parents=True, exist_ok=True)


def test_removing_a_plugin_deletes_its_code_run_directory_and_empty_venvs_root_and_again_does_nothing(
    layout, unprivileged_setup
):
    for plugin in (PLUGIN, "notes"):
        unprivileged_setup.prepare_plugin(plugin, os.getuid())
        _plugin_trees(layout, plugin)

    unprivileged_setup.remove_plugin_trees(PLUGIN)
    unprivileged_setup.remove_plugin_trees(PLUGIN)

    for path in (layout.plugin_code_root(PLUGIN), layout.plugin_run_directory(PLUGIN), layout.plugin_venvs(PLUGIN)):
        assert not os.path.lexists(path)
    assert (layout.plugin_code("notes", "0.2.0") / "backend" / "src" / "app.py").exists()
    assert (layout.plugin_run_directory("notes") / "runtime.json").exists()
    assert layout.plugin_venvs("notes").is_dir()


def test_a_link_in_or_in_place_of_a_plugins_trees_is_deleted_never_followed(layout, unprivileged_setup, tmp_path):
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())
    _plugin_trees(layout, PLUGIN)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("not the plugin's")
    (layout.plugin_code_root(PLUGIN) / "0.2.0" / "link").symlink_to(outside)
    (layout.plugin_run_directory(PLUGIN) / "link").symlink_to(outside / "keep.txt")
    os.rmdir(layout.plugin_venvs(PLUGIN))
    layout.plugin_venvs(PLUGIN).symlink_to(outside)

    unprivileged_setup.remove_plugin_trees(PLUGIN)

    assert not os.path.lexists(layout.plugin_code_root(PLUGIN))
    assert not os.path.lexists(layout.plugin_venvs(PLUGIN))
    assert sorted(os.listdir(outside)) == ["keep.txt"]
    assert (outside / "keep.txt").read_text() == "not the plugin's"


def test_a_venvs_directory_that_still_holds_something_is_refused_by_name(layout, unprivileged_setup):
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())
    _plugin_trees(layout, PLUGIN)
    (layout.plugin_venv(PLUGIN, "0.2.0") / "bin").mkdir(parents=True)

    with pytest.raises(DirectorySetupError, match=f"{layout.plugin_venvs(PLUGIN)} is not empty"):
        unprivileged_setup.remove_plugin_trees(PLUGIN)

    assert (layout.plugin_venv(PLUGIN, "0.2.0") / "bin").is_dir()


@pytest.mark.root
def test_root_removes_everything_of_a_plugin_with_its_processes_and_ipc_objects(layout):
    import ctypes
    import subprocess

    from es_plugins.launcher import protocol
    from es_plugins.launcher.ipc_cleanup import ipc_objects_of
    from es_plugins.launcher.kill_by_uid import run_as_user
    from es_plugins.launcher.privileged_launcher import LauncherOperations
    from es_plugins.process_table import ProcessTable
    from es_plugins.uid_range import UidRange

    setup = DirectorySetup(layout)
    setup.prepare_tree()
    setup.prepare_plugin(PLUGIN, PLUGIN_UID)
    private = layout.plugin_home(PLUGIN) / "private"
    private.mkdir()
    (private / "secret.txt").write_text("the plugin's")
    for path in (private, private / "secret.txt"):
        os.chown(path, PLUGIN_UID, PLUGIN_UID)
    os.chmod(private, 0o700)
    code = layout.plugin_code(PLUGIN, "0.2.0") / "backend" / "src"
    code.mkdir(parents=True)
    (code / "app.py").write_text("app = None\n")
    (layout.plugin_run_directory(PLUGIN) / "runtime.json").write_text("{}")
    def create_a_shared_memory_segment():
        if ctypes.CDLL(None).shmget(0, 4096, 0o1000 | 0o600) < 0:
            raise OSError("shmget failed")

    assert run_as_user(PLUGIN_UID, create_a_shared_memory_segment)
    sleeper = subprocess.Popen(
        ["/bin/sleep", "300"], user=PLUGIN_UID, group=PLUGIN_UID, extra_groups=[], start_new_session=True
    )
    operations = LauncherOperations(layout, UidRange(PLUGIN_UID, PLUGIN_UID + 9), setup, ProcessTable())

    def remove() -> dict:
        _, [result_pipe] = operations.handle(protocol.RemovePlugin(plugin=PLUGIN, uid=PLUGIN_UID), [])
        with os.fdopen(result_pipe, "rb") as result:
            outcome = json.loads(result.read())
        operations.reap()
        return outcome

    assert remove() == {"ok": True, "ipc_objects": 1}

    assert sleeper.wait(timeout=5) is not None
    assert ipc_objects_of(PLUGIN_UID) == []
    for path in (
        layout.plugin_home(PLUGIN),
        layout.plugin_code_root(PLUGIN),
        layout.plugin_run_directory(PLUGIN),
        layout.plugin_venvs(PLUGIN),
    ):
        assert not os.path.lexists(path)
    assert remove() == {"ok": True, "ipc_objects": 0}


def test_pruning_keeps_only_the_version_the_plugin_runs_and_again_does_nothing(layout, unprivileged_setup, tmp_path):
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())
    for version in ("0.6.0", "0.7.0", "0.7.1"):
        code = layout.plugin_code(PLUGIN, version) / "backend" / "src"
        code.mkdir(parents=True)
        (code / "app.py").write_text(version)
    (layout.plugin_code_root(PLUGIN) / ".install-0.7.1").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "kept.txt").write_text("not the plugin's")
    (layout.plugin_code_root(PLUGIN) / "0.5.0").symlink_to(outside)

    removed = unprivileged_setup.prune_code(PLUGIN, "0.7.0")
    again = unprivileged_setup.prune_code(PLUGIN, "0.7.0")

    assert removed == [".install-0.7.1", "0.5.0", "0.6.0", "0.7.1"]
    assert again == []
    assert os.listdir(layout.plugin_code_root(PLUGIN)) == ["0.7.0"]
    assert (layout.plugin_code(PLUGIN, "0.7.0") / "backend" / "src" / "app.py").read_text() == "0.7.0"
    assert (outside / "kept.txt").read_text() == "not the plugin's"


def test_pruning_a_plugin_without_code_does_nothing(layout, unprivileged_setup):
    assert unprivileged_setup.prune_code(PLUGIN, "0.7.0") == []


@pytest.mark.parametrize("version", ["..", "../other", ".hidden"])
def test_pruning_refuses_a_version_that_is_not_one_path_segment(layout, unprivileged_setup, version):
    with pytest.raises(ValueError):
        unprivileged_setup.prune_code(PLUGIN, version)

