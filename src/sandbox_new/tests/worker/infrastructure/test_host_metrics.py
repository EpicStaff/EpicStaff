"""How host and container load are read from procfs and cgroupfs.

Run against files laid out the way cgroup v1 and v2 lay them out, under tmp_path. A file
that is missing or holds garbage yields None, never a guess, because the gate treats
None as "does not block".
"""

from pathlib import Path

import pytest

from worker.infrastructure.admission import HostMetrics

V1_UNLIMITED_MEMORY = "9223372036854771712"


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


@pytest.fixture
def cgroup(tmp_path) -> Path:
    root = tmp_path / "cgroup"
    root.mkdir()
    return root


@pytest.fixture
def proc(tmp_path) -> Path:
    root = tmp_path / "proc"
    root.mkdir()
    return root


def metrics(cgroup: Path, proc: Path) -> HostMetrics:
    return HostMetrics(cgroup_root=cgroup, proc_root=proc)


@pytest.mark.parametrize(
    ("cpu_max", "floor"),
    [("200000 100000\n", 2), ("150000 100000\n", 1), ("50000 100000\n", 1)],
    ids=["two-cpus", "rounded-down", "at-least-one"],
)
def test_a_cgroup_v2_quota_sets_the_floor(cgroup, proc, cpu_max, floor):
    write(cgroup, "cpu.max", cpu_max)

    assert metrics(cgroup, proc).floor() == floor


def test_a_cgroup_v1_quota_sets_the_floor(cgroup, proc):
    write(cgroup, "cpu/cpu.cfs_quota_us", "300000\n")
    write(cgroup, "cpu/cpu.cfs_period_us", "100000\n")

    assert metrics(cgroup, proc).floor() == 3


@pytest.mark.parametrize(
    "files",
    [
        {"cpu.max": "max 100000\n"},
        {"cpu/cpu.cfs_quota_us": "-1\n", "cpu/cpu.cfs_period_us": "100000\n"},
        {"cpu.max": "garbage\n"},
    ],
    ids=["v2-max", "v1-minus-one", "unparseable"],
)
def test_no_quota_falls_back_to_the_cpus_the_process_may_use(cgroup, proc, tmp_path, files):
    for relative, content in files.items():
        write(cgroup, relative, content)
    without_cgroup = HostMetrics(cgroup_root=tmp_path / "absent", proc_root=proc)

    assert metrics(cgroup, proc).floor() == without_cgroup.floor() >= 1


def test_cgroup_v2_memory_is_the_working_set_over_the_limit(cgroup, proc):
    write(cgroup, "memory.current", "600\n")
    write(cgroup, "memory.stat", "anon 400\ninactive_file 100\nactive_file 100\n")
    write(cgroup, "memory.max", "1000\n")

    assert metrics(cgroup, proc).sample().memory_used_percent == 50.0


def test_cgroup_v1_memory_is_the_working_set_over_the_limit(cgroup, proc):
    write(cgroup, "memory/memory.usage_in_bytes", "800\n")
    write(cgroup, "memory/memory.stat", "cache 400\ntotal_inactive_file 300\n")
    write(cgroup, "memory/memory.limit_in_bytes", "1000\n")

    assert metrics(cgroup, proc).sample().memory_used_percent == 50.0


@pytest.mark.parametrize(
    "files",
    [
        {"memory.current": "600\n", "memory.max": "max\n"},
        {
            "memory/memory.usage_in_bytes": "800\n",
            "memory/memory.limit_in_bytes": f"{V1_UNLIMITED_MEMORY}\n",
        },
        {},
        {"memory.current": "garbage\n", "memory.max": "1000\n"},
    ],
    ids=["v2-max", "v1-unlimited", "unreadable", "unparseable"],
)
def test_memory_without_a_usable_limit_is_unknown(cgroup, proc, files):
    for relative, content in files.items():
        write(cgroup, relative, content)

    assert metrics(cgroup, proc).sample().memory_used_percent is None


def test_cpu_busy_is_the_share_of_non_idle_time_between_samples(cgroup, proc):
    host = metrics(cgroup, proc)
    # user nice system idle iowait irq softirq steal guest guest_nice
    write(proc, "stat", "cpu  100 0 100 700 100 0 0 0 50 0\ncpu0 1 2 3\n")
    first = host.sample()
    write(proc, "stat", "cpu  200 0 200 1300 300 0 0 0 90 0\ncpu0 1 2 3\n")

    second = host.sample()

    assert first.cpu_busy_percent is None
    assert second.cpu_busy_percent == 20.0


@pytest.mark.parametrize("stat", [None, "garbage\n", "cpu  1 2\n"])
def test_cpu_busy_is_unknown_when_proc_stat_is_unusable(cgroup, proc, stat):
    host = metrics(cgroup, proc)
    if stat is not None:
        write(proc, "stat", stat)

    host.sample()

    assert host.sample().cpu_busy_percent is None
