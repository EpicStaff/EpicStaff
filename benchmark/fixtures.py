"""Synthetic run folders built through the real analyzer — for tests and for checking the viewer.

python benchmark/fixtures.py /tmp/bench-demo   # three runs + index.json
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import analyze
import push
from config import load_case
from load import SessionRecord

HERE = Path(__file__).resolve().parent
CONTAINERS = ("django_app", "crew", "agent", "sandbox")


def _run(
    out_dir: Path,
    name: str,
    case_file: str,
    levels: tuple[int, ...],
    fail_from: int | None,
    seed: int,
    kind: str,
) -> Path:
    rng = random.Random(seed)
    case = load_case(
        HERE / "cases" / case_file,
        {phase: index + 1 for index, phase in enumerate(("payload", "complex"))}
        if case_file == "server.toml"
        else {"payload": 1},
    )
    clock, records, events, windows, timeline, container_timeline, segments = (
        1_000_000.0,
        [],
        [],
        [],
        [],
        [],
        [],
    )
    session_id = 0
    for phase in case.phases:
        baseline_start = clock
        for sample in range(10):
            ts = clock + sample * 2
            timeline.append(
                {
                    "ts": ts,
                    "rel_s": ts - 1_000_000,
                    "phase": phase.name,
                    "segment": 1,
                    "level": 0,
                    "target": 0,
                    "inflight": 0,
                    "running": 0,
                    "queued": 0,
                    "completed": 0,
                    "failed": 0,
                    "host_cpu_pct": 3,
                    "host_mem_avail_mb": 40000,
                    "host_mem_avail_pct": 85,
                    "load1": 0.2,
                    "pg_connections": 10,
                    "pg_max_connections": 100,
                    "redis_used_mb": 20,
                    "runner_cpu_pct": 1,
                }
            )
            for container in CONTAINERS:
                container_timeline.append(
                    {
                        "ts": ts,
                        "rel_s": ts - 1_000_000,
                        "phase": phase.name,
                        "segment": 1,
                        "level": 0,
                        "container": container,
                        "cpu_pct": 1,
                        "mem_mb": 300,
                        "restarts": 0,
                        "oom_kills": 0,
                    }
                )
        clock += 20
        load_start = clock
        for level in levels:
            failing = fail_from is not None and level >= fail_from
            start, settle_end, end = clock, clock + 30, clock + 210
            windows.append(
                analyze.Window(
                    phase.name, level, kind, 1, start, settle_end, end, live_verdict=None
                )
            )
            for index in range(level * 3):
                session_id += 1
                sent = start + index * (180 / (level * 3)) + 30
                e2e = rng.uniform(2, 4) * (6 if failing else 1) * (1 + level / 400)
                records.append(
                    SessionRecord(
                        phase.name,
                        level,
                        kind,
                        1,
                        sent,
                        sent + 0.001,
                        8,
                        200,
                        session_id,
                        None,
                        sent + e2e,
                        "end",
                    )
                )
                slot = sent + 0.2 + (rng.uniform(5, 9) if failing else 0.05)
                events += [
                    {
                        "service": "django_app",
                        "checkpoint": "request_received",
                        "session_id": session_id,
                        "ts": sent + 0.01,
                        "arrival_ts": sent,
                    },
                    {
                        "service": "crew",
                        "checkpoint": "received",
                        "session_id": session_id,
                        "ts": sent + 0.1,
                    },
                    {
                        "service": "crew",
                        "checkpoint": "slot_acquired",
                        "session_id": session_id,
                        "ts": slot,
                    },
                ]
                for node in range(5):
                    node_start = slot + node * (e2e - 0.3) / 5
                    events += [
                        {
                            "service": "crew",
                            "checkpoint": "node_start",
                            "session_id": session_id,
                            "node_name": f"Python {node + 1}",
                            "node_type": "PythonNode",
                            "ts": node_start,
                        },
                        {
                            "service": "sandbox",
                            "checkpoint": "exec_start",
                            "session_id": session_id,
                            "execution_id": f"e{session_id}-{node}",
                            "ts": node_start + 0.05,
                        },
                        {
                            "service": "sandbox",
                            "checkpoint": "exec_end",
                            "session_id": session_id,
                            "execution_id": f"e{session_id}-{node}",
                            "ts": node_start + (e2e - 0.3) / 5 - 0.05,
                            "returncode": 0,
                        },
                        {
                            "service": "crew",
                            "checkpoint": "node_end",
                            "session_id": session_id,
                            "node_name": f"Python {node + 1}",
                            "node_type": "PythonNode",
                            "ok": True,
                            "ts": node_start + (e2e - 0.3) / 5,
                        },
                    ]
                events.append(
                    {
                        "service": "crew",
                        "checkpoint": "session_end",
                        "session_id": session_id,
                        "status": "end",
                        "ts": sent + e2e,
                    }
                )
            for sample in range(105):
                ts = start + sample * 2
                timeline.append(
                    {
                        "ts": ts,
                        "rel_s": ts - 1_000_000,
                        "phase": phase.name,
                        "segment": 1,
                        "level": level,
                        "target": level,
                        "inflight": level,
                        "running": min(level, 25 if failing else level),
                        "queued": level - min(level, 25 if failing else level),
                        "completed": 0,
                        "failed": 0,
                        "host_cpu_pct": min(98, 10 + level * 1.5),
                        "host_mem_avail_mb": 40000 - level * 40,
                        "host_mem_avail_pct": 85 - level * 0.1,
                        "load1": level / 10,
                        "pg_connections": 10 + level // 2,
                        "pg_max_connections": 100,
                        "redis_used_mb": 20 + level / 10,
                        "runner_cpu_pct": 4,
                    }
                )
                for container in CONTAINERS:
                    container_timeline.append(
                        {
                            "ts": ts,
                            "rel_s": ts - 1_000_000,
                            "phase": phase.name,
                            "segment": 1,
                            "level": level,
                            "container": container,
                            "cpu_pct": min(400, level * (3 if container == "sandbox" else 1)),
                            "mem_mb": 300 + level * (4 if container == "crew" else 1.5),
                            "restarts": 0,
                            "oom_kills": 0,
                        }
                    )
            clock = end
            if failing:
                break
        segments.append(
            analyze.Segment(phase.name, 1, kind, baseline_start, load_start, clock, clock + 60)
        )
        clock += 60
    meta = {
        "run_id": name,
        "created_at": f"2026-10-0{seed}T10:00:00+00:00",
        "note": f"demo {name}",
        "kind": case.kind,
        "case": {"name": case.name, "hash": case.case_hash, "variant": "default", "overrides": {}},
        "git": {
            "ref": "feat/EST-4430-benchmark",
            "sha": f"{seed:07d}abcdef",
            "dirty": False,
            "built": True,
        },
        "images": {},
        "host": {"hostname": "demo", "vcpu": 12, "ram_mb": 48000},
        "container_limits": {},
        "env": {"CREW_MAX_CONCURRENT_SESSIONS": "100000"},
        "labels": [],
        "smoke": {"ran": False},
        "graphs": {
            phase.name: {"graph_id": 1, "graph_name": phase.name, "graph_hash": "demo"}
            for phase in case.phases
        },
    }
    run_dir = out_dir / name
    analyze.analyze(
        analyze.RunData(
            case, "default", meta, records, windows, segments, events, timeline, container_timeline
        ),
        run_dir,
    )
    return run_dir


def write_capacity_run(
    out_dir: Path, name: str, levels=(25, 50, 100, 200), fail_from=200, seed=1
) -> Path:
    return _run(out_dir, name, "server.toml", tuple(levels), fail_from, seed, "ladder")


def write_dev_run(out_dir: Path, name: str, seed: int = 3) -> Path:
    return _run(out_dir, name, "dev.toml", (25,), None, seed, "dev")


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "benchmark/results/demo")
    write_capacity_run(
        target, "2026-10-01_1000_demo_developer_0000001_server-capacity-default", seed=1
    )
    write_capacity_run(
        target,
        "2026-10-02_1000_demo_fix-x_0000002_server-capacity-default",
        levels=(100, 200, 400, 800),
        fail_from=800,
        seed=2,
    )
    write_dev_run(target, "2026-10-03_1000_demo_fix-x_0000003_dev-payload-default")
    (target / "index.json").write_text(
        json.dumps(push.build_index(target, None), indent=2), encoding="utf-8"
    )
    print(f"wrote demo runs to {target}")
