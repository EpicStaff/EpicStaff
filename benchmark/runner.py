"""Run lifecycle: pre-flight → build + env → resolve graphs → smoke → phases → analyze."""

from __future__ import annotations

import contextlib
import os
import re
import shlex
import time
import traceback
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

import analyze
import stack
from api import Api, ApiError, graph_hash
from config import (
    Case,
    DevSettings,
    Phase,
    Variant,
    allowlisted,
    bisect_next,
    ladder_levels,
)
from load import FINISH_KIND, INTERRUPTED, RUNNER_STATUSES, Controller
from sample import Sampler

RESULTS_DIR = Path(__file__).resolve().parent / "results"
EXPECTED_CHECKPOINTS = {
    "django_app": {"request_received"},
    "crew": {"received", "slot_acquired", "session_end"},
}
LOG_LEVEL_VARIABLES = {
    "django_app": "DJANGO_LOG_LEVEL",
    "crew": "CREW_LOG_LEVEL",
    "agent": "AGENT_LOG_LEVEL",
    "sandbox": "SANDBOX_LOG_LEVEL",
}
API_ERROR_PERSIST_S = 10  # a failing sessions API this long makes the level fail
BENCH_LEVELS = ("BENCH", "DEBUG", "TRACE")
CAP_VARIABLES = ("CREW_MAX_CONCURRENT_SESSIONS", "AGENT_MAX_CONCURRENT_RUNS")
FINISH_MARGIN_S = 5  # past a level's finish cap: a few controller ticks for the timeout rule
FALLBACK_REFRESH_S = 5  # how often fallback mode asks the sessions API whether sessions ended


@dataclass
class Options:
    api_base: str
    api_key: str
    org_id: str
    note: str = ""
    build: bool = True
    smoke: bool = True
    restart: bool = True
    results_dir: Path = RESULTS_DIR
    repo: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)


def evaluate_host(facts: dict) -> list[tuple[str, str]]:
    findings = []
    if not facts["docker_ok"]:
        findings.append(("error", "docker is not reachable"))
    if facts["backup_exists"]:
        findings.append(
            (
                "error",
                "src/.env.bench-backup exists: a previous run did not restore .env (move it back first)",
            )
        )
    if facts["load1"] is not None and facts["load1"] > 0.5 * facts["vcpu"]:
        findings.append(
            (
                "error",
                f"host load {facts['load1']:.1f} > half of {facts['vcpu']} vCPU: something else is running",
            )
        )
    if facts["mem_avail_pct"] is not None and facts["mem_avail_pct"] < 20:
        findings.append(("error", f"only {facts['mem_avail_pct']:.0f}% RAM available"))
    return findings


def evaluate_stack(facts: dict, case: Case) -> list[tuple[str, str]]:
    findings = (
        [("error", f"unhealthy containers: {facts['unhealthy']}")] if facts["unhealthy"] else []
    )
    findings += [
        ("error", f"phase {phase}: graph not readable ({error})")
        for phase, error in facts["graph_errors"].items()
    ]
    findings += [
        ("error", f"phase {phase}: {count} sessions still pending/run — wait or stop them")
        for phase, count in facts["leftover"].items()
        if count
    ]
    findings += [
        ("error", f"{name} log driver '{driver}' cannot be followed (need json-file or local)")
        for name, driver in facts["log_drivers"].items()
        if driver not in ("json-file", "local")
    ]
    findings += [
        ("warn", f"BENCH not active on {name}: its checkpoints are missing from this run")
        for name, active in facts["bench_active"].items()
        if not active
    ]
    if case.kind == "capacity":
        for key, value in facts["caps"].items():
            if value is not None and value < case.ladder.max:
                findings.append(
                    (
                        "warn",
                        f"{key}={value} is below ladder.max={case.ladder.max}: you will measure the cap",
                    )
                )
        if any(not limit for limit in facts["memory_limits"].values()):
            findings.append(
                (
                    "warn",
                    "no container memory limit: a break can take the whole host down (host-RAM guard only)",
                )
            )
    return findings


def plan_text(case: Case, variants: list[Variant]) -> str:
    ladder = case.ladder
    levels = ladder_levels(ladder)
    lines = [f"case {case.name} ({case.kind}), hash {case.case_hash}"]
    for variant in variants:
        lines.append(
            f"variant {variant.name}: ref={variant.ref or 'current checkout'} env={allowlisted({**case.env, **variant.env})}"
        )
    if case.kind == "dev":
        lines.append(f"dev: {case.dev.sessions} sessions, {case.dev.concurrency} in flight")
        return "\n".join(lines)
    # worst case a level also waits a full session_timeout_s for its measured sessions to end
    per_level = ladder.settle_s + ladder.hold_s + ladder.session_timeout_s
    drain = ladder.session_timeout_s + 95
    segment = 60 + ladder.baseline_s + ladder.cooldown_s + drain
    smoke = len(case.phases) * (segment + 60)
    worst = smoke + len(case.phases) * (
        segment + len(levels) * per_level + ladder.bisect_steps * (segment + per_level)
    )
    for phase in case.phases:
        lines.append(
            f"{phase.name}: {' → '.join(map(str, levels))} (+ up to {ladder.bisect_steps} bisect probes)"
        )
    lines.append(
        f"worst case per variant: {worst / 60:.0f} min, {len(variants) * worst / 60:.0f} min total"
    )
    return "\n".join(lines)


def run_dir_name(
    created: str, host: str, ref: str, sha: str, case_name: str, variant_name: str
) -> str:
    def slug(text: str) -> str:
        return re.sub(r"[^A-Za-z0-9.-]+", "-", text).strip("-")

    return f"{created}_{slug(host)}_{slug(ref)}_{sha[:7]}_{slug(case_name)}-{slug(variant_name)}"


class PhaseRunner:
    """Drives one phase: segments (ladder, bisect probes), followers, sampler, controller."""

    def __init__(
        self,
        case: Case,
        phase: Phase,
        api: Api,
        compose: stack.Compose,
        options: Options,
        env: dict[str, str],
        settle_s: float,
    ):
        self.case, self.phase, self.api, self.compose, self.options = (
            case,
            phase,
            api,
            compose,
            options,
        )
        self.env, self.settle_s = env, settle_s
        self.windows: list[analyze.Window] = []
        self.segments: list[analyze.Segment] = []
        self.events: list[dict] = []
        self.timeline: list[dict] = []
        self.container_timeline: list[dict] = []
        self.records = []
        self.fallback = False
        self.clock = time.time
        self.api_error_persist_s = API_ERROR_PERSIST_S
        self._api_error: tuple[float, str] | None = None
        self._last_in_flight = 0

    def run_capacity(self) -> None:
        levels = ladder_levels(self.case.ladder)
        last_pass, first_fail = None, None
        for level, verdict in self._segment("ladder", levels):
            if verdict == "pass":
                last_pass = level
            else:
                first_fail = level if verdict == "fail" else None
                break
        for _ in range(self.case.ladder.bisect_steps):
            probe = bisect_next(last_pass, first_fail) if first_fail else None
            if probe is None:
                return
            ((_, verdict),) = self._segment("bisect", [probe])
            if verdict == "pass":
                last_pass = probe
            elif verdict == "fail":
                first_fail = probe
            else:
                return

    def run_dev(self, sessions: int, concurrency: int) -> None:
        self._segment("dev", [concurrency], max_starts=sessions)

    def _segment(
        self, kind: str, levels: list[int], max_starts: int | None = None
    ) -> list[tuple[int, str]]:
        ladder, segment_no = self.case.ladder, len(self.segments) + 1
        if self.options.restart:
            self.compose.restart()
        containers = self.compose.containers()
        since = time.time()
        controller = Controller(
            lambda: self.api.start_session(self.phase.graph_id, self.phase.variables),
            self.api.stop_session,
        )
        followers: list[stack.LogFollower] = []
        sampler: Sampler | None = None
        results: list[tuple[int, str]] = []
        baseline_start = load_start = None
        completed = False
        try:
            for name in stack.INSTRUMENTED:
                if name in containers:
                    followers.append(
                        stack.LogFollower(
                            containers[name]["Name"],
                            since,
                            controller.on_event if name == "crew" else None,
                            service=name,
                        )
                    )
            inspected = stack.inspect([row["Name"] for row in containers.values()])
            sampler = Sampler(
                {
                    row["Name"]: inspected.get(row["Name"], {}).get("Id") or row["ID"]
                    for row in containers.values()
                },
                controller.status,
                self.env.get("DB_USER"),
                self.env.get("REDIS_USER"),
                self.env.get("REDIS_PASSWORD"),
            )
            sampler.mark(phase=self.phase.name, segment=segment_no, level=0, target=0)
            sampler.start()
            crew = next(
                (f for f in followers if f.container == containers.get("crew", {}).get("Name")),
                None,
            )
            # The cold session is tracked by DB counts, so it ends even on a branch without BENCH lines.
            controller.external_in_flight = self._count_in_flight
            controller.set_context(self.phase.name, 0, "cold", segment_no)
            controller.hold(
                1, ladder.session_timeout_s, ladder.session_timeout_s, lambda: None, max_starts=1
            )
            time.sleep(2)  # let crew's session_end line reach the follower
            self.fallback = crew is None or not any(
                e.get("checkpoint") == "session_end" for e in crew.events
            )
            if not self.fallback:
                controller.external_in_flight = None
                self._api_error = None  # left over from counting the cold session
            baseline_start = time.time()
            time.sleep(ladder.baseline_s)
            load_start = time.time()
            counts = sampler.snapshot_counts()
            for level in levels:
                start = time.time()
                controller.set_context(self.phase.name, level, kind, segment_no)
                sampler.mark(level=level, target=level)
                hold_s = (
                    ladder.session_timeout_s * 4 if max_starts else self.settle_s + ladder.hold_s
                )
                abort_check = self._abort_check(controller, sampler, counts)
                reason = controller.hold(
                    level, hold_s, ladder.session_timeout_s, abort_check, max_starts=max_starts
                )
                window = analyze.Window(
                    self.phase.name,
                    level,
                    kind,
                    segment_no,
                    start,
                    start + (0 if max_starts else self.settle_s),
                    time.time(),
                    reason,
                )
                if reason is None and not max_starts:  # a dev run's hold already waited
                    window.abort_reason = self._finish_measured(controller, window, abort_check)
                if self.fallback:
                    # crew has no BENCH lines: end times only exist in the sessions API
                    try:
                        self._apply_sessions_api(
                            [
                                r
                                for r in controller.records
                                if r.segment == segment_no and r.level == level
                            ]
                        )
                    except ApiError as error:
                        print(
                            f"[{self.phase.name}] could not refresh sessions from the API: {error}"
                        )
                live_rows = analyze.build_rows(
                    controller.records, [e for f in followers for e in f.events], now=time.time()
                )
                verdict, reasons = analyze.judge(
                    analyze.measured(live_rows, window),
                    window,
                    self.phase.pass_rules,
                    self.case.abort,
                )
                window.live_verdict = verdict
                self.windows.append(window)
                results.append((level, verdict))
                if kind != "smoke":
                    print(
                        f"[{self.phase.name}] {kind} level {level}: {verdict} {'; '.join(reasons)}"
                    )
                if verdict != "pass":
                    break
            load_end = time.time()
            sampler.mark(level=0, target=0)
            controller.drain(ladder.session_timeout_s)
            time.sleep(ladder.cooldown_s)
            self.segments.append(
                analyze.Segment(
                    self.phase.name,
                    segment_no,
                    kind,
                    baseline_start,
                    load_start,
                    load_end,
                    time.time(),
                )
            )
            completed = True
        finally:
            self.records += controller.records  # first: a second Ctrl+C below must not lose them
            if not completed:
                print(f"[{self.phase.name}] stopping in-flight sessions...")
                # stop what is still running before cleanup deletes it; in fallback mode drop the
                # API-based count so drain only waits for pending HTTP and never calls the API
                counted_by_api = controller.external_in_flight is not None
                controller.external_in_flight = None
                self._safe("drain", lambda: controller.drain(0, stop_status=INTERRUPTED))
                if counted_by_api:  # the controller knew counts, not ids, so it stopped nothing
                    self._safe(
                        "stop unfinished sessions",
                        lambda: self._stop_unfinished(controller.records),
                    )
            if load_start is not None and len(self.segments) < segment_no:
                # interrupted mid-segment: keep what was measured
                now = time.time()
                self.segments.append(
                    analyze.Segment(
                        self.phase.name, segment_no, kind, baseline_start, load_start, now, now
                    )
                )
            if sampler:
                self._safe("sampler stop", sampler.stop)
                self.timeline += sampler.rows
                self.container_timeline += sampler.container_rows
            for follower in followers:
                self._safe("log follower stop", follower.stop)
            self._safe("controller close", controller.close)
            self.events += [event for follower in followers for event in follower.events]
        return results

    def _finish_measured(
        self, controller: Controller, window: analyze.Window, abort_check
    ) -> str | None:
        """Keep the level's load until every session the hold measured has ended, so the verdict
        uses their true durations instead of lower bounds. Sessions sent meanwhile get kind
        FINISH_KIND and are never measured. Each measured session's own session_timeout_s caps
        the wait: one still running then is stopped as `timeout`, a failure. Sets
        window.finish_end_ts; returns an abort reason or None."""
        measured = [record for record in controller.records if window.measures(vars(record))]
        timeout_s = self.case.ladder.session_timeout_s
        last_refresh = 0.0

        def all_ended() -> bool:
            nonlocal last_refresh
            if self.fallback and time.time() - last_refresh >= FALLBACK_REFRESH_S:
                # without BENCH lines end times exist only in the sessions API
                last_refresh = time.time()
                with contextlib.suppress(ApiError):
                    self._apply_sessions_api(measured)
            return all(record.done for record in measured)

        controller.set_context(self.phase.name, window.level, FINISH_KIND, window.segment)
        # by timeout_s after the hold the timeout rule has stopped every measured session; the
        # margin only gives that rule a last tick
        reason = controller.hold(
            window.level, timeout_s + FINISH_MARGIN_S, timeout_s, abort_check, until=all_ended
        )
        if self.fallback and not all(record.done for record in measured):
            # fallback control cannot time sessions out by id: stop the rest through the API
            self._stop_unfinished(measured, status="timeout")
        window.finish_end_ts = time.time()
        return reason

    def _safe(self, step: str, action) -> None:
        try:
            action()
        except Exception:
            print(f"[{self.phase.name}] {step} failed:\n{traceback.format_exc()}")

    def _count_in_flight(self) -> int:
        """Fallback session count; a failing API is the break being measured, not a crash."""
        try:
            count = self.api.in_flight(self.phase.graph_id)
        except ApiError as error:
            if self._api_error is None:
                self._api_error = (self.clock(), str(error))
            # never report 0 while a session may be running: hold() would end early
            return max(self._last_in_flight, 1)
        self._api_error = None
        self._last_in_flight = count
        return count

    def _abort_check(self, controller: Controller, sampler: Sampler, counts: dict):
        abort = self.case.abort

        def check() -> str | None:
            latest = sampler.latest
            if abort.container_restart:
                restarted = sampler.restarts_since(counts)
                if restarted:
                    return f"container restart/OOM: {', '.join(restarted)}"
            available = latest.get("host_mem_avail_pct")
            if available is not None and available < abort.host_min_available_ram_pct:
                return (
                    f"host RAM available {available:.0f}% < {abort.host_min_available_ram_pct:g}%"
                )
            if (
                controller.external_in_flight is not None
                and self._api_error
                and self.clock() - self._api_error[0] >= self.api_error_persist_s
            ):
                return f"API unreachable while counting sessions: {self._api_error[1]}"
            rate = controller.recent_error_rate(time.time())
            if rate is not None and rate >= abort.error_rate_30s:
                return f"error rate {rate:.0%} over 30 s"
            return None

        return check

    def finish_fallback(self) -> None:
        """Branches without crew BENCH lines: take end times from the sessions API."""
        if self.fallback:
            self._apply_sessions_api(self.records)

    def _apply_sessions_api(self, records: list) -> dict[int, dict]:
        """Set end times and statuses from the sessions API; returns its rows by session id."""
        if not records:
            return {}
        since = datetime.fromtimestamp(min(r.intended_ts for r in records), UTC).isoformat()
        by_id = {row["id"]: row for row in self.api.sessions_since(self.phase.graph_id, since)}
        for record in records:
            row = by_id.get(record.session_id)
            if row and row.get("finished_at") and record.end_status not in RUNNER_STATUSES:
                record.done_ts = datetime.fromisoformat(row["finished_at"]).timestamp()
                record.end_status = row.get("status")
        return by_id

    def _stop_unfinished(self, records: list, status: str = INTERRUPTED) -> None:
        """Fallback mode knows no ids live: stop those of `records` the API still has pending
        or running, and mark them `status`. On an interrupt this keeps cleanup from deleting
        sessions crew is still executing; at the finish cap it enforces session_timeout_s."""
        rows = self._apply_sessions_api(records)
        for record in records:
            row = rows.get(record.session_id)
            if not record.done and row and row.get("status") in ("pending", "run"):
                try:
                    self.api.stop_session(record.session_id)
                except ApiError as error:  # one failed stop must not leave the others running
                    print(
                        f"[{self.phase.name}] could not stop session {record.session_id}: {error}"
                    )
                    continue
                record.done_ts, record.end_status = time.time(), status

    def cleanup(self) -> None:
        ids = [record.session_id for record in self.records if record.session_id]
        if ids:
            print(f"[{self.phase.name}] deleted {self.api.delete_sessions(ids)} sessions")


def run_variant(case: Case, variant: Variant, options: Options) -> Path:
    api = Api(options.api_base, options.api_key, options.org_id)
    env_path = options.repo / "src" / ".env"
    host_findings = evaluate_host(_host_facts(options.repo))
    _report(host_findings)
    created = datetime.now(UTC)
    phases, labels = [], []
    images, limits, crash, interrupted = {}, {}, None, False
    project = stack.detect_project()
    meta_git = stack.git_info(options.repo)
    overrides = {**case.env, **variant.env}

    def save() -> Path:
        """Analyze what the phases collected into the run folder. Reads the variables of
        run_variant as they are when it is called."""
        run_labels = [
            *labels,
            *[
                f"fallback-control:{phase_runner.phase.name}"
                for phase_runner in phases
                if phase_runner.fallback
            ],
            *(["dirty-tree"] if meta_git["dirty"] else []),
            *([] if options.build else ["build-unverified"]),
        ]
        host = stack.host_info()
        name = run_dir_name(
            created.strftime("%Y-%m-%d_%H%M"),
            host["hostname"],
            meta_git["ref"],
            meta_git["sha"],
            case.name,
            variant.name,
        )
        meta = {
            "run_id": name,
            "created_at": created.isoformat(timespec="seconds"),
            "note": options.note,
            "kind": case.kind,
            "case": {
                "name": case.name,
                "hash": case.case_hash,
                "variant": variant.name,
                "overrides": allowlisted(overrides),
            },
            "git": {**meta_git, "built": options.build},
            "images": images,
            "host": host,
            "container_limits": limits,
            "env": {key: value for key, value in allowlisted(env).items() if value != "<set>"},
            "labels": run_labels,
            "smoke": smoke,
            "graphs": graphs,
        }
        data = analyze.RunData(
            case,
            variant.name,
            meta,
            [r for p in phases for r in p.records],
            [w for p in phases for w in p.windows],
            [s for p in phases for s in p.segments],
            [e for p in phases for e in p.events],
            [t for p in phases for t in p.timeline],
            [c for p in phases for c in p.container_timeline],
        )
        run_dir = options.results_dir / name
        analyze.analyze(data, run_dir)
        print(f"\nRun folder: {run_dir}")
        return run_dir

    with contextlib.ExitStack() as exits:
        root = (
            exits.enter_context(stack.Worktree(options.repo, variant.ref))
            if variant.ref
            else options.repo
        )
        if variant.ref:
            meta_git = {**stack.git_info(root), "ref": variant.ref}
        compose = stack.Compose(root / "src", env_path, project)
        try:
            try:
                with stack.EnvOverride(env_path, overrides):
                    compose.up(build=options.build)
                    env = stack.read_env_file(env_path)
                    graphs = _resolve_graphs(api, case)
                    _report(evaluate_stack(_stack_facts(compose, api, case, env, graphs), case))
                    smoke = (
                        run_smoke(case, api, compose, options, env)
                        if options.smoke
                        else {
                            "ran": False,
                            "passed": None,
                            "details": "",
                            "e2e_p95_s": {},
                            "llm_p95_s": {},
                        }
                    )
                    settle_s = max(
                        [
                            case.ladder.settle_s,
                            *[v for v in smoke.get("e2e_p95_s", {}).values() if v],
                        ]
                    )
                    for phase in case.phases:
                        phase_runner = PhaseRunner(
                            case, phase, api, compose, options, env, settle_s
                        )
                        phases.append(phase_runner)
                        try:
                            if case.kind == "dev":
                                phase_runner.run_dev(case.dev.sessions, case.dev.concurrency)
                            else:
                                phase_runner.run_capacity()
                        except KeyboardInterrupt:
                            interrupted = True
                            labels.append("interrupted")
                            print("\n[run] interrupted: saving what was measured")
                            break
                        except Exception as error:
                            crash = error
                            labels.append(f"crashed:{type(error).__name__}")
                            print(f"\n[run] phase {phase.name} crashed; saving what was measured")
                            break
                        finally:
                            for step in (phase_runner.finish_fallback, phase_runner.cleanup):
                                try:
                                    step()
                                except Exception as step_error:
                                    print(f"[{phase.name}] {step.__name__} failed: {step_error!r}")
                    try:
                        images, limits = compose.images(), _container_limits(compose)
                    except Exception as error:  # unknown image ids must not cost the measurements
                        print(f"could not read images/limits: {error}")
            finally:
                # .env is restored by now. Save before re-applying the stack below: that takes
                # minutes, and a second Ctrl+C during it must not lose the measurements.
                if phases:
                    run_dir = save()
        finally:
            # re-apply the original settings with the MAIN checkout's compose
            main_compose = stack.Compose(options.repo / "src", env_path, project)
            try:
                main_compose.up(build=False)
            except stack.StackError as error:
                print(
                    f"\n!!! re-applying the original .env failed: {error}"
                    f"\n!!! run: {shlex.join(main_compose.cmd('up', '-d'))}\n"
                )
    if crash is not None:
        raise crash
    if interrupted:
        raise KeyboardInterrupt
    return run_dir


def _report(findings: list[tuple[str, str]], fatal: bool = True) -> bool:
    """Print findings; returns True when any is an error (and exits 2 on it unless not fatal)."""
    for level, message in findings:
        print(f"{'✗' if level == 'error' else '⚠'} {message}")
    has_error = any(level == "error" for level, _ in findings)
    if has_error and fatal:
        raise SystemExit(2)
    return has_error


def _docker_ok() -> bool:
    try:
        return stack.run(["docker", "info"], timeout=30, check=False).returncode == 0
    except stack.StackError:  # docker binary missing or hung
        return False


def _host_facts(repo: Path) -> dict:
    load1 = mem_avail_pct = None
    with contextlib.suppress(OSError, ValueError, IndexError):
        load1 = float(Path("/proc/loadavg").read_text().split()[0])
    with contextlib.suppress(OSError, KeyError, ZeroDivisionError, ValueError):
        meminfo = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            name, _, rest = line.partition(":")
            meminfo[name] = int(rest.split()[0])
        mem_avail_pct = 100 * meminfo["MemAvailable"] / meminfo["MemTotal"]
    return {
        "docker_ok": _docker_ok(),
        "load1": load1,
        "vcpu": os.cpu_count() or 1,
        "mem_avail_pct": mem_avail_pct,
        "backup_exists": (repo / "src" / f".env{stack.BACKUP_SUFFIX}").exists(),
    }


def _resolve_graphs(api: Api, case: Case) -> dict[str, dict]:
    graphs = {}
    for phase in case.phases:
        try:
            graph = api.get_graph(phase.graph_id)
            graphs[phase.name] = {
                "graph_id": phase.graph_id,
                "graph_name": graph["name"],
                "graph_hash": graph_hash(graph),
            }
        except ApiError as error:
            graphs[phase.name] = {"error": str(error)}
    return graphs


def _stack_facts(
    compose: stack.Compose,
    api: Api,
    case: Case,
    env: dict,
    graphs: dict,
    case_env: dict | None = None,
) -> dict:
    unhealthy = [
        row["Service"]
        for row in compose.ps()
        if not (row.get("State") == "running" and row.get("Health") in ("", "healthy", None))
        and not (row.get("State") == "exited" and row.get("ExitCode") == 0)
    ]
    graph_errors = {name: graph["error"] for name, graph in graphs.items() if "error" in graph}
    leftover = {}
    for phase in case.phases:
        if phase.name in graph_errors:
            continue
        try:
            leftover[phase.name] = api.in_flight(phase.graph_id)
        except ApiError as error:
            graph_errors[phase.name] = str(error)
    containers = compose.containers()
    names = [containers[name]["Name"] for name in stack.INSTRUMENTED if name in containers]
    inspected = stack.inspect(names)
    log_drivers, bench_active, memory_limits = {}, {}, {}
    for service in stack.INSTRUMENTED:
        data = inspected.get(containers.get(service, {}).get("Name", ""))
        if data is None:
            continue
        host_config = data.get("HostConfig", {})
        log_drivers[service] = host_config.get("LogConfig", {}).get("Type")
        variable = LOG_LEVEL_VARIABLES[service]
        # a run applies the case env, so it wins over the running container's env
        level = (case_env or {}).get(variable) or stack.container_env(data).get(variable, "")
        bench_active[service] = level.upper() in BENCH_LEVELS
        memory_limits[service] = host_config.get("Memory") or 0
    caps = {}
    for key in CAP_VARIABLES:
        try:
            caps[key] = int(env[key])
        except (KeyError, ValueError):
            caps[key] = None
    return {
        "unhealthy": unhealthy,
        "graph_errors": graph_errors,
        "leftover": leftover,
        "log_drivers": log_drivers,
        "bench_active": bench_active,
        "caps": caps,
        "memory_limits": memory_limits,
    }


def _container_limits(compose: stack.Compose) -> dict[str, dict]:
    names = [row["Name"] for row in compose.containers().values()]
    limits = {}
    for name, data in stack.inspect(names).items():
        host_config = data.get("HostConfig", {})
        cpus, memory = host_config.get("NanoCpus"), host_config.get("Memory")
        limits[name] = {
            "cpus": cpus / 1e9 if cpus else None,
            "mem_mb": memory / 2**20 if memory else None,
        }
    return limits


def _smoke_failures(rows: list[dict], events: list[dict]) -> list[str]:
    """Why a smoke phase is not trustworthy; empty when it is. `rows` come from
    `analyze.build_rows`, whose status prefers crew's session_end event over the record."""
    problems = []
    if not any(row["status"] == "end" for row in rows):
        problems.append("no session finished with status 'end'")
    failed = [row for row in rows if row["status"] != "end"]
    if failed:
        statuses = sorted({str(row["status"]) for row in failed})
        problems.append(f"{len(failed)} of {len(rows)} sessions did not end cleanly ({statuses})")
    seen = {(event["service"], event["checkpoint"]) for event in events}
    active = {service for service, _ in seen}  # a service that logged nothing has BENCH inactive
    required = {
        service: set(names) for service, names in EXPECTED_CHECKPOINTS.items() if service in active
    }
    if "agent" in active and ("crew", "agent_dispatched") in seen:
        required["agent"] = {"llm_start", "llm_end"}
    if "sandbox" in active:
        required["sandbox"] = {"exec_start", "exec_end"}
    for service, checkpoints in required.items():
        missing = sorted(name for name in checkpoints if (service, name) not in seen)
        if missing:
            problems.append(f"{service}: missing checkpoints {missing}")
    return problems


def run_smoke(case: Case, api: Api, compose: stack.Compose, options: Options, env: dict) -> dict:
    """A short real run per phase, to prove the instrumentation works before the long ladder."""
    smoke_case = replace(case, ladder=replace(case.ladder, hold_s=60))
    smoke_options = replace(options, restart=False)
    details, e2e_p95, llm_p95 = [], {}, {}
    for phase in case.phases:
        phase_runner = PhaseRunner(smoke_case, phase, api, compose, smoke_options, env, settle_s=0)
        try:
            phase_runner._segment("smoke", [2])
            try:
                phase_runner.finish_fallback()
            except ApiError as error:
                print(f"[{phase.name}] could not refresh smoke sessions from the API: {error}")
            rows = analyze.build_rows(phase_runner.records, phase_runner.events)
            details += [
                f"{phase.name}: {problem}" for problem in _smoke_failures(rows, phase_runner.events)
            ]
            e2e_p95[phase.name] = analyze.percentile(
                [row["e2e_s"] for row in rows if row["status"] == "end" and row["e2e_s"]], 0.95
            )
            calls = [
                float(end["ts"]) - float(start["ts"])
                for start, end in analyze.pair_spans(
                    phase_runner.events,
                    "llm_start",
                    "llm_end",
                    lambda event: event.get("correlation_id"),
                )
            ]
            llm_p95[phase.name] = analyze.percentile(calls, 0.95)
        finally:
            phase_runner.cleanup()
    result = {
        "ran": True,
        "passed": not details,
        "details": "; ".join(details) or "ok",
        "e2e_p95_s": e2e_p95,
        "llm_p95_s": llm_p95,
    }
    if details:
        print(f"✗ smoke failed: {result['details']}")
        raise SystemExit(3)
    print("smoke passed")
    return result


def run_dev(case: Case, options: Options, sessions: int, concurrency: int) -> Path:
    dev_case = replace(
        case, kind="dev", dev=DevSettings(sessions, concurrency), phases=case.phases[:1]
    )
    return run_variant(dev_case, Variant("default"), replace(options, smoke=False))


def preflight_only(case: Case, options: Options) -> int:
    findings = evaluate_host(_host_facts(options.repo))
    if _report(findings, fatal=False):
        return 2  # any host-level error (e.g. docker down) makes the stack checks below meaningless
    api = Api(options.api_base, options.api_key, options.org_id)
    env_path = options.repo / "src" / ".env"
    compose = stack.Compose(options.repo / "src", env_path, stack.detect_project())
    graphs = _resolve_graphs(api, case)
    env = {**stack.read_env_file(env_path), **case.env}  # a run applies the case env on top
    facts = _stack_facts(compose, api, case, env, graphs, case_env=case.env)
    stack_findings = evaluate_stack(facts, case)
    has_error = _report(stack_findings, fatal=False)
    if not findings and not stack_findings:
        print("preflight ok")
    return 2 if has_error else 0
