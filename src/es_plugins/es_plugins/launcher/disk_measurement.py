"""The launcher's disk measurement of one plugin, in a helper process of its own.

The agent cannot enter a plugin's HOME (0700, the plugin's UID), and the launcher holds no
capability to read past file permissions. The helper the launcher forks for each measurement
therefore takes only the plugin's *filesystem* identity (`setfsgid`, `setfsuid`): it reads
exactly what the plugin itself could, including the plugin's `/proc/<pid>/fd`, while its real,
effective and saved IDs stay root's, so the plugin can neither signal nor trace it to hide
from the measurement.

The helper writes one `DiskUsage` as JSON to a pipe whose read end goes to the agent, and an
alarm ends it if the scan takes longer than `MEASUREMENT_SECONDS`: the launcher's loop never
waits for it, and reaps it like any other child.
"""

import ctypes
import os
import signal
from pathlib import Path

from es_plugins.descriptors import write_all
from es_plugins.disk_usage import measure_plugin_data
from es_plugins.process_table import ProcessTable

MEASUREMENT_SECONDS = 20

_libc = ctypes.CDLL(None, use_errno=True)


def start_measurement(
    home: Path,
    uid: int,
    gid: int,
    *,
    max_bytes: int,
    max_files: int,
    process_table: ProcessTable,
) -> int:
    """Fork the measuring helper; return the read end of the pipe its result arrives on.

    The pipe closes without a result when the helper fails or runs out of time.
    """
    read_end, write_end = os.pipe2(os.O_CLOEXEC)
    helper = os.fork()
    if helper == 0:
        status = 1
        try:
            os.close(read_end)
            signal.signal(signal.SIGALRM, signal.SIG_DFL)
            signal.alarm(MEASUREMENT_SECONDS)
            take_filesystem_identity(uid, gid)
            usage = measure_plugin_data(
                home, uid, max_bytes=max_bytes, max_files=max_files, process_table=process_table
            )
            write_all(write_end, usage.to_json())
            status = 0
        except BaseException:
            status = 1
        finally:
            os._exit(status)
    os.close(write_end)
    return read_end


def take_filesystem_identity(uid: int, gid: int) -> None:
    """Check permissions as `uid`:`gid` from now on, in this process only, with no other group.

    `setfsuid` reports no error; it returns the previous value, so a second call shows whether
    the first took effect.

    Raises:
        PermissionError: The switch did not take effect.
    """
    if os.geteuid() == 0:
        # Root's supplementary groups would let the helper read what the plugin cannot.
        os.setgroups([])
    _libc.setfsgid(gid)
    _libc.setfsuid(uid)
    if _libc.setfsgid(gid) != gid or _libc.setfsuid(uid) != uid:
        raise PermissionError(f"could not take the filesystem identity {uid}:{gid}")
