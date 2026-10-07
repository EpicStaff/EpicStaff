"""Unit tests for benchmark/ (standard library only).

Run from the repo root:  python -m unittest discover -s benchmark -p "test_*.py"
"""

import itertools
import json
import tempfile
import textwrap
import threading
import time as time_module
import unittest
from pathlib import Path
from unittest import mock

import analyze
import api
import compare
import config
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
        self.assertIsNone(
            controller.hold(
                target=5, duration_s=0.6, timeout_s=10, abort_check=lambda: None, tick_s=0.05
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

    def test_percentiles(self):
        self.assertIsNone(analyze.percentile([], 0.5))
        self.assertEqual(analyze.percentile([1, 2, 3, 4], 0.5), 2.5)
        self.assertEqual(analyze.stats([2, 4])["mean"], 3)


class JudgeTest(unittest.TestCase):
    def rows(self, count, e2e, status="end", lag=1.0):
        return [
            {
                "phase": "payload",
                "segment": 1,
                "level": 10,
                "kind": "ladder",
                "intended_ts": 20,
                "e2e_s": e2e,
                "queue_wait_s": 0.5,
                "status": status,
                "censored": False,
                "gen_lag_ms": lag,
            }
            for _ in range(count)
        ]

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


@unittest.skipUnless(Path(__file__).with_name("fixtures.py").exists(), "fixtures arrive in Task 11")
class AnalyzeFolderTest(unittest.TestCase):
    def test_writes_every_file_with_the_schema_columns(self):
        import fixtures

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
            "2026-10-07_1432", "host", "feat/EST-4430-x", "a1b2c3d4", "server-capacity", "default"
        )
        self.assertEqual(
            name, "2026-10-07_1432_host_feat-EST-4430-x_a1b2c3d_server-capacity-default"
        )


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
                import shutil

                shutil.rmtree(worktree._temp_root, ignore_errors=True)
        self.assertEqual(copied, ["server.crt"])


if __name__ == "__main__":
    unittest.main()
