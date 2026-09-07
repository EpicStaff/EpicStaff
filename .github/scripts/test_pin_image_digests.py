#!/usr/bin/env python3
"""Minimal standalone tests for pin_image_digests.py.

No pytest dependency — run directly:
    python .github/scripts/test_pin_image_digests.py

Covers the regex/pinning behavior for the standard `${IMAGE_TAG:-latest}`
services as well as the webhook service's required-variable guard syntax
(`${IMAGE_TAG:?...}`), which must be fully replaced by the digest-pinned
reference with no leftover `${...}` fragment.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ruamel.yaml import YAML

SCRIPT = Path(__file__).parent / "pin_image_digests.py"


def run_pin_script(digest_map: dict[str, str], compose_yaml: str) -> tuple[int, str, dict]:
    """Runs pin_image_digests.py against a temp compose file and returns
    (exit_code, stderr, parsed_output_yaml)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        digest_map_path = tmp_path / "digest-map.json"
        src_path = tmp_path / "src-compose.yaml"
        dst_path = tmp_path / "dst-compose.yaml"

        digest_map_path.write_text(json.dumps(digest_map), encoding="utf-8")
        src_path.write_text(compose_yaml, encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(digest_map_path), str(src_path), str(dst_path)],
            capture_output=True,
            text=True,
        )

        parsed: dict = {}
        if dst_path.exists() and dst_path.stat().st_size > 0:
            yaml = YAML()
            with open(dst_path, "r", encoding="utf-8") as f:
                parsed = yaml.load(f) or {}

        return result.returncode, result.stderr, parsed


class PinImageDigestsTests(unittest.TestCase):
    def test_webhook_required_var_guard_is_fully_replaced(self) -> None:
        compose_yaml = """\
services:
  webhook:
    image: ghcr.io/epicstaff/webhook:${IMAGE_TAG:?IMAGE_TAG is required — set it to a pinned release tag, e.g. IMAGE_TAG=v1.1.2.}
"""
        exit_code, stderr, parsed = run_pin_script(
            {"webhook": "sha256:" + "a" * 64}, compose_yaml
        )

        self.assertEqual(exit_code, 0, msg=stderr)
        image = parsed["services"]["webhook"]["image"]
        self.assertEqual(image, f"ghcr.io/epicstaff/webhook@sha256:{'a' * 64}")
        self.assertNotIn("${", image)
        self.assertNotIn("IMAGE_TAG", image)

    def test_soft_default_service_is_pinned(self) -> None:
        compose_yaml = """\
services:
  django:
    image: ghcr.io/epicstaff/django:${IMAGE_TAG:-latest}
"""
        exit_code, stderr, parsed = run_pin_script(
            {"django": "sha256:" + "b" * 64}, compose_yaml
        )

        self.assertEqual(exit_code, 0, msg=stderr)
        self.assertEqual(
            parsed["services"]["django"]["image"],
            f"ghcr.io/epicstaff/django@sha256:{'b' * 64}",
        )

    def test_missing_digest_map_entry_fails_loudly(self) -> None:
        """If a service can't be pinned (no digest-map.json entry) and its
        image still contains ${IMAGE_TAG, the script must fail rather than
        silently ship an unpinned/broken reference."""
        compose_yaml = """\
services:
  webhook:
    image: ghcr.io/epicstaff/webhook:${IMAGE_TAG:?IMAGE_TAG is required — set it to a pinned release tag, e.g. IMAGE_TAG=v1.1.2.}
"""
        exit_code, stderr, _parsed = run_pin_script({}, compose_yaml)

        self.assertNotEqual(exit_code, 0)
        self.assertIn("webhook", stderr)

    def test_third_party_image_left_untouched(self) -> None:
        compose_yaml = """\
services:
  redis:
    image: redis:7-alpine
"""
        exit_code, stderr, parsed = run_pin_script({}, compose_yaml)

        self.assertEqual(exit_code, 0, msg=stderr)
        self.assertEqual(parsed["services"]["redis"]["image"], "redis:7-alpine")


if __name__ == "__main__":
    unittest.main()
