"""Synthetic run folders built through the real analyzer — for tests and for checking the viewer.

  python benchmark/fixtures.py /tmp/bench-demo   # three runs + index.json

The numbers are self-consistent: each level keeps `level` sessions in flight (closed loop, so
throughput = in flight / end-to-end, Little's law); crew runs at most `crew_slots` of them and the
rest queue; container memory and CPU follow the running sessions; memory returns to (almost)
baseline after cooldown.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import analyze
import push
from config import load_case
from load import FINISH_KIND, SessionRecord

HERE = Path(__file__).resolve().parent
# container: (baseline MB, MB per running session, share of a session's CPU, MB kept after cooldown)
CONTAINERS = {
    "django_app": (420, 0.4, 0.15, 1.0),
    "crew": (610, 3.0, 0.35, 4.0),
    "agent": (380, 0.15, 0.10, 0.5),
    "sandbox": (250, 1.2, 0.40, 0.5),
}
# phase: (run seconds of one session on an idle stack, CPU-seconds per session)
PHASE_COST = {"payload": (12.0, 0.3), "complex": (24.0, 0.45)}
HOST_VCPU, HOST_RAM_MB, HOST_AVAILABLE_MB = 12, 48000, 40000
SAMPLE_S = 2


def _samples(
    rows: tuple[list, list],
    rng: random.Random,
    phase: str,
    level: int,
    start: float,
    count: int,
    running: int = 0,
    cores: float = 0.0,
    cooldown: bool = False,
) -> None:
    """`count` samples every 2 s from start + 1, so none sits on a window boundary."""
    timeline, container_timeline = rows
    used_mb = sum(per_session * running for _, per_session, _, _ in CONTAINERS.values())
    available_mb = HOST_AVAILABLE_MB - used_mb
    for sample in range(count):
        ts = start + 1 + sample * SAMPLE_S
        base = {"ts": ts, "rel_s": ts - 1_000_000, "phase": phase, "segment": 1, "level": level}
        timeline.append(
            base
            | {
                "target": level,
                "inflight": level,
                "running": running,
                "queued": level - running,
                "completed": 0,
                "failed": 0,
                "host_cpu_pct": round(3 + cores / HOST_VCPU * 100, 1),
                "host_mem_avail_mb": round(available_mb),
                "host_mem_avail_pct": round(available_mb / HOST_RAM_MB * 100, 1),
                "load1": round(cores + 0.2, 2),
                "pg_connections": 10 + running // 5,
                "pg_max_connections": 200,
                "redis_used_mb": round(20 + level / 20, 1),
                "runner_cpu_pct": 4 if level else 1,
            }
        )
        for container, (baseline_mb, per_session, cpu_share, kept_mb) in CONTAINERS.items():
            if running:
                mem_mb = baseline_mb + per_session * running + rng.gauss(0, 1.5)
            elif cooldown:
                mem_mb = baseline_mb + kept_mb + rng.uniform(0, 0.5)
            else:
                mem_mb = baseline_mb
            container_timeline.append(
                base
                | {
                    "container": container,
                    "cpu_pct": round(1 + cpu_share * cores * 100, 1),
                    "mem_mb": round(mem_mb, 1),
                    "restarts": 0,
                    "oom_kills": 0,
                }
            )


def _session_events(session_id: int, sent: float, slot: float, done: float) -> list[dict]:
    """Checkpoints of one session: five Python nodes, each wrapping a sandbox execution."""
    node_s = (done - slot - 0.05) / 5  # all five nodes end before session_end
    events = [
        {
            "service": "django_app",
            "checkpoint": "request_received",
            "session_id": session_id,
            "ts": sent + 0.01,
            "arrival_ts": sent,
        },
        {"service": "crew", "checkpoint": "received", "session_id": session_id, "ts": sent + 0.1},
        {"service": "crew", "checkpoint": "slot_acquired", "session_id": session_id, "ts": slot},
    ]
    for node in range(5):
        node_start = slot + node * node_s
        name, execution = f"Python {node + 1}", f"e{session_id}-{node}"
        events += [
            {
                "service": "crew",
                "checkpoint": "node_start",
                "session_id": session_id,
                "node_name": name,
                "node_type": "PythonNode",
                "ts": node_start,
            },
            {
                "service": "sandbox",
                "checkpoint": "exec_start",
                "session_id": session_id,
                "execution_id": execution,
                "ts": node_start + 0.05,
            },
            {
                "service": "sandbox",
                "checkpoint": "exec_end",
                "session_id": session_id,
                "execution_id": execution,
                "ts": node_start + node_s - 0.05,
                "returncode": 0,
            },
            {
                "service": "crew",
                "checkpoint": "node_end",
                "session_id": session_id,
                "node_name": name,
                "node_type": "PythonNode",
                "ok": True,
                "ts": node_start + node_s,
            },
        ]
    events.append(
        {
            "service": "crew",
            "checkpoint": "session_end",
            "session_id": session_id,
            "status": "end",
            "ts": done,
        }
    )
    return events


def _run(
    out_dir: Path,
    name: str,
    case_file: str,
    levels: tuple[int, ...],
    fail_from: int | None,
    seed: int,
    kind: str,
) -> Path:
    run_dir = out_dir / name
    analyze.analyze(build_run(name, case_file, levels, fail_from, seed, kind), run_dir)
    return run_dir


def build_run(
    name: str,
    case_file: str,
    levels: tuple[int, ...],
    fail_from: int | None,
    seed: int,
    kind: str,
) -> analyze.RunData:
    """The data a run collects, before analysis. Each level runs like the runner does it:
    settle, hold, then the same load until the hold's sessions have ended (kind `finish`)."""
    rng = random.Random(seed)
    case = load_case(
        HERE / "cases" / case_file,
        {phase: index + 1 for index, phase in enumerate(("payload", "complex"))}
        if case_file == "server.toml"
        else {"payload": 1},
    )
    # Crew slots sit between the last passing level and fail_from (a x2 ladder), so fail_from
    # is the first level whose sessions queue — long enough to fail p95_queue_wait_s.
    crew_slots = fail_from * 5 // 8 if fail_from is not None else 100_000
    clock, records, events, windows, segments = 1_000_000.0, [], [], [], []
    samples: tuple[list, list] = ([], [])
    session_id = 0
    for phase in case.phases:
        idle_run_s, cpu_s_per_session = PHASE_COST[phase.name]
        baseline_start = clock
        _samples(samples, rng, phase.name, 0, clock, 10)
        clock += 20
        load_start = clock
        for level in levels:
            running = min(level, crew_slots)
            run_s = idle_run_s * (1 + running / 800)
            queue_s = run_s * (level - running) / running  # Little's law for the queued rest
            start, settle_end, end = clock, clock + 30, clock + 210
            mean_e2e = 0.1 + queue_s + run_s
            # closed loop: each user starts its next session at once
            next_sent = [start + user * mean_e2e / level for user in range(level)]
            finish_end = end
            for session_kind in (kind, FINISH_KIND):
                # first up to the end of the hold, then until the hold's sessions have ended
                send_until = end if session_kind == kind else finish_end
                for user in range(level):
                    while next_sent[user] < send_until:
                        sent = next_sent[user]
                        session_id += 1
                        queue = (
                            queue_s * rng.uniform(0.7, 1.3) if queue_s else rng.uniform(0.03, 0.08)
                        )
                        slot = sent + 0.1 + queue
                        done = slot + run_s * rng.uniform(0.85, 1.15)
                        records.append(
                            SessionRecord(
                                phase.name,
                                level,
                                session_kind,
                                1,
                                sent,
                                sent + 0.001,
                                8,
                                200,
                                session_id,
                                None,
                                done,
                                "end",
                            )
                        )
                        events += _session_events(session_id, sent, slot, done)
                        if session_kind == kind and sent >= settle_end:
                            finish_end = max(finish_end, done)
                        next_sent[user] = done + 0.05
            windows.append(
                analyze.Window(
                    phase.name, level, kind, 1, start, settle_end, end, finish_end_ts=finish_end
                )
            )
            cores = cpu_s_per_session * running / run_s  # sessions finished per second x CPU-s
            sample_count = round((finish_end - start) / SAMPLE_S)
            _samples(samples, rng, phase.name, level, start, sample_count, running, cores)
            clock = finish_end
            if fail_from is not None and level >= fail_from:
                break
        _samples(samples, rng, phase.name, 0, clock, 30, cooldown=True)
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
            "ref": "feat/session-benchmark",
            "sha": f"{seed:07d}abcdef",
            "dirty": False,
            "built": True,
        },
        "images": {},
        "host": {"hostname": "demo", "vcpu": HOST_VCPU, "ram_mb": HOST_RAM_MB},
        "container_limits": {},
        "env": {"CREW_MAX_CONCURRENT_SESSIONS": str(crew_slots)},
        "labels": [],
        "smoke": {"ran": False},
        "graphs": {
            phase.name: {"graph_id": 1, "graph_name": phase.name, "graph_hash": "demo"}
            for phase in case.phases
        },
    }
    return analyze.RunData(case, "default", meta, records, windows, segments, events, *samples)


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
