"""Unit tests for benchmark/ (standard library only).

Run from the repo root:  python -m unittest discover -s benchmark -p "test_*.py"
"""

import contextlib
import csv
import dataclasses
import email.parser
import email.policy
import io
import itertools
import json
import re
import shutil
import tempfile
import textwrap
import threading
import time as time_module
import tomllib
import types
import unittest
from collections import defaultdict
from pathlib import Path
from unittest import mock

import analyze
import api
import bench
import compare
import config
import fixtures
import flows
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

    def test_phase_with_a_flow_export_may_omit_its_graph_id(self):
        export = Path(tempfile.mkdtemp()) / "payload.json"
        export.write_text("{}", encoding="utf-8")
        text = CASE_TOML.replace("graph_id = 17\n", "")
        case = config.load_case(write_case(text), flow_exports={"payload": export})
        self.assertIsNone(case.phases[0].graph_id)
        self.assertEqual(case.case_hash, config.load_case(write_case()).case_hash)

    def test_phase_whose_flow_export_is_missing_names_the_export(self):
        export = Path(tempfile.mkdtemp()) / "payload.json"
        text = CASE_TOML.replace("graph_id = 17\n", "")
        with self.assertRaisesRegex(config.CaseError, "payload.json.*flow import"):
            config.load_case(write_case(text), flow_exports={"payload": export})

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


class ComposeUpTest(unittest.TestCase):
    def run_up(self, build: bool) -> list[list[str]]:
        compose = stack.Compose(Path("src"), Path("src/.env"), "src")
        commands = []
        with (
            mock.patch.object(stack, "run", side_effect=lambda args, **_: commands.append(args)),
            mock.patch.object(stack.Compose, "wait_healthy") as wait_healthy,
        ):
            compose.up(build=build)
        wait_healthy.assert_called_once()
        return [command[command.index("--env-file") + 2 :] for command in commands]

    def test_up_restarts_nginx_so_it_resolves_recreated_containers_again(self):
        self.assertEqual(self.run_up(build=False), [["up", "-d"], ["restart", stack.PROXY_SERVICE]])

    def test_override_file_next_to_env_is_loaded_when_present(self):
        with tempfile.TemporaryDirectory() as folder:
            env_file = Path(folder) / ".env"
            compose = stack.Compose(Path("worktree/src"), env_file, "src")

            def files() -> list[str]:
                return [arg for flag, arg in itertools.pairwise(compose.cmd()) if flag == "-f"]

            self.assertEqual(files(), [str(Path("worktree/src/docker-compose.yaml"))])
            (Path(folder) / stack.OVERRIDE_FILE).write_text("services: {}\n", encoding="utf-8")
            self.assertEqual(
                files(),
                [
                    str(Path("worktree/src/docker-compose.yaml")),
                    str(Path(folder) / stack.OVERRIDE_FILE),
                ],
            )

    def test_build_is_passed_before_the_nginx_restart(self):
        self.assertEqual(
            self.run_up(build=True), [["up", "-d", "--build"], ["restart", stack.PROXY_SERVICE]]
        )


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


class ChildEnvTest(unittest.TestCase):
    """compose prefers a shell variable over --env-file, so a child must not inherit names that
    src/.env defines: an org key exported as DJANGO_API_KEY once became Django's system key."""

    SHELL = {
        "DJANGO_API_KEY": "org-key",
        "CREW_LOG_LEVEL": "INFO",
        "BENCH_API_KEY": "org-key",
        "BENCH_ORG_ID": "1",
        "BENCH_API": "http://server",
        "BENCH_RESULTS_REPO": "/srv/results",
        "COMMENTED": "keep",
        "UNRELATED": "keep",
        "DOCKER_HOST": "unix:///var/run/docker.sock",
    }
    STRIPPED = (
        "DJANGO_API_KEY",
        "CREW_LOG_LEVEL",
        "BENCH_API_KEY",
        "BENCH_ORG_ID",
        "BENCH_API",
        "BENCH_RESULTS_REPO",
    )

    def setUp(self):
        self.env_file = Path(tempfile.mkdtemp()) / ".env"
        self.env_file.write_text(
            "DJANGO_API_KEY=system-key\nCREW_LOG_LEVEL=BENCH\n# COMMENTED=1\n", encoding="utf-8"
        )
        patches = [
            mock.patch.dict(stack.os.environ, self.SHELL),
            mock.patch.object(stack, "ENV_FILE", self.env_file),
            mock.patch.object(
                stack.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="[]")
            ),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def child_env(self) -> dict:
        return stack.subprocess.run.call_args.kwargs["env"]

    def assert_stripped(self, env: dict) -> None:
        self.assertFalse(set(self.STRIPPED) & set(env), sorted(set(self.STRIPPED) & set(env)))
        for name in ("COMMENTED", "UNRELATED", "DOCKER_HOST"):
            self.assertEqual(env[name], self.SHELL[name])
        if "PATH" in stack.os.environ:
            self.assertEqual(env["PATH"], stack.os.environ["PATH"])

    def test_compose_child_env_lacks_the_env_file_names_and_the_bench_names(self):
        compose = stack.Compose(self.env_file.parent, self.env_file, "src")
        compose.ps()
        self.assert_stripped(self.child_env())

    def test_compose_uses_its_own_env_file(self):
        other_env_file = self.env_file.with_name("other.env")
        other_env_file.write_text("UNRELATED=1\n", encoding="utf-8")
        stack.Compose(self.env_file.parent, other_env_file, "src").ps()
        env = self.child_env()
        self.assertNotIn("UNRELATED", env)
        self.assertEqual(env["DJANGO_API_KEY"], "org-key")
        self.assertFalse({"BENCH_API_KEY", "BENCH_ORG_ID"} & set(env))

    def test_compose_reads_the_env_file_names_when_the_command_runs(self):
        compose = stack.Compose(self.env_file.parent, self.env_file, "src")
        compose.ps()
        with (
            stack.EnvOverride(self.env_file, {"AGENT_LOG_LEVEL": "BENCH"}),
            mock.patch.dict(stack.os.environ, {"AGENT_LOG_LEVEL": "INFO"}),
        ):
            compose.ps()
        self.assertNotIn("AGENT_LOG_LEVEL", self.child_env())

    def test_plain_docker_commands_use_the_default_env_file(self):
        stack.inspect(["crew"])
        self.assert_stripped(self.child_env())

    def test_an_env_from_the_caller_is_filtered_too(self):
        stack.run(["docker", "exec"], env={"REDISCLI_AUTH": "pw", "DJANGO_API_KEY": "org-key"})
        self.assertEqual(self.child_env(), {"REDISCLI_AUTH": "pw"})

    def test_missing_env_file_strips_only_the_bench_names(self):
        self.env_file.unlink()
        stack.inspect(["crew"])
        env = self.child_env()
        self.assertEqual(env["DJANGO_API_KEY"], "org-key")
        self.assertFalse({"BENCH_API_KEY", "BENCH_ORG_ID"} & set(env))

    def test_log_follower_child_env_is_filtered(self):
        with mock.patch.object(
            stack.subprocess, "Popen", return_value=mock.Mock(stdout=[])
        ) as popen:
            follower = stack.LogFollower("crew", 0)
            follower._thread.join(timeout=5)
        self.assert_stripped(popen.call_args.kwargs["env"])


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

    def test_drain_stops_a_session_once_its_own_age_passes_the_timeout(self):
        fake = FakeStack(duration_s=None)  # never ends by itself
        controller = make_controller(fake)
        controller.hold(target=2, duration_s=0.1, timeout_s=10, abort_check=lambda: None)
        while controller.in_flight_count() < 2 or controller._pending_http:
            time_module.sleep(0.01)  # both start requests answered
        stuck, ending = controller.records
        stuck.sent_ts -= 60  # sent long before the drain: past its 30 s timeout already
        threading.Timer(
            0.3,
            lambda: controller.on_event(
                {"session_id": ending.session_id, "checkpoint": "session_end", "status": "end"}
            ),
        ).start()
        started = time_module.time()
        self.assertEqual(controller.drain(timeout_s=30), 1)
        controller.close()
        self.assertLess(time_module.time() - started, 10)  # did not wait for the drain deadline
        self.assertEqual((stuck.end_status, ending.end_status), ("timeout", "end"))
        self.assertLess(stuck.done_ts - started, 1)  # stopped at once, not after 30 s
        self.assertEqual(fake.stopped, [stuck.session_id])

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

    def test_runner_ended_session_keeps_the_runner_end_time(self):
        # crew answered the runner's stop only at the next stack restart, 15 minutes later
        late = crew_events(5, received=11.0, slot=12.0, end=1810.0, status="stop")
        events, _ = analyze.index_events(late)
        row = analyze.session_row(
            record(5, intended=10, sent=10, done=910.0, status="timeout"), events[5]
        )
        self.assertEqual((row["status"], row["end_ts"], row["e2e_s"]), ("timeout", 910.0, 900.0))
        self.assertTrue(analyze.is_failed(row))

    def test_sandbox_wait_is_paired_by_execution_id_and_leaves_crew_overhead(self):
        events = [
            *crew_events(6, received=11.0, slot=12.0, end=20.0),
            {
                "service": "crew",
                "checkpoint": "sandbox_dispatched",
                "session_id": 6,
                "execution_id": "a",
                "ts": 14.0,
            },
            {
                "service": "sandbox",
                "checkpoint": "exec_start",
                "session_id": 6,
                "execution_id": "a",
                "ts": 16.5,
            },
            {
                "service": "sandbox",
                "checkpoint": "exec_end",
                "session_id": 6,
                "execution_id": "a",
                "ts": 17.5,
            },
            # the agent's tool call: also waits for the sandbox
            {
                "service": "agent",
                "checkpoint": "sandbox_dispatched",
                "session_id": 6,
                "execution_id": "b",
                "ts": 18.0,
            },
            {
                "service": "sandbox",
                "checkpoint": "exec_start",
                "session_id": 6,
                "execution_id": "b",
                "ts": 18.5,
            },
            {
                "service": "sandbox",
                "checkpoint": "exec_end",
                "session_id": 6,
                "execution_id": "b",
                "ts": 19.0,
            },
            # lost: dispatched, never started; counts nowhere in sandbox_wait_s
            {
                "service": "crew",
                "checkpoint": "sandbox_dispatched",
                "session_id": 6,
                "execution_id": "c",
                "ts": 19.5,
            },
        ]
        by_session, _ = analyze.index_events(events)
        row = analyze.session_row(record(6, intended=10, sent=10, done=20.0), by_session[6])
        self.assertAlmostEqual(row["sandbox_wait_s"], 3.0)  # 2.5 + 0.5
        self.assertAlmostEqual(row["python_s"], 1.5)
        self.assertAlmostEqual(row["llm_s"], 1.0)
        # run 8 s - LLM 1 s - Python 1.5 s - sandbox wait 3 s
        self.assertAlmostEqual(row["other_s"], 2.5)

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
            "failure": None,
            "saturated_processes": [],
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
            "inflight_stages.csv",
            "findings.csv",
        }
        self.assertEqual({path.name for path in run_dir.iterdir()}, expected)
        for file_name, columns in (
            ("steps.csv", analyze.STEP_COLUMNS),
            ("containers.csv", analyze.CONTAINER_COLUMNS),
            ("timeline.csv", analyze.TIMELINE_COLUMNS),
            ("inflight_stages.csv", analyze.INFLIGHT_STAGE_COLUMNS),
            ("findings.csv", analyze.FINDING_COLUMNS),
        ):
            with open(run_dir / file_name, encoding="utf-8") as csv_file:
                self.assertEqual(csv_file.readline().strip().split(","), columns)
        with open(run_dir / "steps.csv", encoding="utf-8") as steps_file:
            first_level = next(csv.DictReader(steps_file))
        # five sandbox executions per fixture session, each waiting 40 ms to start
        self.assertAlmostEqual(float(first_level["sandbox_wait_s_mean"]), 0.2, places=3)
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
    return runner.judge_live(records, events, window, rules, data.case.abort, now)[0]


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
        (repo / "src" / "docker-compose.yaml").write_text("services: {}\n", encoding="utf-8")
        results = repo / "results"
        case = config.load_case(write_case())
        options = runner.Options(
            "http://x",
            "key",
            "3",
            org_source="default",
            build=False,
            smoke=False,
            results_dir=results,
            repo=repo,
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
        self.assertEqual((meta["org_id"], meta["org_source"]), ("3", "default"))


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


class EnvPreflightTest(unittest.TestCase):
    COMPOSE = textwrap.dedent(
        """
        services:
          crew:
            image: "crew:${IMAGE_TAG:?}"
            environment:
              SET_IN_ENV: ${SET_IN_ENV:?}
              ONLY_IN_CASE: ${ONLY_IN_CASE:?set it in src/.env}
              MISSING_ONE: ${MISSING_ONE:?}
              EMPTY_ONE: ${EMPTY_ONE:?}
              FROM_SHELL: ${FROM_SHELL:?}
              OPTIONAL: ${OPTIONAL:-x}
              LITERAL: $${ESCAPED_LITERAL:?}
        """
    )

    def facts(self, env_text: str, overrides: dict, environ: dict | None = None) -> dict:
        folder = Path(tempfile.mkdtemp())
        compose_file = folder / "docker-compose.yaml"
        compose_file.write_text(self.COMPOSE, encoding="utf-8")
        env_path = folder / ".env"
        env_path.write_text(env_text, encoding="utf-8")
        return runner._env_facts(compose_file, env_path, overrides, environ or {})

    def test_required_variables_missing_or_empty_are_an_error_naming_the_fix(self):
        facts = self.facts(
            "IMAGE_TAG=latest\nexport SET_IN_ENV=1\nEMPTY_ONE=\n# MISSING_ONE=x\n",
            {"ONLY_IN_CASE": "1"},
            {"FROM_SHELL": "1"},
        )
        self.assertEqual(facts["missing"], ["EMPTY_ONE", "MISSING_ONE"])
        ((level, message),) = runner.evaluate_env(facts)
        self.assertEqual(level, "error")
        self.assertIn("EMPTY_ONE, MISSING_ONE", message)
        self.assertIn("python scripts/envtool.py --update", message)
        self.assertIn("make env-update", message)

    def test_a_variable_set_only_by_the_case_counts_as_set(self):
        env_text = "IMAGE_TAG=latest\nSET_IN_ENV=1\nMISSING_ONE=1\nEMPTY_ONE=1\nFROM_SHELL=1\n"
        self.assertEqual(self.facts(env_text, {})["missing"], ["ONLY_IN_CASE"])
        self.assertEqual(self.facts(env_text, {"ONLY_IN_CASE": "1"})["missing"], [])

    def test_dev_profile_settings_are_a_warning_not_an_error(self):
        env_text = (
            "DJANGO_DEBUG=True\nCREW_LOG_LEVEL=DEBUG\nWEBHOOK_LOG_LEVEL=trace\n"
            "AGENT_LOG_LEVEL=INFO\nKNOWLEDGE_DEBUG=true\n"
        )
        facts = self.facts(env_text, {"ONLY_IN_CASE": "1", "CREW_LOG_LEVEL": "BENCH"})
        # the case raises crew to BENCH for the run, so only the settings still in effect count
        self.assertEqual(facts["debug"], ["DJANGO_DEBUG=True", "WEBHOOK_LOG_LEVEL=trace"])
        findings = runner.evaluate_env({**facts, "missing": []})
        self.assertEqual([level for level, _ in findings], ["warn"])
        self.assertIn("debug overhead", findings[0][1])
        self.assertIn("without --dev", findings[0][1])

    def test_production_settings_give_no_finding(self):
        env_text = "DJANGO_DEBUG=false\nCREW_LOG_LEVEL=INFO\nDJANGO_LOG_LEVEL=BENCH\n"
        facts = self.facts(env_text, {})
        self.assertEqual(facts["debug"], [])
        self.assertEqual(runner.evaluate_env({**facts, "missing": []}), [])

    def test_every_spelling_django_reads_as_true_counts_as_debug(self):
        for value in ("1", "True", "yes", "on", "y", "OK"):
            facts = self.facts(f"DJANGO_DEBUG={value}\n", {})
            self.assertEqual(facts["debug"], [f"DJANGO_DEBUG={value}"])

    def test_missing_env_file_is_an_error(self):
        folder = Path(tempfile.mkdtemp())
        compose_file = folder / "docker-compose.yaml"
        compose_file.write_text(self.COMPOSE, encoding="utf-8")
        facts = runner._env_facts(compose_file, folder / ".env", {}, {})
        ((level, message),) = runner.evaluate_env(facts)
        self.assertEqual(level, "error")
        self.assertIn("python scripts/envtool.py", message)


class MultipartTest(unittest.TestCase):
    def test_body_parses_back_into_the_fields_and_the_file(self):
        path = Path(tempfile.mkdtemp()) / "payload.json"
        content = b'{"main_entity": "Flow", "text": "\\r\\n--not-a-boundary"}'
        path.write_bytes(content)
        body, content_type = api.encode_multipart({"preserve_uuids": "true"}, "file", path)
        message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
            f"Content-Type: {content_type}\r\n\r\n".encode() + body
        )
        parts = {
            part.get_param("name", header="content-disposition"): part
            for part in message.iter_parts()
        }
        self.assertEqual(parts["preserve_uuids"].get_content(), "true")
        self.assertEqual(parts["file"].get_filename(), "payload.json")
        self.assertEqual(parts["file"].get_payload(decode=True), content)

    def test_upload_sends_the_auth_headers_and_the_multipart_type(self):
        path = Path(tempfile.mkdtemp()) / "payload.json"
        path.write_text("{}", encoding="utf-8")
        sent = {}

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

            def read(self):
                return b'{"ok": true}'

        def fake_urlopen(request, timeout):
            sent["request"] = request
            return Response()

        client = api.Api("http://host/", "secret-key", 3)
        with mock.patch.object(api.urllib.request, "urlopen", side_effect=fake_urlopen):
            status, payload = client.upload("/api/graphs/import/", path, {"a": "1"})
        request = sent["request"]
        self.assertEqual((status, payload), (200, {"ok": True}))
        self.assertEqual(request.full_url, "http://host/api/graphs/import/")
        self.assertEqual(request.get_header("X-api-key"), "secret-key")
        self.assertEqual(request.get_header("X-organization-id"), "3")
        self.assertTrue(request.get_header("Content-type").startswith("multipart/form-data"))


class ApiForbiddenTest(unittest.TestCase):
    def send(self, default_org: bool) -> str:
        forbidden = api.urllib.error.HTTPError(
            "http://host/api/graphs/1/",
            403,
            "Forbidden",
            {},
            io.BytesIO(b'{"detail": "You are not a member of the specified organization."}'),
        )
        client = api.Api("http://host", "key", "3", default_org=default_org)
        with (
            mock.patch.object(api.urllib.request, "urlopen", side_effect=forbidden),
            self.assertRaises(api.ApiError) as raised,
        ):
            client.get_graph(1)
        self.assertEqual(raised.exception.status, 403)
        return str(raised.exception)

    def test_403_with_the_default_organization_says_to_set_bench_org_id(self):
        message = self.send(default_org=True)
        self.assertIn(
            "the API key's owner is not a member of the default organization 3; "
            "set BENCH_ORG_ID to your organization",
            message,
        )
        self.assertIn("not a member of the specified organization", message)

    def test_403_with_an_explicit_organization_keeps_the_server_message(self):
        self.assertEqual(
            self.send(default_org=False),
            'HTTP 403: {"detail": "You are not a member of the specified organization."}',
        )


class FakeFlowApi:
    """The API calls of flows.py: the import upload and the light graph read."""

    def __init__(
        self,
        summary=None,
        created_at="2026-01-01T10:00:00.100000Z",
        error=None,
        org_id="1",
        read_error=None,
    ):
        self.summary, self.created_at, self.error = summary, created_at, error
        self.base_url, self.org_id, self.read_error = "http://host", org_id, read_error
        self.graphs: dict[int, dict] = {}
        self.uploads = []

    def upload(self, path, file_path, fields):
        self.uploads.append((path, file_path, fields))
        if self.error:
            raise self.error
        for section in ("created", "reused"):
            for item in (self.summary or {}).get("Flow", {}).get(section, {}).get("items", []):
                self.graphs.setdefault(
                    item["id"],
                    {
                        "name": item.get("name"),
                        "created_at": self.created_at,
                        "updated_at": "2026-01-01T10:00:00.400000Z",
                    },
                )
        return 200, self.summary

    def request(self, method, path, body=None, query=None):
        if self.read_error:
            raise self.read_error
        graph_id = int(path.rstrip("/").rsplit("/", 1)[1])
        if graph_id not in self.graphs:
            raise api.ApiError(404, '{"detail": "Not found."}')
        return 200, self.graphs[graph_id]


def flow_summary(created=(), reused=()):
    return {
        "Label": {"total": 1, "created": {"count": 1, "items": [{"id": 3, "name": "benchmark"}]}},
        "Flow": {
            "total": len(created) + len(reused),
            "created": {"count": len(created), "items": list(created)},
            "reused": {"count": len(reused), "items": list(reused)},
        },
    }


class FlowImportTest(unittest.TestCase):
    def setUp(self):
        folder = Path(tempfile.mkdtemp())
        self.export = folder / "payload.json"
        self.export.write_text('{"main_entity": "Flow"}', encoding="utf-8")
        self.cache = folder / ".flow-cache.json"

    def import_flow(self, fake, path=None):
        return flows.import_flow(fake, path or self.export, self.cache)

    def test_new_flow_is_created_with_uuid_preserving_replace_settings(self):
        fake = FakeFlowApi(flow_summary(created=[{"id": 41, "name": "payload"}]))
        self.assertEqual(self.import_flow(fake), flows.ImportedFlow(41, "payload", "created"))
        ((path, file_path, fields),) = fake.uploads
        self.assertEqual((path, file_path), ("/api/graphs/import/", self.export))
        self.assertEqual(
            fields, {"preserve_uuids": "true", "replace_existing": "true", "import_labels": "true"}
        )

    def test_replaced_flow_keeps_its_id_and_is_reported_updated(self):
        # a replace keeps the row, so its created_at is older than the import
        fake = FakeFlowApi(
            flow_summary(created=[{"id": 41, "name": "payload"}]),
            created_at="2025-12-31T09:00:00Z",
        )
        self.assertEqual(self.import_flow(fake), flows.ImportedFlow(41, "payload", "updated"))

    def test_reused_flow_is_reported_updated(self):
        fake = FakeFlowApi(flow_summary(reused=[{"id": 9, "name": "payload"}]))
        self.assertEqual(self.import_flow(fake), flows.ImportedFlow(9, "payload", "updated"))

    def test_missing_export_explains_how_to_create_it(self):
        with self.assertRaises(flows.FlowImportError) as raised:
            self.import_flow(FakeFlowApi(), self.export.with_name("absent.json"))
        message = str(raised.exception)
        self.assertIn("absent.json not found", message)
        self.assertIn("Python nodes only, no LLM", message)
        self.assertIn("`benchmark` label", message)

    def test_http_error_reports_status_and_body(self):
        fake = FakeFlowApi(error=api.ApiError(403, '{"detail": "Missing CREATE permission"}'))
        with self.assertRaisesRegex(flows.FlowImportError, "HTTP 403: .*Missing CREATE"):
            self.import_flow(fake)

    def test_answer_without_exactly_one_flow_is_an_error(self):
        two = flow_summary(created=[{"id": 1, "name": "a"}, {"id": 2, "name": "b"}])
        for summary in (two, {"Label": {}}):
            with self.assertRaisesRegex(flows.FlowImportError, "exactly one flow"):
                self.import_flow(FakeFlowApi(summary))

    def test_summary_item_without_a_name_is_a_clear_error(self):
        # the import summary's shape for an entity it could not read back
        fake = FakeFlowApi(flow_summary(created=[{"id": 41, "error": "Not found"}]))
        with self.assertRaisesRegex(flows.FlowImportError, "unexpected answer.*'name'"):
            self.import_flow(fake)

    def test_graph_without_timestamps_is_a_clear_error(self):
        fake = FakeFlowApi(flow_summary(created=[{"id": 41, "name": "payload"}]))
        fake.graphs[41] = {"name": "payload"}
        with self.assertRaisesRegex(flows.FlowImportError, "unexpected answer.*'updated_at'"):
            self.import_flow(fake)


class FlowCacheTest(unittest.TestCase):
    def setUp(self):
        folder = Path(tempfile.mkdtemp())
        self.export = folder / "payload.json"
        self.export.write_text('{"main_entity": "Flow", "version": 1}', encoding="utf-8")
        self.cache = folder / ".flow-cache.json"
        self.fake = FakeFlowApi(flow_summary(created=[{"id": 41, "name": "payload"}]))

    def ensure(self, fake=None):
        return flows.ensure_flow(fake or self.fake, self.export, self.cache)

    def test_second_resolve_with_an_unchanged_export_does_not_import_again(self):
        first, second = self.ensure(), self.ensure()
        self.assertEqual(len(self.fake.uploads), 1)
        self.assertEqual(first, flows.ImportedFlow(41, "payload", "created"))
        self.assertEqual(second, flows.ImportedFlow(41, "payload", "existing"))

    def test_changed_export_is_imported_again(self):
        self.ensure()
        self.export.write_text('{"main_entity": "Flow", "version": 2}', encoding="utf-8")
        self.ensure()
        self.ensure()
        self.assertEqual(len(self.fake.uploads), 2)

    def test_flow_deleted_on_the_server_is_imported_again(self):
        self.ensure()
        self.fake.graphs.clear()
        self.assertEqual(self.ensure().status, "created")
        self.assertEqual(len(self.fake.uploads), 2)

    def test_explicit_import_always_imports_and_refreshes_the_cache(self):
        self.ensure()
        flows.import_flow(self.fake, self.export, self.cache)
        self.assertEqual(len(self.fake.uploads), 2)
        self.ensure()
        self.assertEqual(len(self.fake.uploads), 2)

    def test_cache_is_per_server_organization(self):
        self.ensure()
        other_org = FakeFlowApi(flow_summary(created=[{"id": 7, "name": "payload"}]), org_id="2")
        self.assertEqual(self.ensure(other_org).id, 7)
        self.assertEqual(len(other_org.uploads), 1)
        self.assertEqual(self.ensure().status, "existing")

    def test_unreadable_cache_is_ignored(self):
        self.cache.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.ensure().status, "created")
        self.assertEqual(self.ensure().status, "existing")

    def test_verification_failure_other_than_not_found_is_an_error_not_an_import(self):
        self.ensure()
        self.fake.read_error = api.ApiError(500, "boom")
        with self.assertRaisesRegex(flows.FlowImportError, "HTTP 500: boom"):
            self.ensure()
        self.assertEqual(len(self.fake.uploads), 1)

    def test_describe(self):
        flow = flows.ImportedFlow(41, "payload", "existing")
        self.assertEqual(
            flows.describe("payload", flow), 'payload flow: id 41 (existing) "payload"'
        )


class ImportedPhaseTest(unittest.TestCase):
    """Phases whose graph id comes from a flow export are resolved after the host and .env
    checks, so a down stack or a broken .env is reported before anything is written."""

    DEV_CASE = 'name = "dev"\nkind = "dev"\n[[phase]]\nname = "payload"\n'
    HOST_OK = {
        "docker_ok": True,
        "load1": None,
        "vcpu": 4,
        "mem_avail_pct": None,
        "backup_exists": False,
    }

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        (self.repo / "src").mkdir()
        (self.repo / "src" / ".env").write_text("NEEDED=1\n", encoding="utf-8")
        (self.repo / "src" / "docker-compose.yaml").write_text(
            "services:\n  crew:\n    environment:\n      NEEDED: ${NEEDED:?}\n", encoding="utf-8"
        )
        export = self.repo / "payload.json"
        export.write_text("{}", encoding="utf-8")
        self.exports = {"payload": export}
        self.case = config.load_case(write_case(self.DEV_CASE), flow_exports=self.exports)
        self.options = runner.Options(
            "http://x",
            "key",
            "1",
            build=False,
            smoke=False,
            repo=self.repo,
            results_dir=self.repo / "results",
            flow_exports=self.exports,
        )
        self.calls = []
        patch = mock.patch.object(
            runner.flows,
            "ensure_flow",
            side_effect=lambda *args: (
                self.calls.append("import") or flows.ImportedFlow(42, "payload", "existing")
            ),
        )
        patch.start()
        self.addCleanup(patch.stop)

    def test_case_keeps_the_graph_id_open(self):
        self.assertIsNone(self.case.phases[0].graph_id)

    def test_import_fills_the_graph_id_and_prints_one_line(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            case = runner._import_flows(self.case, mock.Mock(), self.exports)
        self.assertEqual(case.phases[0].graph_id, 42)
        self.assertEqual(output.getvalue(), 'payload flow: id 42 (existing) "payload"\n')

    def preflight(self, host_facts):
        output = io.StringIO()
        with (
            mock.patch.object(runner, "_host_facts", return_value=host_facts),
            mock.patch.object(runner, "_resolve_graphs", return_value={}) as resolve,
            mock.patch.object(runner, "_stack_facts", return_value={}),
            mock.patch.object(runner, "evaluate_stack", return_value=[]),
            mock.patch.object(runner.stack, "detect_project", return_value="src"),
            contextlib.redirect_stdout(output),
        ):
            code = runner.preflight_only(self.case, self.options)
        return code, output.getvalue(), resolve

    def test_preflight_reports_a_host_error_without_importing(self):
        code, output, _ = self.preflight({**self.HOST_OK, "docker_ok": False})
        self.assertEqual(code, 2)
        self.assertIn("docker is not reachable", output)
        self.assertEqual(self.calls, [])

    def test_preflight_reports_an_env_error_without_importing(self):
        (self.repo / "src" / ".env").write_text("OTHER=1\n", encoding="utf-8")
        code, output, _ = self.preflight(self.HOST_OK)
        self.assertEqual(code, 2)
        self.assertIn("does not set NEEDED", output)
        self.assertEqual(self.calls, [])

    def test_preflight_imports_after_the_checks_and_checks_the_imported_graph(self):
        code, _, resolve = self.preflight(self.HOST_OK)
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, ["import"])
        self.assertEqual(resolve.call_args.args[1].phases[0].graph_id, 42)

    def test_preflight_reports_a_missing_graph_id_and_checks_the_other_phases(self):
        self.case = config.load_case(
            write_case(self.DEV_CASE + '[[phase]]\nname = "complex"\n'),
            flow_exports=self.exports,
            require_graph_ids=False,
        )
        code, output, resolve = self.preflight(self.HOST_OK)
        self.assertEqual(code, 2)
        self.assertIn("✗ phase complex: graph id: set with --graph complex=<id>", output)
        self.assertNotIn("preflight ok", output)
        self.assertEqual(self.calls, ["import"])  # the payload phase is still imported ...
        checked = resolve.call_args.args[1].phases  # ... and its graph checked
        self.assertEqual([(phase.name, phase.graph_id) for phase in checked], [("payload", 42)])

    def test_run_imports_once_the_stack_is_up_and_before_resolving_graphs(self):
        compose = mock.Mock()
        compose.up.side_effect = lambda build: self.calls.append("up")
        compose.images.return_value = {}
        phase_runner = mock.Mock(fallback=False, records=[], windows=[], segments=[], events=[])
        phase_runner.timeline, phase_runner.container_timeline = [], []

        def resolve_graphs(api_client, case):
            self.calls.append(f"resolve {case.phases[0].graph_id}")
            return {}

        git = {"ref": "dev", "sha": "abc1234", "dirty": False}
        with (
            mock.patch.object(runner, "_host_facts", return_value=self.HOST_OK),
            mock.patch.object(runner, "_resolve_graphs", side_effect=resolve_graphs),
            mock.patch.object(runner, "_stack_facts", return_value={}),
            mock.patch.object(runner, "evaluate_stack", return_value=[]),
            mock.patch.object(runner, "_container_limits", return_value={}),
            mock.patch.object(runner, "PhaseRunner", return_value=phase_runner) as runner_class,
            mock.patch.object(runner.stack, "Compose", return_value=compose),
            mock.patch.object(runner.stack, "detect_project", return_value="src"),
            mock.patch.object(runner.stack, "git_info", return_value=git),
            mock.patch.object(runner.stack, "host_info", return_value={"hostname": "host"}),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            runner.run_variant(self.case, self.case.variants[0], self.options)
        self.assertEqual(self.calls[:3], ["up", "import", "resolve 42"])
        self.assertEqual(runner_class.call_args.args[1].graph_id, 42)

    def test_run_with_an_env_error_stops_before_importing(self):
        (self.repo / "src" / ".env").write_text("OTHER=1\n", encoding="utf-8")
        with (
            mock.patch.object(runner, "_host_facts", return_value=self.HOST_OK),
            mock.patch.object(runner.stack, "detect_project", return_value="src"),
            mock.patch.object(runner.stack, "git_info", return_value={"dirty": False}),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            runner.run_variant(self.case, self.case.variants[0], self.options)
        self.assertEqual(self.calls, [])


class BenchCliTest(unittest.TestCase):
    DEV_CASE = 'name = "dev"\nkind = "dev"\n[[phase]]\nname = "payload"\n'

    def setUp(self):
        self.export = Path(tempfile.mkdtemp()) / "payload.json"
        self.export.write_text("{}", encoding="utf-8")
        patches = [
            mock.patch.dict(bench.os.environ, {"BENCH_API_KEY": "key", "BENCH_ORG_ID": "1"}),
            # never read the developer's real ~/.epicstaff-bench.env from a test
            mock.patch.object(bench, "load_bench_env"),
            mock.patch.object(bench, "BENCH_ENV_FILE", self.export.with_name("absent.env")),
            mock.patch.object(bench, "PAYLOAD_EXPORT", self.export),
            mock.patch.object(
                bench.flows,
                "import_flow",
                return_value=flows.ImportedFlow(42, "payload", "created"),
            ),
            mock.patch.object(bench.flows, "ensure_flow"),
        ]
        for patch in patches:
            self.start(patch)
        # every docker call a command makes; the default organization lookup is the only one
        self.stack_run = self.start(mock.patch.object(bench.stack, "run"))
        env_file = self.export.with_name(".env")
        env_file.write_text("DB_USER=bench\nDB_NAME=db\n", encoding="utf-8")
        self.start(mock.patch.object(bench.stack, "ENV_FILE", env_file))

    def start(self, patch):
        started = patch.start()
        self.addCleanup(patch.stop)
        return started

    def without_org_id(self, default_org: str = "3\n"):
        """No BENCH_ORG_ID; Postgres answers the default organization query with `default_org`."""
        del bench.os.environ["BENCH_ORG_ID"]  # mock.patch.dict restores it
        self.stack_run.return_value = mock.Mock(returncode=0, stdout=default_org, stderr="")

    def run_main(self, *argv: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = bench.main(list(argv))
        return code, stdout.getvalue(), stderr.getvalue()

    def run_dev(self, *argv: str):
        case = str(write_case(self.DEV_CASE))
        with mock.patch.object(bench.runner, "run_dev") as run_dev:
            code, stdout, stderr = self.run_main("dev", "--case", case, *argv)
        return code, stdout, stderr, run_dev

    def assert_nothing_imported(self):
        bench.flows.import_flow.assert_not_called()
        bench.flows.ensure_flow.assert_not_called()

    def test_dev_leaves_the_payload_graph_to_the_export(self):
        code, _, _, run_dev = self.run_dev()
        self.assertEqual(code, 0)
        case, run_options = run_dev.call_args.args[:2]
        self.assertIsNone(case.phases[0].graph_id)
        self.assertEqual(run_options.flow_exports, {"payload": self.export})
        self.assert_nothing_imported()  # the runner imports, after its checks

    def test_graph_override_wins_over_the_export(self):
        code, _, _, run_dev = self.run_dev("--graph", "payload=7")
        self.assertEqual((code, run_dev.call_args.args[0].phases[0].graph_id), (0, 7))

    def test_graph_id_in_the_case_wins_over_the_export(self):
        case = write_case(self.DEV_CASE + "graph_id = 17\n")
        with mock.patch.object(bench.runner, "preflight_only", return_value=0) as preflight:
            code, _, _ = self.run_main("preflight", str(case))
        self.assertEqual((code, preflight.call_args.args[0].phases[0].graph_id), (0, 17))

    def test_missing_export_keeps_the_graph_id_error_and_names_flow_import(self):
        self.export.unlink()
        code, _, stderr, run_dev = self.run_dev()
        self.assertEqual(code, 2)
        self.assertIn("--graph payload=<id>", stderr)
        self.assertIn("bench.py flow import", stderr)
        run_dev.assert_not_called()

    def test_run_still_needs_a_graph_id_for_other_phases(self):
        case = write_case(self.DEV_CASE + '[[phase]]\nname = "complex"\n')
        with mock.patch.object(bench.runner, "run_variant") as run_variant:
            code, _, stderr = self.run_main("run", str(case))
        self.assertEqual(code, 2)
        self.assertIn("'complex' needs a positive integer graph_id", stderr)
        run_variant.assert_not_called()

    def test_plan_without_a_graph_id_names_the_flag(self):
        case = write_case(
            'name = "server"\nkind = "capacity"\n[[phase]]\nname = "payload"\n'
            '[[phase]]\nname = "complex"\n'
        )
        code, stdout, _ = self.run_main("plan", str(case))
        self.assertEqual(code, 0)
        self.assertIn("phase complex: graph id: set with --graph complex=<id>", stdout)
        self.assertNotIn("phase payload: graph id", stdout)  # imported from its export
        self.assertIn("complex: 25 → 50", stdout)

    def test_preflight_without_a_graph_id_still_runs_its_checks(self):
        case = write_case(self.DEV_CASE + '[[phase]]\nname = "complex"\n')
        with mock.patch.object(bench.runner, "preflight_only", return_value=2) as preflight:
            code, _, _ = self.run_main("preflight", str(case))
        self.assertEqual(code, 2)
        phases = preflight.call_args.args[0].phases
        self.assertEqual(
            [(phase.name, phase.graph_id) for phase in phases],
            [("payload", None), ("complex", None)],
        )

    def test_plan_works_without_the_payload_graph_id_and_never_imports(self):
        code, stdout, _ = self.run_main("plan", str(write_case(self.DEV_CASE)))
        self.assertEqual(code, 0)
        self.assertIn("case dev", stdout)
        self.assert_nothing_imported()

    def test_case_name_matching_a_directory_is_looked_up_under_cases(self):
        # the repo root has a `dev/` folder, so `bench dev` run from there must not open it
        folder = Path(tempfile.mkdtemp())
        (folder / "dev").mkdir()
        with contextlib.chdir(folder):
            self.assertEqual(bench.case_path("dev"), bench.HERE / "cases" / "dev.toml")

    def test_flow_import_always_imports_and_prints_one_line_or_only_the_id(self):
        self.assertEqual(
            self.run_main("flow", "import"), (0, 'payload flow: id 42 (created) "payload"\n', "")
        )
        self.assertEqual(self.run_main("flow", "import", "--quiet"), (0, "42\n", ""))
        self.assertEqual(bench.flows.import_flow.call_count, 2)
        bench.flows.ensure_flow.assert_not_called()

    def test_flow_import_error_exits_2(self):
        bench.flows.import_flow.side_effect = flows.FlowImportError("HTTP 500: boom")
        code, stdout, stderr = self.run_main("flow", "import")
        self.assertEqual((code, stdout), (2, ""))
        self.assertIn("HTTP 500: boom", stderr)

    def test_push_scans_with_bench_api_key(self):
        with mock.patch.object(bench.push, "push") as push_runs:
            self.assertEqual(self.run_main("push", "run-a")[0], 0)
        self.assertEqual(push_runs.call_args.args[3], "key")

    def test_push_with_only_django_api_key_exits_before_pushing(self):
        with (
            mock.patch.dict(bench.os.environ, {"DJANGO_API_KEY": "org-key"}),
            mock.patch.object(bench.push, "push") as push_runs,
            self.assertRaises(SystemExit) as raised,
        ):
            del bench.os.environ["BENCH_API_KEY"]
            self.run_main("push", "run-a")
        self.assertIn("set BENCH_API_KEY to your org API key", str(raised.exception.code))
        push_runs.assert_not_called()

    def test_plan_compare_and_push_never_query_the_default_organization(self):
        self.without_org_id()
        with (
            mock.patch.object(bench.compare, "compare_runs", return_value="table"),
            mock.patch.object(bench.push, "push"),
        ):
            self.assertEqual(self.run_main("plan", str(write_case(self.DEV_CASE)))[0], 0)
            self.assertEqual(self.run_main("compare", "run-a", "run-b")[0], 0)
            self.assertEqual(self.run_main("push", "run-a")[0], 0)
        self.stack_run.assert_not_called()

    def test_explicit_org_id_is_used_without_a_query(self):
        code, _, stderr, run_dev = self.run_dev()
        run_options = run_dev.call_args.args[1]
        self.assertEqual((code, run_options.org_id, run_options.org_source), (0, "1", "env"))
        self.assertFalse(run_options.api().default_org)
        self.assertEqual(stderr, "")
        self.stack_run.assert_not_called()

    def test_without_org_id_dev_uses_the_default_organization(self):
        self.without_org_id()
        code, _, stderr, run_dev = self.run_dev()
        run_options = run_dev.call_args.args[1]
        self.assertEqual((code, run_options.org_id, run_options.org_source), (0, "3", "default"))
        self.assertTrue(run_options.api().default_org)
        self.assertEqual(stderr, "organization: id 3 (default)\n")

    def test_without_org_id_flow_import_quiet_still_prints_only_the_id(self):
        self.without_org_id()
        self.assertEqual(
            self.run_main("flow", "import", "--quiet"),
            (0, "42\n", "organization: id 3 (default)\n"),
        )
        self.assertEqual(bench.flows.import_flow.call_args.args[0].org_id, "3")

    def test_no_default_organization_exits_2_before_running(self):
        self.without_org_id(default_org="")
        code, _, stderr, run_dev = self.run_dev()
        self.assertEqual(code, 2)
        self.assertIn("no default organization: run `docker compose exec django_app", stderr)
        self.assertIn("or set BENCH_ORG_ID", stderr)
        run_dev.assert_not_called()


class OrganizationTest(unittest.TestCase):
    DB_USER = "bench_db_owner"
    PSQL_FAILED = "could not read the default organization from Postgres"

    def setUp(self):
        self.env_file = Path(tempfile.mkdtemp()) / ".env"
        self.env_file.write_text(
            f"DB_USER={self.DB_USER}\nDB_NAME=epicstaff_db\n", encoding="utf-8"
        )

    def organization(self, environ: dict, **psql) -> tuple[tuple[str, str], str, mock.Mock]:
        answer = {"returncode": 0, "stdout": "", "stderr": "", **psql}
        stderr = io.StringIO()
        with (
            mock.patch.object(bench.stack, "run", return_value=mock.Mock(**answer)) as run,
            contextlib.redirect_stderr(stderr),
        ):
            result = bench.organization(environ, self.env_file)
        return result, stderr.getvalue(), run

    def error(self, **psql) -> str:
        with self.assertRaises(bench.OrganizationError) as raised:
            self.organization({}, **psql)
        message = str(raised.exception)
        self.assertNotIn(self.DB_USER, message)
        return message

    def test_explicit_org_id_wins_without_a_query(self):
        result, printed, run = self.organization({"BENCH_ORG_ID": "5"}, stdout="3\n")
        self.assertEqual((result, printed), (("5", "env"), ""))
        run.assert_not_called()

    def test_default_organization_is_read_through_stack_run(self):
        result, printed, run = self.organization({}, stdout="3\n")
        self.assertEqual(result, ("3", "default"))
        self.assertEqual(printed, "organization: id 3 (default)\n")
        args = run.call_args.args[0]
        self.assertEqual(args[:4], ["docker", "exec", "crewdb", "psql"])
        self.assertEqual(args[args.index("-U") + 1], self.DB_USER)
        self.assertEqual(args[args.index("-d") + 1], "epicstaff_db")
        self.assertEqual(args[-1], bench.DEFAULT_ORG_QUERY)

    def test_no_row_names_create_superadmin(self):
        self.assertEqual(
            self.error(stdout="\n"),
            "no default organization: run `docker compose exec django_app python manage.py "
            "create_superadmin` or set BENCH_ORG_ID",
        )

    def test_psql_failure_gives_its_reason_without_the_db_user(self):
        message = self.error(
            returncode=2, stderr=f'psql: error: FATAL:  role "{self.DB_USER}" does not exist\n'
        )
        self.assertTrue(message.startswith(self.PSQL_FAILED), message)
        self.assertIn("does not exist", message)
        self.assertTrue(message.endswith("; set BENCH_ORG_ID"), message)

    def test_docker_failure_gives_its_reason(self):
        failure = stack.StackError("docker exec crewdb: [Errno 2] No such file or directory")
        with (
            mock.patch.object(bench.stack, "run", side_effect=failure),
            self.assertRaises(bench.OrganizationError) as raised,
        ):
            bench.organization({}, self.env_file)
        self.assertEqual(
            str(raised.exception),
            f"{self.PSQL_FAILED} (docker exec crewdb: [Errno 2] No such file or directory); "
            "set BENCH_ORG_ID",
        )

    def test_unexpected_answer_is_a_failure(self):
        self.assertIn(self.PSQL_FAILED, self.error(stdout="id\n3\n"))

    def test_env_file_without_db_settings_is_a_failure(self):
        self.env_file.write_text("OTHER=1\n", encoding="utf-8")
        self.assertIn("DB_USER", self.error(stdout="3\n"))


class BenchEnvFileTest(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / ".epicstaff-bench.env"
        self.path.write_text(
            "# benchmark settings\n"
            "export BENCH_API_KEY='file-key'\n"
            'BENCH_ORG_ID="7"\n'
            "export BENCH_API=http://server\n"
            "BENCH_RESULTS_REPO=/srv/results\n"
            "export OTHER_SECRET=nope\n",
            encoding="utf-8",
        )
        self.path.chmod(0o600)

    def load(self, environ: dict) -> tuple[dict, str]:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            bench.load_bench_env(self.path, environ)
        return environ, stderr.getvalue()

    def test_sets_only_the_known_names(self):
        environ, _ = self.load({})
        self.assertEqual(
            environ,
            {
                "BENCH_API_KEY": "file-key",
                "BENCH_ORG_ID": "7",
                "BENCH_API": "http://server",
                "BENCH_RESULTS_REPO": "/srv/results",
            },
        )

    def test_environment_values_win(self):
        environ, _ = self.load({"BENCH_ORG_ID": "1"})
        self.assertEqual((environ["BENCH_ORG_ID"], environ["BENCH_API_KEY"]), ("1", "file-key"))

    def test_exported_key_wins_and_the_other_names_still_load(self):
        environ, _ = self.load({"BENCH_API_KEY": "shell-key"})
        self.assertEqual(environ["BENCH_API_KEY"], "shell-key")
        self.assertEqual(environ["BENCH_ORG_ID"], "7")

    def test_missing_file_changes_nothing(self):
        environ = {}
        bench.load_bench_env(self.path.with_name("absent.env"), environ)
        self.assertEqual(environ, {})

    def test_group_or_world_readable_file_warns_on_posix(self):
        self.path.chmod(0o644)
        with mock.patch.object(bench.os, "name", "posix"):
            _, warning = self.load({})
        self.assertIn(f"chmod 600 {self.path}", warning)
        with mock.patch.object(bench.os, "name", "nt"):  # Windows has no group/other bits
            _, warning = self.load({})
        self.assertEqual(warning, "")

    @unittest.skipUnless(bench.os.name == "posix", "file modes are POSIX-only")
    def test_private_file_does_not_warn(self):
        _, warning = self.load({})
        self.assertEqual(warning, "")

    def test_django_api_key_in_the_file_is_not_loaded(self):
        self.path.write_text("DJANGO_API_KEY=org-key\n", encoding="utf-8")
        environ, _ = self.load({})
        self.assertEqual(environ, {})


class ApiKeyTest(unittest.TestCase):
    RENAMED = "DJANGO_API_KEY is Django's system key and is not read"

    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / ".epicstaff-bench.env"

    def exit_message(self, environ: dict) -> str:
        with self.assertRaises(SystemExit) as raised:
            bench.api_key(environ, self.path)
        return str(raised.exception.code)

    def test_returns_bench_api_key_even_when_django_api_key_is_set(self):
        environ = {"BENCH_API_KEY": "org-key", "DJANGO_API_KEY": "system-key"}
        self.assertEqual(bench.api_key(environ, self.path), "org-key")

    def test_django_api_key_in_the_shell_asks_for_the_rename(self):
        message = self.exit_message({"DJANGO_API_KEY": "org-key"})
        self.assertIn(self.RENAMED, message)
        self.assertIn("DJANGO_API_KEY is Django's system key and is not read", message)

    def test_django_api_key_in_the_bench_env_file_asks_for_the_rename(self):
        self.path.write_text("export DJANGO_API_KEY=org-key\n", encoding="utf-8")
        self.assertIn(self.RENAMED, self.exit_message({}))

    def test_no_key_says_how_to_set_bench_api_key(self):
        message = self.exit_message({})
        self.assertIn("BENCH_API_KEY is not set", message)
        self.assertNotIn("DJANGO_API_KEY", message)


def hung_at_sandbox(session_id, sent, crew_answer_ts):
    """Checkpoints of a session whose code never started in the sandbox; crew reports its end
    only at `crew_answer_ts`, long after the runner stopped it."""
    events = [
        ("received", sent + 0.1),
        ("slot_acquired", sent + 0.2),
        ("node_start", sent + 0.3),
        ("sandbox_dispatched", sent + 0.4),
    ]
    return [
        {"service": "crew", "checkpoint": checkpoint, "session_id": session_id, "ts": ts}
        | ({"execution_id": f"x{session_id}"} if checkpoint == "sandbox_dispatched" else {})
        for checkpoint, ts in events
    ] + [
        {
            "service": "crew",
            "checkpoint": "session_end",
            "session_id": session_id,
            "status": "stop",
            "ts": crew_answer_ts,
        }
    ]


class TimedOutLevelTest(unittest.TestCase):
    """A bisect probe whose measured sessions all hung: the runner stopped them at
    session_timeout_s (900 s) and crew answered the stops only at the next stack restart."""

    WINDOW = analyze.Window(
        "payload", 150, "bisect", 2, start_ts=0, settle_end_ts=30, end_ts=210, finish_end_ts=1115
    )

    def hung(self):
        records = [
            record(
                number,
                intended=40 + number,
                sent=40 + number,
                done=940 + number,
                status="timeout",
                level=150,
                kind="bisect",
                segment=2,
            )
            for number in range(1, 21)
        ]
        events = [
            event for number in range(1, 21) for event in hung_at_sandbox(number, 40 + number, 2460)
        ]
        return records, events

    def test_verdict_is_fail_on_the_error_rate_not_invalid(self):
        records, events = self.hung()
        rows = analyze.build_rows(records, events)
        verdict, reasons = analyze.judge(
            analyze.measured(rows, self.WINDOW), self.WINDOW, PassRules(p95_e2e_s=120), AbortRules()
        )
        self.assertEqual((verdict, reasons), ("fail", ["error rate 100.0% > 1.0%"]))

    def test_timed_out_text_counts_the_two_most_common_last_checkpoints(self):
        records, events = self.hung()
        # three more hung inside their Python code, one before crew received it
        for number in (21, 22, 23):
            records.append(record(number, intended=41, sent=41, done=941, status="timeout"))
            events += [
                *hung_at_sandbox(number, 41, 2460)[:4],
                {"service": "sandbox", "checkpoint": "exec_start", "session_id": number, "ts": 42},
            ]
        records.append(record(24, intended=41, sent=41, done=941, status="timeout"))
        records.append(record(25, intended=41, sent=41, done=50, status="end"))
        rows = analyze.build_rows(records, events)
        by_session, _ = analyze.index_events(events)
        self.assertEqual(
            analyze.timed_out_text(rows, by_session),
            "24 timed out; last checkpoint: crew sandbox_dispatched (20), sandbox exec_start (3)",
        )
        self.assertIsNone(analyze.timed_out_text(rows[-1:], by_session))
        self.assertEqual(analyze.last_checkpoint([], 10.0), "no checkpoint")

    def test_bottleneck_names_the_timeouts_after_restarts_and_before_resources(self):
        context = {
            "restarts": [],
            "failure": "20 timed out; last checkpoint: crew sandbox_dispatched (20)",
            "saturated_processes": [],
            "host_mem_avail_min_pct": 50,
            "ram_guard_pct": 5,
            "host_cpu_mean": 95,
            "containers_at_cpu_limit": [],
            "running_mean": 10,
            "queued_mean": 0,
            "crew_cap": None,
            "agent_queue_p95": None,
            "previous_agent_queue_p95": None,
            "pg_ratio_max": None,
        }
        self.assertEqual(analyze.bottleneck(context), context["failure"])
        self.assertEqual(
            analyze.bottleneck({**context, "restarts": ["sandbox"]}),
            "container restart/OOM: sandbox",
        )

    def test_analyzed_level_reports_the_timeouts_as_bottleneck_and_critical_finding(self):
        records, events = self.hung()
        data = synthetic_run(mem_slope=0.3)
        data.records, data.events, data.windows = records, events, [self.WINDOW]
        out = Path(tempfile.mkdtemp())
        analyze.analyze(data, out)
        with open(out / "steps.csv", encoding="utf-8") as steps_file:
            (step,) = list(csv.DictReader(steps_file))
        self.assertEqual(
            (step["verdict"], step["fail_reasons"], step["bottleneck"]),
            (
                "fail",
                "error rate 100.0% > 1.0%",
                "20 timed out; last checkpoint: crew sandbox_dispatched (20)",
            ),
        )
        with open(out / "findings.csv", encoding="utf-8") as findings_file:
            first = next(csv.DictReader(findings_file))
        self.assertEqual(
            first,
            {
                "phase": "payload",
                "severity": "critical",
                "kind": "timeouts",
                "message": "bisect level 150: 20 timed out; last checkpoint: crew sandbox_dispatched (20)",
                "ts": "941",  # the first runner stop, not crew's late answer
                "run_rel_s": "941",
                "tab": "Timeline",
                "container": "",
            },
        )


class TimelineColumnsTest(unittest.TestCase):
    def test_rolling_throughput_p95_and_time_continuous_across_segments(self):
        samples = [
            {"ts": ts, "rel_s": rel_s, "segment": segment}
            for ts, rel_s, segment in (
                (1000, 0, 1),
                (1030, 30, 1),
                (1060, 60, 1),
                (1200, 0, 2),
                (1230, 30, 2),
            )
        ]
        ended = [
            (1010, 5, "end"),
            (1020, 7, "end"),
            (1025, 900, "timeout"),
            (1050, 9, "end"),
            (1210, 3, "end"),
        ]
        rows = [{"end_ts": end, "e2e_s": e2e, "status": status} for end, e2e, status in ended]
        result = analyze._timeline_rows(types.SimpleNamespace(timeline=samples), rows, 1000)
        self.assertEqual(
            [
                (row["run_rel_s"], row["rel_s"], row["throughput_per_min"], row["e2e_p95_60s"])
                for row in result
            ],
            [
                (0, 0, 0, None),
                (30, 30, 2, 6.9),
                (60, 60, 3, 8.8),
                (200, 0, 0, None),
                (230, 30, 1, 3),
            ],
        )


class InflightStagesTest(unittest.TestCase):
    def test_sessions_are_counted_at_the_stage_of_their_last_checkpoint(self):
        def event(service, checkpoint, session_id, ts, **extra):
            return {
                "service": service,
                "checkpoint": checkpoint,
                "session_id": session_id,
                "ts": ts,
                **extra,
            }

        events = [
            event("crew", "received", 1, 1.0),
            event("crew", "slot_acquired", 1, 2.0),
            event("crew", "sandbox_dispatched", 1, 3.0, execution_id="e1"),
            event("sandbox", "exec_start", 1, 5.0, execution_id="e1"),
            event("sandbox", "exec_end", 1, 6.0, execution_id="e1"),
            event("crew", "node_end", 1, 6.5),
            event("crew", "session_end", 1, 8.0, status="end"),
            event("crew", "received", 2, 1.2),
            event("crew", "slot_acquired", 2, 1.4),
            event("crew", "agent_dispatched", 2, 1.6, correlation_id="c2"),
            event("agent", "request_consumed", 2, 2.2, correlation_id="c2"),
            event("agent", "llm_start", 2, 2.4, correlation_id="c2"),
            event("agent", "llm_end", 2, 4.0, correlation_id="c2"),
            event("agent", "sandbox_dispatched", 2, 4.5, execution_id="e2"),
            event("crew", "session_end", 2, 30.0, status="stop"),  # answers the runner's stop
        ]
        records = [
            record(1, intended=0, sent=0, done=8.0),
            record(2, intended=0.2, sent=0.2, done=9.0, status="timeout"),
        ]
        rows = analyze.build_rows(records, events)
        by_session, _ = analyze.index_events(events)
        samples = [
            {"ts": ts, "phase": "payload", "segment": 1}
            for ts in (0.5, 1.5, 2.5, 3.5, 4.2, 5.5, 6.2, 7.0, 8.5, 9.5)
        ]
        result = analyze._inflight_stage_rows(
            types.SimpleNamespace(timeline=samples, segments=[]), rows, by_session, 0.0
        )
        by_ts = defaultdict(dict)
        for row in result:
            by_ts[row["ts"]][row["stage"]] = row["count"]
        self.assertEqual(
            dict(by_ts),
            {
                0.5: {"waiting for crew": 2},
                1.5: {"waiting for crew": 1, "crew": 1},
                2.5: {"crew": 1, "LLM": 1},
                3.5: {"LLM": 1, "waiting for sandbox": 1},
                4.2: {"agent": 1, "waiting for sandbox": 1},
                5.5: {"waiting for sandbox": 1, "python": 1},
                6.2: {"waiting for sandbox": 1, "result return": 1},
                7.0: {"crew": 1, "waiting for sandbox": 1},
                8.5: {"waiting for sandbox": 1},
            },
        )
        self.assertEqual({row["run_rel_s"] for row in result if row["ts"] == 8.5}, {8.5})


class PhasePeakTest(unittest.TestCase):
    def test_peak_covers_the_whole_phase_and_keeps_its_level(self):
        rows = [
            {"phase": "payload", "container": "django_app", "level": 100, "mem_mb": 857.0},
            {"phase": "payload", "container": "django_app", "level": 0, "mem_mb": 1284.0},
            {"phase": "payload", "container": "django_app", "level": 200, "mem_mb": None},
            {"phase": "complex", "container": "django_app", "level": 25, "mem_mb": 900.0},
        ]
        self.assertEqual(
            analyze._phase_peaks(rows),
            {("payload", "django_app"): (1284.0, 0), ("complex", "django_app"): (900.0, 25)},
        )

    def test_every_level_row_carries_the_phase_peak(self):
        run_dir = fixtures.write_capacity_run(
            Path(tempfile.mkdtemp()), "peaks", levels=(10, 20), fail_from=None
        )
        with open(run_dir / "containers.csv", encoding="utf-8") as containers_file:
            rows = list(csv.DictReader(containers_file))
        self.assertTrue(rows)
        for row in rows:
            self.assertGreaterEqual(float(row["phase_peak_mb"]), float(row["mem_peak_mb"]))
            self.assertIn(row["phase_peak_level"], {"0", "10", "20"})


def session(status="end", **values):
    """A sessions.csv row of the synthetic level (payload, level 10, measured)."""
    row = dict.fromkeys(analyze.SESSION_COLUMNS, 0.0)
    row.update(
        phase="payload",
        segment=1,
        level=10,
        kind="ladder",
        cold=0,
        session_id=None,
        intended_ts=30,
        sent_ts=30,
        end_ts=40,
        status=status,
        censored=False,
        e2e_s=10.0,
        http_status=200,
    )
    return row | values


class FindingsTest(unittest.TestCase):
    def setUp(self):
        self.data = synthetic_run(mem_slope=0.3)  # one payload level 10: settle 10-20, hold to 100

    def findings(self, rows=(), steps=(), container_phase_rows=(), kind=None):
        found = analyze._findings(
            self.data, list(rows), {}, list(steps), list(container_phase_rows), 0.0
        )
        return [finding for finding in found if kind is None or finding["kind"] == kind]

    @staticmethod
    def step(level, throughput, verdict="pass", fail_reasons=""):
        return {
            "phase": "payload",
            "segment": 1,
            "level": level,
            "kind": "ladder",
            "throughput_per_min": throughput,
            "verdict": verdict,
            "fail_reasons": fail_reasons,
        }

    def test_throughput_plateau_names_the_last_level_that_still_grew(self):
        steps = [self.step(25, 218.09), self.step(50, 212.07), self.step(100, 218.72)]
        (finding,) = self.findings(steps=steps, kind="throughput_plateau")
        self.assertEqual(
            finding["message"],
            "throughput stopped growing at level 25 (~218/min); passing level 50 only added latency",
        )
        self.assertEqual(
            (finding["severity"], finding["tab"], finding["ts"]), ("warning", "Curves", None)
        )
        growing = [self.step(25, 100), self.step(50, 190), self.step(100, 370)]
        self.assertEqual(self.findings(steps=growing, kind="throughput_plateau"), [])

    def test_dominant_stage_at_the_headline_level(self):
        waiting = [
            session(sandbox_wait_s=7.6, python_s=1.0, other_s=1.0, dispatch_s=0.4)
            for _ in range(12)
        ]
        (finding,) = self.findings(rows=waiting, steps=[self.step(10, 6)], kind="dominant_stage")
        self.assertEqual(
            (finding["severity"], finding["message"], finding["tab"]),
            ("warning", "sandbox wait = 76% of session time at L10", "Time breakdown"),
        )
        llm_bound = [session(llm_s=8.0, other_s=2.0) for _ in range(12)]
        (finding,) = self.findings(rows=llm_bound, steps=[self.step(10, 6)], kind="dominant_stage")
        self.assertEqual(
            (finding["severity"], finding["message"]), ("info", "LLM = 80% of session time at L10")
        )
        spread = [session(python_s=5.0, other_s=5.0) for _ in range(12)]
        self.assertEqual(
            self.findings(rows=spread, steps=[self.step(10, 6)], kind="dominant_stage"), []
        )

    def test_memory_not_released_above_50_mb_and_10_percent_of_baseline(self):
        models = [
            {
                "phase": "payload",
                "container": "crewdb",
                "baseline_mb": 47.3,
                "retained_mb_after_cooldown": 643.0,
            },
            {
                "phase": "payload",
                "container": "django_app",
                "baseline_mb": 759.5,
                "retained_mb_after_cooldown": 60.0,
            },
            {
                "phase": "payload",
                "container": "redis",
                "baseline_mb": 11.5,
                "retained_mb_after_cooldown": None,
            },
        ]
        (finding,) = self.findings(container_phase_rows=models, kind="memory_retained")
        self.assertEqual(
            (finding["message"], finding["container"], finding["tab"]),
            ("crewdb kept 643 MB after cooldown (baseline 47 MB)", "crewdb", "Containers"),
        )

    def test_moments_are_sorted_critical_first_with_timeline_positions(self):
        self.data.windows[0].abort_reason = "container restart/OOM: crew"
        self.data.container_timeline += [
            {
                "ts": ts,
                "phase": "payload",
                "segment": 1,
                "container": "crew",
                "restarts": restarts,
                "oom_kills": 0,
                "cpu_pct": 1.0,
                "mem_mb": 100.0,
            }
            for ts, restarts in ((50, 0), (60, 1), (70, 1))
        ]
        rows = [session(), *(session("http_error", http_status=502, sent_ts=35) for _ in range(2))]
        rows.append(session("http_error", http_status=None, sent_ts=33))
        steps = [
            self.step(10, 0, verdict="invalid", fail_reasons="too few measured sessions ended (0)")
        ]
        found = self.findings(rows=rows, steps=steps)
        self.assertEqual(
            [
                (finding["severity"], finding["kind"], finding["ts"], finding["run_rel_s"])
                for finding in found
            ],
            [
                ("critical", "container_restart", 60, 60.0),
                ("critical", "abort", 100, 100.0),
                ("warning", "invalid_level", 10, 10.0),
                ("warning", "http_errors", 33, 33.0),
            ],
        )
        self.assertEqual(found[0]["container"], "crew")
        self.assertEqual(
            found[1]["message"], "ladder level 10 aborted: container restart/OOM: crew"
        )
        self.assertEqual(
            found[2]["message"], "ladder level 10 invalid: too few measured sessions ended (0)"
        )
        self.assertEqual(
            found[3]["message"],
            "ladder level 10: 3 of 4 start requests failed (HTTP 502: 2, no answer: 1; API p95 0.0 s)",
        )

    def test_a_few_http_errors_are_info(self):
        rows = [session() for _ in range(200)] + [session("http_error", http_status=502)]
        (finding,) = self.findings(rows=rows, kind="http_errors")
        self.assertEqual(finding["severity"], "info")


class ViewerDefinitionsTest(unittest.TestCase):
    """Every column the analyzer writes has a tooltip in the viewer's DEFINITIONS dictionary, so a
    new column cannot reach the viewer unexplained."""

    def test_every_written_column_has_a_definition(self):
        html = (Path(__file__).with_name("viewer.html")).read_text(encoding="utf-8")
        body = html.split("const DEFINITIONS = {", 1)[1].split("\n    };", 1)[0]
        keys = set(re.findall(r'^\s*"?([\w.]+)"?\s*:', body, re.MULTILINE))
        column_lists = {
            "sessions.csv.gz": analyze.SESSION_COLUMNS,
            "steps.csv": analyze.STEP_COLUMNS,
            "containers.csv": analyze.CONTAINER_COLUMNS,
            "container_phases.csv": analyze.CONTAINER_PHASE_COLUMNS,
            "nodes.csv": analyze.NODE_COLUMNS,
            "timeline.csv": analyze.TIMELINE_COLUMNS,
            "container_timeline.csv": analyze.CONTAINER_TIMELINE_COLUMNS,
            "events_sample.csv": analyze.EVENT_COLUMNS,
            "inflight_stages.csv": analyze.INFLIGHT_STAGE_COLUMNS,
            "findings.csv": analyze.FINDING_COLUMNS,
        }
        missing = []
        for file_name, columns in column_lists.items():
            for column in columns:
                # duration statistics (e2e_s_p95) are defined by their duration and statistic
                base, _, statistic = column.rpartition("_")
                if column not in keys and not (base in keys and statistic in analyze.STAT_KEYS):
                    missing.append(f"{file_name}: {column}")
        self.assertEqual(missing, [])
        self.assertTrue(set(analyze.STAT_KEYS) <= keys)


class StalledSettleTest(unittest.TestCase):
    """The real bisect probe: every session was sent in the settle window and hung at
    sandbox_dispatched, so the hold sent nothing new and measured no session."""

    WINDOW = analyze.Window(
        "payload", 150, "bisect", 2, start_ts=0, settle_end_ts=30, end_ts=210, finish_end_ts=925
    )
    REASON = "20 settle sessions timed out (last checkpoint: crew sandbox_dispatched (20))"

    def stalled(self):
        records = [
            record(
                number,
                intended=5 + number,
                sent=5 + number,
                done=905 + number,
                status="timeout",
                level=150,
                kind="bisect",
                segment=2,
            )
            for number in range(1, 21)
        ]
        events = [
            event for number in range(1, 21) for event in hung_at_sandbox(number, 5 + number, 2460)
        ]
        return records, events

    def test_settle_timeouts_fail_the_level_instead_of_invalid(self):
        records, events = self.stalled()
        rows = analyze.build_rows(records, events)
        by_session, _ = analyze.index_events(events)
        self.assertEqual(analyze.measured(rows, self.WINDOW), [])
        self.assertEqual(
            analyze.judge_level(
                rows, self.WINDOW, PassRules(p95_e2e_s=120), AbortRules(), by_session
            ),
            ("fail", [self.REASON]),
        )
        # settle timeouts after the verdict time do not count: still too few measured
        early = dataclasses.replace(self.WINDOW, finish_end_ts=500)
        verdict, reasons = analyze.judge_level(rows, early, PassRules(), AbortRules(), by_session)
        self.assertEqual(verdict, "invalid")
        self.assertIn("too few measured sessions", reasons[0])

    def test_live_and_final_verdicts_agree_and_name_the_checkpoint_once(self):
        records, events = self.stalled()
        verdict, text = runner.judge_live(
            records, events, self.WINDOW, PassRules(p95_e2e_s=120), AbortRules(), now=930
        )
        self.assertEqual((verdict, text), ("fail", f"fail {self.REASON}"))
        data = synthetic_run(mem_slope=0.3)
        data.records, data.events, data.windows = records, events, [self.WINDOW]
        out = Path(tempfile.mkdtemp())
        analyze.analyze(data, out)
        with open(out / "steps.csv", encoding="utf-8") as steps_file:
            (step,) = list(csv.DictReader(steps_file))
        self.assertEqual(
            (step["sent"], step["verdict"], step["fail_reasons"], step["bottleneck"]),
            (
                "0",
                "fail",
                self.REASON,
                "20 timed out; last checkpoint: crew sandbox_dispatched (20)",
            ),
        )

    def test_runner_waits_for_settle_sessions_when_none_was_measured(self):
        fake = FakeStack(duration_s=None)  # the stack stalls: nothing ever ends
        controller = make_controller(fake)
        phase_runner = make_phase_runner(FakeSessionsApi())
        ladder = dataclasses.replace(phase_runner.case.ladder, session_timeout_s=0.3)
        phase_runner.case = dataclasses.replace(phase_runner.case, ladder=ladder)
        start = time_module.time()
        controller.hold(3, 0.1, 10, abort_check=lambda: None, tick_s=0.02)
        # every session of the hold was sent before the settle window ended
        window = analyze.Window(
            "payload", 5, "ladder", 1, start, time_module.time() + 1, time_module.time()
        )
        phase_runner._finish_measured(controller, window, lambda: None)
        controller.close()
        settle = [record for record in controller.records if window.settles(vars(record))]
        self.assertEqual({record.end_status for record in settle}, {"timeout"})
        self.assertGreaterEqual(window.finish_end_ts, max(record.done_ts for record in settle))
        no_lag_guard = AbortRules(generator_lag_p99_ms=float("inf"))
        live, text = runner.judge_live(
            controller.records, [], window, PassRules(), no_lag_guard, window.finish_end_ts
        )
        final, _ = analyze.judge_level(
            analyze.build_rows(controller.records, []), window, PassRules(), no_lag_guard, {}
        )
        self.assertEqual((live, final), ("fail", "fail"))
        self.assertEqual(
            text, "fail 3 settle sessions timed out (last checkpoint: no checkpoint (3))"
        )


class TimeoutBottleneckTest(unittest.TestCase):
    def test_live_line_adds_the_timed_out_text_to_an_error_rate_fail(self):
        records, events = TimedOutLevelTest().hung()
        verdict, text = runner.judge_live(
            records, events, TimedOutLevelTest.WINDOW, PassRules(), AbortRules(), now=1200
        )
        self.assertEqual(verdict, "fail")
        self.assertEqual(
            text,
            "fail error rate 100.0% > 1.0% · 20 timed out; last checkpoint: crew sandbox_dispatched (20)",
        )

    def test_timeouts_name_the_bottleneck_only_when_they_failed_the_level(self):
        records, events = TimedOutLevelTest().hung()
        rows = analyze.build_rows(records, events)
        by_session, _ = analyze.index_events(events)
        window = TimedOutLevelTest.WINDOW
        text = "20 timed out; last checkpoint: crew sandbox_dispatched (20)"
        for reasons, expected in (
            (["error rate 100.0% > 1.0%"], text),
            (["error rate 7% over 30 s"], text),  # the abort on the error rate
            (["p95 e2e 200.0 s > 120 s"], None),  # latency failed it: resource rules decide
            (["container restart/OOM: crew"], None),
        ):
            self.assertEqual(analyze.failure_text(rows, window, reasons, by_session), expected)

    def test_a_finish_session_timing_out_after_the_verdict_leaves_the_resource_rule(self):
        data = synthetic_run(mem_slope=0.3)
        data.windows[0].finish_end_ts = 140
        for session_record in data.records:
            session_record.end_status = "error"  # the error-rate rule fails the level
        for timeline_row in data.timeline:
            timeline_row["host_cpu_pct"] = 95
        # kept the load during the finish step, stopped in the drain after the verdict
        data.records.append(
            record(99, intended=101, sent=101, done=1001, status="timeout", kind=load.FINISH_KIND)
        )
        out = Path(tempfile.mkdtemp())
        analyze.analyze(data, out)
        with open(out / "steps.csv", encoding="utf-8") as steps_file:
            (step,) = list(csv.DictReader(steps_file))
        self.assertEqual((step["verdict"], step["bottleneck"]), ("fail", "host CPU 95%"))


class DrainAgeTest(unittest.TestCase):
    def test_a_session_younger_than_the_timeout_ages_out_during_the_drain(self):
        fake = FakeStack(duration_s=None)
        controller = make_controller(fake)
        controller.hold(target=2, duration_s=0.1, timeout_s=10, abort_check=lambda: None)
        while controller.in_flight_count() < 2 or controller._pending_http:
            time_module.sleep(0.01)
        young, ending = controller.records
        young.sent_ts = time_module.time() - 1.5  # 1.5 s left of its 3 s timeout
        threading.Timer(
            2.5,
            lambda: controller.on_event(
                {"session_id": ending.session_id, "checkpoint": "session_end", "status": "end"}
            ),
        ).start()
        started = time_module.time()
        self.assertEqual(controller.drain(timeout_s=3), 1)
        controller.close()
        self.assertEqual((young.end_status, ending.end_status), ("timeout", "end"))
        # stopped when it turned 3 s old: not at once, and not at the drain deadline
        self.assertGreater(young.done_ts - started, 1.2)
        self.assertLess(young.done_ts - started, 2.4)


class StageSweepEdgesTest(unittest.TestCase):
    def counts(self, rows, events, samples, segments=()):
        by_session, _ = analyze.index_events(events)
        data = types.SimpleNamespace(timeline=samples, segments=list(segments))
        by_ts = defaultdict(dict)
        for row in analyze._inflight_stage_rows(data, rows, by_session, 0.0):
            by_ts[row["ts"]][row["stage"]] = row["count"]
        return dict(by_ts)

    def test_exec_start_logged_before_sandbox_dispatched_counts_as_python(self):
        def event(service, checkpoint, ts, **extra):
            return {
                "service": service,
                "checkpoint": checkpoint,
                "session_id": 1,
                "ts": ts,
                **extra,
            }

        events = [
            event("crew", "slot_acquired", 1.0),
            event("sandbox", "exec_start", 2.0, execution_id="e"),
            event("crew", "sandbox_dispatched", 2.1, execution_id="e"),
            event("crew", "session_end", 9.0, status="end"),
        ]
        rows = analyze.build_rows([record(1, intended=0, sent=0, done=9.0)], events)
        samples = [{"ts": ts, "phase": "payload", "segment": 1} for ts in (1.5, 3.0)]
        self.assertEqual(self.counts(rows, events, samples), {1.5: {"crew": 1}, 3.0: {"python": 1}})
        self.assertEqual(rows[0]["sandbox_wait_s"], 0)  # a lower bound: this wait is unknown

    def test_unended_session_stops_at_its_segment_end_and_skew_writes_no_negative_count(self):
        rows = [
            # no end known: in flight until its segment's cooldown end, not into segment 2
            session(status=None, sent_ts=1.0, end_ts=None),
            # another clock put its end before its send
            session(sent_ts=5.0, end_ts=4.0),
        ]
        samples = [
            {"ts": ts, "phase": "payload", "segment": segment}
            for ts, segment in ((2.0, 1), (4.5, 1), (6.0, 1), (11.0, 2))
        ]
        segments = [analyze.Segment("payload", 1, "ladder", 0, 1, 8, 10)]
        self.assertEqual(
            self.counts(rows, [], samples, segments),
            {
                2.0: {"waiting for crew": 1},
                4.5: {"waiting for crew": 1},
                6.0: {"waiting for crew": 1},
            },
        )


class FindingNitsTest(unittest.TestCase):
    def test_cpu_limit_is_reported_once_per_container_and_phase(self):
        data = synthetic_run(mem_slope=0.3)  # crew at 50 % CPU throughout
        data.meta["container_limits"] = {"crew": {"cpus": 0.5}}
        data.windows.append(dataclasses.replace(data.windows[0], level=20))
        found = analyze._findings(data, [], {}, [], [], 0.0)
        (finding,) = [item for item in found if item["kind"] == "cpu_limit"]
        self.assertEqual(finding["message"], "crew CPU at its limit (0.5 CPUs) at level 10")

    def test_plateau_ignores_failed_levels(self):
        steps = [
            FindingsTest.step(25, 218.0),
            FindingsTest.step(50, 420.0),
            FindingsTest.step(100, 150.0, verdict="fail"),
        ]
        found = analyze._findings(synthetic_run(mem_slope=0.3), [], {}, steps, [], 0.0)
        self.assertEqual([item for item in found if item["kind"] == "throughput_plateau"], [])

    def test_overlapping_llm_spans_cap_the_share_at_100_percent(self):
        rows = [session(llm_s=12.0) for _ in range(12)]  # parallel calls: 12 s of LLM in 10 s
        steps = [FindingsTest.step(10, 6)]
        found = analyze._findings(synthetic_run(mem_slope=0.3), rows, {}, steps, [], 0.0)
        (finding,) = [item for item in found if item["kind"] == "dominant_stage"]
        self.assertEqual(finding["message"], "LLM = 100% of session time at L10")


class SenderCapacityTest(unittest.TestCase):
    """A start request blocks its sender for its whole duration. When the API is slow and the
    level is above the initial sender pool, the sends must not queue behind the pool: that
    queueing reads as generator lag and makes the level invalid."""

    def test_a_target_above_the_initial_senders_is_sent_without_lag(self):
        ids = itertools.count(1)

        def slow_start():  # the API answers every start request after 0.3 s
            time_module.sleep(0.3)
            return 200, next(ids)

        controller = load.Controller(slow_start, lambda session_id: None, senders=64)
        controller.set_context("payload", 100, "ladder", 1)
        try:
            controller.hold(100, 0.1, 60, abort_check=lambda: None, tick_s=0.05)
            controller.drain(0)  # waits for the unanswered start requests
        finally:
            controller.close()
        lags_ms = [(record.sent_ts - record.intended_ts) * 1000 for record in controller.records]
        self.assertEqual(len(lags_ms), 100)
        # a fixed pool of 64 would start the last 36 sends 300 ms late
        self.assertLess(analyze.percentile(lags_ms, 0.99), 200)

    def test_close_leaves_no_sender_thread_of_any_pool(self):
        def senders():
            return {
                thread
                for thread in threading.enumerate()
                if thread.name.startswith(load.SENDER_THREAD)
            }

        before = senders()
        ids = itertools.count(1)

        def slow_start():
            time_module.sleep(0.2)
            return 200, next(ids)

        controller = load.Controller(slow_start, lambda session_id: None, senders=2)
        controller.set_context("payload", 5, "ladder", 1)
        controller.hold(2, 0.05, 60, abort_check=lambda: None, tick_s=0.05)
        controller.hold(5, 0.05, 60, abort_check=lambda: None, tick_s=0.05)  # replaces the pool
        controller.drain(0)
        controller.close()
        for thread in senders() - before:
            thread.join(timeout=5)
        self.assertEqual(senders() - before, set())
        self.assertEqual(len(controller.records), 5)
        self.assertTrue(all(record.session_id for record in controller.records))  # none lost


def start_request(number, intended, api_ms, error=None, level=40):
    """A session record whose start request took `api_ms`; with `error` it failed (http_error)."""
    return load.SessionRecord(
        "payload",
        level,
        "ladder",
        1,
        intended,
        sent_ts=intended,
        api_ms=api_ms,
        http_status=None if error else 200,
        session_id=None if error else number,
        error=error,
        done_ts=intended + (api_ms / 1000 if error else 10),
        end_status="http_error" if error else "end",
    )


class StartFailuresTest(unittest.TestCase):
    """The 1-worker run: level 40 aborted on the error rate because 16 start requests hit the
    API client's 30 s timeout while django_app ran its one worker at 124 % CPU."""

    WINDOW = analyze.Window(
        "payload", 40, "ladder", 1, 0, 30, 210, abort_reason="error rate 12% over 30 s"
    )

    def records(self):
        return [start_request(number, 30 + number, 1000) for number in range(1, 21)] + [
            start_request(100 + number, 100 + number, 30000, "TimeoutError: timed out")
            for number in range(1, 17)
        ]

    def test_the_live_line_names_the_failed_start_requests(self):
        verdict, text = runner.judge_live(
            self.records(), [], self.WINDOW, PassRules(), AbortRules(), now=300
        )
        self.assertEqual(
            (verdict, text),
            (
                "fail",
                "fail error rate 12% over 30 s · 16 start requests failed (TimeoutError; API p95 30.0 s)",
            ),
        )

    def test_start_requests_timing_out_after_the_abort_still_count(self):
        # aborted at 120 s: the 16 measured requests sent from 101 s time out only at 131-146 s
        window = dataclasses.replace(self.WINDOW, end_ts=120)
        rows = analyze.build_rows(self.records(), [])
        self.assertEqual(
            analyze.failure_text(rows, window, ["error rate 12% over 30 s"], {}),
            "16 start requests failed (TimeoutError; API p95 30.0 s)",
        )

    def test_bottleneck_names_the_requests_and_the_saturated_worker_and_findings_follow(self):
        data = synthetic_run(mem_slope=0.3)  # crew at 50 % CPU: not saturated
        data.records, data.windows = self.records(), [self.WINDOW]
        data.container_timeline += [
            {**row, "container": "django_app", "cpu_pct": 124.0}
            for row in data.container_timeline
            if row["container"] == "crew"
        ]
        out = Path(tempfile.mkdtemp())
        analyze.analyze(data, out)
        with open(out / "steps.csv", encoding="utf-8") as steps_file:
            (step,) = list(csv.DictReader(steps_file))
        self.assertEqual(
            step["bottleneck"],
            "16 start requests failed (TimeoutError; API p95 30.0 s); django_app at its 1 worker (124 % CPU)",
        )
        with open(out / "findings.csv", encoding="utf-8") as findings_file:
            found = {row["kind"]: row for row in csv.DictReader(findings_file)}
        self.assertEqual(
            (found["http_errors"]["severity"], found["http_errors"]["message"]),
            (
                "critical",
                "ladder level 40: 16 of 36 start requests failed (TimeoutError: 16; API p95 30.0 s)",
            ),
        )
        saturated = found["single_process_saturated"]
        self.assertEqual(
            (saturated["severity"], saturated["message"], saturated["container"]),
            ("warning", "django_app at its 1 worker (124 % CPU) at ladder level 40", "django_app"),
        )

    def test_failed_start_requests_that_did_not_fail_a_level_are_rated_by_the_phase_share(self):
        data = synthetic_run(mem_slope=0.3)
        steps = [FindingsTest.step(10, 6), FindingsTest.step(20, 6)]  # both levels passed
        # 36 sessions at level 10, 364 at level 20: a phase of 400
        for failed, expected in ((1, "info"), (6, "warning")):  # of the phase: 0.25 %, 1.5 %
            rows = [session() for _ in range(36 - failed)]
            rows += [
                session("http_error", error_reason="HTTP 502: bad gateway") for _ in range(failed)
            ]
            rows += [session(level=20) for _ in range(364)]
            found = analyze._findings(data, rows, {}, steps, [], 0.0)
            (finding,) = [item for item in found if item["kind"] == "http_errors"]
            self.assertEqual(finding["severity"], expected)
            self.assertIn(
                f"ladder level 10: {failed} of 36 start requests failed (HTTP 502: {failed}",
                finding["message"],
            )


class FailureBoundaryTest(unittest.TestCase):
    WINDOW = analyze.Window("payload", 10, "ladder", 1, 0, 10, 100)

    def test_failed_start_requests_name_the_level_from_half_of_its_failures(self):
        def failures(requests, timeouts):
            records = [
                start_request(number, 20 + number, 30000, "TimeoutError: timed out", level=10)
                for number in range(requests)
            ]
            records += [
                record(50 + number, 50 + number, 50 + number, 60 + number, status="timeout")
                for number in range(timeouts)
            ]
            rows = analyze.build_rows(records, [])
            return analyze.failure_text(rows, self.WINDOW, ["error rate 50.0% > 1.0%"], {})

        for requests, timeouts, expected in (
            (2, 2, "2 start requests failed (TimeoutError; API p95 30.0 s)"),  # exactly half
            (1, 2, "2 timed out; last checkpoint: no checkpoint (2)"),
            (0, 2, "2 timed out; last checkpoint: no checkpoint (2)"),
        ):
            self.assertEqual(failures(requests, timeouts), expected)

    def test_sessions_the_drain_stops_after_an_abort_do_not_change_what_failed_the_level(self):
        window = analyze.Window(
            "payload", 10, "ladder", 1, 0, 30, 120, abort_reason="error rate 40% over 30 s"
        )
        failed = [
            start_request(number, 40 + number, 30000, "TimeoutError: timed out", level=10)
            for number in range(10)
        ]
        running = [start_request(100 + number, 50 + number, 500, level=10) for number in range(15)]
        live = [dataclasses.replace(item, done_ts=None, end_status=None) for item in running]
        _, text = runner.judge_live(failed + live, [], window, PassRules(), AbortRules(), now=125)
        # the drain stops the 15 still running as `timeout`, long after the abort
        stopped = [dataclasses.replace(item, done_ts=400, end_status="timeout") for item in running]
        data = synthetic_run(mem_slope=0.3)
        data.records, data.windows = failed + stopped, [window]
        out = Path(tempfile.mkdtemp())
        analyze.analyze(data, out)
        with open(out / "steps.csv", encoding="utf-8") as steps_file:
            (step,) = list(csv.DictReader(steps_file))
        self.assertEqual(
            step["bottleneck"], "10 start requests failed (TimeoutError; API p95 30.0 s)"
        )
        self.assertEqual(text, f"fail error rate 40% over 30 s · {step['bottleneck']}")

    def test_the_settle_reason_does_not_hide_failed_start_requests_on_the_live_line(self):
        window = analyze.Window("payload", 40, "ladder", 1, 0, 30, 210, finish_end_ts=925)
        records = [
            record(number, 5 + number, 5 + number, 905 + number, status="timeout", level=40)
            for number in range(1, 4)
        ]
        records += [
            start_request(100 + number, 10 + number, 30000, "TimeoutError: timed out")
            for number in range(4)
        ]
        verdict, text = runner.judge_live(records, [], window, PassRules(), AbortRules(), now=930)
        self.assertEqual(
            (verdict, text),
            (
                "fail",
                (
                    "fail 3 settle sessions timed out (last checkpoint: no checkpoint (3)) · "
                    "4 start requests failed (TimeoutError; API p95 30.0 s)"
                ),
            ),
        )


class SaturatedProcessTest(unittest.TestCase):
    """Python services run one process per core: crew and agent one, django_app one per
    DJANGO_SGI_WORKERS. At about one core each they are the limit, whatever the host has left."""

    def test_saturation_per_process_count(self):
        def samples(name, cpu_pct):
            return [{"container": name, "cpu_pct": cpu_pct} for _ in range(3)]

        for container_samples, env, expected in (
            (samples("crew", 86), {}, [("crew", "crew at one core (one process, 86 % CPU)")]),
            (samples("crew", 82), {}, []),
            (samples("agent", 18), {}, []),
            (
                samples("django_app", 124),
                {"DJANGO_SGI_WORKERS": "1"},
                [("django_app", "django_app at its 1 worker (124 % CPU)")],
            ),
            (
                samples("django_app", 124),
                {},
                [("django_app", "django_app at its 1 worker (124 % CPU)")],
            ),
            (samples("django_app", 116), {"DJANGO_SGI_WORKERS": "4"}, []),
            (
                samples("django_app", 350),
                {"DJANGO_SGI_WORKERS": "4"},
                [("django_app", "django_app at its 4 workers (350 % CPU)")],
            ),
            (samples("sandbox", 900), {}, []),  # runs a process per execution: not single-process
            (samples("django_app", 124), {"DJANGO_SGI_WORKERS": " 2 "}, []),  # 2 workers, 62 % each
            (
                samples("django_app", 900),
                {"DJANGO_SGI_WORKERS": "four"},
                [],
            ),  # unreadable: no verdict
            (samples("django_app", 900), {"DJANGO_SGI_WORKERS": ""}, []),
            (samples("django_app", 900), {"DJANGO_SGI_WORKERS": "0"}, []),
        ):
            self.assertEqual(analyze.saturated_processes(container_samples, env), expected)

    def test_bottleneck_order(self):
        crew = "crew at one core (one process, 86 % CPU)"
        context = {
            "restarts": [],
            "failure": None,
            "saturated_processes": [crew],
            "host_mem_avail_min_pct": 50,
            "ram_guard_pct": 5,
            "host_cpu_mean": 93,
            "containers_at_cpu_limit": [],
            "running_mean": 300,
            "queued_mean": 0,
            "crew_cap": None,
            "agent_queue_p95": None,
            "previous_agent_queue_p95": None,
            "pg_ratio_max": None,
        }
        for changes, expected in (
            ({}, f"{crew}; host CPU 93%"),  # the 4-worker run at level 320: both are said
            ({"host_cpu_mean": 60}, crew),
            ({"saturated_processes": []}, "host CPU 93%"),
            ({"host_mem_avail_min_pct": 3}, "host RAM (available 3%)"),
            (
                {"failure": "3 timed out; last checkpoint: x (3)"},
                f"3 timed out; last checkpoint: x (3); {crew}",
            ),
            ({"restarts": ["crew"]}, "container restart/OOM: crew"),
        ):
            self.assertEqual(analyze.bottleneck({**context, **changes}), expected)

    def test_finding_once_per_container_and_phase_at_its_first_level(self):
        data = synthetic_run(mem_slope=0.3)
        for row in data.container_timeline:
            row["cpu_pct"] = 90.0  # crew at its one core throughout
        data.windows.append(dataclasses.replace(data.windows[0], level=20))
        found = analyze._findings(data, [], {}, [], [], 0.0)
        (finding,) = [item for item in found if item["kind"] == "single_process_saturated"]
        self.assertEqual(
            finding["message"], "crew at one core (one process, 90 % CPU) at ladder level 10"
        )
        self.assertEqual(finding["container"], "crew")


def llm_run(host_cpu_pct):
    """Two levels: LLM calls of 0.6 s at level 20 (host CPU 40 %), of 6 s at level 320 with
    the host at `host_cpu_pct` (the 4-worker run's shape). The smoke step's LLM p95 was 0.9 s."""
    return llm_levels([(20, 0, 10, 50, 0.6, 40), (320, 50, 60, 100, 6.0, host_cpu_pct)])


def llm_levels(levels):
    """One window per (level, start, settle end, end, LLM call seconds, host CPU %), 12 measured
    sessions each with one LLM call; the smoke step's LLM p95 was 0.9 s."""
    data = synthetic_run(mem_slope=0.3)
    data.windows = [
        analyze.Window("payload", level, "ladder", 1, start, settle, end)
        for level, start, settle, end, _, _ in levels
    ]
    data.records, data.events = [], []
    for number in range(12 * len(levels)):
        level, _, settle, _, call_s, _ = levels[number // 12]
        sent = settle + 2 + 3 * (number % 12)
        data.records.append(record(number + 1, sent, sent, sent + 8, level=level))
        correlation = f"c{number}"
        data.events += [
            {
                "service": "agent",
                "checkpoint": checkpoint,
                "session_id": number + 1,
                "correlation_id": correlation,
                "ts": ts,
            }
            for checkpoint, ts in (("llm_start", sent + 1), ("llm_end", sent + 1 + call_s))
        ]
    for row in data.timeline:
        # each level's host CPU from its start until the next level starts
        row["host_cpu_pct"] = next(
            (host for _, start, _, _, _, host in reversed(levels) if start <= row["ts"]), 0
        )
    data.meta["smoke"] = {"llm_p95_s": {"payload": 0.9}}
    return data


class LlmSlowedByHostTest(unittest.TestCase):
    def analyzed(self, host_cpu_pct=None, data=None):
        out = Path(tempfile.mkdtemp())
        meta = analyze.analyze(data or llm_run(host_cpu_pct), out)
        with open(out / "findings.csv", encoding="utf-8") as findings_file:
            found = [
                row for row in csv.DictReader(findings_file) if row["kind"] == "llm_slowed_by_host"
            ]
        return meta["phases"][0]["provider_health"]["slow_provider"], found

    def test_slow_calls_on_a_saturated_host_are_not_the_provider(self):
        slow_provider, found = self.analyzed(95)
        self.assertFalse(slow_provider)
        (finding,) = found
        self.assertEqual(
            (finding["severity"], finding["message"], finding["ts"]),
            (
                "warning",
                "LLM call time rose 0.60 s → 6.0 s while host CPU was 95 %: likely CPU contention, not the provider",
                "50",
            ),
        )

    def test_without_a_smoke_step_the_first_level_is_the_reference(self):
        data = llm_run(95)
        data.meta["smoke"] = {"ran": False}
        slow_provider, found = self.analyzed(data=data)
        self.assertFalse(slow_provider)  # no smoke reference: never claimed, as before
        self.assertEqual(
            [finding["message"] for finding in found],
            [
                "LLM call time rose 0.60 s → 6.0 s while host CPU was 95 %: likely CPU contention, not the provider"
            ],
        )

    def test_one_slow_level_on_an_idle_host_keeps_it_the_provider(self):
        data = llm_levels(
            [
                (20, 0, 5, 40, 0.6, 40),
                (160, 40, 45, 80, 6.0, 60),  # slow while the host had CPU to spare
                (320, 80, 85, 120, 6.0, 95),
            ]
        )
        slow_provider, found = self.analyzed(data=data)
        self.assertTrue(slow_provider)
        self.assertEqual(found, [])

    def test_slow_calls_on_an_idle_host_are_the_provider(self):
        slow_provider, found = self.analyzed(60)
        self.assertTrue(slow_provider)
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
