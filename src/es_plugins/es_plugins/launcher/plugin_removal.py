"""The launcher's removal of one plugin's files, in a helper process of its own.

Deleting a plugin's HOME can take seconds (one at the default file cap holds 100,000 files), and
the launcher answers every plugin's requests one at a time: spawns, kills, the memory watchdog's
kills among them. So `RemovePlugin` kills the UID's processes itself, which is quick and must come
first, and forks this helper for the rest, in order:

1. the HOME, emptied by a helper of its own running as the UID (`purge_plugin_data`);
2. `plugins/<id>/`, `/run/es_plugins/<id>/` and the empty `venvs/<id>/` (`remove_plugin_trees`);
3. the System V IPC objects of the UID (`ipc_cleanup`), last: an object another UID holds
   attached can delay freeing the UID, but never keep the plugin's files.

The helper writes one JSON result to a pipe whose read end goes to the agent, `{"ok": true,
"ipc_objects": n}` or `{"ok": false, "error": "..."}`, and an alarm ends it after
`REMOVAL_SECONDS`, closing the pipe without a result. The launcher's loop never waits for it, and
reaps it like any other child.
"""

import json
import os
import signal
import time

from loguru import logger

from es_plugins.descriptors import write_all
from es_plugins.launcher.directory_setup import DirectorySetup, DirectorySetupError
from es_plugins.launcher.ipc_cleanup import IpcCleanupError, remove_ipc_objects_of

REMOVAL_SECONDS = 600
MAX_RESULT_BYTES = 4096


def start_removal(directory_setup: DirectorySetup, plugin: str, uid: int) -> tuple[int, int]:
    """Fork the removing helper; return its pid and the read end of the pipe its result arrives on.

    The caller has killed every process of the UID.
    """
    read_end, write_end = os.pipe2(os.O_CLOEXEC)
    helper = os.fork()
    if helper == 0:
        status = 1
        try:
            os.close(read_end)
            signal.signal(signal.SIGALRM, signal.SIG_DFL)
            signal.alarm(REMOVAL_SECONDS)
            write_all(write_end, json.dumps(_remove(directory_setup, plugin, uid)).encode())
            status = 0
        except BaseException:
            status = 1
        finally:
            os._exit(status)
    os.close(write_end)
    return helper, read_end


def _remove(directory_setup: DirectorySetup, plugin: str, uid: int) -> dict:
    started = time.monotonic()
    try:
        directory_setup.purge_plugin_data(plugin, uid)
        directory_setup.remove_plugin_trees(plugin)
        ipc_objects = remove_ipc_objects_of(uid)
    except (DirectorySetupError, IpcCleanupError, OSError) as error:
        return {"ok": False, "error": str(error)[:2000]}
    logger.info(
        "plugins.launcher.plugin_removed plugin={} uid={} ipc_objects={} seconds={:.2f}",
        plugin,
        uid,
        ipc_objects,
        time.monotonic() - started,
    )
    return {"ok": True, "ipc_objects": ipc_objects}
