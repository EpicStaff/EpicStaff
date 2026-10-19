#!/usr/bin/env python3
"""Tests for check_env_conventions.py: each rule passes good input and catches bad input.

No pytest dependency, run directly:
    python3 .github/scripts/test_check_env_conventions.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import check_env_conventions as check  # noqa: E402

TRUE_VALUES = frozenset({"1", "on", "t", "true", "y", "yes"})
FALSE_VALUES = frozenset({"0", "f", "false", "n", "no", "off"})

HELPER = """\
# >>> env_bool
env_bool() {
  case "$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')" in
    1|on|t|true|y|yes) return 0 ;;
    0|f|false|n|no|off) return 1 ;;
  esac
  exit 64
}
# <<< env_bool
""".splitlines()


def shell(*body: str, helper: list[str] = HELPER) -> list[str]:
    return ["#!/bin/sh", *helper, *body]


class ComposeTest(unittest.TestCase):
    def test_required_and_escaped_interpolations_pass(self):
        lines = [
            "  DB_PORT: ${DB_PORT:?}",
            '  TAG: "${IMAGE_TAG:?set a release tag}"',
            '  test: ["CMD-SHELL", "redis-cli -p $${REDIS_PORT} ping"]',
            "  DJANGO_EMAIL_HOST: ${DJANGO_EMAIL_HOST?}",
            "#  OLD: ${COMMENTED_OUT}",
        ]
        self.assertEqual(check.check_compose({"docker-compose.yaml": lines}), [])

    def test_defaults_bare_and_unlisted_may_be_empty_are_caught(self):
        lines = [
            "  A: ${A:-false}",
            "  B: ${B}",
            "  C: ${C-x}",
            "  D: $D",
            "  E: ${E?}",
        ]
        violations = check.check_compose({"docker-compose.yaml": lines})
        self.assertEqual(len(violations), len(lines))


class PythonTest(unittest.TestCase):
    def test_reads_that_are_not_boolean_parsing_pass(self):
        for line in [
            'DEBUG = env.bool("DJANGO_DEBUG")',
            'path = os.getenv("CONTAINER_SAVEFILES_PATH", ".")',
            'IS_PROD = os.getenv("ENVIRONMENT") == "production"',
            'LEVEL = os.getenv("LOG_LEVEL", "info").lower()',
            'if env.str("MODE").lower() in ("dev", "prod"):',
            "overwrite = strtobool(overwrite)",
        ]:
            with self.subTest(line=line):
                self.assertEqual(check.check_python({"settings.py": [line]}), [])

    def test_ad_hoc_boolean_parsing_is_caught(self):
        for line in [
            'DEBUG = os.getenv("DEBUG", "False") in ["True", "true"]',
            'ENABLED = os.environ.get("ENABLED") == "1"',
            'ON = os.environ["ON"].lower() == "on"',
            'FLAG = env.str("FLAG").lower() == "true"',
            'FLAG = env.str("FLAG").strip().lower() in ("1", "yes")',
            'FLAG = "true" == os.environ.get("FLAG")',
            'DEBUG = bool(int(os.getenv("DEBUG", "0")))',
            'FLAG = strtobool(os.getenv("FLAG", "no"))',
            "from distutils.util import strtobool",
        ]:
            with self.subTest(line=line):
                self.assertEqual(len(check.check_python({"settings.py": [line]})), 1)

    def test_envtools_and_test_files_are_exempt(self):
        line = 'value = os.environ.get("X") == "1"'
        for path in [
            "src/shared/envtools.py",
            "src/sandbox/tests/chain_tests/test_env.py",
            "src/crew/conftest.py",
            ".github/scripts/test_check_env_conventions.py",
        ]:
            with self.subTest(path=path):
                self.assertEqual(check.check_python({path: [line]}), [])


class ShellTest(unittest.TestCase):
    def check(self, files):
        return check.check_shell(files, TRUE_VALUES, FALSE_VALUES)

    def test_helper_use_and_local_or_non_boolean_comparisons_pass(self):
        script = shell(
            "if env_bool AUDIT_TRAIL_ENABLED; then echo on; fi",
            'if [ "$failed" = "1" ]; then exit 1; fi',
            'if [[ "$1" = "healthcheck-users" ]]; then check; fi',
            'case "$MODE" in',
            "  prod|dev) run ;;",
            "esac",
            'case "$1" in',
            "  true) echo positional ;;",
            "esac",
        )
        self.assertEqual(self.check({"a.sh": script, "b.sh": shell()}), [])

    def test_ad_hoc_parsing_of_an_env_variable_is_caught(self):
        for body in [
            ['if [ "$NUKE_DB" = "true" ]; then nuke; fi'],
            ['if [ "${RELOAD:-0}" = 1 ]; then reload; fi'],
            ['if [ "true" = "$NUKE_DB" ]; then nuke; fi'],
            ["flag=$(echo \"$FLAG\" | tr '[:upper:]' '[:lower:]')"],
            ['flag=$(echo "$FLAG" | tr "[:upper:]" "[:lower:]")'],
            ['flag=$(echo "$FLAG" | tr A-Z a-z)'],
            ['if [ "${FLAG,,}" = yes ]; then go; fi'],
            ['case "$AUDIT_TRAIL_ENABLED" in', "  True|true) start ;;", "  *) exit 0 ;;", "esac"],
        ]:
            with self.subTest(body=body):
                self.assertEqual(len(self.check({"a.sh": shell(*body)})), 1)

    def test_a_call_without_the_helper_block_is_caught(self):
        script = ["#!/bin/sh", "if env_bool NUKE_DB; then nuke; fi"]
        self.assertEqual(len(self.check({"a.sh": script})), 1)

    def test_drifted_copy_is_caught(self):
        drifted = [line.replace("1|on|t|true|y|yes", "1|true") for line in HELPER]
        violations = self.check({"a.sh": shell(), "b.sh": shell(helper=drifted)})
        self.assertEqual(violations, ["b.sh: env_bool differs from the copy in a.sh"])

    def test_values_differing_from_env_bool_are_caught(self):
        violations = check.check_shell({"a.sh": shell()}, TRUE_VALUES - {"t"}, FALSE_VALUES)
        self.assertEqual(len(violations), 1)
        self.assertIn("Env.bool accepts", violations[0])


if __name__ == "__main__":
    unittest.main()
