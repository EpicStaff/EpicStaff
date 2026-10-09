"""Samples host, container and saturation metrics every 2 s into timeline rows."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path

import stack

CGROUP_ROOTS = (
    "/sys/fs/cgroup/system.slice/docker-{id}.scope",
    "/sys/fs/cgroup/docker/{id}",
)
SIZE_TO_MB = {
    "b": 1 / 1024**2,
    "kib": 1 / 1024,
    "mib": 1.0,
    "gib": 1024.0,
    "kb": 1e3 / 1024**2,
    "mb": 1e6 / 1024**2,
    "gb": 1e9 / 1024**2,
}


def parse_cpu_stat(text: str) -> int:
    return int(re.search(r"^usage_usec (\d+)", text, re.MULTILINE).group(1))


def parse_memory_events(text: str) -> int:
    match = re.search(r"^oom_kill (\d+)", text, re.MULTILINE)
    return int(match.group(1)) if match else 0


def parse_proc_stat(text: str) -> tuple[int, int]:
    fields = [int(value) for value in text.splitlines()[0].split()[1:]]
    return fields[3] + fields[4], sum(fields)


def parse_meminfo(text: str) -> dict[str, int]:
    return {line.split(":")[0]: int(line.split()[1]) for line in text.splitlines() if ":" in line}


def parse_redis_used_mb(text: str) -> float | None:
    match = re.search(r"^used_memory:(\d+)", text, re.MULTILINE)
    return round(int(match.group(1)) / 1024**2, 1) if match else None


def parse_docker_size_mb(text: str) -> float | None:
    match = re.match(r"\s*([\d.]+)\s*([A-Za-z]+)", text or "")
    factor = SIZE_TO_MB.get(match.group(2).lower()) if match else None
    return float(match.group(1)) * factor if factor else None


def live_line(row: dict, per_container: dict[str, dict]) -> str:
    """The status line printed every sample, so the operator watches the pool grow."""

    def number(value, unit: str = "") -> str:
        return "—" + unit if value is None else f"{value:.0f}{unit}"

    containers = " ".join(
        f"{name} {number(metrics['mem_mb'], ' MB')}" for name, metrics in per_container.items()
    )
    return (
        f"{row['phase']} L{row['level']} target {row['target']} in-flight {row['inflight']} "
        f"running {row['running']} queued {row['queued']} done {row['completed']} err {row['failed']} | "
        f"CPU {number(row['host_cpu_pct'], '%')} | RAM avail {number(row['host_mem_avail_mb'], ' MB')} | "
        f"{containers} | pg {number(row['pg_connections'])} | redis {number(row['redis_used_mb'], ' MB')}"
    )


def _docker_oom(state: dict) -> int | None:
    """OOM flag from `docker inspect` State; None when the inspect gave no state."""
    return int(bool(state["OOMKilled"])) if "OOMKilled" in state else None


class Sampler:
    def __init__(
        self,
        containers: dict[str, str],
        status: Callable[[], dict],
        db_user: str | None,
        redis_user: str | None,
        redis_password: str | None,
        interval_s: float = 2.0,
    ):
        self.containers, self.status, self.interval_s = containers, status, interval_s
        self.db_user, self.redis_user, self.redis_password = (
            db_user,
            redis_user,
            redis_password,
        )
        self.rows: list[dict] = []
        self.container_rows: list[dict] = []
        self.latest: dict = {}
        self.context = {"phase": "", "segment": 0, "level": 0, "target": 0}
        self._cgroups = {
            name: self._cgroup_dir(container_id) for name, container_id in containers.items()
        }
        self._previous_cpu: dict[str, tuple[float, int]] = {}
        self._previous_host: tuple[int, int] | None = None
        self._previous_runner = (time.monotonic(), time.process_time())
        self._started = time.time()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    @staticmethod
    def _cgroup_dir(container_id: str) -> Path | None:
        for root in CGROUP_ROOTS:
            path = Path(root.format(id=container_id))
            cpu_stat_path = path / "cpu.stat"
            if cpu_stat_path.exists():
                try:
                    text = cpu_stat_path.read_text()
                    if "usage_usec" in text:
                        return path
                except (OSError, ValueError):
                    pass
        return None

    def mark(self, **context) -> None:
        self.context.update(context)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=60)

    def _loop(self) -> None:
        next_at = time.monotonic()
        while not self._stop.is_set():
            try:
                self._sample()
            except Exception as error:  # a failed sample is a gap, never a crashed run
                print(f"[sampler] {type(error).__name__}: {error}", flush=True)
            next_at += self.interval_s
            self._stop.wait(max(0.0, next_at - time.monotonic()))

    def _sample(self) -> None:
        now = time.time()
        base = {"ts": round(now, 3), "rel_s": round(now - self._started, 1), **self.context}
        try:
            inspected = stack.inspect(list(self.containers))
        except (stack.StackError, ValueError):
            inspected = {}
        per_container = self._container_metrics(now, inspected)
        container_rows = [
            {**base, "container": name, **metrics} for name, metrics in per_container.items()
        ]
        status = self.status()
        row = {
            **base,
            "target": self.context["target"],
            **status,
            "queued": max(0, status["inflight"] - status["running"]),
            **self._host_metrics(),
            **self._saturation(),
            "runner_cpu_pct": self._runner_cpu(),
        }
        self.rows.append(row)
        self.container_rows.extend(container_rows)
        self.latest = {**row, "containers": per_container}
        print(live_line(row, per_container), flush=True)

    def _container_metrics(self, now: float, inspected: dict) -> dict[str, dict]:
        metrics: dict[str, dict] = {}
        fallback = [name for name, path in self._cgroups.items() if path is None]
        stats = self._docker_stats(fallback) if fallback else {}
        for name, path in self._cgroups.items():
            state = inspected.get(name, {}).get("State", {})
            restarts = inspected.get(name, {}).get("RestartCount")
            if path is not None:
                try:
                    usage = parse_cpu_stat((path / "cpu.stat").read_text())
                    previous = self._previous_cpu.get(name)
                    wall = time.monotonic()
                    cpu_pct = None
                    if previous:
                        prev_wall, prev_usage = previous
                        delta_usage = usage - prev_usage
                        if delta_usage < 0:
                            cpu_pct = None
                        else:
                            cpu_pct = round(delta_usage / 1e6 / (wall - prev_wall) * 100, 1)
                    self._previous_cpu[name] = (wall, usage)
                    mem_mb = round(int((path / "memory.current").read_text()) / 1024**2, 1)
                    oom = parse_memory_events((path / "memory.events").read_text())
                except (OSError, AttributeError, ValueError):
                    self._cgroups[name] = None
                    cpu_pct, mem_mb = stats.get(name, (None, None))
                    oom = _docker_oom(state)
            else:
                cpu_pct, mem_mb = stats.get(name, (None, None))
                oom = _docker_oom(state)
            metrics[name] = {
                "cpu_pct": cpu_pct,
                "mem_mb": mem_mb,
                "restarts": restarts,
                "oom_kills": oom,
            }
        return metrics

    def _docker_stats(self, names: list[str]) -> dict[str, tuple[float | None, float | None]]:
        try:
            result = stack.run(
                [
                    "docker",
                    "stats",
                    "--no-stream",
                    "--format",
                    "{{json .}}",
                    *names,
                ],
                check=False,
                timeout=30,
            )
        except stack.StackError:
            return {}
        stats = {}
        for line in result.stdout.splitlines():
            try:
                row = json.loads(line)
                cpu = row.get("CPUPerc", "").rstrip("%")
                stats[row["Name"]] = (
                    float(cpu) if cpu else None,
                    parse_docker_size_mb(row.get("MemUsage", "").split("/")[0]),
                )
            except (json.JSONDecodeError, ValueError, KeyError):
                continue
        return stats

    def _host_metrics(self) -> dict:
        if not Path("/proc/stat").exists():
            return {
                "host_cpu_pct": None,
                "host_mem_avail_mb": None,
                "host_mem_avail_pct": None,
                "load1": None,
            }
        idle, total = parse_proc_stat(Path("/proc/stat").read_text())
        cpu_pct = None
        if self._previous_host:
            busy = (total - self._previous_host[1]) - (idle - self._previous_host[0])
            cpu_pct = round(busy / max(total - self._previous_host[1], 1) * 100, 1)
        self._previous_host = (idle, total)
        meminfo = parse_meminfo(Path("/proc/meminfo").read_text())
        return {
            "host_cpu_pct": cpu_pct,
            "host_mem_avail_mb": round(meminfo["MemAvailable"] / 1024),
            "host_mem_avail_pct": round(meminfo["MemAvailable"] / meminfo["MemTotal"] * 100, 1),
            "load1": float(Path("/proc/loadavg").read_text().split()[0]),
        }

    def _saturation(self) -> dict:
        result = {"pg_connections": None, "pg_max_connections": None, "redis_used_mb": None}
        if self.db_user:
            try:
                query = "select count(*), current_setting('max_connections') from pg_stat_activity"
                pg = stack.run(
                    [
                        "docker",
                        "exec",
                        "crewdb",
                        "psql",
                        "-U",
                        self.db_user,
                        "-d",
                        "postgres",
                        "-tAc",
                        query,
                    ],
                    check=False,
                    timeout=10,
                )
                if pg.returncode == 0 and "|" in pg.stdout:
                    count, maximum = pg.stdout.strip().split("|")
                    result.update(pg_connections=int(count), pg_max_connections=int(maximum))
            except (stack.StackError, ValueError):
                pass
        if self.redis_user:
            try:
                env = {**os.environ, "REDISCLI_AUTH": self.redis_password or ""}
                redis = stack.run(
                    [
                        "docker",
                        "exec",
                        "-e",
                        "REDISCLI_AUTH",
                        "redis",
                        "redis-cli",
                        "--user",
                        self.redis_user,
                        "--no-auth-warning",
                        "INFO",
                        "memory",
                    ],
                    check=False,
                    timeout=10,
                    env=env,
                )
                result["redis_used_mb"] = (
                    parse_redis_used_mb(redis.stdout) if redis.returncode == 0 else None
                )
            except stack.StackError:
                pass
        return result

    def _runner_cpu(self) -> float:
        wall, cpu = time.monotonic(), time.process_time()
        previous_wall, previous_cpu = self._previous_runner
        self._previous_runner = (wall, cpu)
        return round((cpu - previous_cpu) / max(wall - previous_wall, 1e-6) * 100, 1)

    def snapshot_counts(self) -> dict[str, tuple[int | None, int | None]]:
        """(restarts, oom_kills) per container from the latest sample; None = unknown."""
        return {
            name: (metrics["restarts"], metrics["oom_kills"])
            for name, metrics in self.latest.get("containers", {}).items()
        }

    def restarts_since(self, baseline: dict[str, tuple[int | None, int | None]]) -> list[str]:
        """Containers whose restart or OOM counter rose; an unknown value never counts."""
        return [
            name
            for name, counts in self.snapshot_counts().items()
            if any(
                now is not None and before is not None and now > before
                for now, before in zip(counts, baseline.get(name, (0, 0)), strict=True)
            )
        ]
