#!/usr/bin/env python3
"""Turn a stress/bench.py run directory into a self-contained summary.json. Standard library only.

    python3 stress/analyze.py stress/runs/<dir>
    python3 stress/analyze.py --self-test
"""

import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

JOIN_KEYS = ("correlation_id", "execution_id")
QUEUE_GROWTH_RATIO = 1.2
# Below this, queue wait is scheduler jitter (ms-level); a 1.2x ratio on jitter is noise, not a queue.
QUEUE_GROWTH_FLOOR_S = 1.0
MAX_FAILURE_RATE = 0.01
MINUTE_S = 60.0


# ---------------------------------------------------------------- loading


def read_jsonl(path):
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def read_memory(path):
    try:
        with open(path, newline="", encoding="utf-8") as memory_file:
            raw_rows = list(csv.DictReader(memory_file))
    except OSError:
        return []
    rows = []
    for raw in raw_rows:
        try:
            cpu = raw.get("cpu_pct")
            rows.append({
                "ts": float(raw["ts"]),
                "container": raw["container"],
                "mem_mb": float(raw["mem_mb"]),
                "cpu_pct": float(cpu) if cpu not in (None, "") else 0.0,
            })
        except (KeyError, TypeError, ValueError):
            continue
    return rows


def load_run(run_dir):
    run_dir = Path(run_dir)
    try:
        config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        config = {}
    events = [event for path in sorted((run_dir / "services").glob("*.jsonl")) for event in read_jsonl(path)]
    return (config, read_jsonl(run_dir / "fired.jsonl"), events, read_memory(run_dir / "memory.csv"),
            read_jsonl(run_dir / "turns.jsonl"))


# ---------------------------------------------------------------- math


def distribution(values):
    values = sorted(values)
    if not values:
        return {"n": 0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    if len(values) == 1:
        p50 = p95 = values[0]
    else:
        cuts = statistics.quantiles(values, n=100, method="inclusive")
        p50, p95 = cuts[49], cuts[94]
    return {"n": len(values), "p50": round(p50, 3), "p95": round(p95, 3), "max": round(values[-1], 3)}


def fit_line(xs, ys):
    """Least squares ys ~ xs. slope = MB per active session, intercept = baseline MB."""
    if len(xs) < 2 or len(set(xs)) < 2:
        return {
            "mb_per_session": 0.0,
            "intercept_mb": round(statistics.fmean(ys), 1) if ys else 0.0,
            "r2": 0.0,
            "samples": len(xs),
            "fit": "no data" if not xs else "no variation in active sessions",
        }
    slope, intercept = statistics.linear_regression(xs, ys)
    try:
        r2 = statistics.correlation(xs, ys) ** 2
    except statistics.StatisticsError:  # constant memory
        r2 = 0.0
    return {"mb_per_session": round(slope, 2), "intercept_mb": round(intercept, 1), "r2": round(r2, 3),
            "samples": len(xs), "fit": "ok"}


def mean_or_none(values):
    return round(statistics.fmean(values), 1) if values else None


# ---------------------------------------------------------------- events


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def join_id(event):
    return next((str(event[key]) for key in JOIN_KEYS if event.get(key) is not None), None)


def attribute_sessions(events):
    """Give every event a session_id; agent/sandbox lines may only carry a correlation/execution id
    that some other line (crew dispatch) logged next to its session_id."""
    id_to_session = {}
    for event in events:
        session_id = to_int(event.get("session_id"))
        if session_id is not None:
            for key in JOIN_KEYS:
                if event.get(key) is not None:
                    id_to_session[str(event[key])] = session_id
    # Chained ids: agent `sandbox_dispatched` carries correlation_id + execution_id but no
    # session_id, so a sandbox exec of an agent tool resolves execution -> correlation -> session.
    changed = True
    while changed:
        changed = False
        for event in events:
            ids = [str(event[key]) for key in JOIN_KEYS if event.get(key) is not None]
            known = next((id_to_session[i] for i in ids if i in id_to_session), None)
            if known is None:
                continue
            for i in ids:
                if i not in id_to_session:
                    id_to_session[i] = known
                    changed = True
    attributed, unattributed = [], 0
    for event in events:
        try:
            ts = float(event["ts"])
        except (KeyError, TypeError, ValueError):
            unattributed += 1
            continue
        session_id = to_int(event.get("session_id"))
        if session_id is None:
            session_id = next(
                (id_to_session[str(event[key])] for key in JOIN_KEYS
                 if event.get(key) is not None and str(event[key]) in id_to_session),
                None,
            )
        if session_id is None:
            unattributed += 1
            continue
        attributed.append({**event, "ts": ts, "session_id": session_id})
    attributed.sort(key=lambda event: event["ts"])
    return attributed, unattributed


def pair_spans(events, start_checkpoint, end_checkpoint, key):
    """FIFO-pair start/end checkpoints sharing a key. Returns (start_event, end_event, seconds)."""
    open_starts = defaultdict(list)
    spans = []
    for event in events:
        checkpoint = event.get("checkpoint")
        if checkpoint == start_checkpoint:
            open_starts[key(event)].append(event)
        elif checkpoint == end_checkpoint and open_starts.get(key(event)):
            start_event = open_starts[key(event)].pop(0)
            spans.append((start_event, event, event["ts"] - start_event["ts"]))
    return spans


# ---------------------------------------------------------------- summary


def summarize_step(step_rate, records, checkpoints, node_spans, llm_spans, exec_spans, active_intervals,
                   agent_queue_spans, tokens_by_session):
    fired_sessions = {}
    http_failures = Counter()
    for record in records:
        session_id = to_int(record.get("session_id"))
        if session_id is None:
            http_failures[f"http {record.get('http_status')}: {str(record.get('error'))[:120]}"] += 1
        else:
            fired_sessions[session_id] = record
    session_ids = set(fired_sessions)

    completed = stopped = unfinished = 0
    failed_reasons = Counter()
    queue_waits, run_times, totals = {}, {}, []
    for session_id, record in fired_sessions.items():
        marks = checkpoints.get(session_id, {})
        end_event = marks.get("session_end")
        if end_event is None:
            unfinished += 1
        elif end_event.get("status") == "end":
            completed += 1
        elif end_event.get("status") == "stop":
            stopped += 1
        else:
            failed_reasons[str(end_event.get("reason") or end_event.get("status") or "unknown")[:120]] += 1
        if "received" in marks and "slot_acquired" in marks:
            queue_waits[session_id] = marks["slot_acquired"]["ts"] - marks["received"]["ts"]
        if end_event is not None and "slot_acquired" in marks:
            run_times[session_id] = end_event["ts"] - marks["slot_acquired"]["ts"]
        if end_event is not None:
            start_ts = marks["request_received"]["ts"] if "request_received" in marks else record.get("ts")
            if start_ts is not None:
                totals.append(end_event["ts"] - float(start_ts))

    failed = sum(failed_reasons.values()) + sum(http_failures.values())
    failure_rate = failed / len(records) if records else 0.0

    # Queue growth: compare sessions fired in the step's first minute against its last minute.
    fire_times = [(float(r["ts"]), to_int(r.get("session_id"))) for r in records if r.get("ts") is not None]
    first_p95 = last_p95 = 0.0
    queue_growing = None
    if fire_times:
        step_start = min(ts for ts, _ in fire_times)
        step_end = max(ts for ts, _ in fire_times)
        first = [queue_waits[s] for ts, s in fire_times if ts < step_start + MINUTE_S and s in queue_waits]
        last = [queue_waits[s] for ts, s in fire_times if ts >= step_end - MINUTE_S and s in queue_waits]
        first_p95, last_p95 = distribution(first)["p95"], distribution(last)["p95"]
        if first and last:
            queue_growing = last_p95 > max(QUEUE_GROWTH_RATIO * first_p95, first_p95 + QUEUE_GROWTH_FLOOR_S)
    sustained = queue_growing is False and failure_rate < MAX_FAILURE_RATE

    node_types = defaultdict(list)
    node_failures = Counter()
    for start_event, end_event, seconds in node_spans:
        if start_event["session_id"] in session_ids:
            node_type = end_event.get("node_type") or start_event.get("node_type") or "unknown"
            node_types[node_type].append(seconds)
            if end_event.get("ok") is False:
                node_failures[node_type] += 1
    run_time_total = sum(run_times.values())

    def time_share(spans):
        busy = sum(seconds for start_event, _, seconds in spans if start_event["session_id"] in session_ids)
        return round(busy / run_time_total, 3) if run_time_total else 0.0

    peak_active = 0
    for start_ts, end_ts in (active_intervals[s] for s in session_ids if s in active_intervals):
        overlapping = sum(1 for other_start, other_end in active_intervals.values()
                          if other_start <= start_ts < other_end)
        peak_active = max(peak_active, overlapping)

    return {
        "step_rate": step_rate,
        "fired": len(records),
        "completed": completed,
        "failed": failed,
        "failed_reasons": dict(failed_reasons + http_failures),
        "stopped": stopped,
        "unfinished": unfinished,
        "failure_rate": round(failure_rate, 4),
        "api_latency_ms": distribution([float(r["api_latency_ms"]) for r in records
                                        if r.get("api_latency_ms") is not None]),
        "queue_wait_s": distribution(list(queue_waits.values())),
        "run_time_s": distribution(list(run_times.values())),
        "total_s": distribution(totals),
        "queue_wait_p95_first_minute_s": first_p95,
        "queue_wait_p95_last_minute_s": last_p95,
        "queue_growing": queue_growing,
        "sustained": sustained,
        "peak_active_sessions": peak_active,
        "node_types": {
            node_type: {**{k: v for k, v in distribution(durations).items() if k != "max"},
                        "failed": node_failures[node_type]}
            for node_type, durations in sorted(node_types.items())
        },
        "llm_time_share": time_share(llm_spans),
        "sandbox_exec_time_share": time_share(exec_spans),
        # Crew handed the agent node over but the agent service had not picked it up yet.
        "agent_queue_wait_s": distribution([seconds for start_event, _, seconds in agent_queue_spans
                                            if start_event["session_id"] in session_ids]),
        "agent_queue_time_share": time_share(agent_queue_spans),
        "tokens_per_session": distribution([tokens_by_session[s] for s in session_ids if s in tokens_by_session]),
    }


def summarize_conversation(turns, config):
    """turns.jsonl from conversation.py: how far each user got and how turns grow with history."""
    turn_count = len((config.get("args") or {}).get("turns") or []) or max(to_int(t.get("turn")) or 0 for t in turns)
    last_turn = {}
    for row in turns:
        last_turn[row.get("user")] = row  # rows are appended in order per user
    completed = sum(1 for row in last_turn.values() if row.get("turn") == turn_count and row.get("status") == "end")
    stopped_at = Counter(f"turn{row.get('turn')}: {row.get('status') or row.get('error') or 'no reply'}"[:120]
                         for row in last_turn.values()
                         if not (row.get("turn") == turn_count and row.get("status") == "end"))
    by_turn = defaultdict(list)
    for row in turns:
        by_turn[to_int(row.get("turn"))].append(row)
    return {
        "users": len(last_turn),
        "turns_per_user": turn_count,
        "users_completed": completed,
        "stopped_at": dict(stopped_at),
        "per_turn": [
            {
                "turn": turn,
                "history_messages": rows[0].get("history_messages"),
                "turn_s": distribution([float(r["turn_s"]) for r in rows if r.get("turn_s") is not None]),
                "reply_chars_p50": distribution([float(r["reply_chars"]) for r in rows
                                                 if r.get("reply_chars")])["p50"],
            }
            for turn, rows in sorted(by_turn.items(), key=lambda item: item[0] or 0)
        ],
    }


def build_summary(config, fired, events, memory, turns=None):
    events, unattributed = attribute_sessions(events)
    fired_session_ids = {to_int(r.get("session_id")) for r in fired} - {None}
    events = [event for event in events if event["session_id"] in fired_session_ids]

    checkpoints = defaultdict(dict)  # session -> checkpoint -> first event
    for event in events:
        checkpoints[event["session_id"]].setdefault(event.get("checkpoint"), event)

    node_spans = pair_spans(events, "node_start", "node_end",
                            lambda e: (e["session_id"], e.get("node_name")))
    call_key = lambda e: (e["session_id"], e.get("service"), join_id(e))  # noqa: E731
    llm_spans = pair_spans(events, "llm_start", "llm_end", call_key)
    exec_spans = pair_spans(events, "exec_start", "exec_end", call_key)
    agent_queue_spans = pair_spans(events, "agent_dispatched", "request_consumed",
                                   lambda e: (e["session_id"], e.get("correlation_id")))
    tokens_by_session = defaultdict(int)
    for event in events:
        if event.get("checkpoint") == "llm_end" and to_int(event.get("total_tokens")) is not None:
            tokens_by_session[event["session_id"]] += to_int(event["total_tokens"])

    active_intervals = {
        session_id: (marks["slot_acquired"]["ts"],
                     marks["session_end"]["ts"] if "session_end" in marks else math.inf)
        for session_id, marks in checkpoints.items() if "slot_acquired" in marks
    }

    def active_at(ts):
        return sum(1 for start_ts, end_ts in active_intervals.values() if start_ts <= ts < end_ts)

    fire_ts = [float(r["ts"]) for r in fired if r.get("ts") is not None]
    memory_ts = [row["ts"] for row in memory]
    load_start = config.get("load_start_ts") or (min(fire_ts) if fire_ts else min(memory_ts, default=0.0))
    load_end = config.get("load_end_ts") or (max(fire_ts) if fire_ts else load_start)

    steps = {}
    for record in sorted(fired, key=lambda r: r.get("ts") or 0):
        steps.setdefault(record.get("step_rate"), []).append(record)
    step_summaries = [
        summarize_step(rate, records, checkpoints, node_spans, llm_spans, exec_spans, active_intervals,
                       agent_queue_spans, tokens_by_session)
        for rate, records in steps.items()
    ]
    # conversation.py names its steps "turn1".."turnN": arrivals are closed-loop, so the
    # fixed-rate queue-growth verdict does not apply to them.
    mode = "conversation" if any(isinstance(rate, str) for rate in steps) else "fixed_rate"
    if mode == "conversation":
        for step in step_summaries:
            step["sustained"] = None

    sample_times = sorted(set(memory_ts))
    active_by_ts = {ts: active_at(ts) for ts in sample_times}
    containers = {}
    rows_by_container = defaultdict(list)
    for row in memory:
        rows_by_container[row["container"]].append(row)
    for container, rows in sorted(rows_by_container.items()):
        baseline = mean_or_none([row["mem_mb"] for row in rows if row["ts"] < load_start])
        cooldown = [row for row in rows if row["ts"] >= load_end]
        last_minute = [row["mem_mb"] for row in cooldown if row["ts"] >= cooldown[-1]["ts"] - MINUTE_S] \
            if cooldown else []
        fit = fit_line([active_by_ts[row["ts"]] for row in rows], [row["mem_mb"] for row in rows])
        leak_reference = baseline if baseline is not None else fit["intercept_mb"]
        containers[container] = {
            **fit,
            "baseline_sample_mb": baseline,
            "peak_mb": round(max(row["mem_mb"] for row in rows), 1),
            "peak_cpu_pct": round(max(row["cpu_pct"] for row in rows), 1),
            "cooldown_last_minute_mb": mean_or_none(last_minute),
            "leak_mb": round(statistics.fmean(last_minute) - leak_reference, 1) if last_minute else None,
        }

    sustained_rates = [step["step_rate"] for step in step_summaries if step["sustained"]]
    return {
        "meta": config,
        "mode": mode,
        "events_unattributed": unattributed,
        "steps": step_summaries,
        "conversation": summarize_conversation(turns, config) if turns else None,
        "containers": containers,
        "concurrency_timeline": [[round(ts - load_start, 1), active_by_ts[ts]] for ts in sample_times],
        "verdict": {
            "max_sustained_rate": max(sustained_rates) if sustained_rates else None,
            "rule": (f"highest step with last-minute queue-wait p95 <= max({QUEUE_GROWTH_RATIO} x first-minute p95, "
                     f"first-minute p95 + {QUEUE_GROWTH_FLOOR_S} s) and failure rate < {MAX_FAILURE_RATE:.0%}"),
        },
    }


def print_table(summary):
    print(f"{'step':>8} {'fired':>6} {'done':>6} {'fail':>5} {'unfin':>6} {'queue p95 s':>12} "
          f"{'agentQ p95 s':>12} {'run p50/p95 s':>15} {'llm %':>6} {'tok p50':>8} {'sustained':>9}")
    for step in summary["steps"]:
        run = step["run_time_s"]
        print(f"{str(step['step_rate']):>8} {step['fired']:>6} {step['completed']:>6} {step['failed']:>5} "
              f"{step['unfinished']:>6} {step['queue_wait_s']['p95']:>12} {step['agent_queue_wait_s']['p95']:>12} "
              f"{run['p50']:>7}/{run['p95']:<7} {step['llm_time_share'] * 100:>6.1f} "
              f"{step['tokens_per_session']['p50']:>8} {str(step['sustained']):>9}")
    if not summary["steps"]:
        print("  no data (fired.jsonl empty)")
    print(f"\n{'container':<28} {'MB/session':>10} {'base MB':>8} {'R2':>6} {'peak MB':>8} {'peak CPU%':>9} {'leak MB':>8}")
    for name, container in summary["containers"].items():
        print(f"{name:<28} {container['mb_per_session']:>10} {container['intercept_mb']:>8} {container['r2']:>6} "
              f"{container['peak_mb']:>8} {container['peak_cpu_pct']:>9} {str(container['leak_mb']):>8}")
    if not summary["containers"]:
        print("  no data (memory.csv empty)")
    conversation = summary.get("conversation")
    if conversation:
        print(f"\nconversation: {conversation['users_completed']}/{conversation['users']} users finished all "
              f"{conversation['turns_per_user']} turns; stopped: {conversation['stopped_at'] or 'none'}")
        for turn in conversation["per_turn"]:
            print(f"  turn {turn['turn']}: history {turn['history_messages']} msgs, "
                  f"turn p50/p95 {turn['turn_s']['p50']}/{turn['turn_s']['p95']} s, reply p50 {turn['reply_chars_p50']} chars")
    if summary.get("mode") == "conversation":
        print(f"\nmode: conversation (no sustained-rate verdict)   (unattributed log lines: {summary['events_unattributed']})")
    else:
        print(f"\nmax sustained rate: {summary['verdict']['max_sustained_rate']} sessions/min"
              f"   (unattributed log lines: {summary['events_unattributed']})")


# ---------------------------------------------------------------- self-test


def self_test():
    p = distribution(range(1, 101))
    assert (p["p50"], p["p95"], p["max"], p["n"]) == (50.5, 95.05, 100, 100), p
    assert distribution([])["n"] == 0 and distribution([7.0])["p95"] == 7.0
    line = fit_line([0, 1, 2, 3], [100, 110, 120, 130])
    assert (line["mb_per_session"], line["intercept_mb"], line["r2"]) == (10, 100, 1), line
    assert fit_line([2, 2], [1, 5])["fit"] == "no variation in active sessions"

    fired, events = [], []

    def session(session_id, rate, fire_ts, queue_s, status="end"):
        fired.append({"run_index": session_id, "step_rate": rate, "graph_id": 1, "ts": fire_ts,
                      "session_id": session_id, "http_status": 201, "api_latency_ms": 50.0, "error": None})
        slot = fire_ts + 0.2 + queue_s
        events.extend([
            {"ts": fire_ts, "service": "django", "session_id": session_id, "checkpoint": "request_received"},
            {"ts": fire_ts + 0.1, "service": "crew", "session_id": session_id, "checkpoint": "received"},
            {"ts": slot, "service": "crew", "session_id": session_id, "checkpoint": "slot_acquired"},
            {"ts": slot + 0.5, "service": "crew", "session_id": session_id, "checkpoint": "node_start",
             "node_type": "agent", "node_name": "a", "correlation_id": f"c{session_id}"},
            # agent line with no session_id: must be joined via correlation_id
            {"ts": slot + 0.6, "service": "crew", "session_id": session_id, "checkpoint": "agent_dispatched",
             "correlation_id": f"c{session_id}"},
            {"ts": slot + 0.8, "service": "agent", "session_id": None, "checkpoint": "request_consumed",
             "correlation_id": f"c{session_id}"},
            {"ts": slot + 1, "service": "agent", "session_id": None, "checkpoint": "llm_start",
             "correlation_id": f"c{session_id}"},
            {"ts": slot + 2, "service": "agent", "session_id": None, "checkpoint": "llm_end",
             "correlation_id": f"c{session_id}", "total_tokens": 100},
            {"ts": slot + 2.5, "service": "crew", "session_id": session_id, "checkpoint": "node_end",
             "node_type": "agent", "node_name": "a", "ok": True},
            {"ts": slot + 10, "service": "crew", "session_id": session_id, "checkpoint": "session_end",
             "status": status, "reason": "boom" if status == "error" else None},
        ])

    for index in range(20):  # 10/min for 120 s, flat 0.1 s queue
        session(index + 1, 10, 1000 + index * 6, 0.0)
    for index in range(100):  # 50/min for 120 s, queue grows 0.5 s per session
        session(index + 101, 50, 1200 + index * 1.2, index * 0.5, "error" if index == 50 else "end")
    events.append({"ts": 1500, "service": "sandbox", "session_id": None, "checkpoint": "exec_start",
                   "execution_id": "orphan"})
    # active: t=990 -> 0, t=1005 -> 1 (session 1), t=1008 -> 2 (sessions 1, 2), t=1600 -> 0
    memory = [{"ts": ts, "container": "crew", "mem_mb": 100 + 10 * active, "cpu_pct": 5.0}
              for ts, active in ((990, 0), (1005, 1), (1008, 2), (1600, 0))]
    config = {"load_start_ts": 1000, "load_end_ts": 1320}

    summary = build_summary(config, fired, events, memory)
    slow, fast = summary["steps"]
    assert (slow["step_rate"], slow["fired"], slow["completed"], slow["unfinished"]) == (10, 20, 20, 0), slow
    assert slow["queue_wait_s"]["p95"] == 0.1 and slow["run_time_s"]["p50"] == 10.0, slow
    assert slow["llm_time_share"] == 0.1 and slow["node_types"]["agent"]["n"] == 20, slow
    assert slow["sustained"] is True and slow["queue_growing"] is False, slow
    assert fast["queue_growing"] is True and fast["sustained"] is False, fast
    assert fast["failed"] == 1 and fast["failed_reasons"] == {"boom": 1}, fast
    assert summary["verdict"]["max_sustained_rate"] == 10, summary["verdict"]
    assert summary["events_unattributed"] == 1, summary["events_unattributed"]
    crew = summary["containers"]["crew"]
    assert (crew["mb_per_session"], crew["intercept_mb"], crew["r2"]) == (10, 100, 1), crew
    assert crew["baseline_sample_mb"] == 100 and crew["leak_mb"] == 0, crew
    assert slow["agent_queue_wait_s"]["p50"] == 0.2 and slow["tokens_per_session"]["p50"] == 100, slow
    assert summary["mode"] == "fixed_rate" and summary["conversation"] is None
    empty = build_summary({}, [], [], [])
    assert empty["verdict"]["max_sustained_rate"] is None  # empty run never crashes

    # conversation run: 2 users x 2 turns, user 2 stops at turn 2; steps are "turnN", no verdict
    chat_fired = [{**record, "step_rate": f"turn{1 + index % 2}"} for index, record in enumerate(fired[:4])]
    turns = [{"user": 1, "turn": 1, "status": "end", "turn_s": 3.0, "history_messages": 0, "reply_chars": 50},
             {"user": 1, "turn": 2, "status": "end", "turn_s": 5.0, "history_messages": 2, "reply_chars": 70},
             {"user": 2, "turn": 1, "status": "end", "turn_s": 4.0, "history_messages": 0, "reply_chars": 60},
             {"user": 2, "turn": 2, "status": "error", "turn_s": 1.0, "history_messages": 2, "reply_chars": None}]
    chat = build_summary({"args": {"turns": ["hi", "more"]}}, chat_fired, events, memory, turns)
    assert chat["mode"] == "conversation" and chat["verdict"]["max_sustained_rate"] is None, chat["verdict"]
    assert [step["step_rate"] for step in chat["steps"]] == ["turn1", "turn2"]
    assert all(step["sustained"] is None for step in chat["steps"])
    talk = chat["conversation"]
    assert (talk["users"], talk["users_completed"], talk["stopped_at"]) == (2, 1, {"turn2: error": 1}), talk
    assert [t["history_messages"] for t in talk["per_turn"]] == [0, 2] and talk["per_turn"][1]["turn_s"]["max"] == 5.0
    print_table(summary)
    print_table(empty)
    print_table(chat)
    print("self-test OK")


def main():
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    run_dir = Path(sys.argv[1])
    summary = build_summary(*load_run(run_dir))
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print_table(summary)
    print(f"\nwrote {run_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
