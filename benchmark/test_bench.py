"""Unit tests for benchmark/ (standard library only).

Run from the repo root:  python -m unittest discover -s benchmark -p "test_*.py"
"""

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

import api
import config
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


class ComposeParseTest(unittest.TestCase):
    def test_parse_ps_accepts_array_and_json_lines(self):
        row = {"Service": "crew", "State": "running", "Health": ""}
        self.assertEqual(stack.parse_ps(json.dumps([row])), [row])
        self.assertEqual(stack.parse_ps(json.dumps(row) + "\n" + json.dumps(row)), [row, row])
        self.assertEqual(stack.parse_ps(""), [])

    def test_read_env_file_skips_comments(self):
        folder = Path(tempfile.mkdtemp())
        (folder / ".env").write_text("# X=1\nA = 2 # note\nB='3'\n", encoding="utf-8")
        self.assertEqual(stack.read_env_file(folder / ".env"), {"A": "2", "B": "3"})


if __name__ == "__main__":
    unittest.main()
