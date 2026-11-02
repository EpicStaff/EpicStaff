"""Unit tests for scripts/envtool.py --update (standard library unittest; envtool needs PyYAML).

Run from the repo root:  python -m unittest scripts/test_envtool.py
"""

import contextlib
import io
import os
import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import envtool
from src.shared.humanize import to_time

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

    def test_override_fills_a_required_variable(self):
        self.env_file.write_text("CREW_LOG_LEVEL=INFO\n", encoding="utf-8")
        added, needs_value = envtool.update_env_file(
            SCHEMA, "prod", self.env_file, TODAY, overrides={"DB_PASSWORD": "generated"}
        )
        self.assertEqual((added, needs_value), (["CREW_PORT", "DB_PASSWORD"], []))
        self.assertTrue(
            self.env_file.read_text(encoding="utf-8").endswith("\nDB_PASSWORD=generated\n")
        )

    def test_override_replaces_an_existing_placeholder_instead_of_skipping_it(self):
        original = "CREW_LOG_LEVEL=INFO\nCREW_PORT=1\n# DB_PASSWORD=<enter your value>\n"
        self.env_file.write_text(original, encoding="utf-8")
        added, _ = envtool.update_env_file(
            SCHEMA, "prod", self.env_file, TODAY, overrides={"DB_PASSWORD": "generated"}
        )
        self.assertEqual(added, ["DB_PASSWORD"])
        text = self.env_file.read_text(encoding="utf-8")
        self.assertEqual(envtool.read_env_values(text)["DB_PASSWORD"], "generated")

    def test_summary(self):
        self.assertEqual(envtool.update_summary([], []), "nothing to add")
        self.assertEqual(
            envtool.update_summary(["A", "B"], ["C"]), "added 2: A, B; needs a value: C"
        )
        self.assertEqual(envtool.update_summary([], ["C"]), "needs a value: C")


class GenerateEnvFileTest(unittest.TestCase):
    def test_override_replaces_the_default(self):
        env_file = Path(tempfile.mkdtemp()) / ".env"
        schema_file = envtool.BASE_DIR / "env.yaml"
        envtool.generate_env_file(
            SCHEMA, "prod", schema_file, env_file, overrides={"CREW_LOG_LEVEL": "WARNING"}
        )
        text = env_file.read_text(encoding="utf-8")
        self.assertIn("\nCREW_LOG_LEVEL=WARNING\n", text)
        self.assertIn("\n# DB_PASSWORD=<enter your value>\n", text)


class EnvFileValuesTest(unittest.TestCase):
    def setUp(self):
        self.env_file = Path(tempfile.mkdtemp()) / ".env"

    def test_read_handles_export_quotes_comments_and_spaces(self):
        text = "﻿export A = 'x y'\nB=2  # note\n# C=3\nD=\"q\"\nE=a#b\nF='x # y'\n"
        text += "G=\"root_password\" # c\nI='x # y' # z\n"
        self.assertEqual(
            envtool.read_env_values(text),
            {
                "A": "x y",
                "B": "2",
                "D": "q",
                "E": "a#b",
                "F": "x # y",
                "G": "root_password",
                "I": "x # y",
            },
        )

    def test_rewrite_of_a_quoted_value_with_a_comment_keeps_the_comment(self):
        self.env_file.write_text("CHAT_ENABLED='x # y' # z\n", encoding="utf-8")
        envtool.rewrite_env_values(self.env_file, {"CHAT_ENABLED": "true"})
        self.assertEqual(self.env_file.read_text(encoding="utf-8"), "CHAT_ENABLED=true # z\n")

    def test_rewrite_changes_only_the_value_and_keeps_crlf_bom_and_comments(self):
        original = "﻿# keep\r\nexport CHAT_ENABLED=false  # was off\r\nOTHER=1\r\n"
        self.env_file.write_bytes(original.encode())
        envtool.rewrite_env_values(self.env_file, {"CHAT_ENABLED": "true"})
        self.assertEqual(self.env_file.read_bytes(), original.replace("=false", "=true").encode())

    def test_rewrite_fills_a_placeholder_and_appends_a_missing_name(self):
        self.env_file.write_text("# DB_PASSWORD=<enter your value>\nA=1\n", encoding="utf-8")
        envtool.rewrite_env_values(self.env_file, {"DB_PASSWORD": "s3cret", "NEW": "v"})
        text = self.env_file.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("DB_PASSWORD=s3cret\nA=1\n"))
        self.assertTrue(text.endswith("\nNEW=v\n"))

    def test_rewrite_keeps_the_file_mode(self):
        self.env_file.write_text("A=1\n", encoding="utf-8")
        self.env_file.chmod(0o600)
        envtool.rewrite_env_values(self.env_file, {"A": "2"})
        self.assertEqual(self.env_file.stat().st_mode & 0o777, 0o600)

    def test_rewrite_through_a_symlink_keeps_the_link(self):
        target = self.env_file.with_name("real.env")
        target.write_text("A=1\n", encoding="utf-8")
        self.env_file.symlink_to(target)
        envtool.rewrite_env_values(self.env_file, {"A": "2"})
        self.assertTrue(self.env_file.is_symlink())
        self.assertEqual(target.read_text(encoding="utf-8"), "A=2\n")

    def test_private_files_are_created_owner_only_whatever_the_umask(self):
        previous = os.umask(0)
        try:
            path = self.env_file.with_name("secret.env")
            path.write_text("old\n", encoding="utf-8")
            path.chmod(0o644)
            envtool.write_private(path, b"A=1\n")
        finally:
            os.umask(previous)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.read_bytes(), b"A=1\n")

    def test_failed_rewrite_leaves_the_file_and_no_temporary_behind(self):
        self.env_file.write_text("A=1\n", encoding="utf-8")
        with (
            mock.patch.object(envtool.os, "replace", side_effect=OSError("disk full")),
            self.assertRaises(OSError),
        ):
            envtool.rewrite_env_values(self.env_file, {"A": "2"})
        self.assertEqual(self.env_file.read_text(encoding="utf-8"), "A=1\n")
        self.assertEqual(sorted(path.name for path in self.env_file.parent.iterdir()), [".env"])

    def test_rewrite_of_a_file_without_final_newline(self):
        self.env_file.write_text("A=1", encoding="utf-8")
        envtool.rewrite_env_values(self.env_file, {"NEW": "v"})
        self.assertEqual(self.env_file.read_text(encoding="utf-8"), "A=1\nNEW=v\n")


def real_schema() -> dict:
    return envtool.load_schema(envtool.BASE_DIR / "env.yaml")


class SecretTest(unittest.TestCase):
    def test_secrets_are_letters_and_digits(self):
        for name in envtool.GENERATED_SECRETS:
            if name != "OPENSEARCH_PASSWORD":
                self.assertRegex(envtool.generate_secret(name), r"^[A-Za-z0-9]{32,}$", name)

    def test_opensearch_password_meets_the_strength_policy(self):
        for _ in range(50):
            value = envtool.generate_secret("OPENSEARCH_PASSWORD")
            self.assertRegex(value, r"^[A-Za-z0-9_]{8,}$")
            for pattern in (r"[A-Z]", r"[a-z]", r"[0-9]", r"_"):
                self.assertRegex(value, pattern)

    def test_avatar_signing_secret_is_hex(self):
        # nginx pastes it literally into its config, so env.yaml allows hex only.
        self.assertRegex(envtool.generate_secret("AVATAR_URL_SIGNING_SECRET"), r"^[0-9a-f]{64}$")

    def test_two_calls_differ(self):
        self.assertNotEqual(
            envtool.generate_secret("DB_PASSWORD"), envtool.generate_secret("DB_PASSWORD")
        )

    def test_production_usernames_differ_from_dev_defaults(self):
        dev_defaults = envtool.target_defaults(real_schema(), "dev")
        for name, value in envtool.PRODUCTION_USERNAMES.items():
            self.assertNotEqual(value, dev_defaults[name], name)


class FeatureProfilesTest(unittest.TestCase):
    def test_parse_tolerates_spaces_none_and_empty(self):
        self.assertEqual(envtool.parse_profiles("dev, chat"), ["dev", "chat"])
        self.assertEqual(envtool.parse_profiles("none"), [])
        self.assertEqual(envtool.parse_profiles(""), [])

    def test_local_keeps_dev_and_unknown_profiles(self):
        values = envtool.feature_values(
            {"CHAT_ENABLED": False, "AUDIT_TRAIL_ENABLED": True, "PLUGINS_ENABLED": False},
            "mcp,dev,chat",
            local=True,
        )
        self.assertEqual(
            values,
            {
                "CHAT_ENABLED": "false",
                "AUDIT_TRAIL_ENABLED": "true",
                "PLUGINS_ENABLED": "false",
                "COMPOSE_PROFILES": "mcp,dev,auditor",
            },
        )

    def test_production_with_nothing_enabled_writes_none(self):
        values = envtool.feature_values(
            {"CHAT_ENABLED": False, "AUDIT_TRAIL_ENABLED": False, "PLUGINS_ENABLED": False},
            "chat,auditor,plugins",
            local=False,
        )
        self.assertEqual(values["COMPOSE_PROFILES"], "none")

    def test_production_drops_the_dev_profile(self):
        values = envtool.feature_values(
            {"CHAT_ENABLED": True, "AUDIT_TRAIL_ENABLED": False, "PLUGINS_ENABLED": False},
            "dev,auditor",
            local=False,
        )
        self.assertEqual(values["COMPOSE_PROFILES"], "chat")

    def test_local_adds_dev_when_missing(self):
        values = envtool.feature_values(
            {"CHAT_ENABLED": True, "AUDIT_TRAIL_ENABLED": False, "PLUGINS_ENABLED": True},
            "none",
            local=True,
        )
        self.assertEqual(values["COMPOSE_PROFILES"], "dev,chat,plugins")


class ProductionValuesTest(unittest.TestCase):
    def test_url_is_normalised_and_server_name_drops_the_port(self):
        values = envtool.production_values("HTTPS://Host.example.com:8443/", "nginx-tls", "v1.3.0")
        for name in (
            "DJANGO_FRONTEND_BASE_URL",
            "CHAT_PUBLIC_BASE_URL",
            "DJANGO_CORS_ALLOWED_ORIGINS",
        ):
            self.assertEqual(values[name], "https://host.example.com:8443", name)
        self.assertEqual(values["NGINX_SERVER_NAME"], "host.example.com")
        self.assertEqual(values["IMAGE_TAG"], "v1.3.0")

    def test_url_with_a_path_query_or_no_scheme_is_refused(self):
        for url in (
            "https://host.example.com/app",
            "https://host.example.com/?a=1",
            "host.example.com",
            "ftp://host",
            "https://",
        ):
            with self.assertRaises(ValueError, msg=url):
                envtool.normalize_public_url(url)

    def test_serving_modes(self):
        self.assertEqual(
            envtool.production_values("https://host", "proxy-tls", "v1")["NGINX_SSL_MODE"], "off"
        )
        plain = envtool.production_values("http://10.0.0.5", "http", "v1")
        self.assertEqual(
            (
                plain["NGINX_SSL_MODE"],
                plain["NGINX_HSTS_ENABLED"],
                plain["DJANGO_REFRESH_COOKIE_SECURE"],
            ),
            ("off", "false", "false"),
        )
        tls = envtool.production_values("https://host", "nginx-tls", "v1")
        self.assertEqual(
            (tls["NGINX_SSL_MODE"], tls["NGINX_HSTS_ENABLED"], tls["DJANGO_REFRESH_COOKIE_SECURE"]),
            ("on", "true", "true"),
        )

    def test_scheme_must_match_the_serving_mode(self):
        with self.assertRaises(ValueError):
            envtool.check_scheme_matches("http://host", "nginx-tls")
        with self.assertRaises(ValueError):
            envtool.check_scheme_matches("http://host", "proxy-tls")
        with self.assertRaises(ValueError):
            envtool.production_values("https://host", "http", "v1")

    def test_latest_and_blank_tags_are_refused(self):
        for tag in ("latest", " LATEST ", ""):
            with self.assertRaises(ValueError, msg=tag):
                envtool.validate_image_tag(tag)
        self.assertEqual(envtool.validate_image_tag(" v1.3.0 "), "v1.3.0")

    def test_fixed_values_and_usernames_are_included(self):
        values = envtool.production_values("https://host", "nginx-tls", "v1")
        self.assertEqual(values["DJANGO_AUTH_URL"], "http://django:8000")
        self.assertEqual(values["DB_USER"], "epicstaff")


class SchemaCoverageTest(unittest.TestCase):
    def test_every_production_required_variable_is_generated_asked_or_filled(self):
        self.assertEqual(envtool.production_coverage_gaps(real_schema()), [])

    def test_every_name_the_wizard_writes_exists_in_the_schema(self):
        written = set(envtool.production_values("https://host", "nginx-tls", "v1"))
        written |= set(envtool.GENERATED_SECRETS) | {"COMPOSE_PROFILES"}
        written |= set(envtool.RETENTION_DAYS)
        for group in (*envtool.SERVING_MODES.values(), *envtool.SERVER_SIZE_VALUES.values()):
            written |= set(group)
        for feature in envtool.FEATURES:
            written |= {feature.flag, *feature.settings}
        written |= set(envtool.advanced_values(None, "5m", "INFO", ALL_ON, real_schema(), {}))
        known = set(envtool.target_defaults(real_schema(), "prod"))
        self.assertEqual(sorted(written - known), [])

    def test_a_new_required_variable_is_reported(self):
        schema = {"groups": {"new": {"vars": {"BRAND_NEW": {"default": {"dev": "x"}}}}}}
        self.assertEqual(envtool.production_coverage_gaps(schema), ["BRAND_NEW"])


class SetupWizardTest(unittest.TestCase):
    def setUp(self):
        self.env_file = Path(tempfile.mkdtemp()) / ".env"
        self.schema = real_schema()

    def run_setup(self, target: str, answers: list) -> tuple[dict[str, str], str]:
        output = io.StringIO()
        with mock.patch("builtins.input", side_effect=answers), contextlib.redirect_stdout(output):
            envtool.run_setup(self.schema, target, self.env_file)
        return envtool.read_env_values(self.env_file.read_text(encoding="utf-8")), output.getvalue()

    def test_local_new_file_asks_only_features(self):
        values, _ = self.run_setup("dev", ["n", "y", ""])
        self.assertEqual(values["CHAT_ENABLED"], "false")
        self.assertEqual(values["AUDIT_TRAIL_ENABLED"], "true")
        self.assertEqual(values["COMPOSE_PROFILES"], "dev,auditor")
        self.assertEqual(values["DB_PASSWORD"], "root_password")
        self.assertEqual(values["PLUGINS_ENABLED"], "false")
        for name in envtool.PLUGIN_SECRETS:
            self.assertRegex(values[name], r"^[A-Za-z0-9]{32,}$", name)

    def test_local_plugins_use_the_localhost_host_django_accepts(self):
        values, output = self.run_setup("dev", ["n", "y", "y"])
        self.assertEqual(values["COMPOSE_PROFILES"], "dev,auditor,plugins")
        self.assertEqual(values["DJANGO_FRONTEND_BASE_URL"], "http://epicstaff.localhost")
        self.assertEqual(values["NGINX_SERVER_NAME"], "epicstaff.localhost")
        self.assertIn("http://epicstaff.localhost", output)

    def test_production_with_plugins_asks_their_domain(self):
        values, output = self.run_setup(
            "prod",
            [
                "https://es.example.com", "1", "n", "n", "y",
                "plugins.invalid", "example.com", "Plugins.Example.com.", "v1", "1", "n",
            ],
        )  # fmt: skip
        self.assertEqual(values["PLUGINS_ENABLED"], "true")
        self.assertEqual(values["COMPOSE_PROFILES"], "plugins")
        self.assertEqual(values["PLUGINS_BASE_DOMAIN"], "plugins.example.com")
        for name in envtool.PLUGIN_SECRETS:
            self.assertRegex(values[name], r"^[A-Za-z0-9]{32,}$", name)
        self.assertIn("*.plugins.example.com", output)

    def test_plugins_stay_off_for_an_ip_or_plain_http_host(self):
        for public_url in ("http://10.0.0.5", "http://es.example.com"):
            self.env_file.unlink(missing_ok=True)
            values, output = self.run_setup(
                "prod", [public_url, "3", "n", "n", "y", "v1", "1", "n"]
            )
            self.assertEqual(values["PLUGINS_ENABLED"], "false", public_url)
            self.assertNotIn("plugins", values["COMPOSE_PROFILES"])
            self.assertIn("Plugins stay off", output)

    def test_plugins_over_plain_http_need_a_localhost_domain(self):
        values, output = self.run_setup(
            "prod",
            [
                "http://es.localhost", "3", "n", "n", "y",
                "plugins.example.com", "p.localhost", "v1", "1", "n",
            ],
        )  # fmt: skip
        self.assertEqual(values["PLUGINS_BASE_DOMAIN"], "p.localhost")
        self.assertNotIn("Point *.", output)

    def test_turning_plugins_on_fills_missing_secrets_and_keeps_set_ones(self):
        envtool.main(["--dev", "--env-file", str(self.env_file)])
        text = self.env_file.read_text(encoding="utf-8")
        text = text.replace(
            "\nPLUGINS_DB_ADMIN_PASSWORD=none\n", "\nPLUGINS_DB_ADMIN_PASSWORD=keepme123\n"
        )
        self.env_file.write_text(text, encoding="utf-8")
        # The dev domain default is valid, so it is not asked again.
        values, _ = self.run_setup("dev", ["1", "", "", "y"])
        self.assertEqual(values["PLUGINS_ENABLED"], "true")
        self.assertEqual(values["COMPOSE_PROFILES"], "dev,chat,auditor,plugins")
        self.assertEqual(values["PLUGINS_BASE_DOMAIN"], "plugins.epicstaff.localhost")
        self.assertEqual(values["DJANGO_FRONTEND_BASE_URL"], "http://epicstaff.localhost")
        self.assertEqual(values["PLUGINS_DB_ADMIN_PASSWORD"], "keepme123")
        self.assertRegex(values["PLUGINS_NODE_KEY"], r"^[A-Za-z0-9]{32,}$")

    def test_add_missing_settings_locally_generates_plugin_secrets(self):
        self.env_file.write_text("IMAGE_TAG=latest\n", encoding="utf-8")
        values, _ = self.run_setup("dev", ["3"])
        for name in envtool.PLUGIN_SECRETS:
            self.assertRegex(values[name], r"^[A-Za-z0-9]{32,}$", name)

    def test_production_new_file(self):
        values, output = self.run_setup(
            "prod", ["https://es.example.com", "1", "y", "n", "n", "latest", "v1.3.0", "3", "n"]
        )
        self.assertNotRegex(
            self.env_file.read_text(encoding="utf-8"), r"(?m)^# \w+=<enter your value>$"
        )
        self.assertEqual(values["IMAGE_TAG"], "v1.3.0")
        for name in envtool.RETENTION_DAYS:
            self.assertEqual(values[name], "90", name)
        self.assertEqual(values["NGINX_SSL_MODE"], "on")
        self.assertEqual(values["NGINX_SERVER_NAME"], "es.example.com")
        self.assertEqual(values["COMPOSE_PROFILES"], "chat")
        self.assertEqual(values["CHAT_ENABLED"], "true")
        self.assertEqual(values["DB_USER"], "epicstaff")
        self.assertRegex(values["DJANGO_API_KEY"], r"^[A-Za-z0-9]{32,}$")
        for name in envtool.production_required(self.schema):
            self.assertTrue(values.get(name), name)
        self.assertIn("create_superadmin", output)
        self.assertIn("src/nginx/certs", output)

    def test_wizard_files_are_private(self):
        self.run_setup("prod", ["https://es.example.com", "1", "n", "n", "n", "v1", "1", "n"])
        self.assertEqual(self.env_file.stat().st_mode & 0o777, 0o600)

    def test_wizard_header_warns_against_plain_regeneration(self):
        self.run_setup("prod", ["https://es.example.com", "1", "n", "n", "n", "v1", "1", "n"])
        header = self.env_file.read_text(encoding="utf-8").split("\n# Deploy\n")[0]
        self.assertIn("envtool.py --setup", header)
        self.assertIn("overwrites this file", header)
        self.assertNotIn("Regenerate it with", header)

    def test_proxy_in_front_points_at_the_proxy_count(self):
        _, behind_proxy = self.run_setup(
            "prod", ["https://es.example.com", "2", "n", "n", "n", "v1", "1", "n"]
        )
        self.assertIn("DJANGO_NUM_PROXIES", behind_proxy)
        self.env_file.unlink()
        _, nginx_tls = self.run_setup(
            "prod", ["https://es.example.com", "1", "n", "n", "n", "v1", "1", "n"]
        )
        self.assertNotIn("DJANGO_NUM_PROXIES", nginx_tls)

    def test_production_advanced_settings(self):
        values, _ = self.run_setup(
            "prod", ["https://es.example.com", "1", "y", "n", "n", "v1", "1", "y", "3", "3", "1"]
        )
        self.assertEqual(values["DJANGO_SGI_WORKERS"], "3")
        self.assertEqual(values["DJANGO_DB_POOL_MAX_SIZE"], "12")
        self.assertEqual(values["CHAT_WORKERS"], "4")
        self.assertEqual(values["SANDBOX_MAX_EXECUTION_TIMEOUT"], "2h")
        self.assertEqual(values["CREW_CODE_RESULT_TIMEOUT"], "130m")
        self.assertEqual(values["DJANGO_LOG_LEVEL"], "DEBUG")

    def test_tune_rewrites_only_its_lines_and_skips_chat_when_off(self):
        envtool.main(["--env-file", str(self.env_file)])
        original = self.env_file.read_text(encoding="utf-8").splitlines()
        # Tune lists "Keep current" first: medium is 3, five minutes is 2, logging is kept.
        _, output = self.run_setup("prod", ["2", "3", "2", "1"])
        changed = set(self.env_file.read_text(encoding="utf-8").splitlines()) - set(original)
        self.assertEqual(
            changed,
            {
                "DJANGO_SGI_WORKERS=2",
                "SANDBOX_MAX_EXECUTION_TIMEOUT=5m",
                "CREW_CODE_RESULT_TIMEOUT=15m",
            },
        )
        self.assertIn("docker compose up -d", output)

    def test_verbose_logging_reminds_to_switch_back(self):
        _, created = self.run_setup(
            "prod", ["https://es.example.com", "1", "n", "n", "n", "v1", "1", "y", "1", "2", "1"]
        )
        self.assertIn("back to INFO", created)
        # Tune lists "Keep current" first, so DEBUG is 2 and WARNING is 4.
        _, tuned = self.run_setup("prod", ["2", "1", "1", "2"])
        self.assertIn("back to INFO", tuned)
        values, quiet = self.run_setup("prod", ["2", "1", "1", "4"])
        self.assertNotIn("back to INFO", quiet)
        self.assertEqual(values["DJANGO_LOG_LEVEL"], "WARNING")
        self.assertEqual(values["CREW_LOG_LEVEL"], "WARNING")

    def test_tune_keeping_everything_leaves_the_file_byte_identical(self):
        envtool.main(["--dev", "--env-file", str(self.env_file)])
        text = self.env_file.read_text(encoding="utf-8")
        text = text.replace(
            "\nSANDBOX_MAX_EXECUTION_TIMEOUT=30m\n", "\nSANDBOX_MAX_EXECUTION_TIMEOUT=none\n"
        )
        text = text.replace("\nCREW_LOG_LEVEL=DEBUG\n", "\nCREW_LOG_LEVEL=BENCH\n")
        self.env_file.write_text(text, encoding="utf-8")
        self.run_setup("dev", ["2", "1", "1", "1"])
        self.assertEqual(self.env_file.read_text(encoding="utf-8"), text)

    def test_tune_lowers_a_default_execution_timeout_above_the_new_limit(self):
        envtool.main(["--env-file", str(self.env_file)])
        text = self.env_file.read_text(encoding="utf-8")
        self.env_file.write_text(
            text.replace(
                "\nSANDBOX_DEFAULT_EXECUTION_TIMEOUT=5m\n",
                "\nSANDBOX_DEFAULT_EXECUTION_TIMEOUT=10m\n",
            ),
            encoding="utf-8",
        )
        values, _ = self.run_setup("prod", ["2", "1", "2", "1"])
        self.assertEqual(values["SANDBOX_MAX_EXECUTION_TIMEOUT"], "5m")
        self.assertEqual(values["SANDBOX_DEFAULT_EXECUTION_TIMEOUT"], "5m")

    def test_scheme_mismatch_reasks_the_serving_mode(self):
        values, _ = self.run_setup(
            "prod", ["http://10.0.0.5", "1", "3", "n", "n", "n", "v1", "1", "n"]
        )
        self.assertEqual(values["NGINX_SSL_MODE"], "off")
        self.assertEqual(values["NGINX_HSTS_ENABLED"], "false")

    def test_change_features_rewrites_only_feature_lines(self):
        envtool.main(["--dev", "--env-file", str(self.env_file)])
        original = self.env_file.read_text(encoding="utf-8").splitlines()
        _, output = self.run_setup("dev", ["1", "n", "y", ""])
        changed = set(self.env_file.read_text(encoding="utf-8").splitlines()) - set(original)
        self.assertEqual(
            changed,
            {"CHAT_ENABLED=false", "AUDIT_TRAIL_ENABLED=true", "COMPOSE_PROFILES=dev,auditor"},
        )
        self.assertIn("docker compose stop chat chatdb", output)
        self.assertNotIn("stop auditor", output)

    def test_add_missing_settings_in_production_generates_secrets(self):
        self.env_file.write_text("IMAGE_TAG=v1\n", encoding="utf-8")
        values, _ = self.run_setup("prod", ["3"])
        self.assertEqual(values["IMAGE_TAG"], "v1")
        self.assertRegex(values["DB_PASSWORD"], r"^[A-Za-z0-9]{32,}$")

    def test_start_over_in_production_drops_dev_values_and_keeps_real_ones(self):
        self.env_file.write_text(
            "DB_PASSWORD=root_password\nREDIS_PASSWORD=keepme123\nCHAT_DB_USER=chat\n",
            encoding="utf-8",
        )
        values, output = self.run_setup(
            "prod", ["4", "n", "y", "https://es.example.com", "2", "n", "n", "n", "v1", "1", "n"]
        )
        self.assertEqual(values["REDIS_PASSWORD"], "keepme123")
        self.assertEqual(values["CHAT_DB_USER"], "chat")
        self.assertNotIn(values["DB_PASSWORD"], ("root_password", ""))
        self.assertRegex(values["DJANGO_API_KEY"], r"^[A-Za-z0-9]{32,}$")
        self.assertIn("DB_PASSWORD", output)

    def test_start_over_drops_a_quoted_dev_value(self):
        self.env_file.write_text('DB_PASSWORD="root_password"  # dev\n', encoding="utf-8")
        values, output = self.run_setup(
            "prod", ["4", "n", "y", "https://es.example.com", "2", "n", "n", "n", "v1", "1", "n"]
        )
        self.assertNotIn("root_password", values["DB_PASSWORD"])
        self.assertIn("DB_PASSWORD", output)

    def test_change_features_reads_a_quoted_flag_with_a_comment(self):
        envtool.main(["--dev", "--env-file", str(self.env_file)])
        text = self.env_file.read_text(encoding="utf-8")
        self.env_file.write_text(
            text.replace("\nCHAT_ENABLED=true\n", '\nCHAT_ENABLED="true" # on\n'), encoding="utf-8"
        )
        _, output = self.run_setup("dev", ["1", "", "", ""])
        self.assertNotIn("out of sync", output)
        self.assertNotIn("docker compose stop", output)

    def test_start_over_keeps_a_private_backup_of_the_old_file(self):
        original = "DB_PASSWORD=keepme123\nDB_NAME=custom_db\n"
        self.env_file.write_text(original, encoding="utf-8")
        self.run_setup(
            "prod", ["4", "y", "https://es.example.com", "2", "n", "n", "n", "v1", "1", "n"]
        )
        backup = self.env_file.with_name(".env.backup.env")
        self.assertEqual(backup.read_text(encoding="utf-8"), original)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)

    def test_start_over_in_production_rotates_keys_and_drops_historically_published_values(self):
        self.env_file.write_text(
            "DJANGO_API_KEY=epicstaff_realtime_api_key\nAUDIT_JWT_SECRET=keepme123\n"
            "REDIS_PASSWORD=redis_password\nMANAGER_DB_PASSWORD=manager_db_password\n"
            "DB_PASSWORD=keepme456\n",
            encoding="utf-8",
        )
        values, output = self.run_setup(
            "prod", ["4", "n", "y", "https://es.example.com", "2", "n", "n", "n", "v1", "1", "n"]
        )
        self.assertNotEqual(values["DJANGO_API_KEY"], "epicstaff_realtime_api_key")
        self.assertNotEqual(values["AUDIT_JWT_SECRET"], "keepme123")
        self.assertNotEqual(values["REDIS_PASSWORD"], "redis_password")
        self.assertNotEqual(values["MANAGER_DB_PASSWORD"], "manager_db_password")
        self.assertEqual(values["DB_PASSWORD"], "keepme456")
        self.assertIn("REDIS_PASSWORD", output)

    def test_start_over_declined_leaves_the_file_alone(self):
        original = "DB_PASSWORD=root_password\n"
        self.env_file.write_text(original, encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_setup("prod", ["4", "n", "n"])
        self.assertEqual(self.env_file.read_text(encoding="utf-8"), original)

    def test_interrupt_writes_nothing(self):
        with self.assertRaises(SystemExit):
            self.run_setup("prod", ["https://es.example.com", EOFError()])
        self.assertFalse(self.env_file.exists())


class FakeTerminal(io.StringIO):
    def isatty(self):
        return True


ANSI_CODE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


ALL_ON = {"CHAT_ENABLED": True, "AUDIT_TRAIL_ENABLED": True, "PLUGINS_ENABLED": True}


class AdvancedSettingsTest(unittest.TestCase):
    def test_small_size_matches_the_schema_defaults(self):
        defaults = envtool.target_defaults(real_schema(), "prod")
        for name, value in envtool.SERVER_SIZE_VALUES["small"].items():
            self.assertEqual(value, str(defaults[name]), name)

    def test_every_size_fits_the_postgres_connection_budget(self):
        # env.yaml: ~97 usable connections, ~40 for other services, django_app adds 4.
        for size, values in envtool.SERVER_SIZE_VALUES.items():
            django = int(values["DJANGO_SGI_WORKERS"]) * int(values["DJANGO_DB_POOL_MAX_SIZE"]) + 4
            self.assertLessEqual(django + 40, 97, size)
            self.assertLessEqual(int(values["CHAT_WORKERS"]), 6, size)

    def test_code_time_limits_keep_crew_waiting_longer_than_sandbox(self):
        for limit in envtool.CODE_TIME_LIMITS:
            values = envtool.advanced_values("small", limit, None, ALL_ON, real_schema())
            sandbox = to_time(values["SANDBOX_MAX_EXECUTION_TIMEOUT"])
            self.assertGreater(to_time(values["CREW_CODE_RESULT_TIMEOUT"]), sandbox, limit)
            self.assertGreaterEqual(sandbox, to_time("5m"), limit)

    def test_schema_defaults_keep_crew_waiting_longer_than_sandbox(self):
        for target in ("prod", "dev"):
            defaults = envtool.target_defaults(real_schema(), target)
            self.assertGreater(
                to_time(str(defaults["CREW_CODE_RESULT_TIMEOUT"])),
                to_time(str(defaults["SANDBOX_MAX_EXECUTION_TIMEOUT"])),
                target,
            )

    def test_verbose_logging_sets_every_service_log_level(self):
        values = envtool.advanced_values("small", "30m", "DEBUG", ALL_ON, real_schema())
        levels = {name: value for name, value in values.items() if name.endswith("_LOG_LEVEL")}
        self.assertEqual(len(levels), 10)
        self.assertEqual(set(levels.values()), {"DEBUG"})

    def test_settings_of_disabled_features_are_left_alone(self):
        all_off = {"CHAT_ENABLED": False, "AUDIT_TRAIL_ENABLED": False, "PLUGINS_ENABLED": False}
        values = envtool.advanced_values("large", "30m", "DEBUG", all_off, real_schema())
        for name in ("CHAT_WORKERS", "CHAT_LOG_LEVEL", "AUDITOR_LOG_LEVEL"):
            self.assertNotIn(name, values)
        self.assertEqual(values["DJANGO_SGI_WORKERS"], "3")
        self.assertEqual(values["DJANGO_LOG_LEVEL"], "DEBUG")
        values = envtool.advanced_values("large", "30m", "DEBUG", ALL_ON, real_schema())
        self.assertEqual(values["CHAT_WORKERS"], "4")
        self.assertEqual(values["AUDITOR_LOG_LEVEL"], "DEBUG")

    def test_offered_log_levels_are_accepted_by_every_service(self):
        # Django accepts stdlib names plus BENCH (settings/logging.py); auditor and webhook hand
        # the level to uvicorn; the rest validate with Env.LOG_LEVELS.
        django = {"CRITICAL", "ERROR", "WARNING", "INFO", "BENCH", "DEBUG"}
        uvicorn = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "TRACE"}
        accepted = django & uvicorn & set(envtool.Env.LOG_LEVELS)
        self.assertEqual({level.upper() for level in envtool.LOG_CHOICES}, accepted)

    def test_nothing_chosen_changes_nothing(self):
        self.assertEqual(envtool.advanced_values(None, None, None, ALL_ON, real_schema()), {})


class TerminalOutputTest(unittest.TestCase):
    def run_setup(self, answers: list, environment: dict[str, str], output: io.StringIO) -> str:
        env_file = Path(tempfile.mkdtemp()) / ".env"
        with (
            mock.patch.dict(os.environ, {"TERM": "xterm-256color", **environment}),
            mock.patch("builtins.input", side_effect=answers),
            contextlib.redirect_stdout(output),
        ):
            if "NO_COLOR" not in environment:
                os.environ.pop("NO_COLOR", None)
            envtool.run_setup(real_schema(), "dev", env_file)
        return output.getvalue()

    def test_terminal_clears_the_screen_per_question_and_shows_the_answers_so_far(self):
        output = self.run_setup(["n", "y", ""], {}, FakeTerminal())
        self.assertEqual(output.count("\x1b[2J"), 4)
        self.assertIn("\x1b[32m", output)
        final_screen = ANSI_CODE.sub("", output.split("\x1b[2J\x1b[H")[-1])
        self.assertIn("EpicStaff setup", final_screen)
        self.assertIn("✓ Chat: no", final_screen)
        self.assertIn("✓ Audit trail: yes", final_screen)
        self.assertIn("✓ Wrote", final_screen)

    def test_no_color_keeps_clearing_but_drops_colours(self):
        output = self.run_setup(["n", "y", ""], {"NO_COLOR": "1"}, FakeTerminal())
        self.assertIn("\x1b[2J", output)
        self.assertEqual(
            ANSI_CODE.sub("", output.replace("\x1b[2J\x1b[H", "")),
            output.replace("\x1b[2J\x1b[H", ""),
        )

    def test_output_that_is_not_a_terminal_has_no_escape_codes(self):
        output = self.run_setup(["n", "y", ""], {}, io.StringIO())
        self.assertNotIn("\x1b", output)
        self.assertIn("✓ Chat: no", output)


class MainTest(unittest.TestCase):
    def test_setup_without_a_tty_exits_with_a_hint(self):
        env_file = Path(tempfile.mkdtemp()) / ".env"
        with (
            mock.patch.object(sys.stdin, "isatty", return_value=False),
            self.assertRaises(SystemExit) as raised,
        ):
            envtool.main(["--setup", "--env-file", str(env_file)])
        self.assertIn("docker run -it", str(raised.exception.code))
        self.assertFalse(env_file.exists())

    def test_setup_with_update_is_a_usage_error(self):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
            envtool.main(["--setup", "--update"])
        self.assertEqual(raised.exception.code, 2)
        self.assertRegex(
            errors.getvalue(), r"--(setup|update): not allowed with argument --(update|setup)"
        )

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
