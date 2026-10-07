"""Keeps exactly N sessions in flight. Completion comes from crew's BENCH `session_end` lines
(fed in through `on_event`), or — for branches without them — from `external_in_flight`."""

from __future__ import annotations

import concurrent.futures
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class SessionRecord:
    phase: str
    level: int
    kind: str
    segment: int
    intended_ts: float
    sent_ts: float | None = None
    api_ms: float | None = None
    http_status: int | None = None
    session_id: int | None = None
    error: str | None = None
    done_ts: float | None = None
    end_status: str | None = None

    @property
    def done(self) -> bool:
        return self.done_ts is not None

    @property
    def ok(self) -> bool:
        return self.end_status == "end"


class Controller:
    def __init__(
        self,
        start_session: Callable[[], tuple[int, int]],
        stop_session: Callable[[int], None],
        senders: int = 64,
        clock: Callable[[], float] = time.time,
    ):
        self._start_session, self._stop_session, self._clock = start_session, stop_session, clock
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=senders)
        self._lock = threading.Lock()
        self.records: list[SessionRecord] = []
        self._in_flight: dict[int, SessionRecord] = {}
        self._early_done: dict[int, tuple[float, str]] = {}
        self._running: set[int] = set()
        self._pending_http = 0
        self.external_in_flight: Callable[[], int] | None = None
        self._context = ("", 0, "", 0)

    def set_context(self, phase: str, level: int, kind: str, segment: int) -> None:
        self._context = (phase, level, kind, segment)

    # ---- completion events from the crew log follower
    def on_event(self, event: dict) -> None:
        session_id = event.get("session_id")
        if not isinstance(session_id, int):
            return
        with self._lock:
            if event.get("checkpoint") == "slot_acquired" and session_id in self._in_flight:
                self._running.add(session_id)
            elif event.get("checkpoint") == "session_end":
                self._finish(
                    session_id,
                    float(event.get("ts") or self._clock()),
                    event.get("status") or "end",
                )

    def _finish(self, session_id: int, ts: float, status: str) -> None:  # caller holds the lock
        self._running.discard(session_id)
        record = self._in_flight.pop(session_id, None)
        if record is None:
            self._early_done[session_id] = (
                ts,
                status,
            )  # session_end arrived before the HTTP answer
        elif record.done_ts is None:
            record.done_ts, record.end_status = ts, status

    # ---- sending
    def _send(self, record: SessionRecord) -> None:
        record.sent_ts = self._clock()
        started = time.monotonic()
        try:
            status, session_id = self._start_session()
        except Exception as error:
            with self._lock:
                record.api_ms = round((time.monotonic() - started) * 1000, 1)
                record.http_status = getattr(error, "status", None)
                record.error = str(error)[:300]
                record.done_ts, record.end_status = self._clock(), "http_error"
                self._pending_http -= 1
            return
        with self._lock:
            record.api_ms = round((time.monotonic() - started) * 1000, 1)
            record.http_status, record.session_id = status, session_id
            self._pending_http -= 1
            early = self._early_done.pop(session_id, None)
            if early:
                record.done_ts, record.end_status = early
            else:
                self._in_flight[session_id] = record

    def _submit(self, count: int, now: float) -> None:
        phase, level, kind, segment = self._context
        for _ in range(count):
            record = SessionRecord(phase, level, kind, segment, intended_ts=now)
            with self._lock:
                self.records.append(record)
                self._pending_http += 1
            self._pool.submit(self._send, record)

    def _expire(self, now: float, timeout_s: float) -> None:
        if self.external_in_flight is not None:
            return  # fallback control knows counts, not ids: nothing to expire or stop
        with self._lock:
            expired = [
                record for record in self._in_flight.values() if now - record.sent_ts > timeout_s
            ]
            for record in expired:
                self._in_flight.pop(record.session_id)
                self._running.discard(record.session_id)
                record.done_ts, record.end_status = now, "timeout"
        for record in expired:
            self._pool.submit(self._safe_stop, record.session_id)

    def _safe_stop(self, session_id: int) -> None:
        try:
            self._stop_session(session_id)
        except Exception as error:
            print(f"[load] could not stop session {session_id}: {error}")

    # ---- counts
    def in_flight_count(self) -> int:
        with self._lock:
            local, pending = len(self._in_flight) + self._pending_http, self._pending_http
        if self.external_in_flight is not None:
            return self.external_in_flight() + pending
        return local

    def running_count(self) -> int:
        with self._lock:
            return len(self._running)

    def status(self) -> dict:
        with self._lock:
            done = [record for record in self.records if record.done_ts is not None]
            return {
                "inflight": len(self._in_flight) + self._pending_http,
                "running": len(self._running),
                "completed": sum(record.ok for record in done),
                "failed": sum(not record.ok for record in done),
            }

    def recent_error_rate(
        self, now: float, window_s: float = 30, min_done: int = 20
    ) -> float | None:
        with self._lock:
            done = [
                record
                for record in self.records
                if record.done_ts is not None
                and now - window_s <= record.done_ts <= now
                and record.kind != "cold"
            ]
        if len(done) < min_done:
            return None
        return sum(not record.ok for record in done) / len(done)

    # ---- the loop
    def hold(
        self,
        target: int,
        duration_s: float,
        timeout_s: float,
        abort_check: Callable[[], str | None],
        max_starts: int | None = None,
        tick_s: float = 0.25,
    ) -> str | None:
        """Keep `target` sessions in flight for `duration_s` (or until `max_starts` sessions have
        started and finished). Returns the abort reason, or None."""
        deadline = self._clock() + duration_s
        started = 0
        while self._clock() < deadline:
            now = self._clock()
            self._expire(now, timeout_s)
            reason = abort_check()
            if reason:
                return reason
            in_flight = self.in_flight_count()
            if max_starts is not None and started >= max_starts and in_flight == 0:
                return None
            deficit = target - in_flight
            if max_starts is not None:
                deficit = min(deficit, max_starts - started)
            if deficit > 0:
                self._submit(deficit, now)
                started += deficit
            time.sleep(tick_s)
        return None

    def drain(self, timeout_s: float) -> int:
        """Wait for in-flight sessions; stop the ones still running after `timeout_s`."""
        deadline = time.monotonic() + timeout_s
        while self.in_flight_count() > 0 and time.monotonic() < deadline:
            time.sleep(0.25)
        with self._lock:
            leftover = list(self._in_flight.values())
        self._expire(self._clock(), timeout_s=-1)
        return len(leftover)

    def close(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=True)
