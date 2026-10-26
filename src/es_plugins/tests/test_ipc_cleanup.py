"""Removing a removed plugin's System V IPC objects before its UID can be given to another."""

import ctypes

import pytest

from es_plugins.launcher.ipc_cleanup import IpcObject, ipc_objects_of, remove_ipc_objects_of
from es_plugins.launcher.kill_by_uid import run_as_user

PLUGIN_UID = 20021
OTHER_UID = 20022
IPC_PRIVATE = 0
IPC_CREAT = 0o1000
IPC_RMID = 0


def test_objects_the_uid_owns_or_created_are_found_and_no_others(tmp_path):
    (tmp_path / "shm").write_text(
        "       key      shmid perms                  size  cpid  lpid nattch   uid   gid  cuid  cgid      atime      dtime      ctime                   rss                  swap\n"
        "         0         11   600                  4096   100   100      0 20021 20021 20021 20021          0          0 1700000000                     0                     0\n"
        "         0         12   600                  4096   100   100      0 20022 20022 20022 20022          0          0 1700000000                     0                     0\n"
    )
    (tmp_path / "msg").write_text(
        "       key      msqid perms      cbytes       qnum lspid lrpid   uid   gid  cuid  cgid      stime      rtime      ctime\n"
        # Given away to another UID by its creator: its creator can still remove it.
        "         0         21   600           0          0     0     0 20022 20022 20021 20021          0          0 1700000000\n"
    )
    (tmp_path / "sem").write_text(
        "       key      semid perms      nsems   uid   gid  cuid  cgid      otime      ctime\n"
        # Handed to the plugin's UID by another creator: its owner can remove it.
        "         0         31   600          1 20021 20021 20022 20022          0 1700000000\n"
    )

    assert ipc_objects_of(PLUGIN_UID, tmp_path) == [
        IpcObject("shm", 11, created=True),
        IpcObject("msg", 21, created=True),
        IpcObject("sem", 31, created=False),
    ]
    assert ipc_objects_of(OTHER_UID, tmp_path) == [
        IpcObject("shm", 12, created=True),
        IpcObject("msg", 21, created=False),
        IpcObject("sem", 31, created=True),
    ]


def test_a_kernel_without_system_v_ipc_has_nothing_to_remove(tmp_path):
    assert ipc_objects_of(PLUGIN_UID, tmp_path) == []
    assert remove_ipc_objects_of(PLUGIN_UID, root=tmp_path) == 0


def _create_one_of_each() -> None:
    """Runs as the UID: a shared memory segment, a message queue and a semaphore set."""
    libc = ctypes.CDLL(None, use_errno=True)
    for created in (
        libc.shmget(IPC_PRIVATE, 4096, IPC_CREAT | 0o600),
        libc.msgget(IPC_PRIVATE, IPC_CREAT | 0o600),
        libc.semget(IPC_PRIVATE, 1, IPC_CREAT | 0o600),
    ):
        if created < 0:
            raise OSError(ctypes.get_errno(), "creating a System V IPC object failed")


def _remove_all_of(uid: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    for item in ipc_objects_of(uid):
        if item.kind == "shm":
            libc.shmctl(item.identifier, IPC_RMID, None)
        elif item.kind == "msg":
            libc.msgctl(item.identifier, IPC_RMID, None)
        else:
            libc.semctl(item.identifier, 0, IPC_RMID)


@pytest.mark.root
def test_the_plugins_objects_are_removed_as_the_plugin_and_another_uids_stay():
    assert run_as_user(PLUGIN_UID, _create_one_of_each)
    assert run_as_user(OTHER_UID, _create_one_of_each)
    try:
        assert sorted(item.kind for item in ipc_objects_of(PLUGIN_UID)) == ["msg", "sem", "shm"]

        assert remove_ipc_objects_of(PLUGIN_UID) == 3

        assert ipc_objects_of(PLUGIN_UID) == []
        assert sorted(item.kind for item in ipc_objects_of(OTHER_UID)) == ["msg", "sem", "shm"]
        assert remove_ipc_objects_of(PLUGIN_UID) == 0
    finally:
        run_as_user(OTHER_UID, lambda: _remove_all_of(OTHER_UID))
        run_as_user(PLUGIN_UID, lambda: _remove_all_of(PLUGIN_UID))


IPC_SET = 1


class _ShmidDs(ctypes.Structure):
    """The head of `struct shmid_ds` on Linux: its `struct ipc_perm`, then the rest unread."""

    _fields_ = [
        ("key", ctypes.c_int),
        ("uid", ctypes.c_uint),
        ("gid", ctypes.c_uint),
        ("cuid", ctypes.c_uint),
        ("cgid", ctypes.c_uint),
        ("mode", ctypes.c_ushort),
        ("padding", ctypes.c_ubyte * 256),
    ]


@pytest.mark.root
def test_a_segment_another_uid_hands_over_and_keeps_attached_never_stops_the_removal():
    import os

    libc = ctypes.CDLL(None, use_errno=True)
    libc.shmat.restype = ctypes.c_void_p
    ready_read, ready_write = os.pipe()
    done_read, done_write = os.pipe()
    holder = os.fork()
    if holder == 0:
        # Another plugin's UID: make a segment, hand it to the removed plugin's UID, keep it attached.
        status = 1
        try:
            os.setgroups([])
            os.setresgid(OTHER_UID, OTHER_UID, OTHER_UID)
            os.setresuid(OTHER_UID, OTHER_UID, OTHER_UID)
            segment = libc.shmget(IPC_PRIVATE, 4096, IPC_CREAT | 0o600)
            libc.shmat(segment, None, 0)
            described = _ShmidDs()
            libc.shmctl(segment, 2, ctypes.byref(described))  # IPC_STAT
            described.uid = PLUGIN_UID
            if libc.shmctl(segment, IPC_SET, ctypes.byref(described)) == 0:
                status = 0
            os.write(ready_write, str(segment).encode())
            os.read(done_read, 1)
            libc.shmctl(segment, IPC_RMID, None)
        finally:
            os._exit(status)
    try:
        segment = int(os.read(ready_read, 32))
        assert any(item.identifier == segment and not item.created for item in ipc_objects_of(PLUGIN_UID))

        # Removed as far as it can be (marked for removal), and the removal goes on.
        assert remove_ipc_objects_of(PLUGIN_UID) >= 1
    finally:
        os.write(done_write, b"x")
        os.waitpid(holder, 0)

