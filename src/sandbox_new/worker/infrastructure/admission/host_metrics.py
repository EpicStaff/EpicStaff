"""Reads the host and container load signals the admission gate decides on.

Everything comes from procfs and cgroupfs, which are in-memory pseudo files: reading
them is cheap enough to do on the event loop. Any value that cannot be read or parsed
is reported as None rather than guessed, and the gate treats None as "does not block".
"""

import os
from pathlib import Path

from worker.application.ports.host_metrics import AbstractHostMetrics, HostSample

__all__ = ["HostMetrics"]

# cgroup v1 has no keyword for "no memory limit": it reports a page-aligned value near
# 2**63. Anything this large is no real limit, so there is no percentage to compute.
_UNLIMITED_MEMORY_BYTES = 2**60


class HostMetrics(AbstractHostMetrics):
    """Read the container's CPU allowance and the current CPU and memory load.

    Args:
        cgroup_root: Where the container's cgroup filesystem is mounted.
        proc_root: Where procfs is mounted.
    """

    def __init__(
        self, *, cgroup_root: Path = Path("/sys/fs/cgroup"), proc_root: Path = Path("/proc")
    ) -> None:
        self._cgroup_root = cgroup_root
        self._proc_root = proc_root
        # (idle, total) jiffies from the previous CPU reading; busy time is a delta.
        self._previous_cpu_times: tuple[int, int] | None = None

    def floor(self) -> int:
        """Return how many CPUs the container may use, at least 1.

        A cgroup CPU quota wins (v2 `cpu.max`, else v1 `cpu.cfs_quota_us` over
        `cpu.cfs_period_us`), rounded down; without one, the CPUs this process may be
        scheduled on, else every CPU the host has.
        """
        cpu_limit = self._cpu_limit()
        if cpu_limit is not None:
            return max(1, int(cpu_limit))
        try:
            return max(1, len(os.sched_getaffinity(0)))
        except AttributeError:
            # Not every platform has CPU affinity (macOS, Windows).
            return max(1, os.cpu_count() or 1)

    def sample(self) -> HostSample:
        """Read the current load.

        The CPU figure is the host's busy share since the previous call, so the first
        call after construction always reports CPU as None.
        """
        return HostSample(
            cpu_busy_percent=self._cpu_busy_percent(),
            memory_used_percent=self._memory_used_percent(),
        )

    def _cpu_limit(self) -> float | None:
        try:
            cpu_max = _read(self._cgroup_root / "cpu.max")
            if cpu_max is not None:
                quota, period = cpu_max.split()
                return None if quota == "max" else int(quota) / int(period)
            quota = _read(self._cgroup_root / "cpu" / "cpu.cfs_quota_us")
            period = _read(self._cgroup_root / "cpu" / "cpu.cfs_period_us")
            if quota is None or period is None or int(quota) < 0:
                return None
            return int(quota) / int(period)
        except (ValueError, ZeroDivisionError):
            return None

    def _cpu_busy_percent(self) -> float | None:
        stat = _read(self._proc_root / "stat")
        if stat is None:
            return None
        try:
            label, *values = stat.splitlines()[0].split()
            if label != "cpu":
                return None
            # user nice system idle iowait irq softirq steal. Guest time is already
            # counted inside user and nice, so the columns after steal are left out.
            times = [int(value) for value in values[:8]]
            idle, total = times[3] + times[4], sum(times)
        except (IndexError, ValueError):
            return None

        previous, self._previous_cpu_times = self._previous_cpu_times, (idle, total)
        if previous is None:
            return None
        total_delta = total - previous[1]
        if total_delta <= 0:
            return None
        return 100 * (total_delta - (idle - previous[0])) / total_delta

    def _memory_used_percent(self) -> float | None:
        """The container's working set -- usage minus reclaimable file cache -- over its limit."""
        root = self._cgroup_root
        usage = _read(root / "memory.current")
        if usage is not None:
            limit = _read(root / "memory.max")
            stat, inactive_key = _read(root / "memory.stat"), "inactive_file"
        else:
            usage = _read(root / "memory" / "memory.usage_in_bytes")
            limit = _read(root / "memory" / "memory.limit_in_bytes")
            stat, inactive_key = _read(root / "memory" / "memory.stat"), "total_inactive_file"
        if usage is None or limit is None or limit == "max":
            return None
        try:
            limit_bytes = int(limit)
            if limit_bytes <= 0 or limit_bytes >= _UNLIMITED_MEMORY_BYTES:
                return None
            working_set = max(0, int(usage) - _stat_value(stat, inactive_key))
        except ValueError:
            return None
        return 100 * working_set / limit_bytes


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _stat_value(stat: str | None, key: str) -> int:
    """Return `key` from a cgroup `memory.stat`; 0 when absent, which overstates usage."""
    for line in (stat or "").splitlines():
        name, _, value = line.partition(" ")
        if name == key:
            return int(value)
    return 0
