"""Turns a run's records, checkpoint events and samples into the flat run folder (schema v1)."""

from __future__ import annotations

import csv
import gzip
import hashlib
import itertools
import json
import math
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from config import AbortRules, Case, PassRules, redacted_case_text
from load import INTERRUPTED, RUNNER_STATUSES, SessionRecord

SCHEMA_VERSION = 1
TOOL_VERSION = "1.0.0"
MIN_MEASURED = 10
# Unfinished sessions could be the slowest ones: once they are more than 5% of a level, its p95
# is unknown until they end.
UNFINISHED_LIMIT = 0.05
MIN_FIT_R2 = 0.5  # weaker memory-vs-running fits are noise and stay out of the headline
SESSION_COLUMNS = [
    "phase",
    "segment",
    "level",
    "kind",
    "cold",
    "session_id",
    "intended_ts",
    "sent_ts",
    "gen_lag_ms",
    "api_ms",
    "http_status",
    "arrival_ts",
    "received_ts",
    "slot_ts",
    "end_ts",
    "status",
    "censored",
    "error_reason",
    "e2e_s",
    "dispatch_s",
    "queue_wait_s",
    "run_s",
    "llm_s",
    "llm_calls",
    "tokens",
    "cost_usd",
    "agent_queue_s",
    "python_s",
    "sandbox_wait_s",
    "other_s",
    "platform_overhead_s",
]
DURATIONS = ["e2e_s", "queue_wait_s", "run_s", "llm_s", "platform_overhead_s", "sandbox_wait_s"]
STAT_KEYS = ["p50", "p90", "p95", "p99", "max", "mean"]
STEP_COLUMNS = [
    "phase",
    "segment",
    "level",
    "kind",
    "target",
    "inflight_mean",
    "running_mean",
    "steady_s",
    "sent",
    "completed",
    "failed",
    "interrupted",
    "throughput_per_min",
    "error_rate",
    *[f"{name}_{key}" for name in DURATIONS for key in STAT_KEYS],
    "cpu_s_per_session",
    "mb_per_concurrent",
    "gen_lag_p99_ms",
    "verdict",
    "live_verdict",
    "fail_reasons",
    "bottleneck",
]
CONTAINER_COLUMNS = [
    "phase",
    "segment",
    "level",
    "kind",
    "container",
    "cpu_s",
    "cpu_s_per_session",
    "cpu_pct_mean",
    "cpu_pct_max",
    "mem_mean_mb",
    "mem_peak_mb",
    "restarts",
    "oom_kills",
    "phase_peak_mb",
    "phase_peak_level",
]
CONTAINER_PHASE_COLUMNS = [
    "phase",
    "container",
    "baseline_mb",
    "mb_per_concurrent",
    "r2",
    "retained_mb_after_cooldown",
]
NODE_COLUMNS = [
    "phase",
    "segment",
    "level",
    "kind",
    "node_name",
    "node_type",
    "count",
    "p50_s",
    "p95_s",
    "mean_s",
    "max_s",
    "error_count",
]
TIMELINE_COLUMNS = [
    "ts",
    "rel_s",
    "phase",
    "segment",
    "level",
    "target",
    "inflight",
    "running",
    "queued",
    "completed",
    "failed",
    "host_cpu_pct",
    "host_mem_avail_mb",
    "host_mem_avail_pct",
    "load1",
    "pg_connections",
    "pg_max_connections",
    "redis_used_mb",
    "runner_cpu_pct",
    "run_rel_s",
    "throughput_per_min",
    "e2e_p95_60s",
]
CONTAINER_TIMELINE_COLUMNS = [
    "ts",
    "rel_s",
    "phase",
    "segment",
    "level",
    "container",
    "cpu_pct",
    "mem_mb",
    "restarts",
    "oom_kills",
]
EVENT_COLUMNS = ["session_id", "service", "checkpoint", "ts", "node_name", "extra_json"]
INFLIGHT_STAGE_COLUMNS = ["ts", "run_rel_s", "phase", "segment", "stage", "count"]
FINDING_COLUMNS = [
    "phase",
    "severity",
    "kind",
    "message",
    "ts",
    "run_rel_s",
    "tab",
    "container",
]
# Window of the timeline's rolling throughput_per_min and e2e_p95_60s.
ROLLING_S = 60
# In-flight stage of a session from the last checkpoint it reached (inflight_stages.csv), in
# pipeline order: the viewer colours the stages in this order, so a new stage goes at its
# place in the pipeline and the list stays at 8 (the categorical palette has 8 colours).
STAGES = [
    "waiting for crew",
    "crew",
    "agent queue",
    "agent",
    "LLM",
    "waiting for sandbox",
    "python",
    "result return",
]
STAGE_AFTER = {
    ("crew", "received"): "waiting for crew",  # received, no slot yet: still queued in crew
    ("crew", "agent_dispatched"): "agent queue",
    ("agent", "llm_start"): "LLM",
    ("agent", "result_published"): "crew",
    ("crew", "sandbox_dispatched"): "waiting for sandbox",
    ("agent", "sandbox_dispatched"): "waiting for sandbox",
    ("sandbox", "exec_start"): "python",
    ("sandbox", "exec_end"): "result return",
}
# Any other checkpoint: crew bookkeeping, agent work outside an LLM call, and so on.
STAGE_BY_SERVICE = {
    "django_app": "waiting for crew",
    "crew": "crew",
    "agent": "agent",
    "sandbox": "python",
}
# Parts of a session's time (sessions.csv.gz columns) with their readable names.
BREAKDOWN_STAGES = {
    "dispatch_s": "dispatch",
    "queue_wait_s": "queue wait",
    "agent_queue_s": "agent queue",
    "llm_s": "LLM",
    "python_s": "Python",
    "sandbox_wait_s": "sandbox wait",
    "other_s": "crew overhead",
}
# judge_level's reason for a level whose settle sessions timed out before any was measured
SETTLE_TIMEOUT_REASON = "settle sessions timed out"
# findings.csv: severities and the rule thresholds (docs/METRICS.md → findings.csv).
CRITICAL, WARNING, INFO = "critical", "warning", "info"
SEVERITY_ORDER = {CRITICAL: 0, WARNING: 1, INFO: 2}
PLATEAU_GROWTH = 0.10  # a ladder level that rose but raised throughput by less has plateaued
DOMINANT_STAGE_SHARE = 0.5  # one stage above this share of the mean e2e at the headline level
RETAINED_MIN_MB = 50  # memory kept after cooldown is flagged above the larger of this ...
RETAINED_SHARE = 0.10  # ... and this share of the container's baseline
# Failed start requests that did not fail their level, above this share of the phase: a warning.
HTTP_ERROR_WARN_SHARE = 0.01
# Failed start requests at least this share of a level's failures: they failed the level.
HTTP_ERROR_MAJORITY = 0.5
HOST_CPU_SATURATED_PCT = 90  # mean host CPU in a level at or above this: the host is saturated
# Containers that run a fixed number of Python processes, each on at most one core: the env
# variable that sets the count (None: always one). Mean CPU at PROCESS_SATURATED_SHARE of those
# cores means the container is at its limit, however many host cores are idle.
PROCESS_COUNT_VARIABLES = {"crew": None, "agent": None, "django_app": "DJANGO_SGI_WORKERS"}
PROCESS_SATURATED_SHARE = 0.85
# LLM call p95 above this many times the reference (the smoke step's) is slow: slow_provider,
# or llm_slowed_by_host when the host CPU was saturated in every such level.
SLOW_LLM_FACTOR = 2


@dataclass
class Window:
    """One level: settle from start_ts, measure sessions sent until end_ts (the end of the
    hold), then keep the load until those sessions have ended (finish_end_ts), and judge."""

    phase: str
    level: int
    kind: str
    segment: int
    start_ts: float
    settle_end_ts: float
    end_ts: float
    abort_reason: str | None = None
    live_verdict: str | None = None
    finish_end_ts: float | None = None  # None: judged at end_ts (dev runs, aborted levels)

    @property
    def verdict_ts(self) -> float:
        """When the level was judged: sessions without an end by then are unfinished."""
        return self.end_ts if self.finish_end_ts is None else self.finish_end_ts

    def measures(self, session: dict) -> bool:
        """A session (row, or `vars()` of a record) sent in this level's measured window.
        Sessions sent while the measured ones finish have kind `finish` and are never measured."""
        return (
            session["phase"] == self.phase
            and session["segment"] == self.segment
            and session["level"] == self.level
            and session["kind"] == self.kind
            and self.settle_end_ts <= session["intended_ts"] <= self.end_ts
        )

    def settles(self, session: dict) -> bool:
        """A session sent in this level's settle window: never measured, but it decides the
        verdict when the level measured nothing (see judge_level)."""
        return (
            session["phase"] == self.phase
            and session["segment"] == self.segment
            and session["level"] == self.level
            and session["kind"] == self.kind
            and session["intended_ts"] < self.settle_end_ts
        )


@dataclass
class Segment:
    phase: str
    segment: int
    kind: str
    baseline_start: float
    load_start: float
    load_end: float
    cooldown_end: float


@dataclass
class RunData:
    case: Case
    variant_name: str
    meta: dict
    records: list[SessionRecord]
    windows: list[Window]
    segments: list[Segment]
    events: list[dict]
    timeline: list[dict]
    container_timeline: list[dict]


# ---------------------------------------------------------------- statistics


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 4)


def stats(values: list[float]) -> dict:
    values = [value for value in values if value is not None]
    if not values:
        return dict.fromkeys(STAT_KEYS)
    return {
        "p50": percentile(values, 0.5),
        "p90": percentile(values, 0.9),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": round(max(values), 4),
        "mean": round(sum(values) / len(values), 4),
    }


def fit_line(xs: list[float], ys: list[float]) -> tuple[float | None, float | None]:
    """Least-squares slope and r²; (None, None) when x does not vary."""
    count = len(xs)
    if count < 3:
        return None, None
    mean_x, mean_y = sum(xs) / count, sum(ys) / count
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        return None, None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / sxx
    total = sum((y - mean_y) ** 2 for y in ys)
    residual = sum((y - (mean_y + slope * (x - mean_x))) ** 2 for x, y in zip(xs, ys, strict=True))
    return round(slope, 3), (round(1 - residual / total, 3) if total else None)


# ---------------------------------------------------------------- sessions


def index_events(events: list[dict]) -> tuple[dict[int, list[dict]], int]:
    """Events per session. Agent lines carry only correlation_id; crew's agent_dispatched maps it."""
    correlation_session = {
        event["correlation_id"]: event["session_id"]
        for event in events
        if event.get("checkpoint") == "agent_dispatched"
        and isinstance(event.get("session_id"), int)
    }
    by_session: dict[int, list[dict]] = defaultdict(list)
    unattributed = 0
    for event in events:
        session_id = event.get("session_id")
        if not isinstance(session_id, int):
            session_id = correlation_session.get(event.get("correlation_id"))
        if isinstance(session_id, int):
            by_session[session_id].append(event)
        else:
            unattributed += 1
    return by_session, unattributed


def pair_spans(events: list[dict], start: str, end: str, key) -> list[tuple[dict, dict]]:
    open_spans: dict = defaultdict(list)
    spans = []
    for event in sorted(events, key=lambda item: float(item["ts"])):
        if event.get("checkpoint") == start:
            open_spans[key(event)].append(event)
        elif event.get("checkpoint") == end and open_spans[key(event)]:
            spans.append((open_spans[key(event)].pop(0), event))
    return spans


def _span_seconds(spans: list[tuple[dict, dict]]) -> float:
    return round(sum(float(end["ts"]) - float(start["ts"]) for start, end in spans), 4)


def session_row(record: SessionRecord, events: list[dict], now: float | None = None) -> dict:
    first: dict = {}
    for event in sorted(events, key=lambda item: float(item["ts"])):
        first.setdefault((event["service"], event["checkpoint"]), event)

    def ts(service: str, checkpoint: str) -> float | None:
        event = first.get((service, checkpoint))
        if event is None:
            return None
        return float(event.get("arrival_ts") or event["ts"])

    end_event = first.get(("crew", "session_end"))
    status = record.end_status
    if status in RUNNER_STATUSES:
        # The runner ended it (timeout, failed send, interrupt): crew's session_end, if any,
        # only answers the runner's stop call and can come much later (e.g. at the next
        # stack restart), so it must not stretch the duration past the verdict time.
        end_ts = record.done_ts
    else:
        end_ts = float(end_event["ts"]) if end_event else record.done_ts
        if end_event:
            status = end_event.get("status") or status
    still_running = end_ts is None and now is not None and record.sent_ts is not None
    if still_running:
        end_ts, status = now, None
    # the e2e of a running or runner-stopped session is only a lower bound of its duration
    censored = still_running or status == INTERRUPTED
    received_ts, slot_ts = ts("crew", "received"), ts("crew", "slot_acquired")
    llm = pair_spans(events, "llm_start", "llm_end", lambda event: event.get("correlation_id"))
    executions = pair_spans(
        [e for e in events if e["service"] == "sandbox"],
        "exec_start",
        "exec_end",
        lambda event: event.get("execution_id"),
    )
    agent_queue = pair_spans(
        events, "agent_dispatched", "request_consumed", lambda event: event.get("correlation_id")
    )
    # crew or agent handing code to the sandbox until the sandbox starts running it; an
    # execution that never started adds nothing here (the session shows up as a timeout)
    sandbox_wait = pair_spans(
        events, "sandbox_dispatched", "exec_start", lambda event: event.get("execution_id")
    )
    llm_s, python_s, agent_queue_s, sandbox_wait_s = (
        _span_seconds(llm),
        _span_seconds(executions),
        _span_seconds(agent_queue),
        _span_seconds(sandbox_wait),
    )
    sent = record.sent_ts

    def minus(later: float | None, earlier: float | None) -> float | None:
        return round(later - earlier, 4) if later is not None and earlier is not None else None

    e2e = minus(end_ts, sent)
    run_s = minus(end_ts, slot_ts)
    return {
        "phase": record.phase,
        "segment": record.segment,
        "level": record.level,
        "kind": record.kind,
        "cold": int(record.kind == "cold"),
        "session_id": record.session_id,
        "intended_ts": record.intended_ts,
        "sent_ts": sent,
        "gen_lag_ms": round((sent - record.intended_ts) * 1000, 1) if sent is not None else None,
        "api_ms": record.api_ms,
        "http_status": record.http_status,
        "arrival_ts": ts("django_app", "request_received"),
        "received_ts": received_ts,
        "slot_ts": slot_ts,
        "end_ts": end_ts,
        "status": status,
        "censored": censored,
        "error_reason": (record.error or (end_event or {}).get("reason") or None)
        if status != "end"
        else None,
        "e2e_s": e2e,
        "dispatch_s": minus(received_ts, sent),
        "queue_wait_s": minus(slot_ts, received_ts),
        "run_s": run_s,
        "llm_s": llm_s,
        "llm_calls": len(llm),
        "tokens": sum(int(end.get("total_tokens") or 0) for _, end in llm),
        "cost_usd": round(sum(float(end.get("total_cost_usd") or 0) for _, end in llm), 6),
        "agent_queue_s": agent_queue_s,
        "python_s": python_s,
        "sandbox_wait_s": sandbox_wait_s,
        "other_s": max(0.0, round(run_s - llm_s - python_s - agent_queue_s - sandbox_wait_s, 4))
        if run_s is not None
        else None,
        "platform_overhead_s": round(e2e - llm_s, 4) if e2e is not None else None,
    }


def build_rows(
    records: list[SessionRecord], events: list[dict], now: float | None = None
) -> list[dict]:
    by_session, _ = index_events(events)
    return [session_row(record, by_session.get(record.session_id, []), now) for record in records]


# ---------------------------------------------------------------- verdicts


def measured(rows: list[dict], window: Window) -> list[dict]:
    return [row for row in rows if window.measures(row)]


def level_rows(rows: list[dict], window: Window) -> list[dict]:
    """Every session the level started (settle, measured and finish), without the cold one."""
    return [
        row
        for row in rows
        if row["phase"] == window.phase
        and row["segment"] == window.segment
        and row["level"] == window.level
        and not row["cold"]
    ]


def last_checkpoint(events: list[dict], before: float | None) -> str:
    """`<service> <checkpoint>` of the last event before `before` (the session's end), so
    crew's session_end answering the runner's stop does not hide where the session hung."""
    reached = [event for event in events if before is None or float(event["ts"]) < before]
    if not reached:
        return "no checkpoint"
    last = max(reached, key=lambda event: float(event["ts"]))
    return f"{last['service']} {last['checkpoint']}"


def _timeout_summary(rows: list[dict], by_session: dict[int, list[dict]]) -> tuple[int, str]:
    """(count, `<where> (count), ...`) of the rows with status timeout: the two most common
    checkpoints they last reached."""
    timed_out = [row for row in rows if row["status"] == "timeout"]
    where = Counter(
        last_checkpoint(by_session.get(row["session_id"], []), row["end_ts"]) for row in timed_out
    )
    return len(timed_out), ", ".join(f"{name} ({count})" for name, count in where.most_common(2))


def timed_out_text(rows: list[dict], by_session: dict[int, list[dict]]) -> str | None:
    """`N timed out; last checkpoint: <where> (count), ...` for the rows with status timeout,
    or None when none timed out."""
    count, where = _timeout_summary(rows, by_session)
    return f"{count} timed out; last checkpoint: {where}" if count else None


def _ended_by_verdict(row: dict, window: Window) -> bool:
    return row["end_ts"] is not None and row["end_ts"] <= window.verdict_ts


def _judged_rows(rows: list[dict], window: Window) -> list[dict]:
    """The level's sessions that count towards what failed it: those that ended by the verdict
    time, plus measured start requests that failed later (sent before an abort, they time out
    up to the API client's 30 s after it). A session the drain stopped after the verdict, as
    `timeout`, did not fail the level and does not count."""
    return [
        row
        for row in level_rows(rows, window)
        if _ended_by_verdict(row, window)
        or (window.measures(row) and row["status"] == "http_error")
    ]


def judge_level(
    rows: list[dict],
    window: Window,
    rules: PassRules,
    abort: AbortRules,
    by_session: dict[int, list[dict]],
) -> tuple[str, list[str]]:
    """judge() for one level from all session rows (live or final).

    When the level measured no session because the stack stalled during the settle window
    (no session ended, so no new one was started in the hold), the settle sessions that timed
    out by the verdict time fail the level: `invalid ... raise ladder.hold_s` would blame the
    hold and stop the bisect. The runner waits for those settle sessions before judging such a
    level (runner._finish_measured), so the live and the final verdict agree.
    """
    measured_rows = measured(rows, window)
    if not measured_rows and not window.abort_reason:
        stalled = [
            row
            for row in rows
            if window.settles(row) and row["status"] == "timeout" and _ended_by_verdict(row, window)
        ]
        if stalled:
            count, where = _timeout_summary(stalled, by_session)
            return "fail", [f"{count} {SETTLE_TIMEOUT_REASON} (last checkpoint: {where})"]
    return judge(measured_rows, window, rules, abort)


def _failed_level(reasons: list[str]) -> bool:
    """The level's failed sessions failed it: the error-rate rule, the abort on the error rate, or
    the settle-timeout rule (not latency, a restart or another abort)."""
    return any(
        reason.startswith("error rate") or SETTLE_TIMEOUT_REASON in reason for reason in reasons
    )


def _error_kind(row: dict) -> str:
    """`TimeoutError`, `HTTP 502`, ...: a failed start request's error up to its first colon."""
    kind = (row["error_reason"] or "").split(":", 1)[0].strip()
    return kind or (f"HTTP {row['http_status']}" if row["http_status"] else "no answer")


def start_failures(rows: list[dict], window: Window, reasons: list[str]) -> list[dict] | None:
    """The level's failed start requests when they failed it: the failures failed the level and
    at least HTTP_ERROR_MAJORITY of the level's failed sessions (_judged_rows) are http_error."""
    if not _failed_level(reasons):
        return None
    failed = [row for row in _judged_rows(rows, window) if is_failed(row)]
    requests = [row for row in failed if row["status"] == "http_error"]
    return requests if requests and len(requests) >= HTTP_ERROR_MAJORITY * len(failed) else None


def start_failures_text(failed: list[dict], started: list[dict]) -> str:
    """`16 start requests failed (TimeoutError; API p95 27.1 s)`: the most common error and the
    p95 start-request time of every session the level started."""
    api_p95 = percentile([row["api_ms"] for row in started if row["api_ms"] is not None], 0.95)
    detail = Counter(_error_kind(row) for row in failed).most_common(1)[0][0]
    if api_p95 is not None:
        detail += f"; API p95 {api_p95 / 1000:.1f} s"
    return f"{len(failed)} start requests failed ({detail})"


def failure_text(
    rows: list[dict], window: Window, reasons: list[str], by_session: dict[int, list[dict]]
) -> str | None:
    """What failed a level, when its failed sessions did (see _failed_level): mostly failed start
    requests (start_failures_text), otherwise timed-out sessions with the checkpoint where they
    hung. Sessions count as in _judged_rows. The runner's live verdict line prints the same text
    from what it knows at its verdict."""
    requests = start_failures(rows, window, reasons)
    if requests:
        return start_failures_text(requests, level_rows(rows, window))
    if not _failed_level(reasons):
        return None
    return timed_out_text(_judged_rows(rows, window), by_session)


def saturated_processes(container_samples: list[dict], env: dict) -> list[tuple[str, str]]:
    """(container, `crew at one core (one process, 86 % CPU)` / `django_app at its 4 workers (350 %
    CPU)`) for each container of PROCESS_COUNT_VARIABLES whose mean CPU in the samples reaches
    PROCESS_SATURATED_SHARE of the cores its processes can use. A Python process uses at most one
    core, so such a container is the limit even while the host has idle cores."""
    saturated = []
    for name, variable in PROCESS_COUNT_VARIABLES.items():
        mean = _mean(row["cpu_pct"] for row in container_samples if row["container"] == name)
        processes = 1  # crew and agent; django_app's default when the variable is not set
        if variable and env.get(variable) is not None:
            count = str(env[variable]).strip()
            if not count.isdecimal() or int(count) == 0:
                # unreadable: the worker count is unknown, and guessing one could call a
                # service saturated that is not (or hide one that is), so no verdict on it
                continue
            processes = int(count)
        if mean is None or mean < PROCESS_SATURATED_SHARE * processes * 100:
            continue
        if variable is None:
            saturated.append((name, f"{name} at one core (one process, {mean:.0f} % CPU)"))
        else:
            workers = f"{processes} worker{'s' if processes > 1 else ''}"
            saturated.append((name, f"{name} at its {workers} ({mean:.0f} % CPU)"))
    return saturated


def is_failed(row: dict) -> bool:
    """Ended with a status other than `end`. A session that has not ended yet, or that the
    runner stopped because the run was interrupted, has not failed."""
    return not row["censored"] and row["status"] not in (None, "end")


def _latency_rules(rows: list[dict], rules: PassRules) -> list[tuple]:
    """(label, limit, known values, lower bounds, unfinished count) per p95 rule.

    Unfinished sessions (still running when judged, stopped by an interrupt, or never seen to
    end) give only lower bounds: the e2e so far, or the queue wait so far for those still
    queued.
    """
    ok = [row for row in rows if row["status"] == "end"]
    unfinished = [row for row in rows if row["censored"] or row["status"] is None]
    still_queued = [row for row in unfinished if row["queue_wait_s"] is None]
    return [
        (
            "e2e",
            rules.p95_e2e_s,
            [row["e2e_s"] for row in ok if row["e2e_s"] is not None],
            [row["e2e_s"] for row in unfinished if row["e2e_s"] is not None],
            len(unfinished),
        ),
        (
            "queue wait",
            rules.p95_queue_wait_s,
            [row["queue_wait_s"] for row in ok + unfinished if row["queue_wait_s"] is not None],
            [
                row["end_ts"] - row["received_ts"]
                for row in still_queued
                if row["end_ts"] is not None and row["received_ts"] is not None
            ],
            len(still_queued),
        ),
    ]


def judge(
    rows: list[dict], window: Window, rules: PassRules, abort: AbortRules
) -> tuple[str, list[str]]:
    """pass / fail / invalid for one window's measured rows (live rows or final rows).

    The runner judges a level only once its measured sessions have ended (or hit
    session_timeout_s), so normally every row has its true duration. A rule fails when it
    fails even with every unfinished session at its lower bound. It can pass only when at
    least MIN_MEASURED sessions ended by the verdict time and no more than UNFINISHED_LIMIT
    of them are unfinished: a safety net for an interrupted level or missing end times.
    """
    lag_p99 = (
        percentile([row["gen_lag_ms"] for row in rows if row["gen_lag_ms"] is not None], 0.99) or 0
    )
    if lag_p99 > abort.generator_lag_p99_ms:
        return "invalid", [f"generator-limited: lag p99 {lag_p99:.0f} ms"]
    if window.abort_reason:
        return "fail", [window.abort_reason]
    finished = [
        row
        for row in rows
        if not row["censored"] and row["end_ts"] is not None and row["end_ts"] <= window.verdict_ts
    ]
    proven, estimated, unknown = [], [], []
    for label, limit, known, bounds, unfinished in _latency_rules(rows, rules):
        if limit is None or not (known or bounds):
            continue  # rule off, or no checkpoints for it (crew wrote no BENCH lines)
        at_least = percentile(known + bounds, 0.95)
        if len(known) + len(bounds) >= MIN_MEASURED and at_least > limit:
            proven.append(f"p95 {label} {at_least:.1f} s > {limit:g} s")
        elif unfinished > UNFINISHED_LIMIT * len(rows):
            unknown.append(
                f"p95 {label} unknown: {unfinished} of {len(rows)} measured sessions had not"
                " ended when the level was judged"
            )
        else:
            p95 = percentile(known, 0.95)
            if p95 is not None and p95 > limit:
                estimated.append(f"p95 {label} {p95:.1f} s > {limit:g} s")
    if len(finished) < MIN_MEASURED:
        if proven:
            return "fail", proven
        return "invalid", [
            f"too few measured sessions ended ({len(finished)}); raise ladder.hold_s"
        ]
    reasons = []
    error_rate = sum(1 for row in rows if is_failed(row)) / len(rows)
    if error_rate > rules.max_error_rate:
        reasons.append(f"error rate {error_rate:.1%} > {rules.max_error_rate:.1%}")
    reasons += proven + estimated
    if reasons:
        return "fail", reasons
    if unknown:
        return "invalid", unknown
    return "pass", []


def bottleneck(context: dict) -> str:
    if context["restarts"]:
        return f"container restart/OOM: {', '.join(context['restarts'])}"
    processes = "; ".join(context["saturated_processes"])
    if context["failure"]:
        # what failed the level (where sessions hung, which requests failed), with the process
        # at its core limit when there is one: that is usually why
        return f"{context['failure']}; {processes}" if processes else context["failure"]
    if (
        context["host_mem_avail_min_pct"] is not None
        and context["host_mem_avail_min_pct"] < context["ram_guard_pct"]
    ):
        return f"host RAM (available {context['host_mem_avail_min_pct']:.0f}%)"
    host_cpu = context["host_cpu_mean"]
    host_saturated = host_cpu is not None and host_cpu >= HOST_CPU_SATURATED_PCT
    if processes:
        # a process at its core caps the service whatever the host has left; a saturated host
        # is said too, as it slows everything else down
        return f"{processes}; host CPU {host_cpu:.0f}%" if host_saturated else processes
    if host_saturated:
        return f"host CPU {host_cpu:.0f}%"
    if context["containers_at_cpu_limit"]:
        return f"container CPU limit: {', '.join(context['containers_at_cpu_limit'])}"
    if (
        context["crew_cap"]
        and context["running_mean"] >= 0.95 * context["crew_cap"]
        and context["queued_mean"] > 0
    ):
        return f"crew slots full ({context['crew_cap']}) with sessions queued"
    previous = context["previous_agent_queue_p95"]
    if (
        context["agent_queue_p95"]
        and previous is not None
        and context["agent_queue_p95"] > max(2 * previous, 1.0)
    ):
        return f"agent queue growing (p95 {context['agent_queue_p95']:.1f} s)"
    if context["pg_ratio_max"] is not None and context["pg_ratio_max"] >= 0.9:
        return f"Postgres connections at {context['pg_ratio_max']:.0%} of max"
    return "no saturated resource found"


# ---------------------------------------------------------------- windows of samples


def _in(rows: list[dict], start: float, end: float) -> list[dict]:
    return [row for row in rows if start <= row["ts"] <= end]


def _mean(values) -> float | None:
    values = [value for value in values if value is not None]
    return round(sum(values) / len(values), 3) if values else None


def _cpu_seconds(container_rows: list[dict], start: float, end: float) -> dict[str, float]:
    """CPU-seconds per container: time-weighted mean of the known cpu_pct x window length.

    Unknown samples (None) are skipped, never integrated as zero; a container with no
    known sample is omitted.
    """
    by_container: dict[str, list[dict]] = defaultdict(list)
    for row in container_rows:
        if row["cpu_pct"] is not None:
            by_container[row["container"]].append(row)
    seconds = {}
    for name, rows in by_container.items():
        rows.sort(key=lambda row: row["ts"])
        weights = [row["ts"] - previous["ts"] for previous, row in itertools.pairwise(rows)]
        if sum(weights) > 0:
            weighted = sum(
                weight * row["cpu_pct"] for weight, row in zip(weights, rows[1:], strict=True)
            )
            mean_pct = weighted / sum(weights)
        else:
            mean_pct = sum(row["cpu_pct"] for row in rows) / len(rows)
        seconds[name] = round(mean_pct / 100 * (end - start), 3)
    return seconds


def _baselines(data: RunData) -> dict[tuple[str, str], float]:
    """(phase, container) → mean mem_mb during the first segment's baseline."""
    result = {}
    for segment in data.segments:
        rows = _in(data.container_timeline, segment.baseline_start, segment.load_start)
        for name in {row["container"] for row in rows}:
            mean = _mean(row["mem_mb"] for row in rows if row["container"] == name)
            if mean is not None:
                result.setdefault((segment.phase, name), mean)
    return result


# ---------------------------------------------------------------- per-window rows


def _step_and_container_rows(data, rows, by_session, baselines, crew_cap):
    steps, containers, previous_agent_p95 = [], [], {}
    phases = {phase.name: phase for phase in data.case.phases}
    for window in data.windows:
        rules = phases[window.phase].pass_rules
        window_rows = measured(rows, window)
        verdict, reasons = judge_level(rows, window, rules, data.case.abort, by_session)
        samples = _in(data.timeline, window.settle_end_ts, window.end_ts)
        container_samples = _in(data.container_timeline, window.settle_end_ts, window.end_ts)
        steady_s = max(window.end_ts - window.settle_end_ts, 1e-6)
        finished_ok = [
            row
            for row in rows
            if row["status"] == "end"
            and row["end_ts"] is not None
            and window.settle_end_ts <= row["end_ts"] <= window.end_ts
            and row["phase"] == window.phase
        ]
        cpu = _cpu_seconds(container_samples, window.settle_end_ts, window.end_ts)
        running_mean = _mean(row["running"] for row in samples) or 0
        per_container_extra = {}
        for name in cpu:
            window_mean = _mean(
                row["mem_mb"] for row in container_samples if row["container"] == name
            )
            baseline = baselines.get((window.phase, name))
            if window_mean is not None and baseline is not None:
                per_container_extra[name] = window_mean - baseline
        ok = [row for row in window_rows if row["status"] == "end"]
        failed = sum(1 for row in window_rows if is_failed(row))
        step = {
            "phase": window.phase,
            "segment": window.segment,
            "level": window.level,
            "kind": window.kind,
            "target": window.level,
            "inflight_mean": _mean(row["inflight"] for row in samples),
            "running_mean": running_mean,
            "steady_s": round(steady_s, 1),
            "sent": len(window_rows),
            "completed": len(ok),
            "failed": failed,
            "interrupted": sum(1 for row in window_rows if row["status"] == INTERRUPTED),
            "throughput_per_min": round(len(finished_ok) / steady_s * 60, 2),
            "error_rate": round(failed / max(len(window_rows), 1), 4),
            "cpu_s_per_session": round(sum(cpu.values()) / len(finished_ok), 3)
            if finished_ok
            else None,
            "mb_per_concurrent": round(sum(per_container_extra.values()) / running_mean, 2)
            if running_mean and per_container_extra
            else None,
            "gen_lag_p99_ms": percentile(
                [row["gen_lag_ms"] for row in window_rows if row["gen_lag_ms"] is not None], 0.99
            ),
            "verdict": verdict,
            "live_verdict": window.live_verdict,
            "fail_reasons": "; ".join(reasons),
            "bottleneck": "",
        }
        for name in DURATIONS:
            for key, value in stats([row[name] for row in ok]).items():
                step[f"{name}_{key}"] = value
        if verdict == "fail":
            agent_p95 = percentile(
                [row["agent_queue_s"] for row in ok if row["agent_queue_s"]], 0.95
            )
            step["bottleneck"] = bottleneck(
                {
                    "restarts": sorted(
                        {row["container"] for row in container_samples}
                        & set(_restarted(data.container_timeline, window))
                    ),
                    "failure": failure_text(rows, window, reasons, by_session),
                    "saturated_processes": [
                        text
                        for _, text in saturated_processes(
                            container_samples, data.meta.get("env", {})
                        )
                    ],
                    "host_mem_avail_min_pct": min(
                        (
                            row["host_mem_avail_pct"]
                            for row in samples
                            if row["host_mem_avail_pct"] is not None
                        ),
                        default=None,
                    ),
                    "ram_guard_pct": data.case.abort.host_min_available_ram_pct,
                    "host_cpu_mean": _mean(row["host_cpu_pct"] for row in samples),
                    "containers_at_cpu_limit": _at_cpu_limit(
                        container_samples, data.meta.get("container_limits", {})
                    ),
                    "running_mean": running_mean,
                    "queued_mean": _mean(row["queued"] for row in samples) or 0,
                    "crew_cap": crew_cap,
                    "agent_queue_p95": agent_p95,
                    "previous_agent_queue_p95": previous_agent_p95.get(window.phase),
                    "pg_ratio_max": max(
                        (
                            row["pg_connections"] / row["pg_max_connections"]
                            for row in samples
                            if row.get("pg_connections") and row.get("pg_max_connections")
                        ),
                        default=None,
                    ),
                }
            )
        previous_agent_p95[window.phase] = percentile(
            [row["agent_queue_s"] for row in ok if row["agent_queue_s"]], 0.95
        )
        steps.append(step)
        for name, cpu_s in cpu.items():
            own = [row for row in container_samples if row["container"] == name]
            containers.append(
                {
                    "phase": window.phase,
                    "segment": window.segment,
                    "level": window.level,
                    "kind": window.kind,
                    "container": name,
                    "cpu_s": cpu_s,
                    "cpu_s_per_session": round(cpu_s / len(finished_ok), 4)
                    if finished_ok
                    else None,
                    "cpu_pct_mean": _mean(row["cpu_pct"] for row in own),
                    "cpu_pct_max": max(
                        (row["cpu_pct"] for row in own if row["cpu_pct"] is not None), default=None
                    ),
                    "mem_mean_mb": _mean(row["mem_mb"] for row in own),
                    "mem_peak_mb": max(
                        (row["mem_mb"] for row in own if row["mem_mb"] is not None), default=None
                    ),
                    "restarts": _counter_delta(own, "restarts"),
                    "oom_kills": _counter_delta(own, "oom_kills"),
                }
            )
    return steps, containers


def _counter_delta(rows: list[dict], key: str) -> int:
    """Growth of a monotonic counter over the rows, ignoring failed probes (None)."""
    values = [row[key] for row in rows if row[key] is not None]
    return values[-1] - values[0] if values else 0


def _restarted(container_timeline: list[dict], window: Window) -> list[str]:
    """Containers whose known restart/OOM counter rose versus its first known value."""
    rows = _in(container_timeline, window.start_ts, window.end_ts)
    first: dict[tuple[str, str], int] = {}
    changed: set[str] = set()
    for row in sorted(rows, key=lambda item: item["ts"]):
        for key in ("restarts", "oom_kills"):
            if row[key] is None:
                continue
            start = first.setdefault((row["container"], key), row[key])
            if row[key] > start:
                changed.add(row["container"])
    return sorted(changed)


def _at_cpu_limit(container_samples: list[dict], limits: dict) -> list[str]:
    names = []
    for name, limit in limits.items():
        cpus = (limit or {}).get("cpus")
        mean = _mean(row["cpu_pct"] for row in container_samples if row["container"] == name)
        if cpus and mean is not None and mean >= 0.9 * cpus * 100:
            names.append(name)
    return names


def _container_phase_rows(data, baselines) -> list[dict]:
    rows = []
    timeline_by_ts = {row["ts"]: row for row in data.timeline}
    for phase in data.case.phases:
        segments = [segment for segment in data.segments if segment.phase == phase.name]
        if not segments:
            continue
        first, last = segments[0], segments[-1]
        load = _in(data.container_timeline, first.load_start, first.load_end)
        cooldown = _in(data.container_timeline, last.load_end, last.cooldown_end)
        for name in sorted({row["container"] for row in load}):
            own = [
                row
                for row in load
                if row["container"] == name
                and row["ts"] in timeline_by_ts
                and row["mem_mb"] is not None
                and timeline_by_ts[row["ts"]]["running"] is not None
            ]
            slope, r2 = fit_line(
                [timeline_by_ts[row["ts"]]["running"] for row in own],
                [row["mem_mb"] for row in own],
            )
            tail = [
                row["mem_mb"]
                for row in cooldown
                if row["container"] == name
                and row["mem_mb"] is not None
                and row["ts"] >= last.cooldown_end - 60
            ]
            baseline = baselines.get((phase.name, name))
            rows.append(
                {
                    "phase": phase.name,
                    "container": name,
                    "baseline_mb": baseline,
                    "mb_per_concurrent": slope,
                    "r2": r2,
                    "retained_mb_after_cooldown": round(_mean(tail) - baseline, 1)
                    if tail and baseline is not None
                    else None,
                }
            )
    return rows


def _node_rows(data, rows, by_session) -> list[dict]:
    result = []
    for window in data.windows:
        spans: dict[tuple[str, str], list[float]] = defaultdict(list)
        errors: dict[tuple[str, str], int] = defaultdict(int)
        for row in measured(rows, window):
            events = by_session.get(row["session_id"], [])
            for start, end in pair_spans(
                events, "node_start", "node_end", lambda event: event.get("node_name")
            ):
                key = (start.get("node_name") or "?", start.get("node_type") or "?")
                spans[key].append(float(end["ts"]) - float(start["ts"]))
                errors[key] += int(end.get("ok") is False)
        for (node_name, node_type), durations in sorted(spans.items()):
            summary = stats(durations)
            result.append(
                {
                    "phase": window.phase,
                    "segment": window.segment,
                    "level": window.level,
                    "kind": window.kind,
                    "node_name": node_name,
                    "node_type": node_type,
                    "count": len(durations),
                    "p50_s": summary["p50"],
                    "p95_s": summary["p95"],
                    "mean_s": summary["mean"],
                    "max_s": summary["max"],
                    "error_count": errors[(node_name, node_type)],
                }
            )
    return result


def _sample_session_ids(rows: list[dict]) -> set[int]:
    ok = sorted(
        (
            row
            for row in rows
            if row["status"] == "end" and row["e2e_s"] is not None and not row["cold"]
        ),
        key=lambda row: row["e2e_s"],
    )
    middle = len(ok) // 2
    chosen = ok[:100] + ok[max(0, middle - 50) : middle + 50] + ok[-100:]
    chosen += [row for row in rows if is_failed(row)][:150]
    chosen += [row for row in rows if row["cold"]]
    return {row["session_id"] for row in chosen if row["session_id"] is not None}


def _event_rows(by_session: dict[int, list[dict]], only: set[int] | None) -> list[dict]:
    result = []
    for session_id, session_events in by_session.items():
        if only is not None and session_id not in only:
            continue
        for event in session_events:
            extra = {
                key: value
                for key, value in event.items()
                if key not in ("session_id", "service", "checkpoint", "ts", "node_name", "bench")
            }
            result.append(
                {
                    "session_id": session_id,
                    "service": event["service"],
                    "checkpoint": event["checkpoint"],
                    "ts": event["ts"],
                    "node_name": event.get("node_name"),
                    "extra_json": json.dumps(extra, default=str),
                }
            )
    return result


def _phase_peaks(container_timeline: list[dict]) -> dict[tuple[str, str], tuple[float, int]]:
    """(phase, container) → (highest sampled mem_mb, level of that sample) over the whole
    phase: every segment, the failing level, drain and cooldown. Level 0 means the sample was
    taken outside a level (cold session, baseline, drain or cooldown)."""
    peaks: dict[tuple[str, str], tuple[float, int]] = {}
    for row in container_timeline:
        key = (row["phase"], row["container"])
        if row["mem_mb"] is not None and (key not in peaks or row["mem_mb"] > peaks[key][0]):
            peaks[key] = (row["mem_mb"], row["level"])
    return peaks


def _timeline_rows(data: RunData, rows: list[dict], origin: float | None) -> list[dict]:
    """The samples with run_rel_s and, over the ROLLING_S before each sample, the sessions that
    ended `end` (throughput_per_min) and the p95 of their e2e (e2e_p95_60s)."""
    ended = sorted(
        (row["end_ts"], row["e2e_s"])
        for row in rows
        if row["status"] == "end" and row["end_ts"] is not None and row["e2e_s"] is not None
    )
    ends = [end_ts for end_ts, _ in ended]
    result = []
    for sample in data.timeline:
        recent = [
            e2e
            for _, e2e in ended[
                bisect_right(ends, sample["ts"] - ROLLING_S) : bisect_right(ends, sample["ts"])
            ]
        ]
        result.append(
            {
                **sample,
                "run_rel_s": round(sample["ts"] - origin, 3),
                "throughput_per_min": round(len(recent) * 60 / ROLLING_S, 2),
                "e2e_p95_60s": percentile(recent, 0.95),
            }
        )
    return result


def _stage_transitions(row: dict, events: list[dict]) -> list[tuple[float, str]]:
    """(from ts, stage) of one in-flight session, from sent_ts until its end: the stage of the
    last checkpoint it reached (STAGES), starting as `waiting for crew`.

    Crew and agent log sandbox_dispatched after publishing the execution, so at low load the
    sandbox's exec_start (or exec_end) can come first; that late sandbox_dispatched is skipped,
    or the session would wait for a sandbox that is already running its code."""
    sent, end = row["sent_ts"], row["end_ts"]
    transitions = [(sent, STAGES[0])]
    in_sandbox: set = set()  # execution ids the sandbox has already logged
    for event in sorted(events, key=lambda item: float(item["ts"])):
        ts = float(event["ts"])
        if end is not None and ts >= end:
            break
        if event["service"] == "sandbox":
            in_sandbox.add(event.get("execution_id"))
        elif (
            event["checkpoint"] == "sandbox_dispatched" and event.get("execution_id") in in_sandbox
        ):
            continue
        stage = STAGE_AFTER.get((event["service"], event["checkpoint"])) or STAGE_BY_SERVICE.get(
            event["service"], "crew"
        )
        if stage != transitions[-1][1]:
            # another container's clock may put a checkpoint a hair before the send
            transitions.append((max(ts, sent), stage))
    return transitions


def _inflight_stage_rows(
    data: RunData, rows: list[dict], by_session: dict[int, list[dict]], origin: float | None
) -> list[dict]:
    """At every sample: sessions in flight (sent, not ended) per stage.

    Each stage change is added to a per-stage difference array over the sample indexes (the
    first sample at or after it), then summed up: memory is stages x samples, time is the
    number of changes. A session with no known end is in flight until its segment's end, never
    into the next segment; an end that another clock puts before the send counts as the send.
    Stages with no session at a sample are left out (count 0)."""
    samples = sorted(data.timeline, key=lambda item: item["ts"])
    times = [sample["ts"] for sample in samples]
    segment_end = {
        (segment.phase, segment.segment): segment.cooldown_end for segment in data.segments
    }
    for sample in samples:  # runs without segment bounds: their last sample
        segment_end.setdefault((sample["phase"], sample["segment"]), sample["ts"])
    differences = {stage: [0] * (len(samples) + 1) for stage in STAGES}
    for row in rows:
        if row["sent_ts"] is None:
            continue
        transitions = _stage_transitions(row, by_session.get(row["session_id"], []))
        end = row["end_ts"]
        if end is None:
            end = segment_end.get((row["phase"], row["segment"]), math.inf)
        stops = [ts for ts, _ in transitions[1:]] + [max(end, row["sent_ts"])]
        for (start, stage), stop in zip(transitions, stops, strict=True):
            differences[stage][bisect_left(times, start)] += 1
            differences[stage][bisect_left(times, stop)] -= 1
    result = []
    counts = dict.fromkeys(STAGES, 0)
    for index, sample in enumerate(samples):
        for stage in STAGES:
            counts[stage] += differences[stage][index]
        result += [
            {
                "ts": sample["ts"],
                "run_rel_s": round(sample["ts"] - origin, 3),
                "phase": sample["phase"],
                "segment": sample["segment"],
                "stage": stage,
                "count": count,
            }
            for stage, count in counts.items()
            if count > 0
        ]
    return result


def _restart_moments(container_timeline: list[dict]) -> list[tuple[str, str, float]]:
    """(phase, container, ts) of the first sample in each segment where a container's known
    restart or OOM counter is above its first known value in that segment (as _restarted)."""
    first: dict[tuple, int] = {}
    restarted: set[tuple] = set()
    moments = []
    for row in sorted(container_timeline, key=lambda item: item["ts"]):
        key = (row["phase"], row["segment"], row["container"])
        for counter in ("restarts", "oom_kills"):
            if key in restarted or row[counter] is None:
                continue
            if row[counter] > first.setdefault((*key, counter), row[counter]):
                restarted.add(key)
                moments.append((row["phase"], row["container"], row["ts"]))
    return moments


def _findings(
    data, rows, by_session, steps, container_phase_rows, origin, llm_contention=None
) -> list[dict]:
    """findings.csv: what to look at first, by simple rules with the thresholds above. A
    finding with a moment (`ts`) is drawn on the viewer's timeline; `tab` is where to read on."""
    findings = []

    def add(phase, severity, kind, message, tab, ts=None, container=None):
        findings.append(
            {
                "phase": phase,
                "severity": severity,
                "kind": kind,
                "message": message,
                "ts": ts,
                "run_rel_s": round(ts - origin, 1)
                if ts is not None and origin is not None
                else None,
                "tab": tab,
                "container": container,
            }
        )

    windows = {(window.phase, window.segment, window.level): window for window in data.windows}
    llm_contention = llm_contention or {}

    def level_name(phase, segment, level):
        window = windows.get((phase, segment, level))
        if window:
            return f"{window.kind} level {level}"
        return "cold session" if level == 0 else f"level {level}"

    timed_out: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        if row["status"] == "timeout":
            timed_out[(row["phase"], row["segment"], row["level"])].append(row)
    for (phase, segment, level), level_timeouts in sorted(timed_out.items()):
        add(
            phase,
            CRITICAL,
            "timeouts",
            f"{level_name(phase, segment, level)}: {timed_out_text(level_timeouts, by_session)}",
            "Timeline",
            min(
                (row["end_ts"] for row in level_timeouts if row["end_ts"] is not None), default=None
            ),
        )
    for window in data.windows:
        if window.abort_reason:
            message = f"{window.kind} level {window.level} aborted: {window.abort_reason}"
            add(window.phase, CRITICAL, "abort", message, "Timeline", window.end_ts)
    for phase, container, ts in _restart_moments(data.container_timeline):
        message = f"{container} restarted or was OOM-killed"
        add(phase, CRITICAL, "container_restart", message, "Containers", ts, container)
    limits = data.meta.get("container_limits", {})
    at_limit: set[tuple[str, str]] = set()  # once per container and phase: its first level
    for window in data.windows:
        samples = _in(data.container_timeline, window.settle_end_ts, window.end_ts)
        for name in _at_cpu_limit(samples, limits):
            if (window.phase, name) in at_limit:
                continue
            at_limit.add((window.phase, name))
            message = (
                f"{name} CPU at its limit ({limits[name]['cpus']:g} CPUs) at level {window.level}"
            )
            add(
                window.phase,
                WARNING,
                "cpu_limit",
                message,
                "Containers",
                window.settle_end_ts,
                name,
            )
    steps_by_level = {(step["phase"], step["segment"], step["level"]): step for step in steps}
    started_by_level: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        started_by_level[(row["phase"], row["segment"], row["level"])].append(row)
    # a level holds a few dozen sessions, so one stray failure would always be over 1 % of it:
    # a failure that did not fail its level is graded by the phase's share instead
    phase_started, phase_failed = Counter(), Counter()
    for row in rows:
        phase_started[row["phase"]] += 1
        phase_failed[row["phase"]] += row["status"] == "http_error"
    for key, started in sorted(started_by_level.items()):
        failed = [row for row in started if row["status"] == "http_error"]
        if not failed:
            continue
        window, step = windows.get(key), steps_by_level.get(key)
        reasons = step["fail_reasons"].split("; ") if step and step["fail_reasons"] else []
        caused = bool(
            window and step and step["verdict"] == "fail" and start_failures(rows, window, reasons)
        )
        kinds = ", ".join(
            f"{kind}: {count}" for kind, count in Counter(map(_error_kind, failed)).most_common()
        )
        api_p95 = percentile([row["api_ms"] for row in started if row["api_ms"] is not None], 0.95)
        message = (
            f"{level_name(*key)}: {len(failed)} of {len(started)} start requests failed ({kinds}"
        )
        message += f"; API p95 {api_p95 / 1000:.1f} s)" if api_p95 is not None else ")"
        if caused:
            severity = CRITICAL  # they failed the level
        elif phase_failed[key[0]] > HTTP_ERROR_WARN_SHARE * phase_started[key[0]]:
            severity = WARNING
        else:
            severity = INFO
        first = min((row["sent_ts"] for row in failed if row["sent_ts"] is not None), default=None)
        add(key[0], severity, "http_errors", message, "Timeline", first)
    env = data.meta.get("env", {})
    saturated_seen: set[tuple[str, str]] = set()  # once per container and phase: its first level
    for window in data.windows:
        samples = _in(data.container_timeline, window.settle_end_ts, window.end_ts)
        for name, saturation in saturated_processes(samples, env):
            if (window.phase, name) in saturated_seen:
                continue
            saturated_seen.add((window.phase, name))
            message = f"{saturation} at {window.kind} level {window.level}"
            add(
                window.phase,
                WARNING,
                "single_process_saturated",
                message,
                "Containers",
                window.settle_end_ts,
                name,
            )
    for phase_name, (message, ts) in llm_contention.items():
        add(phase_name, WARNING, "llm_slowed_by_host", message, "Timeline", ts)
    for phase in data.case.phases:
        own_steps = [step for step in steps if step["phase"] == phase.name]
        for step in own_steps:
            if step["verdict"] == "invalid":
                window = windows.get((step["phase"], step["segment"], step["level"]))
                message = f"{step['kind']} level {step['level']} invalid: {step['fail_reasons']}"
                add(
                    phase.name,
                    WARNING,
                    "invalid_level",
                    message,
                    "Curves",
                    window and window.start_ts,
                )
        # passing levels only: a failed or invalid level's throughput says nothing about latency
        ladder = sorted(
            (step for step in own_steps if step["kind"] == "ladder" and step["verdict"] == "pass"),
            key=lambda step: step["level"],
        )
        for previous, current in itertools.pairwise(ladder):
            if (
                previous["throughput_per_min"]
                and current["level"] > previous["level"]
                and current["throughput_per_min"]
                < previous["throughput_per_min"] * (1 + PLATEAU_GROWTH)
            ):
                message = (
                    f"throughput stopped growing at level {previous['level']} "
                    f"(~{previous['throughput_per_min']:.0f}/min); passing level {current['level']} "
                    "only added latency"
                )
                add(phase.name, WARNING, "throughput_plateau", message, "Curves")
                break
        dominant = _dominant_stage(rows, own_steps, windows)
        if dominant:
            key, share, level = dominant
            message = f"{BREAKDOWN_STAGES[key]} = {share:.0%} of session time at L{level}"
            # most of the time in the LLM provider is what an agent flow is expected to show
            add(
                phase.name,
                INFO if key == "llm_s" else WARNING,
                "dominant_stage",
                message,
                "Time breakdown",
            )
    for row in container_phase_rows:
        retained, baseline = row["retained_mb_after_cooldown"], row["baseline_mb"]
        if (
            retained is not None
            and baseline is not None
            and retained > max(RETAINED_MIN_MB, RETAINED_SHARE * baseline)
        ):
            message = f"{row['container']} kept {retained:.0f} MB after cooldown (baseline {baseline:.0f} MB)"
            add(
                row["phase"],
                WARNING,
                "memory_retained",
                message,
                "Containers",
                container=row["container"],
            )
    return sorted(
        findings,
        key=lambda finding: (
            SEVERITY_ORDER[finding["severity"]],
            finding["ts"] is None,
            finding["ts"] or 0,
        ),
    )


def _dominant_stage(rows, steps, windows) -> tuple[str, float, int] | None:
    """(stage column, share of the mean e2e, level) of the largest stage at the headline level
    (highest pass, else the first level, as the viewer's headline), when above
    DOMINANT_STAGE_SHARE; None otherwise."""
    passes = [step for step in steps if step["verdict"] == "pass"]
    headline = max(passes, key=lambda step: step["level"]) if passes else next(iter(steps), None)
    window = headline and windows.get((headline["phase"], headline["segment"], headline["level"]))
    if not window:
        return None
    completed = [row for row in measured(rows, window) if row["status"] == "end"]
    e2e = _mean(row["e2e_s"] for row in completed)
    if not e2e:
        return None
    means = {key: _mean(row[key] for row in completed) or 0 for key in BREAKDOWN_STAGES}
    key = max(means, key=means.get)
    # LLM calls can run in parallel, so their summed time can exceed the session's
    share = min(1.0, means[key] / e2e)
    return (key, share, headline["level"]) if share > DOMINANT_STAGE_SHARE else None


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _llm_contention(data: RunData, rows: list[dict], by_session) -> dict[str, tuple[str, float]]:
    """phase → (message, moment) when LLM calls got slow only while the host CPU was saturated.

    A level's LLM calls are slow when their p95 exceeds SLOW_LLM_FACTOR x the reference (the
    smoke step's p95 for the phase, else the phase's first level with calls). When every slow
    level had a mean host CPU of at least HOST_CPU_SATURATED_PCT, the calls most likely waited
    for CPU on this host (the agent parses and streams on a starved core), not for the provider.
    """
    smoke = (data.meta.get("smoke") or {}).get("llm_p95_s", {})
    result = {}
    for phase in data.case.phases:
        levels = []
        for window in data.windows:
            if window.phase != phase.name:
                continue
            calls = [
                float(end["ts"]) - float(start["ts"])
                for row in measured(rows, window)
                for start, end in pair_spans(
                    by_session.get(row["session_id"], []),
                    "llm_start",
                    "llm_end",
                    lambda event: event.get("correlation_id"),
                )
            ]
            if calls:
                levels.append((window, calls))
        if not levels:
            continue
        reference = smoke.get(phase.name) or percentile(levels[0][1], 0.95)
        slow = [
            (window, calls)
            for window, calls in levels
            if percentile(calls, 0.95) > SLOW_LLM_FACTOR * reference
        ]
        hosts = [
            _mean(
                row["host_cpu_pct"]
                for row in _in(data.timeline, window.settle_end_ts, window.end_ts)
            )
            for window, _ in slow
        ]
        if not slow or any(host is None or host < HOST_CPU_SATURATED_PCT for host in hosts):
            continue
        first, last = percentile(levels[0][1], 0.5), percentile(slow[-1][1], 0.5)
        message = (
            f"LLM call time rose {first:.2f} s → {last:.1f} s while host CPU was "
            f"{sum(hosts) / len(hosts):.0f} %: likely CPU contention, not the provider"
        )
        result[phase.name] = (message, slow[0][0].start_ts)
    return result


def _phase_summary(
    data, phase, steps, rows, by_session, container_phase_rows, llm_contention=None
) -> dict:
    own = [step for step in steps if step["phase"] == phase.name]
    passes = [step for step in own if step["verdict"] == "pass"]
    fails = [step for step in own if step["verdict"] == "fail"]
    best = max(passes, key=lambda step: step["level"]) if passes else None
    slopes = [
        row["mb_per_concurrent"]
        for row in container_phase_rows
        if row["phase"] == phase.name
        and row["r2"] is not None
        and row["r2"] >= MIN_FIT_R2
        and row["mb_per_concurrent"] is not None
    ]
    mb_total = sum(slopes) if slopes else None
    verdict = {
        "max_pass_concurrency": best["level"] if best else None,
        "first_fail_level": min((step["level"] for step in fails), default=None),
        "throughput_per_min_at_max": best and best["throughput_per_min"],
        "p50_e2e_s_at_max": best and best["e2e_s_p50"],
        "p95_e2e_s_at_max": best and best["e2e_s_p95"],
        "p95_platform_overhead_s_at_max": best and best["platform_overhead_s_p95"],
        "cpu_s_per_session_at_max": best and best["cpu_s_per_session"],
        "mb_per_concurrent_total": round(mb_total, 2) if mb_total is not None else None,
        "bottleneck": next(
            (step["bottleneck"] for step in sorted(fails, key=lambda step: step["level"])), None
        ),
        "fail_reasons": next(
            (step["fail_reasons"] for step in sorted(fails, key=lambda step: step["level"])), None
        ),
    }
    if data.case.kind == "dev" and own:
        verdict.update(
            max_pass_concurrency=None,
            first_fail_level=None,
            level=own[0]["level"],
            throughput_per_min=own[0]["throughput_per_min"],
            p50_e2e_s=own[0]["e2e_s_p50"],
            p95_e2e_s=own[0]["e2e_s_p95"],
            cpu_s_per_session=own[0]["cpu_s_per_session"],
        )
    calls, errors = [], defaultdict(int)
    tokens = cost = 0
    for row in rows:
        if row["phase"] != phase.name:
            continue
        for start, end in pair_spans(
            by_session.get(row["session_id"], []),
            "llm_start",
            "llm_end",
            lambda event: event.get("correlation_id"),
        ):
            calls.append(float(end["ts"]) - float(start["ts"]))
            if end.get("ok") is False:
                errors[end.get("error_type") or "unknown"] += 1
        tokens += row["tokens"] or 0
        cost += row["cost_usd"] or 0
    smoke_p95 = (data.meta.get("smoke") or {}).get("llm_p95_s", {}).get(phase.name)
    health = {
        "llm_calls": len(calls),
        "llm_p50_s": percentile(calls, 0.5),
        "llm_p95_s": percentile(calls, 0.95),
        "errors": dict(errors),
        "tokens": tokens,
        "cost_usd": round(cost, 4),
        # LLM calls slowed by a saturated host are not the provider's (see _llm_contention)
        "slow_provider": bool(
            smoke_p95
            and calls
            and percentile(calls, 0.95) > SLOW_LLM_FACTOR * smoke_p95
            and phase.name not in (llm_contention or {})
        ),
    }
    estimate = None
    host = data.meta.get("host", {})
    if best and best["cpu_s_per_session"] and best["e2e_s_p50"]:
        baseline_avail = _mean(
            row["host_mem_avail_mb"]
            for segment in data.segments
            if segment.phase == phase.name
            for row in _in(data.timeline, segment.baseline_start, segment.load_start)
        )
        bounds = {}
        if host.get("vcpu"):
            bounds["cpu"] = round(host["vcpu"] * best["e2e_s_p50"] / best["cpu_s_per_session"])
        if baseline_avail and mb_total and mb_total > 0:
            bounds["ram"] = round(baseline_avail / mb_total)
        for key in ("CREW_MAX_CONCURRENT_SESSIONS", "AGENT_MAX_CONCURRENT_RUNS"):
            value = data.meta.get("env", {}).get(key)
            if value and value.isdigit() and (key.startswith("CREW") or health["llm_calls"]):
                bounds[key] = int(value)
        if bounds:
            estimate = {
                "bounds": bounds,
                "limit": min(bounds, key=bounds.get),
                "concurrency": min(bounds.values()),
            }
    cold = [row for row in rows if row["phase"] == phase.name and row["cold"]]
    graph = data.meta.get("graphs", {}).get(phase.name, {})
    return {
        "name": phase.name,
        **graph,
        "variables_hash": hashlib.sha256(
            json.dumps(phase.variables or {}, sort_keys=True).encode()
        ).hexdigest()[:16],
        "verdict": verdict,
        "provider_health": health,
        "capacity_estimate": estimate,
        "cold": {key: cold[0][key] for key in ("e2e_s", "queue_wait_s", "run_s", "status")}
        if cold
        else None,
    }


def analyze(data: RunData, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    by_session, unattributed = index_events(data.events)
    rows = [session_row(record, by_session.get(record.session_id, [])) for record in data.records]
    baselines = _baselines(data)
    crew_cap_text = data.meta.get("env", {}).get("CREW_MAX_CONCURRENT_SESSIONS") or ""
    steps, containers = _step_and_container_rows(
        data, rows, by_session, baselines, int(crew_cap_text) if crew_cap_text.isdigit() else None
    )
    peaks = _phase_peaks(data.container_timeline)
    for row in containers:
        row["phase_peak_mb"], row["phase_peak_level"] = peaks.get(
            (row["phase"], row["container"]), (None, None)
        )
    container_phase_rows = _container_phase_rows(data, baselines)
    # every timeline x is seconds since the run's first sample, continuous across segments
    origin = min((sample["ts"] for sample in data.timeline), default=None)
    llm_contention = _llm_contention(data, rows, by_session)
    meta = {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        **data.meta,
        "analyzed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "events_unattributed": unattributed,
        "phases": [
            _phase_summary(
                data, phase, steps, rows, by_session, container_phase_rows, llm_contention
            )
            for phase in data.case.phases
        ],
    }
    revised = [
        f"{step['phase']}:{step['level']}"
        for step in steps
        if step["live_verdict"] and step["live_verdict"] != step["verdict"]
    ]
    if revised:
        meta["labels"] = [*(meta.get("labels") or []), "verdict-revised:" + ",".join(revised)]
    meta.pop("graphs", None)
    _write_csv(out_dir / "sessions.csv.gz", SESSION_COLUMNS, rows)
    _write_csv(out_dir / "steps.csv", STEP_COLUMNS, steps)
    _write_csv(out_dir / "containers.csv", CONTAINER_COLUMNS, containers)
    _write_csv(out_dir / "container_phases.csv", CONTAINER_PHASE_COLUMNS, container_phase_rows)
    _write_csv(out_dir / "nodes.csv", NODE_COLUMNS, _node_rows(data, rows, by_session))
    _write_csv(out_dir / "timeline.csv", TIMELINE_COLUMNS, _timeline_rows(data, rows, origin))
    _write_csv(
        out_dir / "container_timeline.csv", CONTAINER_TIMELINE_COLUMNS, data.container_timeline
    )
    _write_csv(
        out_dir / "inflight_stages.csv",
        INFLIGHT_STAGE_COLUMNS,
        _inflight_stage_rows(data, rows, by_session, origin),
    )
    _write_csv(
        out_dir / "findings.csv",
        FINDING_COLUMNS,
        _findings(data, rows, by_session, steps, container_phase_rows, origin, llm_contention),
    )
    _write_csv(
        out_dir / "events_sample.csv",
        EVENT_COLUMNS,
        _event_rows(by_session, _sample_session_ids(rows)),
    )
    _write_csv(out_dir / "events_full.csv.gz", EVENT_COLUMNS, _event_rows(by_session, None))
    (out_dir / "case.toml").write_text(redacted_case_text(data.case.source_text), encoding="utf-8")
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    return meta
