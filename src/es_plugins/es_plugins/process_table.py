"""The node's processes as `/proc/<pid>/status` shows them, read by UID.

A plugin is identified by its UID, never by a process tree: a plugin's children may call
`setsid` or be reparented to PID 1, and every one of them still runs as the plugin's UID.
`/proc/<pid>/status` is readable by every UID, so the agent and the launcher both use this.
"""

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessEntry:
    pid: int
    uid: int
    """The real UID."""

    rss_kib: int
    """Anonymous and shared-memory resident pages, in KiB (see `_resident_kib`)."""

    zombie: bool


class ProcessTable:
    def __init__(self, proc_root: Path = Path("/proc")):
        self._proc_root = proc_root

    def read(self) -> list[ProcessEntry]:
        """Read every process; one that exits while being read is left out."""
        entries = []
        for name in os.listdir(self._proc_root):
            if not name.isdigit():
                continue
            entry = self._read_status(int(name))
            if entry is not None:
                entries.append(entry)
        return entries

    def living_pids_of_uid(self, uid: int) -> list[int]:
        """Pids of the UID's processes that have not exited (zombies are left out)."""
        return sorted(entry.pid for entry in self.read() if entry.uid == uid and not entry.zombie)

    def rss_kib_by_uid(self, uids: Iterable[int]) -> dict[int, int]:
        """Resident memory of every process of each UID, summed; a UID without processes is 0.

        Copy-on-write pages a forked child still shares with its parent count in both, so the
        sum can exceed the memory actually used: a cap checked against it errs on the strict side.
        """
        totals = dict.fromkeys(uids, 0)
        for entry in self.read():
            if entry.uid in totals:
                totals[entry.uid] += entry.rss_kib
        return totals

    def _read_status(self, pid: int) -> ProcessEntry | None:
        try:
            with open(self._proc_root / str(pid) / "status", encoding="utf-8") as status_file:
                text = status_file.read()
        except (FileNotFoundError, ProcessLookupError):
            return None
        fields = {}
        for line in text.splitlines():
            name, separator, value = line.partition(":")
            if separator:
                fields[name] = value.strip()
        if "Uid" not in fields:
            return None
        return ProcessEntry(
            pid=pid,
            uid=int(fields["Uid"].split()[0]),
            rss_kib=_resident_kib(fields),
            zombie=fields.get("State", "").startswith("Z"),
        )


def _resident_kib(fields: dict[str, str]) -> int:
    """Resident memory the process itself allocated: anonymous plus shared-memory pages.

    File-backed pages (the interpreter, shared libraries) are left out: every process of a
    plugin maps the same ones, and VmRSS would count them once per process. A kernel older
    than 4.5 has no RssAnon line; VmRSS is used then. Kernel threads and zombies have neither.
    """
    if "RssAnon" in fields:
        return _kib(fields["RssAnon"]) + _kib(fields.get("RssShmem", "0 kB"))
    return _kib(fields.get("VmRSS", "0 kB"))


def _kib(value: str) -> int:
    return int(value.split()[0])
