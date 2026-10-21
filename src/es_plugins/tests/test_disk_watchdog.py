import os
from types import SimpleNamespace

import pytest

from es_plugins.agent.launcher_client import LauncherError
from es_plugins.disk_usage import DiskUsage
from es_plugins.node_disk import (
    FLOOR_BYTES,
    FLOOR_FILES,
    INSTALL_RESERVE_BYTES,
    INSTALL_RESERVE_FILES,
    NodeDisk,
    NodeDiskFullError,
)
from es_plugins.supervisor.disk_watchdog import FURTHER_FALL_BYTES, DiskWatchdog

MIB = 1024 * 1024
PLENTY = 100 * 1024 * MIB


class Volume:
    """A statvfs whose free bytes and inodes the test sets."""

    def __init__(self, free_bytes=PLENTY, free_files=10**7, total_files=10**8):
        self.free_bytes = free_bytes
        self.free_files = free_files
        self.total_files = total_files

    def __call__(self, path):
        return SimpleNamespace(
            f_bavail=self.free_bytes // 4096,
            f_frsize=4096,
            f_favail=self.free_files,
            f_files=self.total_files,
        )


class RecordingSupervisor:
    def __init__(self, plugin, uid, watching=True):
        self.plugin = plugin
        self.uid = uid
        self.watching = watching
        self.failed_for = []

    def fail_for(self, reason):
        # As the real supervisor: once its run has ended in `failed`, it is no longer watching.
        self.failed_for.append(reason)
        self.watching = False


class MeasuringLauncher:
    """Answers each measurement with a pipe carrying the usage the test set for that UID."""

    def __init__(self):
        self.usage: dict[int, DiskUsage | bytes] = {}
        self.requests = []

    async def measure_disk(self, plugin, uid, max_bytes, max_files):
        self.requests.append((plugin, uid, max_bytes, max_files))
        result = self.usage[uid]
        if isinstance(result, Exception):
            raise result
        read_end, write_end = os.pipe()
        os.write(write_end, result if isinstance(result, bytes) else result.to_json())
        os.close(write_end)
        return read_end


def watchdog_for(supervisors, launcher, volume=None):
    return DiskWatchdog(
        launcher,
        lambda: supervisors,
        NodeDisk("/var/lib/es_plugins", statvfs=volume or Volume()),
        max_megabytes=64,
        max_files=1000,
    )


async def test_a_plugin_over_its_disk_cap_is_failed_and_the_others_are_left_alone():
    weather, notes = RecordingSupervisor("weather", 20001), RecordingSupervisor("notes", 20002)
    launcher = MeasuringLauncher()
    launcher.usage = {20001: DiskUsage(bytes=70 * MIB, files=12), 20002: DiskUsage(10 * MIB, 5)}

    failed = await watchdog_for([weather, notes], launcher).check_once()

    assert failed == [weather]
    assert weather.failed_for == ["uses 70 MB of disk, more than its limit of 64 MB"]
    assert notes.failed_for == []
    assert launcher.requests[0] == ("weather", 20001, 64 * MIB, 1000)


async def test_a_plugin_over_its_file_cap_is_failed():
    weather = RecordingSupervisor("weather", 20001)
    launcher = MeasuringLauncher()
    launcher.usage = {20001: DiskUsage(bytes=MIB, files=1001)}

    await watchdog_for([weather], launcher).check_once()

    assert weather.failed_for == ["has 1001 files, more than its limit of 1000 files"]


async def test_a_plugin_whose_disk_use_cannot_be_measured_is_failed():
    weather = RecordingSupervisor("weather", 20001)
    launcher = MeasuringLauncher()
    launcher.usage = {20001: DiskUsage(MIB, 3, problem="hidden cannot be read")}

    await watchdog_for([weather], launcher).check_once()

    assert weather.failed_for == ["its disk use cannot be measured: hidden cannot be read"]


@pytest.mark.parametrize("answer", [b"", b"not json", LauncherError("the launcher refused")])
async def test_a_measurement_that_brings_no_result_fails_nobody(answer):
    weather = RecordingSupervisor("weather", 20001)
    launcher = MeasuringLauncher()
    launcher.usage = {20001: answer}

    assert await watchdog_for([weather], launcher).check_once() == []
    assert weather.failed_for == []


async def test_a_stopped_plugin_is_not_measured():
    stopped = RecordingSupervisor("weather", 20001, watching=False)
    launcher = MeasuringLauncher()

    await watchdog_for([stopped], launcher).check_once()

    assert launcher.requests == []


async def test_below_the_floor_the_plugin_using_the_most_disk_is_stopped_while_space_keeps_falling():
    small, large = RecordingSupervisor("small", 20001), RecordingSupervisor("large", 20002)
    launcher = MeasuringLauncher()
    launcher.usage = {20001: DiskUsage(5 * MIB, 900), 20002: DiskUsage(50 * MIB, 10)}
    volume = Volume(free_bytes=FLOOR_BYTES - MIB)
    watchdog = watchdog_for([small, large], launcher, volume)

    await watchdog.check_once()
    assert len(large.failed_for) == 1
    assert large.failed_for[0].startswith("the node's disk is almost full (only 511 MB free)")
    assert large.failed_for[0].endswith("this plugin uses the most of it (50 MB)")

    # Stopping a plugin frees nothing: with the space no lower, nobody else is stopped.
    await watchdog.check_once()
    assert small.failed_for == []

    volume.free_bytes -= FURTHER_FALL_BYTES
    await watchdog.check_once()
    assert len(small.failed_for) == 1
    assert len(large.failed_for) == 1


async def test_below_the_inode_floor_the_plugin_with_the_most_files_is_stopped():
    small, large = RecordingSupervisor("small", 20001), RecordingSupervisor("large", 20002)
    launcher = MeasuringLauncher()
    launcher.usage = {20001: DiskUsage(5 * MIB, 900), 20002: DiskUsage(50 * MIB, 10)}

    await watchdog_for([small, large], launcher, Volume(free_files=FLOOR_FILES - 1)).check_once()

    assert small.failed_for == [
        f"the node's disk is almost full (only {FLOOR_FILES - 1} free inodes), and this plugin "
        "uses the most of it (900 files)"
    ]
    assert large.failed_for == []


def test_installing_needs_the_reserve_free():
    NodeDisk("/data", statvfs=Volume(free_bytes=INSTALL_RESERVE_BYTES)).check_room_for_install()

    with pytest.raises(NodeDiskFullError, match="has only 2047 MB free, and installing needs 2048 MB"):
        NodeDisk("/data", statvfs=Volume(free_bytes=INSTALL_RESERVE_BYTES - MIB)).check_room_for_install()
    with pytest.raises(NodeDiskFullError, match="free inodes"):
        NodeDisk(
            "/data", statvfs=Volume(free_files=INSTALL_RESERVE_FILES - 1)
        ).check_room_for_install()


def test_a_file_system_without_an_inode_limit_is_checked_for_bytes_only():
    unlimited = Volume(free_files=0, total_files=0)

    NodeDisk("/data", statvfs=unlimited).check_room_for_install()
    assert NodeDisk("/data", statvfs=unlimited).below_floor() is None
