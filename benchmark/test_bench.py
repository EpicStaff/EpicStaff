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

import api
import config
import load
import sample
import stack

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
            controller.hold(target=5, duration_s=0.6, timeout_s=10, abort_check=lambda: None)
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
        controller.drain(timeout_s=2)
        self.assertEqual(controller.in_flight_count(), 0)
        self.assertTrue(all(record.done for record in controller.records))
        controller.close()

    def test_http_errors_free_their_slot_and_count_as_failed(self):
        fake = FakeStack(duration_s=0.02, fail_every=2)
        controller = make_controller(fake)
        controller.hold(target=4, duration_s=0.3, timeout_s=10, abort_check=lambda: None)
        controller.drain(timeout_s=2)
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


if __name__ == "__main__":
    unittest.main()
