"""Unit tests for benchmark/ (standard library only).

Run from the repo root:  python -m unittest discover -s benchmark -p "test_*.py"
"""

import csv
import dataclasses
import itertools
import json
import shutil
import tempfile
import textwrap
import threading
import time as time_module
import tomllib
import unittest
from pathlib import Path
from unittest import mock

import analyze
import api
import compare
import config
import fixtures
import load
import push
import runner
import sample
import stack
from config import AbortRules, PassRules

CASE_TOML = textwrap.dedent(
    """
    name = "server-capacity"
    kind = "capacity"
    [env]
    CREW_MAX_CONCURRENT_SESSIONS = 100000
    CREW_LOG_LEVEL = "BENCH"
    [ladder]
    start = 25
    factor = 2
    max = 400
    [pass]
    p95_e2e_s = 120
    [[phase]]
    name = "payload"
    graph_id = 17
    [[phase]]
    name = "complex"
    graph_id = 18
    variables = { question = "hi" }
    pass = { p95_e2e_s = 300 }
    [[variant]]
    name = "default"
    [[variant]]
    name = "crew-cap-50"
    env = { CREW_MAX_CONCURRENT_SESSIONS = 50 }
    """
)


def write_case(text: str = CASE_TOML) -> Path:
    folder = Path(tempfile.mkdtemp())
    path = folder / "case.toml"
    path.write_text(text, encoding="utf-8")
    return path


class ConfigTest(unittest.TestCase):
    def test_loads_phases_with_merged_pass_rules(self):
        case = config.load_case(write_case())
        self.assertEqual([phase.name for phase in case.phases], ["payload", "complex"])
        self.assertEqual(case.phases[0].pass_rules.p95_e2e_s, 120)
        self.assertEqual(case.phases[1].pass_rules.p95_e2e_s, 300)
        self.assertEqual(case.env["CREW_MAX_CONCURRENT_SESSIONS"], "100000")

    def test_graph_override_and_unknown_phase(self):
        case = config.load_case(write_case(), {"payload": 99})
        self.assertEqual(case.phases[0].graph_id, 99)
        with self.assertRaisesRegex(config.CaseError, "unknown phases"):
            config.load_case(write_case(), {"nope": 1})

    def test_missing_graph_id_names_the_flag(self):
        with self.assertRaisesRegex(config.CaseError, "--graph payload=<id>"):
            config.load_case(write_case(CASE_TOML.replace("graph_id = 17\n", "")))

    def test_unknown_key_is_rejected(self):
        with self.assertRaisesRegex(config.CaseError, r"unknown keys in \[ladder\]"):
            config.load_case(write_case(CASE_TOML.replace("factor = 2", "factr = 2")))

    def test_case_hash_ignores_variants_and_graph_ids(self):
        base = config.load_case(write_case()).case_hash
        other_ids = config.load_case(
            write_case(CASE_TOML.replace("graph_id = 17", "graph_id = 5"))
        ).case_hash
        no_variants = config.load_case(write_case(CASE_TOML.split("[[variant]]")[0])).case_hash
        changed = config.load_case(
            write_case(CASE_TOML.replace("max = 400", "max = 800"))
        ).case_hash
        self.assertEqual(base, other_ids)
        self.assertEqual(base, no_variants)
        self.assertNotEqual(base, changed)

    def test_select_variants_with_adhoc_overlay(self):
        case = config.load_case(write_case())
        chosen = config.select_variants(
            case, ["crew-cap-50"], {"AGENT_MAX_CONCURRENT_RUNS": "5"}, "fix/x"
        )
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen[0].name, "crew-cap-50-adhoc")
        self.assertEqual(
            chosen[0].env, {"CREW_MAX_CONCURRENT_SESSIONS": "50", "AGENT_MAX_CONCURRENT_RUNS": "5"}
        )
        self.assertEqual(chosen[0].ref, "fix/x")
        with self.assertRaisesRegex(config.CaseError, "unknown variants"):
            config.select_variants(case, ["missing"], {}, None)

    def test_ladder_levels_and_bisect(self):
        ladder = config.Ladder(start=25, factor=2, max=400)
        self.assertEqual(config.ladder_levels(ladder), [25, 50, 100, 200, 400])
        self.assertEqual(
            config.ladder_levels(config.Ladder(start=1, factor=1.2, max=4)), [1, 2, 3, 4]
        )
        self.assertEqual(config.bisect_next(100, 200), 150)
        self.assertEqual(config.bisect_next(None, 25), 12)
        self.assertIsNone(config.bisect_next(100, 105))  # within 10 %

    def test_parse_assignments_and_allowlist(self):
        self.assertEqual(config.parse_assignments(["payload=17"], int), {"payload": 17})
        with self.assertRaises(config.CaseError):
            config.parse_assignments(["oops"])
        self.assertEqual(
            config.allowlisted({"CREW_LOG_LEVEL": "BENCH", "DB_PASSWORD": "x"}),
            {"CREW_LOG_LEVEL": "BENCH", "DB_PASSWORD": "<set>"},
        )

    def test_shipped_cases_load(self):
        cases = Path(__file__).parent / "cases"
        server = config.load_case(cases / "server.toml", {"payload": 1, "complex": 2})
        dev = config.load_case(cases / "dev.toml", {"payload": 1})
        self.assertEqual(server.kind, "capacity")
        self.assertEqual((dev.kind, dev.dev.sessions, dev.dev.concurrency), ("dev", 100, 25))


class ApiTest(unittest.TestCase):
    def test_graph_hash_ignores_timestamps_and_save_version(self):
        graph = {
            "id": 1,
            "name": "f",
            "updated_at": "x",
            "save_version": 3,
            "python_node_list": [{"id": 5, "code": "print(1)", "created_at": "y"}],
        }
        same = {**graph, "updated_at": "z", "save_version": 9}
        edited = {**graph, "python_node_list": [{"id": 5, "code": "print(2)", "created_at": "y"}]}
        self.assertEqual(api.graph_hash(graph), api.graph_hash(same))
        self.assertNotEqual(api.graph_hash(graph), api.graph_hash(edited))


class EnvOverrideTest(unittest.TestCase):
    def test_apply_replaces_active_lines_and_appends_missing(self):
        text = "A=1\n# B=<enter your value>\nC=3\n"
        self.assertEqual(
            stack.apply_env_overrides(text, {"A": "9", "B": "2"}),
            "A=9\n# B=<enter your value>\nC=3\nB=2\n",
        )

    def test_restores_after_keyboard_interrupt(self):
        folder = Path(tempfile.mkdtemp())
        env_path = folder / ".env"
        env_path.write_text("A=1\n", encoding="utf-8")
        with self.assertRaises(KeyboardInterrupt), stack.EnvOverride(env_path, {"A": "2"}):
            self.assertEqual(env_path.read_text(encoding="utf-8"), "A=2\n")
            raise KeyboardInterrupt
        self.assertEqual(env_path.read_text(encoding="utf-8"), "A=1\n")
        self.assertFalse((folder / ".env.bench-backup").exists())

    def test_refuses_when_previous_backup_exists(self):
        folder = Path(tempfile.mkdtemp())
        (folder / ".env").write_text("A=1\n", encoding="utf-8")
        (folder / ".env.bench-backup").write_text("A=0\n", encoding="utf-8")
        with (
            self.assertRaisesRegex(stack.StackError, "did not restore"),
            stack.EnvOverride(folder / ".env", {}),
        ):
            pass

    def test_restores_and_cleans_backup_on_write_failure(self):
        folder = Path(tempfile.mkdtemp())
        env_path = folder / ".env"
        env_path.write_text("A=1\n", encoding="utf-8")
        original_content = env_path.read_text(encoding="utf-8")
        with (
            self.assertRaises(RuntimeError),
            mock.patch.object(stack, "apply_env_overrides", side_effect=RuntimeError("boom")),
            stack.EnvOverride(env_path, {"A": "2"}),
        ):
            pass
        self.assertEqual(env_path.read_text(encoding="utf-8"), original_content)
        self.assertFalse((folder / ".env.bench-backup").exists())


class ComposeParseTest(unittest.TestCase):
    def test_parse_ps_accepts_array_and_json_lines(self):
        row = {"Service": "crew", "State": "running", "Health": ""}
        self.assertEqual(stack.parse_ps(json.dumps([row])), [row])
        self.assertEqual(stack.parse_ps(json.dumps(row) + "\n" + json.dumps(row)), [row, row])
        self.assertEqual(stack.parse_ps(""), [])

    def test_read_env_file_skips_comments(self):
        folder = Path(tempfile.mkdtemp())
        (folder / ".env").write_text(
            "# X=1\nA = 2 # note\nB='3'\nPASSWORD=ab#cd\nC=1 # note\nQ='x # y'\n",
            encoding="utf-8",
        )
        self.assertEqual(
            stack.read_env_file(folder / ".env"),
            {"A": "2", "B": "3", "PASSWORD": "ab#cd", "C": "1", "Q": "x # y"},
        )


class SampleParseTest(unittest.TestCase):
    def test_cgroup_and_proc_parsers(self):
        self.assertEqual(sample.parse_cpu_stat("usage_usec 1500\nuser_usec 1000\n"), 1500)
        self.assertEqual(sample.parse_memory_events("low 0\noom 2\noom_kill 1\n"), 1)
        self.assertEqual(sample.parse_proc_stat("cpu  10 0 5 80 5 0 0 0 0 0\ncpu0 1 2"), (85, 100))
        self.assertEqual(
            sample.parse_meminfo("MemTotal: 1000 kB\nMemAvailable: 250 kB\n")["MemAvailable"], 250
        )

    def test_live_line(self):
        row = {
            "phase": "payload",
            "level": 50,
            "target": 50,
            "inflight": 48,
            "running": 40,
            "queued": 8,
            "completed": 120,
            "failed": 1,
            "host_cpu_pct": 63.0,
            "host_mem_avail_mb": 30000,
            "pg_connections": 42,
            "redis_used_mb": 25.0,
        }
        line = sample.live_line(row, {"crew": {"mem_mb": 812.4}, "agent": {"mem_mb": None}})
        self.assertEqual(
            line,
            "payload L50 target 50 in-flight 48 running 40 queued 8 done 120 err 1 | "
            "CPU 63% | RAM avail 30000 MB | crew 812 MB agent — MB | pg 42 | redis 25 MB",
        )

    def test_redis_and_docker_size(self):
        self.assertEqual(sample.parse_redis_used_mb("# Memory\r\nused_memory:2097152\r\n"), 2.0)
        self.assertIsNone(sample.parse_redis_used_mb("garbage"))
        self.assertAlmostEqual(sample.parse_docker_size_mb("1.5GiB / 4GiB"), 1536.0)
        self.assertAlmostEqual(sample.parse_docker_size_mb("512MiB"), 512.0)


class SamplerTest(unittest.TestCase):
    def test_probe_failure_degrades_gracefully(self):
        """When stack.run raises StackError, row is appended with those fields None."""
        sampler = sample.Sampler(
            {},
            status=lambda: {
                "inflight": 1,
                "running": 1,
                "completed": 0,
                "failed": 0,
            },
            db_user="u",
            redis_user="r",
            redis_password="p",
        )
        with (
            mock.patch.object(stack, "inspect", return_value={}),
            mock.patch.object(stack, "run", side_effect=stack.StackError("timeout")),
        ):
            sampler._sample()
        self.assertEqual(len(sampler.rows), 1)
        row = sampler.rows[0]
        self.assertIsNone(row["pg_connections"])
        self.assertIsNone(row["redis_used_mb"])
        expected_keys = {
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
        }
        self.assertEqual(set(row.keys()), expected_keys)

    def test_container_restart_negative_cpu(self):
        """After a container restart, cpu_pct should be None when usage resets."""
        folder = Path(tempfile.mkdtemp())
        cpu_stat = folder / "cpu.stat"
        memory_current = folder / "memory.current"
        memory_events = folder / "memory.events"
        cpu_stat.write_text("usage_usec 2000000\nuser_usec 1000000\n")
        memory_current.write_text("1048576\n")
        memory_events.write_text("oom_kill 0\n")

        sampler = sample.Sampler(
            {"test": "dummy"},
            status=lambda: {
                "inflight": 1,
                "running": 1,
                "completed": 0,
                "failed": 0,
            },
            db_user=None,
            redis_user=None,
            redis_password=None,
        )
        sampler._cgroups["test"] = folder

        with mock.patch.object(stack, "inspect", return_value={}):
            sampler._sample()
        self.assertEqual(len(sampler.rows), 1)
        first_row_cpu = sampler.latest["containers"]["test"]["cpu_pct"]
        self.assertIsNone(first_row_cpu)

        cpu_stat.write_text("usage_usec 1000\nuser_usec 500\n")
        with mock.patch.object(stack, "inspect", return_value={}):
            sampler._sample()
        self.assertEqual(len(sampler.rows), 2)
        second_row_cpu = sampler.latest["containers"]["test"]["cpu_pct"]
        self.assertIsNone(second_row_cpu)


class FakeStack:
    """start_session returns new ids; a timer reports session_end after `duration_s`."""

    def __init__(self, duration_s=0.05, fail_every=0, end_before_answer=False):
        self.ids = itertools.count(1)
        self.duration_s, self.fail_every, self.end_before_answer = (
            duration_s,
            fail_every,
            end_before_answer,
        )
        self.controller = None
        self.stopped = []
        self.max_in_flight = 0

    def start(self):
        session_id = next(self.ids)
        if self.fail_every and session_id % self.fail_every == 0:
            raise load_error(503)
        self.max_in_flight = max(self.max_in_flight, self.controller.in_flight_count())
        end = {"session_id": session_id, "checkpoint": "session_end", "status": "end"}
        if self.end_before_answer:
            self.controller.on_event({**end, "ts": time_module.time()})
        elif self.duration_s is not None:
            threading.Timer(
                self.duration_s, lambda: self.controller.on_event({**end, "ts": time_module.time()})
            ).start()
        return 200, session_id

    def stop(self, session_id):
        time_module.sleep(0.05)
        self.stopped.append(session_id)


def load_error(status):
    error = RuntimeError(f"HTTP {status}")
    error.status = status
    return error


def make_controller(fake):
    controller = load.Controller(fake.start, fake.stop, senders=8)
    fake.controller = controller
    controller.set_context("payload", 5, "ladder", 1)
    return controller


class ControllerTest(unittest.TestCase):
    def test_holds_target_and_drains(self):
        fake = FakeStack(duration_s=0.05)
        controller = make_controller(fake)
        # hold until three rounds of sessions have started, not for a fixed time: on a loaded
        # machine the sender and timer threads can be too slow to refill within a short hold
        self.assertIsNone(
            controller.hold(
                target=5,
                duration_s=30,
                timeout_s=10,
                abort_check=lambda: None,
                tick_s=0.05,
                until=lambda: len(controller.records) > 10,
            )
        )
        controller.drain(timeout_s=5)
        self.assertLessEqual(fake.max_in_flight, 5)
        self.assertGreater(len(controller.records), 10)
        self.assertTrue(all(record.ok for record in controller.records))
        controller.close()

    def test_session_end_before_http_answer(self):
        fake = FakeStack(end_before_answer=True)
        controller = make_controller(fake)
        controller.hold(target=3, duration_s=0.3, timeout_s=10, abort_check=lambda: None)
        self.assertEqual(controller.drain(timeout_s=2), 0)
        self.assertEqual(controller.in_flight_count(), 0)
        self.assertTrue(all(record.done for record in controller.records))
        self.assertTrue(all(record.ok for record in controller.records))
        controller.close()

    def test_http_errors_free_their_slot_and_count_as_failed(self):
        fake = FakeStack(duration_s=0.02, fail_every=2)
        controller = make_controller(fake)
        controller.hold(target=4, duration_s=0.3, timeout_s=10, abort_check=lambda: None)
        controller.drain(timeout_s=2)
        self.assertEqual(controller.in_flight_count(), 0)
        failed = [record for record in controller.records if record.end_status == "http_error"]
        self.assertTrue(failed)
        self.assertEqual({record.http_status for record in failed}, {503})
        controller.close()

    def test_timeout_stops_the_session(self):
        fake = FakeStack(duration_s=None)  # never ends
        controller = make_controller(fake)
        controller.hold(target=2, duration_s=0.3, timeout_s=0.1, abort_check=lambda: None)
        controller.drain(timeout_s=0.5)
        self.assertTrue(fake.stopped)
        self.assertTrue(
            all(
                record.end_status == "timeout"
                for record in controller.records
                if record.session_id in fake.stopped
            )
        )
        controller.close()

    def test_max_starts_runs_exactly_n_sessions(self):
        fake = FakeStack(duration_s=0.01)
        controller = make_controller(fake)
        controller.hold(
            target=25, duration_s=30, timeout_s=10, abort_check=lambda: None, max_starts=100
        )
        self.assertEqual(len(controller.records), 100)
        self.assertTrue(all(record.done for record in controller.records))
        controller.close()

    def test_abort_reason_is_returned(self):
        fake = FakeStack(duration_s=0.05)
        controller = make_controller(fake)
        self.assertEqual(
            controller.hold(target=2, duration_s=5, timeout_s=10, abort_check=lambda: "host RAM"),
            "host RAM",
        )
        controller.drain(timeout_s=2)
        controller.close()

    def test_slot_acquired_before_http_answer_counts_as_running(self):
        class EarlySlotStack(FakeStack):
            def start(self):
                session_id = next(self.ids)
                self.controller.on_event({"session_id": session_id, "checkpoint": "slot_acquired"})
                return 200, session_id

        fake = EarlySlotStack()
        controller = make_controller(fake)
        controller.hold(target=1, duration_s=0.3, timeout_s=10, abort_check=lambda: None)
        self.assertEqual(controller.in_flight_count(), 1)
        self.assertEqual(controller.running_count(), 1)
        self.assertEqual(controller.drain(timeout_s=0.2), 1)
        controller.close()

    def test_fallback_mode_uses_external_count_and_stops_nothing(self):
        fake = FakeStack(duration_s=None)
        controller = make_controller(fake)
        controller.external_in_flight = lambda: 3
        controller.hold(target=5, duration_s=0.3, timeout_s=0.05, abort_check=lambda: None)
        self.assertEqual(controller.drain(timeout_s=0.2), 0)
        self.assertEqual(controller.status()["inflight"], 3)
        self.assertEqual(fake.stopped, [])
        controller.close()

    def test_drain_stops_leftovers_before_returning(self):
        fake = FakeStack(duration_s=None)
        controller = make_controller(fake)
        controller.hold(target=3, duration_s=0.3, timeout_s=10, abort_check=lambda: None)
        self.assertEqual(controller.drain(timeout_s=0.2), 3)
        self.assertEqual(sorted(fake.stopped), [1, 2, 3])
        controller.close()

    def test_session_end_without_status_is_unknown_and_not_ok(self):
        fake = FakeStack(duration_s=None)
        controller = make_controller(fake)
        controller.hold(target=1, duration_s=0.1, timeout_s=10, abort_check=lambda: None)
        controller.on_event({"session_id": 1, "checkpoint": "session_end", "ts": 1.0})
        record = controller.records[0]
        self.assertEqual(record.end_status, "unknown")
        self.assertFalse(record.ok)
        controller.close()

    def test_drain_waits_for_unanswered_starts_and_stops_them(self):
        class SlowStartStack(FakeStack):
            def start(self):
                time_module.sleep(0.4)
                return 200, next(self.ids)

        fake = SlowStartStack(duration_s=None)
        controller = make_controller(fake)
        controller.hold(
            target=2, duration_s=0.01, timeout_s=10, abort_check=lambda: None, tick_s=0.01
        )
        self.assertEqual(controller.drain(timeout_s=0), 2)
        self.assertEqual(sorted(fake.stopped), [1, 2])
        controller.close()

    def test_interrupt_drain_marks_stopped_sessions_interrupted_not_timeout(self):
        fake = FakeStack(duration_s=None)
        controller = make_controller(fake)
        controller.hold(target=2, duration_s=0.2, timeout_s=10, abort_check=lambda: None)
        self.assertEqual(controller.drain(timeout_s=0, stop_status=load.INTERRUPTED), 2)
        self.assertEqual({record.end_status for record in controller.records}, {load.INTERRUPTED})
        controller.close()

    def test_status_does_not_count_interrupted_sessions_as_failed(self):
        controller = make_controller(FakeStack())
        for status in ("end", "error", load.INTERRUPTED):
            controller.records.append(
                load.SessionRecord("payload", 5, "ladder", 1, 1.0, done_ts=2.0, end_status=status)
            )
        status = controller.status()
        self.assertEqual((status["completed"], status["failed"]), (1, 1))
        controller.close()

    def test_recent_error_rate_is_none_in_fallback_mode(self):
        controller = make_controller(FakeStack())
        controller.external_in_flight = lambda: 0
        self.assertIsNone(controller.recent_error_rate(time_module.time(), min_done=0))
        controller.close()


def record(
    session_id,
    intended,
    sent,
    done,
    status="end",
    level=10,
    kind="ladder",
    segment=1,
    phase="payload",
):
    return load.SessionRecord(
        phase,
        level,
        kind,
        segment,
        intended,
        sent_ts=sent,
        api_ms=5,
        http_status=200,
        session_id=session_id,
        done_ts=done,
        end_status=status,
    )


def crew_events(session_id, received, slot, end, status="end"):
    return [
        {"service": "crew", "checkpoint": "received", "session_id": session_id, "ts": received},
        {"service": "crew", "checkpoint": "slot_acquired", "session_id": session_id, "ts": slot},
        {
            "service": "crew",
            "checkpoint": "agent_dispatched",
            "session_id": session_id,
            "correlation_id": f"c{session_id}",
            "ts": slot + 0.1,
        },
        {
            "service": "agent",
            "checkpoint": "llm_start",
            "correlation_id": f"c{session_id}",
            "ts": slot + 0.2,
        },
        {
            "service": "agent",
            "checkpoint": "llm_end",
            "correlation_id": f"c{session_id}",
            "ts": slot + 1.2,
            "total_tokens": 50,
            "ok": True,
        },
        {
            "service": "crew",
            "checkpoint": "session_end",
            "session_id": session_id,
            "status": status,
            "ts": end,
        },
    ]


WINDOW = analyze.Window("payload", 10, "ladder", 1, start_ts=0, settle_end_ts=10, end_ts=100)


class AnalyzeTest(unittest.TestCase):
    def test_session_row_breaks_time_down(self):
        events, _ = analyze.index_events(crew_events(1, received=11.0, slot=12.0, end=15.0))
        row = analyze.session_row(record(1, intended=10.5, sent=10.6, done=15.0), events[1])
        self.assertAlmostEqual(row["e2e_s"], 4.4)
        self.assertAlmostEqual(row["queue_wait_s"], 1.0)
        self.assertAlmostEqual(row["run_s"], 3.0)
        self.assertAlmostEqual(row["llm_s"], 1.0)
        self.assertAlmostEqual(row["platform_overhead_s"], 3.4)
        self.assertEqual((row["llm_calls"], row["tokens"]), (1, 50))
        self.assertAlmostEqual(row["gen_lag_ms"], 100.0)

    def test_records_without_events(self):
        row = analyze.session_row(record(2, intended=10, sent=10, done=20), [])
        self.assertEqual(row["e2e_s"], 10)
        self.assertIsNone(row["queue_wait_s"])
        self.assertEqual(row["llm_s"], 0)

    def test_censored_in_live_mode(self):
        row = analyze.session_row(
            record(3, intended=10, sent=10, done=None, status=None), [], now=40
        )
        self.assertTrue(row["censored"])
        self.assertEqual(row["e2e_s"], 30)

    def test_interrupted_session_stays_interrupted_and_censored(self):
        # crew reports the stop the runner sent; that must not turn it into a failure
        stopped = crew_events(4, received=11.0, slot=12.0, end=30.5, status="stop")
        events, _ = analyze.index_events(stopped)
        row = analyze.session_row(
            record(4, intended=10, sent=10, done=30.0, status=load.INTERRUPTED), events[4]
        )
        self.assertEqual(row["status"], load.INTERRUPTED)
        self.assertTrue(row["censored"])
        self.assertFalse(analyze.is_failed(row))

    def test_percentiles(self):
        self.assertIsNone(analyze.percentile([], 0.5))
        self.assertEqual(analyze.percentile([1, 2, 3, 4], 0.5), 2.5)
        self.assertEqual(analyze.stats([2, 4])["mean"], 3)


class JudgeTest(unittest.TestCase):
    def rows(self, count, e2e, status="end", lag=1.0, censored=False, queue_wait=0.5):
        """`count` session rows. A censored row was still running at the window end (`e2e` is
        its lower bound); a finished one was sent at 20 s and ended `e2e` seconds later."""
        end = WINDOW.end_ts if censored else 20 + e2e
        sent = end - e2e
        return [
            {
                "phase": "payload",
                "segment": 1,
                "level": 10,
                "kind": "ladder",
                "intended_ts": sent,
                "sent_ts": sent,
                "received_ts": sent + 0.1,
                "slot_ts": sent + 0.1 + queue_wait if queue_wait is not None else None,
                "end_ts": end,
                "e2e_s": e2e,
                "queue_wait_s": queue_wait,
                "status": status,
                "censored": censored,
                "gen_lag_ms": lag,
            }
            for _ in range(count)
        ]

    def running(self, count, lower_bound, queue_wait=0.5):
        return self.rows(count, lower_bound, status=None, censored=True, queue_wait=queue_wait)

    def test_window_where_nothing_finished_is_invalid_not_pass(self):
        verdict, reasons = analyze.judge(
            self.running(400, 60), WINDOW, PassRules(p95_e2e_s=120), AbortRules()
        )
        self.assertEqual(verdict, "invalid")
        self.assertIn("too few measured sessions", reasons[0])
        self.assertIn("raise ladder.hold_s", reasons[0])

    def test_running_sessions_already_over_the_rule_fail(self):
        verdict, reasons = analyze.judge(
            self.running(400, 130), WINDOW, PassRules(p95_e2e_s=120), AbortRules()
        )
        self.assertEqual(verdict, "fail")
        self.assertIn("p95 e2e", reasons[0])

    def test_more_than_five_percent_still_running_is_invalid(self):
        # only after an interrupt or without end times: the runner waits for measured sessions
        rows = self.rows(100, 5) + self.running(10, 8)
        verdict, reasons = analyze.judge(rows, WINDOW, PassRules(p95_e2e_s=10), AbortRules())
        self.assertEqual(verdict, "invalid")
        self.assertIn("p95 e2e unknown", reasons[0])
        self.assertIn("had not ended when the level was judged", reasons[0])

    def test_few_still_running_sessions_do_not_block_a_pass(self):
        rows = self.rows(100, 5) + self.running(5, 8)
        verdict, _ = analyze.judge(rows, WINDOW, PassRules(p95_e2e_s=10), AbortRules())
        self.assertEqual(verdict, "pass")

    def test_more_than_five_percent_still_queued_is_invalid(self):
        # queued for 2.9 s so far: under the 5 s rule, so no breach is proven yet
        rows = self.rows(100, 5) + self.running(10, 3, queue_wait=None)
        verdict, reasons = analyze.judge(rows, WINDOW, PassRules(p95_queue_wait_s=5), AbortRules())
        self.assertEqual(verdict, "invalid")
        self.assertIn("p95 queue wait unknown", reasons[0])

    def test_queue_wait_rule_without_checkpoints_is_skipped(self):
        rows = self.rows(100, 5, queue_wait=None) + self.running(10, 8, queue_wait=None)
        for row in rows:
            row["received_ts"] = None  # fallback mode: crew wrote no BENCH lines
        verdict, _ = analyze.judge(rows, WINDOW, PassRules(p95_queue_wait_s=5), AbortRules())
        self.assertEqual(verdict, "pass")

    def test_sessions_ending_after_the_verdict_do_not_count_towards_the_minimum(self):
        # the level was judged at the end of the hold (100 s); these ended at 220 s
        rows = self.rows(20, 200)
        verdict, reasons = analyze.judge(rows, WINDOW, PassRules(p95_e2e_s=300), AbortRules())
        self.assertEqual(verdict, "invalid")
        self.assertIn("too few measured sessions", reasons[0])

    def test_sessions_longer_than_the_hold_count_once_the_level_waited_for_them(self):
        waited = dataclasses.replace(WINDOW, finish_end_ts=230)
        rows = self.rows(20, 200)
        self.assertEqual(
            analyze.judge(rows, waited, PassRules(p95_e2e_s=300), AbortRules()), ("pass", [])
        )
        verdict, reasons = analyze.judge(rows, waited, PassRules(p95_e2e_s=120), AbortRules())
        self.assertEqual(verdict, "fail")
        self.assertIn("p95 e2e 200.0 s", reasons[0])

    def test_interrupted_sessions_are_not_failures(self):
        rows = self.rows(40, 5) + self.rows(2, 3, status=load.INTERRUPTED, censored=True)
        verdict, reasons = analyze.judge(rows, WINDOW, PassRules(p95_e2e_s=10), AbortRules())
        self.assertEqual((verdict, reasons), ("pass", []))

    def test_pass(self):
        self.assertEqual(
            analyze.judge(self.rows(20, 5), WINDOW, PassRules(p95_e2e_s=10), AbortRules())[0],
            "pass",
        )

    def test_latency_fail(self):
        verdict, reasons = analyze.judge(
            self.rows(20, 50), WINDOW, PassRules(p95_e2e_s=10), AbortRules()
        )
        self.assertEqual(verdict, "fail")
        self.assertIn("p95 e2e", reasons[0])

    def test_too_few_finished_is_invalid(self):
        self.assertEqual(
            analyze.judge(self.rows(3, 5), WINDOW, PassRules(), AbortRules())[0], "invalid"
        )

    def test_generator_limited_is_invalid_not_fail(self):
        verdict, reasons = analyze.judge(
            self.rows(20, 5, lag=900), WINDOW, PassRules(), AbortRules()
        )
        self.assertEqual(verdict, "invalid")
        self.assertIn("generator-limited", reasons[0])

    def test_abort_is_fail(self):
        aborted = analyze.Window(
            "payload", 10, "ladder", 1, 0, 10, 100, abort_reason="container restart: crew"
        )
        self.assertEqual(
            analyze.judge(self.rows(20, 5), aborted, PassRules(), AbortRules()),
            ("fail", ["container restart: crew"]),
        )


class BottleneckTest(unittest.TestCase):
    def test_first_match_wins(self):
        base = {
            "restarts": [],
            "host_mem_avail_min_pct": 50,
            "ram_guard_pct": 5,
            "host_cpu_mean": 40,
            "containers_at_cpu_limit": [],
            "running_mean": 10,
            "queued_mean": 0,
            "crew_cap": 25,
            "agent_queue_p95": 0.1,
            "previous_agent_queue_p95": 0.1,
            "pg_ratio_max": 0.2,
        }
        self.assertEqual(analyze.bottleneck(base), "no saturated resource found")
        self.assertEqual(analyze.bottleneck({**base, "host_cpu_mean": 95}), "host CPU 95%")
        self.assertEqual(
            analyze.bottleneck({**base, "host_cpu_mean": 95, "restarts": ["crew"]}),
            "container restart/OOM: crew",
        )
        self.assertEqual(
            analyze.bottleneck({**base, "running_mean": 25, "queued_mean": 30}),
            "crew slots full (25) with sessions queued",
        )


class AnalyzeFolderTest(unittest.TestCase):
    def test_writes_every_file_with_the_schema_columns(self):
        out = Path(tempfile.mkdtemp())
        run_dir = fixtures.write_capacity_run(
            out, name="demo", levels=(10, 20, 40), fail_from=40, seed=1
        )
        expected = {
            "meta.json",
            "case.toml",
            "sessions.csv.gz",
            "steps.csv",
            "containers.csv",
            "container_phases.csv",
            "nodes.csv",
            "timeline.csv",
            "container_timeline.csv",
            "events_sample.csv",
            "events_full.csv.gz",
        }
        self.assertEqual({path.name for path in run_dir.iterdir()}, expected)
        with open(run_dir / "steps.csv", encoding="utf-8") as steps_file:
            self.assertEqual(steps_file.readline().strip().split(","), analyze.STEP_COLUMNS)
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["schema_version"], 1)
        verdict = meta["phases"][0]["verdict"]
        self.assertEqual((verdict["max_pass_concurrency"], verdict["first_fail_level"]), (20, 40))


def synthetic_run(mem_slope, vcpu=4, labels=None):
    """One passing 10-session step with a controllable memory-vs-running slope."""
    case_path = Path(tempfile.mkdtemp()) / "case.toml"
    case_path.write_text(CASE_TOML, encoding="utf-8")
    case = config.load_case(case_path)
    records = [record(n, intended=20 + n, sent=20 + n, done=30 + n) for n in range(1, 13)]
    timeline, container_timeline = [], []
    for ts in range(0, 111, 5):
        running = 0 if ts < 10 else (ts // 5 % 4) * 5
        row = dict.fromkeys(analyze.TIMELINE_COLUMNS)
        row.update(ts=ts, running=running, inflight=running, queued=0, host_mem_avail_mb=8000)
        timeline.append(row)
        container_timeline.append(
            dict.fromkeys(analyze.CONTAINER_TIMELINE_COLUMNS)
            | {"ts": ts, "container": "crew", "cpu_pct": 50, "mem_mb": 1000 + mem_slope * running}
            | {"restarts": 0, "oom_kills": 0}
        )
    segment = analyze.Segment("payload", 1, "ladder", 0, 10, 100, 110)
    window = analyze.Window("payload", 10, "ladder", 1, start_ts=10, settle_end_ts=20, end_ts=100)
    meta = {"host": {"vcpu": vcpu}, "env": {}, "labels": labels}
    return analyze.RunData(
        case, "base", meta, records, [window], [segment], [], timeline, container_timeline
    )


class RobustnessTest(unittest.TestCase):
    def test_negative_memory_slope_gives_no_ram_bound(self):
        meta = analyze.analyze(synthetic_run(mem_slope=-0.3), Path(tempfile.mkdtemp()))
        estimate = meta["phases"][0]["capacity_estimate"]
        self.assertNotIn("ram", estimate["bounds"])
        self.assertGreater(estimate["concurrency"], 0)

    def test_memory_headline_uses_only_strong_fits(self):
        data = synthetic_run(mem_slope=0.3)
        best = {"phase": "payload", "level": 10, "verdict": "pass", "throughput_per_min": 6}
        best |= {"e2e_s_p50": 10, "e2e_s_p95": 12, "platform_overhead_s_p95": 2}
        best |= {"cpu_s_per_session": 1, "bottleneck": "", "fail_reasons": ""}
        fits = [
            {"phase": "payload", "container": "crew", "mb_per_concurrent": 2.0, "r2": 0.9},
            {"phase": "payload", "container": "agent", "mb_per_concurrent": -5.0, "r2": 0.006},
        ]
        summary = analyze._phase_summary(data, data.case.phases[0], [best], [], {}, fits)
        self.assertEqual(summary["verdict"]["mb_per_concurrent_total"], 2.0)
        self.assertEqual(summary["capacity_estimate"]["bounds"]["ram"], 4000)  # 8000 MB / 2.0

    def test_unknown_vcpu_gives_no_cpu_bound(self):
        meta = analyze.analyze(synthetic_run(mem_slope=0.3, vcpu=None), Path(tempfile.mkdtemp()))
        self.assertNotIn("cpu", meta["phases"][0]["capacity_estimate"]["bounds"])

    def test_cpu_seconds_skip_unknown_samples(self):
        def rows(cpu_values):
            return [
                {"container": "crew", "ts": index * 5, "cpu_pct": cpu}
                for index, cpu in enumerate(cpu_values)
            ]

        known = analyze._cpu_seconds(rows([50, 50, 50]), 0, 10)
        gappy = analyze._cpu_seconds(rows([50, None, 50]), 0, 10)
        self.assertEqual(known, {"crew": 5.0})
        self.assertEqual(gappy, known)
        self.assertEqual(analyze._cpu_seconds(rows([None, None]), 0, 10), {})

    def test_restarted_ignores_unknown_and_failed_probe(self):
        window = analyze.Window("payload", 10, "ladder", 1, 0, 0, 100)

        def timeline(restarts):
            return [
                {"container": "crew", "ts": index, "restarts": value, "oom_kills": 0}
                for index, value in enumerate(restarts)
            ]

        self.assertEqual(analyze._restarted(timeline([2, None, 2]), window), [])
        self.assertEqual(analyze._restarted(timeline([2, 0, 2]), window), [])
        self.assertEqual(analyze._restarted(timeline([2, 3]), window), ["crew"])

    def test_restarts_since_ignores_unknown_counts(self):
        sampler = sample.Sampler(
            {},
            status=dict,
            db_user="u",
            redis_user="r",
            redis_password="p",
        )
        sampler.latest = {"containers": {"crew": {"restarts": None, "oom_kills": None}}}
        self.assertEqual(sampler.restarts_since({"crew": (2, 0)}), [])
        sampler.latest = {"containers": {"crew": {"restarts": 3, "oom_kills": None}}}
        self.assertEqual(sampler.restarts_since({"crew": (2, 0)}), ["crew"])

    def test_failed_inspect_yields_unknown_restarts(self):
        sampler = sample.Sampler({}, status=dict, db_user="u", redis_user="r", redis_password="p")
        sampler._cgroups = {"crew": None}
        with mock.patch.object(sampler, "_docker_stats", return_value={}):
            metrics = sampler._container_metrics(0.0, {})
        self.assertIsNone(metrics["crew"]["restarts"])
        self.assertIsNone(metrics["crew"]["oom_kills"])

    def test_interrupted_sessions_are_reported_apart_from_failures(self):
        data = synthetic_run(mem_slope=0.3)
        for session_id in (90, 91):  # still running when Ctrl+C stopped the drain
            data.records.append(
                record(session_id, intended=60, sent=60, done=105, status=load.INTERRUPTED)
            )
        out = Path(tempfile.mkdtemp())
        analyze.analyze(data, out)
        with open(out / "steps.csv", encoding="utf-8") as steps_file:
            (step,) = list(csv.DictReader(steps_file))
        self.assertEqual((step["failed"], step["interrupted"]), ("0", "2"))
        self.assertEqual(float(step["error_rate"]), 0)
        self.assertNotEqual(step["verdict"], "fail")

    def test_finish_sessions_are_not_measured(self):
        data = synthetic_run(mem_slope=0.3)
        data.windows[0].finish_end_ts = 140
        # sent while the level waited for its measured sessions: slow and failing, never counted
        for session_id in (80, 81):
            data.records.append(
                record(
                    session_id,
                    intended=101,
                    sent=101,
                    done=139,
                    status="error",
                    kind=load.FINISH_KIND,
                )
            )
        # same kind as the level but sent after the hold ended: outside the measured window
        data.records.append(record(82, intended=102, sent=102, done=138, status="error"))
        out = Path(tempfile.mkdtemp())
        analyze.analyze(data, out)
        with open(out / "steps.csv", encoding="utf-8") as steps_file:
            (step,) = list(csv.DictReader(steps_file))
        self.assertEqual((step["sent"], step["failed"], step["verdict"]), ("12", "0", "pass"))

    def test_stored_case_redacts_env_values_outside_the_allowlist(self):
        text = CASE_TOML.replace(
            'CREW_LOG_LEVEL = "BENCH"', 'CREW_LOG_LEVEL = "BENCH"\nDB_PASSWORD = "hunter2"'
        ).replace(
            "env = { CREW_MAX_CONCURRENT_SESSIONS = 50 }",
            'env = { CREW_MAX_CONCURRENT_SESSIONS = 50, OPENAI_API_KEY = "sk-secret" }',
        )
        case = config.load_case(write_case(text))
        data = synthetic_run(mem_slope=0.3)
        data.case = case
        data.meta["case"] = {"hash": case.case_hash}
        out = Path(tempfile.mkdtemp())
        analyze.analyze(data, out)
        stored = (out / "case.toml").read_text(encoding="utf-8")
        self.assertNotIn("hunter2", stored)
        self.assertNotIn("sk-secret", stored)
        expected = tomllib.loads(text)
        expected["env"]["DB_PASSWORD"] = config.REDACTED
        expected["variant"][1]["env"]["OPENAI_API_KEY"] = config.REDACTED
        self.assertEqual(tomllib.loads(stored), expected)  # nothing else changed
        meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["case"]["hash"], config.case_hash(tomllib.loads(text)))

    def test_stored_case_without_secrets_is_an_exact_copy(self):
        out = Path(tempfile.mkdtemp())
        analyze.analyze(synthetic_run(mem_slope=0.3), out)
        self.assertEqual((out / "case.toml").read_text(encoding="utf-8"), CASE_TOML)

    def test_analyze_does_not_mutate_input_labels(self):
        data = synthetic_run(mem_slope=0.3, labels=["mine"])
        data.windows[0].live_verdict = "fail"
        first = analyze.analyze(data, Path(tempfile.mkdtemp()))
        second = analyze.analyze(data, Path(tempfile.mkdtemp()))
        self.assertEqual(data.meta["labels"], ["mine"])
        self.assertEqual(first["labels"], second["labels"])
        self.assertEqual(len(first["labels"]), 2)


def fake_run(
    folder: Path,
    name: str,
    level: int,
    p95: float,
    graph_hash="g1",
    created="2026-10-07T10:00:00+00:00",
) -> Path:
    run_dir = folder / name
    run_dir.mkdir(parents=True)
    meta = {
        "schema_version": 1,
        "run_id": name,
        "created_at": created,
        "kind": "capacity",
        "note": name,
        "case": {"name": "c", "hash": "h1", "variant": "default"},
        "git": {"ref": "dev", "sha": "abc", "dirty": False},
        "host": {"hostname": "h"},
        "env": {},
        "labels": [],
        "phases": [
            {
                "name": "payload",
                "graph_hash": graph_hash,
                "verdict": {"max_pass_concurrency": level},
            }
        ],
    }
    (run_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    header = ",".join(analyze.STEP_COLUMNS)
    values = dict.fromkeys(analyze.STEP_COLUMNS, "")
    values.update(
        phase="payload",
        segment="1",
        level=str(level),
        kind="ladder",
        verdict="pass",
        e2e_s_p95=str(p95),
        e2e_s_p50="1",
        throughput_per_min="60",
        cpu_s_per_session="0.5",
    )
    (run_dir / "steps.csv").write_text(
        header + "\n" + ",".join(values[c] for c in analyze.STEP_COLUMNS) + "\n", encoding="utf-8"
    )
    for file_name, columns in (
        ("nodes.csv", analyze.NODE_COLUMNS),
        ("containers.csv", analyze.CONTAINER_COLUMNS),
        ("container_phases.csv", analyze.CONTAINER_PHASE_COLUMNS),
    ):
        (run_dir / file_name).write_text(",".join(columns) + "\n", encoding="utf-8")
    return run_dir


class CompareTest(unittest.TestCase):
    def test_deltas_against_the_first_run(self):
        folder = Path(tempfile.mkdtemp())
        text = compare.compare_runs(
            [fake_run(folder, "a", 100, 10.0), fake_run(folder, "b", 200, 5.0)]
        )
        self.assertIn("max_pass_concurrency", text)
        self.assertIn("+100.0%", text)
        self.assertIn("-50.0%", text)
        self.assertNotIn("not comparable", text)

    def test_banner_when_the_graph_changed(self):
        folder = Path(tempfile.mkdtemp())
        text = compare.compare_runs(
            [fake_run(folder, "a", 100, 10.0), fake_run(folder, "b", 100, 10.0, graph_hash="g2")]
        )
        self.assertIn("different workload — not comparable", text)


class PushTest(unittest.TestCase):
    def test_index_keeps_numbers_and_appends(self):
        folder = Path(tempfile.mkdtemp())
        fake_run(folder, "old", 100, 1.0, created="2026-10-01T00:00:00+00:00")
        fake_run(folder, "new", 100, 1.0, created="2026-10-02T00:00:00+00:00")
        index = push.build_index(folder, {"runs": [{"number": 7, "folder": "old"}]})
        self.assertEqual(
            [(run["folder"], run["number"]) for run in index["runs"]], [("old", 7), ("new", 8)]
        )

    def test_refuses_folder_with_api_key(self):
        folder = Path(tempfile.mkdtemp())
        run_dir = fake_run(folder, "leaky", 100, 1.0)
        (run_dir / "events_sample.csv").write_text("x,secret-key-123\n", encoding="utf-8")
        self.assertTrue(push.contains_secret(run_dir, "secret-key-123"))
        with self.assertRaisesRegex(SystemExit, "API key"):
            push.push(
                [run_dir],
                str(folder / "repo"),
                Path(__file__).with_name("viewer.html"),
                "secret-key-123",
                True,
            )

    def test_secret_in_gzip_file_is_found(self):
        folder = Path(tempfile.mkdtemp())
        run_dir = fake_run(folder, "gzipped", 100, 1.0)
        import gzip

        gzip_path = run_dir / "events_sample.csv.gz"
        with gzip.open(gzip_path, "wb") as f:
            f.write(b"x,secret-key-456\ny,z\n")
        self.assertTrue(push.contains_secret(run_dir, "secret-key-456"))

    def test_secret_split_across_chunk_boundary_is_found(self):
        folder = Path(tempfile.mkdtemp())
        run_dir = fake_run(folder, "chunked", 100, 1.0)
        secret = "X" * 1000
        csv_path = run_dir / "events_sample.csv"
        # Write secret split across chunk boundary by using chunks smaller than secret
        content = "a" * (push.CHUNK_SIZE - 500) + secret + "b" * 100
        csv_path.write_text(content, encoding="utf-8")
        self.assertTrue(push.contains_secret(run_dir, secret))

    def test_secret_in_a_subfolder_is_found(self):
        # push copies subfolders too, so the scan must look into them
        run_dir = fake_run(Path(tempfile.mkdtemp()), "nested", 100, 1.0)
        (run_dir / "extra").mkdir()
        (run_dir / "extra" / "notes.txt").write_text("key=secret-key-789", encoding="utf-8")
        self.assertTrue(push.contains_secret(run_dir, "secret-key-789"))

    def test_corrupt_gzip_raises_system_exit(self):
        folder = Path(tempfile.mkdtemp())
        run_dir = fake_run(folder, "corrupt", 100, 1.0)
        corrupt_path = run_dir / "corrupted.csv.gz"
        corrupt_path.write_bytes(b"\x1f\x8b\x08\x00bad data here")
        with self.assertRaisesRegex(SystemExit, "cannot be read"):
            push.contains_secret(run_dir, "anything")

    def test_push_with_no_confirmation_leaves_clone_untouched(self):
        folder = Path(tempfile.mkdtemp())
        run_dir = fake_run(folder, "r1", 100, 1.0)
        repo_path = folder / "repo"
        repo_path.mkdir()
        viewer_src = Path(tempfile.mktemp())
        viewer_src.write_text("viewer", encoding="utf-8")
        git_calls = []

        def mock_git(repo, *args):
            git_calls.append(list(args))
            if "status" in args or "pull" in args:
                return ""
            return ""

        with mock.patch.object(push, "_git", side_effect=mock_git):
            push.push([run_dir], str(repo_path), viewer_src, None, False, ask=lambda _: "n")
        self.assertEqual(git_calls, [["status", "--porcelain"], ["pull", "--ff-only"]])
        benchmarks = repo_path / "benchmarks"
        self.assertFalse(benchmarks.exists())

    def test_push_with_yes_copies_and_commits(self):
        folder = Path(tempfile.mkdtemp())
        run_dir = fake_run(folder, "r2", 100, 1.0)
        (run_dir / "events_full.csv.gz").write_text("full", encoding="utf-8")
        (run_dir / "events_sample.csv").write_text("sample", encoding="utf-8")
        repo_path = folder / "repo"
        repo_path.mkdir()
        benchmarks = repo_path / "benchmarks"
        benchmarks.mkdir()
        viewer_src = Path(tempfile.mktemp())
        viewer_src.write_text("viewer", encoding="utf-8")
        git_calls = []
        call_count = [0]

        def mock_git(repo, *args):
            git_calls.append(list(args))
            if "status" in args:
                # First status call (before copying) should return empty
                # Second status call (after copying) should return modified files
                if call_count[0] == 0 and "status" in args:
                    call_count[0] += 1
                    return ""
                elif "status" in args:
                    return "M benchmarks/index.json"
            return ""

        with mock.patch.object(push, "_git", side_effect=mock_git):
            push.push([run_dir], str(repo_path), viewer_src, None, True, ask=None)

        self.assertTrue((benchmarks / "r2").exists())
        self.assertTrue((benchmarks / "r2" / "events_sample.csv").exists())
        self.assertFalse((benchmarks / "r2" / "events_full.csv.gz").exists())
        self.assertTrue((benchmarks / "index.json").exists())
        self.assertTrue((repo_path / "index.html").exists())
        self.assertEqual(
            git_calls[-3:],
            [["add", "benchmarks", "index.html"], ["commit", "-m", git_calls[-2][2]], ["push"]],
        )

    def test_push_repush_same_run_keeps_one_index_entry(self):
        folder = Path(tempfile.mkdtemp())
        run_dir = fake_run(folder, "r3", 100, 1.0)
        repo_path = folder / "repo"
        repo_path.mkdir()
        (repo_path / "benchmarks").mkdir()
        viewer_src = Path(tempfile.mktemp())
        viewer_src.write_text("viewer", encoding="utf-8")
        all_git_calls = []

        def mock_git(repo, *args):
            all_git_calls.append(list(args))
            if "status" in args:
                return "M benchmarks/index.json" if len(all_git_calls) == 5 else ""
            return ""

        with mock.patch.object(push, "_git", side_effect=mock_git):
            push.push([run_dir], str(repo_path), viewer_src, None, True, ask=None)
            all_git_calls.clear()
            push.push([run_dir], str(repo_path), viewer_src, None, True, ask=None)
            git_calls_second = all_git_calls.copy()

        index = json.loads((repo_path / "benchmarks" / "index.json").read_text(encoding="utf-8"))
        run_entries = [r for r in index["runs"] if r["folder"] == "r3"]
        self.assertEqual(len(run_entries), 1)
        self.assertEqual(run_entries[0]["number"], 1)
        self.assertIn(["status", "--porcelain"], git_calls_second)
        self.assertNotIn(["push"], git_calls_second)

    def test_compare_keeps_numeric_node_name_as_string(self):
        folder = Path(tempfile.mkdtemp())
        run_a = fake_run(folder, "a", 100, 10.0)
        run_b = fake_run(folder, "b", 100, 10.0)
        header = ",".join(analyze.NODE_COLUMNS)
        values = dict.fromkeys(analyze.NODE_COLUMNS, "")
        values.update(phase="payload", node_name="123", level="100", p50_s="1.0")
        (run_a / "nodes.csv").write_text(
            header + "\n" + ",".join(values[c] for c in analyze.NODE_COLUMNS) + "\n",
            encoding="utf-8",
        )
        (run_b / "nodes.csv").write_text(
            header + "\n" + ",".join(values[c] for c in analyze.NODE_COLUMNS) + "\n",
            encoding="utf-8",
        )
        text = compare.compare_runs([run_a, run_b])
        self.assertIn("node p50 123", text)
        self.assertNotIn("node p50 123.0", text)


class PreflightTest(unittest.TestCase):
    def test_host_errors_and_ok(self):
        facts = {
            "docker_ok": True,
            "load1": 1.0,
            "vcpu": 12,
            "mem_avail_pct": 80,
            "backup_exists": False,
        }
        self.assertEqual(runner.evaluate_host(facts), [])
        bad = {
            **facts,
            "load1": 9.0,
            "mem_avail_pct": 10,
            "backup_exists": True,
            "docker_ok": False,
        }
        self.assertEqual({level for level, _ in runner.evaluate_host(bad)}, {"error"})
        self.assertEqual(len(runner.evaluate_host(bad)), 4)

    def test_stack_warnings(self):
        case = config.load_case(write_case())
        facts = {
            "unhealthy": [],
            "graph_errors": {},
            "leftover": {"payload": 0},
            "log_drivers": {"crew": "json-file"},
            "bench_active": {"django_app": True, "crew": True, "agent": False, "sandbox": True},
            "caps": {"CREW_MAX_CONCURRENT_SESSIONS": 25, "AGENT_MAX_CONCURRENT_RUNS": 100000},
            "memory_limits": {"crew": 0},
        }
        findings = runner.evaluate_stack(facts, case)
        self.assertIn(
            ("warn", "BENCH not active on agent: its checkpoints are missing from this run"),
            findings,
        )
        self.assertTrue(
            any("CREW_MAX_CONCURRENT_SESSIONS=25" in message for _, message in findings)
        )
        self.assertTrue(any("memory limit" in message for _, message in findings))
        self.assertFalse(any(level == "error" for level, _ in findings))
        broken = {
            **facts,
            "log_drivers": {"crew": "none"},
            "leftover": {"payload": 3},
            "graph_errors": {"payload": "HTTP 404"},
        }
        errors = sum(level == "error" for level, _ in runner.evaluate_stack(broken, case))
        self.assertEqual(errors, 3)


class PlanTest(unittest.TestCase):
    def test_plan_lists_levels_and_worst_case(self):
        case = config.load_case(write_case())
        text = runner.plan_text(case, list(case.variants))
        self.assertIn("payload: 25 → 50 → 100 → 200 → 400", text)
        self.assertIn("crew-cap-50", text)
        self.assertIn("worst case", text)

    def test_run_dir_name_is_slugged(self):
        name = runner.run_dir_name(
            "2026-10-07_1432", "host", "feat/bench-x", "a1b2c3d4", "server-capacity", "default"
        )
        self.assertEqual(name, "2026-10-07_1432_host_feat-bench-x_a1b2c3d_server-capacity-default")


class SmokeJudgementTest(unittest.TestCase):
    def test_cold_session_ended_by_crew_event_after_fallback_switch_passes(self):
        controller = load.Controller(lambda: (200, 7), lambda session_id: None)
        try:
            controller.external_in_flight = lambda: 0
            controller.set_context("payload", 0, "cold", 1)
            controller.hold(1, 5, 5, lambda: None, max_starts=1, tick_s=0.01)
            controller.external_in_flight = None  # BENCH lines are flowing: switch modes
            end = {"session_id": 7, "checkpoint": "session_end", "status": "end", "ts": 1.0}
            controller.on_event(end)
            events = [
                {**end, "service": "crew"},
                {"session_id": 7, "checkpoint": "received", "ts": 0.1, "service": "crew"},
                {"session_id": 7, "checkpoint": "slot_acquired", "ts": 0.2, "service": "crew"},
                {
                    "session_id": 7,
                    "checkpoint": "request_received",
                    "ts": 0.0,
                    "service": "django_app",
                },
            ]
            self.assertIsNone(controller.records[0].end_status)
            rows = analyze.build_rows(controller.records, events)
        finally:
            controller.close()
        self.assertEqual(runner._smoke_failures(rows, events), [])

    def test_failed_and_missing_checkpoints_are_reported(self):
        rows = [{"status": "end"}, {"status": None}]
        events = [{"service": "crew", "checkpoint": "received"}]
        problems = runner._smoke_failures(rows, events)
        self.assertTrue(any("did not end cleanly" in problem for problem in problems))
        self.assertTrue(any("crew: missing checkpoints" in problem for problem in problems))


class WorktreeCertsTest(unittest.TestCase):
    def test_certs_are_copied_into_the_worktree(self):
        repo = Path(tempfile.mkdtemp())
        certs = repo / "src" / "nginx" / "certs"
        certs.mkdir(parents=True)
        (certs / "server.crt").write_text("cert")
        (certs / ".gitkeep").write_text("")

        def fake_run(args, **kwargs):
            Path(args[6]).mkdir(parents=True)  # `git worktree add --detach <path> <ref>`

        with mock.patch.object(stack, "run", side_effect=fake_run):
            worktree = stack.Worktree(repo, "main")
            path = worktree.__enter__()
            try:
                copied = sorted(item.name for item in (path / "src" / "nginx" / "certs").iterdir())
            finally:
                shutil.rmtree(worktree._temp_root, ignore_errors=True)
        self.assertEqual(copied, ["server.crt"])


class FakeSessionsApi:
    def __init__(self, counts=None, rows=None):
        self.counts, self.rows = list(counts or []), rows or []
        self.stopped = []

    def stop_session(self, session_id):
        self.stopped.append(session_id)

    def in_flight(self, graph_id):
        value = self.counts.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def sessions_since(self, graph_id, since_iso):
        return self.rows


def make_phase_runner(fake_api):
    case = config.load_case(write_case())
    options = runner.Options("http://x", "key", "1")
    return runner.PhaseRunner(case, case.phases[0], fake_api, None, options, {}, 0)


class FallbackApiTest(unittest.TestCase):
    def test_failing_api_returns_last_count_and_aborts_after_the_window(self):
        error = api.ApiError(503, "boom")
        phase_runner = make_phase_runner(FakeSessionsApi([4, error, error, 6]))
        now = [100.0]
        phase_runner.clock = lambda: now[0]
        sampler = mock.Mock(latest={})
        sampler.restarts_since.return_value = []
        controller = mock.Mock()
        controller.recent_error_rate.return_value = None
        check = phase_runner._abort_check(controller, sampler, {})
        self.assertEqual(phase_runner._count_in_flight(), 4)
        self.assertEqual(phase_runner._count_in_flight(), 4)  # error: last known count
        self.assertIsNone(check())  # error just started
        now[0] += runner.API_ERROR_PERSIST_S
        self.assertEqual(phase_runner._count_in_flight(), 4)
        self.assertIn("API unreachable while counting sessions", check())
        self.assertEqual(phase_runner._count_in_flight(), 6)  # recovered: error cleared
        self.assertIsNone(check())

    def test_first_failure_without_a_known_count_assumes_one_session(self):
        phase_runner = make_phase_runner(FakeSessionsApi([api.ApiError(None, "down")]))
        self.assertEqual(phase_runner._count_in_flight(), 1)

    def test_stale_api_error_does_not_abort_once_bench_control_is_active(self):
        phase_runner = make_phase_runner(FakeSessionsApi())
        phase_runner._api_error = (0.0, "old cold-session error")
        phase_runner.clock = lambda: 1000.0
        sampler = mock.Mock(latest={})
        sampler.restarts_since.return_value = []
        controller = mock.Mock(external_in_flight=None)  # switched to BENCH control
        controller.recent_error_rate.return_value = None
        self.assertIsNone(phase_runner._abort_check(controller, sampler, {})())

    def test_sessions_api_rows_set_end_times_but_not_for_failed_sends(self):
        rows = [
            {"id": 1, "status": "end", "finished_at": "2026-10-07T10:00:00Z"},
            {"id": 2, "status": "error", "finished_at": "2026-10-07T10:00:05+00:00"},
            {"id": 3, "status": "end", "finished_at": "2026-10-07T10:00:09Z"},
            {"id": 4, "status": "run", "finished_at": None},
        ]
        phase_runner = make_phase_runner(FakeSessionsApi(rows=rows))
        records = []
        for session_id, status in [
            (1, None),
            (2, None),
            (3, "timeout"),
            (4, None),
            (3, "http_error"),
        ]:
            record = load.SessionRecord("payload", 25, "ladder", 1, intended_ts=1.0)
            record.session_id, record.end_status = session_id, status
            records.append(record)
        phase_runner._apply_sessions_api(records)
        self.assertEqual((records[0].end_status, records[0].done_ts), ("end", 1791367200.0))
        self.assertEqual((records[1].end_status, records[1].done_ts), ("error", 1791367205.0))
        self.assertEqual((records[2].end_status, records[2].done_ts), ("timeout", None))
        self.assertEqual((records[3].end_status, records[3].done_ts), (None, None))
        self.assertEqual((records[4].end_status, records[4].done_ts), ("http_error", None))

    def test_interrupt_in_fallback_mode_stops_the_sessions_the_api_still_runs(self):
        rows = [
            {"id": 1, "status": "run", "finished_at": None},
            {"id": 2, "status": "end", "finished_at": "2026-10-07T10:00:00Z"},
            {"id": 3, "status": "pending", "finished_at": None},
            {"id": 9, "status": "run", "finished_at": None},  # another client's session
        ]
        fake_api = FakeSessionsApi(rows=rows)
        phase_runner = make_phase_runner(fake_api)
        records = []
        for session_id in (1, 2, 3):
            session_record = load.SessionRecord("payload", 25, "ladder", 1, intended_ts=1.0)
            session_record.session_id = session_id
            records.append(session_record)
        phase_runner._stop_unfinished(records)
        self.assertEqual(fake_api.stopped, [1, 3])
        self.assertEqual(
            [session_record.end_status for session_record in records],
            [load.INTERRUPTED, "end", load.INTERRUPTED],
        )


class FinishExtensionTest(unittest.TestCase):
    """After the hold, a level keeps its load until the sessions it measured have ended."""

    def hold_window(self, controller, target):
        start = time_module.time()
        controller.hold(target, 0.1, 10, abort_check=lambda: None, tick_s=0.02)
        return analyze.Window("payload", 5, "ladder", 1, start, start, time_module.time())

    def test_live_verdict_waits_for_the_measured_sessions_to_end(self):
        class SlowFirstStack(FakeStack):
            calls = 0

            def start(self):
                self.duration_s = 0.5 if self.calls == 0 else 0.05
                self.calls += 1
                return super().start()

        fake = SlowFirstStack()
        controller = make_controller(fake)
        phase_runner = make_phase_runner(FakeSessionsApi())
        window = self.hold_window(controller, target=2)
        self.assertIsNone(phase_runner._finish_measured(controller, window, lambda: None))
        controller.close()
        measured = [record for record in controller.records if window.measures(vars(record))]
        self.assertTrue(all(record.end_status == "end" for record in measured))
        slowest_end = max(record.done_ts for record in measured)
        self.assertGreater(slowest_end, window.end_ts)  # ended after the hold
        self.assertGreaterEqual(window.finish_end_ts, slowest_end)  # and the verdict waited
        finish = [record for record in controller.records if record.kind == load.FINISH_KIND]
        self.assertTrue(finish)  # the second slot kept running while the first one finished
        # >=: the Windows clock can give the first one the same reading as the hold's end
        self.assertTrue(all(record.intended_ts >= window.end_ts for record in finish))
        self.assertFalse(any(window.measures(vars(record)) for record in finish))
        rows = analyze.build_rows(controller.records, [], now=window.finish_end_ts)
        self.assertFalse(any(row["censored"] for row in analyze.measured(rows, window)))

    def test_measured_sessions_still_running_at_the_cap_time_out_and_fail_the_level(self):
        fake = FakeStack(duration_s=None)  # never ends
        controller = make_controller(fake)
        phase_runner = make_phase_runner(FakeSessionsApi())
        ladder = dataclasses.replace(phase_runner.case.ladder, session_timeout_s=0.3)
        phase_runner.case = dataclasses.replace(phase_runner.case, ladder=ladder)
        window = self.hold_window(controller, target=12)
        phase_runner._finish_measured(controller, window, lambda: None)
        controller.close()
        measured = [record for record in controller.records if window.measures(vars(record))]
        self.assertEqual(len(measured), 12)
        self.assertEqual({record.end_status for record in measured}, {"timeout"})
        self.assertLessEqual({record.session_id for record in measured}, set(fake.stopped))
        rows = analyze.build_rows(controller.records, [], now=window.finish_end_ts)
        # a loaded test machine delays the sender threads; the lag guard is not under test here
        no_lag_guard = AbortRules(generator_lag_p99_ms=float("inf"))
        verdict, reasons = analyze.judge(
            analyze.measured(rows, window), window, PassRules(), no_lag_guard
        )
        self.assertEqual(verdict, "fail", reasons)
        self.assertIn("error rate 100.0%", reasons[0])


def live_verdict(data, window, rules):
    """The verdict the runner takes at the end of a level, from what it knows by then."""
    now = window.verdict_ts
    records = [
        dataclasses.replace(item, done_ts=None, end_status=None) if item.done_ts > now else item
        for item in data.records
        if item.intended_ts <= now
    ]
    events = [event for event in data.events if float(event["ts"]) <= now]
    rows = analyze.build_rows(records, events, now=now)
    return analyze.judge(analyze.measured(rows, window), window, rules, data.case.abort)[0]


class FixtureReplayTest(unittest.TestCase):
    def test_live_and_final_verdicts_agree(self):
        # 12 s payload and 24 s complex sessions, 180 s hold: the case that stalled the ladder
        data = fixtures.build_run("replay", "server.toml", (10, 20, 40), 40, 1, "ladder")
        rules = {phase.name: phase.pass_rules for phase in data.case.phases}
        final_rows = analyze.build_rows(data.records, data.events)
        verdicts = {}
        for window in data.windows:
            final, _ = analyze.judge(
                analyze.measured(final_rows, window), window, rules[window.phase], data.case.abort
            )
            live = live_verdict(data, window, rules[window.phase])
            verdicts[(window.phase, window.level)] = (live, final)
        expected = {}
        for phase in ("payload", "complex"):
            expected |= {(phase, 10): ("pass", "pass"), (phase, 20): ("pass", "pass")}
            expected[(phase, 40)] = ("fail", "fail")
        self.assertEqual(verdicts, expected)


class RunVariantSaveTest(unittest.TestCase):
    def test_second_interrupt_still_writes_the_run_folder_before_the_stack_is_reapplied(self):
        repo = Path(tempfile.mkdtemp())
        (repo / "src").mkdir()
        env_path = repo / "src" / ".env"
        env_path.write_text("A=1\n", encoding="utf-8")
        results = repo / "results"
        case = config.load_case(write_case())
        options = runner.Options(
            "http://x", "key", "1", build=False, smoke=False, results_dir=results, repo=repo
        )
        folders_when_reapplied = []

        def compose_up(build):
            if env_path.read_text(encoding="utf-8") == "A=1\n":  # the original .env is back
                folders_when_reapplied.append(
                    sorted(path.name for path in results.iterdir()) if results.exists() else []
                )

        compose = mock.Mock()
        compose.up.side_effect = compose_up
        compose.images.side_effect = KeyboardInterrupt  # the second Ctrl+C
        phase_runner = mock.Mock(fallback=False, records=[], windows=[], segments=[], events=[])
        phase_runner.timeline, phase_runner.container_timeline = [], []
        phase_runner.run_capacity.side_effect = KeyboardInterrupt  # the first Ctrl+C
        host_facts = {
            "docker_ok": True,
            "load1": None,
            "vcpu": 4,
            "mem_avail_pct": None,
            "backup_exists": False,
        }
        git = {"ref": "dev", "sha": "abc1234", "dirty": False}
        with (
            mock.patch.object(runner, "_host_facts", return_value=host_facts),
            mock.patch.object(runner, "_resolve_graphs", return_value={}),
            mock.patch.object(runner, "_stack_facts", return_value={}),
            mock.patch.object(runner, "evaluate_stack", return_value=[]),
            mock.patch.object(runner, "PhaseRunner", return_value=phase_runner),
            mock.patch.object(runner.stack, "Compose", return_value=compose),
            mock.patch.object(runner.stack, "detect_project", return_value="src"),
            mock.patch.object(runner.stack, "git_info", return_value=git),
            mock.patch.object(runner.stack, "host_info", return_value={"hostname": "host"}),
            self.assertRaises(KeyboardInterrupt),
        ):
            runner.run_variant(case, case.variants[0], options)
        self.assertEqual(env_path.read_text(encoding="utf-8"), "A=1\n")
        (run_dir,) = results.iterdir()
        self.assertEqual(folders_when_reapplied, [[run_dir.name]])
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        self.assertIn("interrupted", meta["labels"])


class WorktreeCleanupTest(unittest.TestCase):
    def test_certs_copy_failure_removes_the_worktree_and_temp_root(self):
        repo = Path(tempfile.mkdtemp())
        certs = repo / "src" / "nginx" / "certs"
        certs.mkdir(parents=True)
        (certs / "server.crt").write_text("cert")
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            if "add" in args:
                Path(args[6]).mkdir(parents=True)
            return mock.Mock(returncode=0)

        worktree = stack.Worktree(repo, "main")
        with (
            mock.patch.object(stack, "run", side_effect=fake_run),
            mock.patch.object(stack.shutil, "copy2", side_effect=OSError("disk full")),
            self.assertRaises(OSError),
        ):
            worktree.__enter__()
        self.assertTrue(any("remove" in call for call in calls))
        self.assertTrue(any("prune" in call for call in calls))
        self.assertFalse(worktree._temp_root.exists())
        shutil.rmtree(repo, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
