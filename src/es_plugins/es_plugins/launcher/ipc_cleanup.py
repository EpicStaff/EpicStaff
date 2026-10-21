"""Remove the System V IPC objects a removed plugin's UID owns or created.

Shared memory segments, message queues and semaphore sets outlive the processes that made them:
they stay in the container's IPC namespace until removed. A later plugin given the same UID could
open them and read what the removed plugin left there. So the removal deletes every object whose
owner (`uid`) or creator (`cuid`) is the plugin's UID: an object's owner can hand it to another
UID, and its creator can still remove it.

The launcher holds no CAP_IPC_OWNER, so a helper running as the UID removes them, which the owner
and the creator both may. A segment another process still has attached is only marked for
removal and stays listed; that one is reported, not left silently.
"""

import ctypes
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from es_plugins.launcher.kill_by_uid import run_as_user

SYSVIPC_ROOT = Path("/proc/sysvipc")
IPC_RMID = 0
IpcKind = Literal["shm", "msg", "sem"]
# The column naming each object's id in /proc/sysvipc/<kind>.
_ID_COLUMNS: dict[IpcKind, str] = {"shm": "shmid", "msg": "msqid", "sem": "semid"}


class IpcCleanupError(Exception):
    """Objects of the UID are still there after the helper removed them; the message counts them."""


@dataclass(frozen=True)
class IpcObject:
    kind: IpcKind
    identifier: int


def ipc_objects_of(uid: int, root: Path = SYSVIPC_ROOT) -> list[IpcObject]:
    """Every System V IPC object whose owner or creator is `uid`, as /proc lists them."""
    found = []
    for kind, id_column in _ID_COLUMNS.items():
        try:
            lines = (root / kind).read_text().splitlines()
        except FileNotFoundError:
            # A kernel without System V IPC has nothing to remove.
            continue
        if not lines:
            continue
        columns = lines[0].split()
        positions = {name: columns.index(name) for name in (id_column, "uid", "cuid")}
        for line in lines[1:]:
            fields = line.split()
            if len(fields) < len(columns):
                continue
            if uid in (int(fields[positions["uid"]]), int(fields[positions["cuid"]])):
                found.append(IpcObject(kind, int(fields[positions[id_column]])))
    return found


def remove_ipc_objects_of(uid: int, *, root: Path = SYSVIPC_ROOT) -> int:
    """Remove the UID's objects as that UID; return how many there were.

    Raises:
        IpcCleanupError: Some are still listed afterwards.
    """
    objects = ipc_objects_of(uid, root)
    if not objects:
        return 0
    run_as_user(uid, lambda: _remove(objects))
    left = ipc_objects_of(uid, root)
    if left:
        kinds = ", ".join(sorted({item.kind for item in left}))
        raise IpcCleanupError(
            f"{len(left)} System V IPC object(s) ({kinds}) of UID {uid} are still there; another "
            "process may still have a segment attached"
        )
    return len(objects)


def _remove(objects: list[IpcObject]) -> None:
    """Runs in the helper. An object already gone, or not removable, is checked for afterwards."""
    libc = ctypes.CDLL(None, use_errno=True)
    for item in objects:
        if item.kind == "shm":
            libc.shmctl(item.identifier, IPC_RMID, None)
        elif item.kind == "msg":
            libc.msgctl(item.identifier, IPC_RMID, None)
        else:
            libc.semctl(item.identifier, 0, IPC_RMID)
