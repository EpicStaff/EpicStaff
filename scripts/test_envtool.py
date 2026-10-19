"""Unit tests for scripts/envtool.py --update (standard library unittest; envtool needs PyYAML).

Run from the repo root:  python -m unittest scripts/test_envtool.py
"""

import contextlib
import io
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import envtool

SCHEMA = {
    "groups": {
        "crew": {
            "vars": {
                "CREW_LOG_LEVEL": {
                    "description": "Log level for crew.",
                    "default": {"prod": "INFO", "dev": "DEBUG"},
                },
                "CREW_PORT": {"description": "Crew port.", "default": 8000},
            }
        },
        "secrets": {
            "vars": {
                "DB_PASSWORD": {
                    "description": "Database password.",
                    "default": {"dev": "root_password"},
                },
            }
        },
    }
}
TODAY = date(2026, 1, 2)


class UpdateEnvFileTest(unittest.TestCase):
    def setUp(self):
        self.env_file = Path(tempfile.mkdtemp()) / ".env"

    def update(self, text: str, target: str = "prod"):
        self.env_file.write_text(text, encoding="utf-8", newline="")
        return envtool.update_env_file(SCHEMA, target, self.env_file, TODAY)

    def test_keeps_existing_lines_and_appends_missing_with_the_profile_default(self):
        original = "# my notes\nCREW_LOG_LEVEL=WARNING  # tuned by hand\n\nOTHER=1\n"
        added, needs_value = self.update(original)
        self.assertEqual(added, ["CREW_PORT"])
        self.assertEqual(needs_value, ["DB_PASSWORD"])
        text = self.env_file.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(original))
        self.assertEqual(
            text[len(original) :],
            "\n# Added by envtool --update on 2026-01-02 (prod defaults)\n"
            "\n# Crew port.\nCREW_PORT=8000\n"
            "\n# Database password.\n# DB_PASSWORD=<enter your value>\n",
        )

    def test_dev_profile_uses_dev_defaults(self):
        added, needs_value = self.update("CREW_PORT=1\n", target="dev")
        self.assertEqual(added, ["CREW_LOG_LEVEL", "DB_PASSWORD"])
        self.assertEqual(needs_value, [])
        text = self.env_file.read_text(encoding="utf-8")
        self.assertIn("(dev defaults)", text)
        self.assertIn("\nCREW_LOG_LEVEL=DEBUG\n", text)
        self.assertIn("\nDB_PASSWORD=root_password\n", text)

    def test_prod_profile_uses_prod_defaults(self):
        self.update("CREW_PORT=1\nDB_PASSWORD=secret\n")
        self.assertIn("\nCREW_LOG_LEVEL=INFO\n", self.env_file.read_text(encoding="utf-8"))

    def test_export_prefix_counts_as_set(self):
        added, _ = self.update("export CREW_LOG_LEVEL=INFO\n  export CREW_PORT = 1\n")
        self.assertEqual(added, [])

    def test_commented_variable_counts_as_missing(self):
        added, _ = self.update("# CREW_PORT=9000\nCREW_LOG_LEVEL=INFO\nDB_PASSWORD=x\n")
        self.assertEqual(added, ["CREW_PORT"])
        self.assertTrue(self.env_file.read_text(encoding="utf-8").endswith("\nCREW_PORT=8000\n"))

    def test_required_placeholder_already_present_is_reported_but_not_appended_again(self):
        original = "CREW_LOG_LEVEL=INFO\nCREW_PORT=1\n# DB_PASSWORD=<enter your value>\n"
        added, needs_value = self.update(original)
        self.assertEqual((added, needs_value), ([], ["DB_PASSWORD"]))
        self.assertEqual(self.env_file.read_text(encoding="utf-8"), original)

    def test_exported_required_placeholder_is_not_appended_again(self):
        original = "CREW_LOG_LEVEL=INFO\nCREW_PORT=1\n# export DB_PASSWORD=<enter your value>\n"
        self.assertEqual(self.update(original), ([], ["DB_PASSWORD"]))
        self.assertEqual(self.env_file.read_text(encoding="utf-8"), original)

    def test_byte_order_mark_does_not_hide_the_first_variable(self):
        original = "﻿CREW_LOG_LEVEL=INFO\nCREW_PORT=1\nDB_PASSWORD=x\n"
        self.assertEqual(self.update(original), ([], []))
        self.assertEqual(self.env_file.read_bytes(), original.encode())

    def test_nothing_to_add_leaves_the_file_byte_identical(self):
        original = "CREW_LOG_LEVEL=INFO\r\nCREW_PORT=1\r\nDB_PASSWORD=x"
        self.assertEqual(self.update(original), ([], []))
        self.assertEqual(self.env_file.read_bytes(), original.encode())

    def test_file_without_final_newline_and_crlf_endings_stays_consistent(self):
        original = "CREW_LOG_LEVEL=INFO\r\nDB_PASSWORD=x"
        self.update(original)
        data = self.env_file.read_bytes()
        self.assertTrue(data.startswith(original.encode() + b"\r\n"))
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))

    def test_summary(self):
        self.assertEqual(envtool.update_summary([], []), "nothing to add")
        self.assertEqual(
            envtool.update_summary(["A", "B"], ["C"]), "added 2: A, B; needs a value: C"
        )
        self.assertEqual(envtool.update_summary([], ["C"]), "needs a value: C")


class MainTest(unittest.TestCase):
    def test_update_of_a_missing_file_tells_to_generate_it_first(self):
        missing = Path(tempfile.mkdtemp()) / ".env"
        with self.assertRaises(SystemExit) as raised:
            envtool.main(["--update", "--dev", "--env-file", str(missing)])
        self.assertIn("without --update", str(raised.exception.code))
        self.assertFalse(missing.exists())

    def test_update_prints_the_summary(self):
        env_file = Path(tempfile.mkdtemp()) / ".env"
        env_file.write_text("CREW_PORT=1\n", encoding="utf-8")
        schema_file = env_file.with_name("env.yaml")
        schema_file.write_text(
            "groups:\n  crew:\n    vars:\n      CREW_PORT:\n        default: 8000\n"
            "      CREW_HOST:\n        default: crew\n",
            encoding="utf-8",
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            envtool.main(
                ["--update", "--env-file", str(env_file), "--schema-file", str(schema_file)]
            )
        self.assertIn("added 1: CREW_HOST", output.getvalue())
        self.assertTrue(env_file.read_text(encoding="utf-8").endswith("\nCREW_HOST=crew\n"))


if __name__ == "__main__":
    unittest.main()
