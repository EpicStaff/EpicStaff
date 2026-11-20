#!/usr/bin/env python3
"""Tests for deploy.sh against a fake `docker` that logs every call.

No pytest dependency, run directly:
    python3 .github/scripts/test_deploy.py
"""

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

DEPLOY_SCRIPT = Path(__file__).parent / "deploy.sh"

CONFIG = {
    "name": "epicstaff-dev",
    "volumes": {
        "crew_pgdata": {"name": "dev_crew_pgdata", "external": True},
        "opensearch_data": {"name": "dev_opensearch_data", "external": True},
        "redis_data": {"name": "epicstaff-dev_redis_data"},
    },
}

# Answers what deploy.sh asks and logs every call, one per line. On `up`, it also keeps a
# copy of the second compose file, which deploy.sh removes when it exits.
FAKE_DOCKER = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_LOG"
case "$*" in
  *"config --services"*) printf 'crewdb\\ndjango_app\\n' ;;
  *"config --format json"*) cat "$FAKE_CONFIG" ;;
  *"ps --all --format json"*) echo '[{"Service":"crewdb","State":"running","Health":"healthy"}]' ;;
  "volume inspect "*) exit 1 ;;
  *" up "*)
    set -- $*
    files=()
    while [ $# -gt 0 ]; do [ "$1" = "-f" ] && files+=("$2"); shift; done
    [ ${#files[@]} -gt 1 ] && cp "${files[1]}" "$FAKE_LOG.override"
    ;;
esac
exit 0
"""


class DeployTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        compose_dir = self.root / "app" / "src"
        compose_dir.mkdir(parents=True)
        for name in ("docker-compose.yaml", ".env", "deploy.env"):
            (compose_dir / name).write_text("")
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        docker = bin_dir / "docker"
        docker.write_text(FAKE_DOCKER)
        docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
        config = self.root / "config.json"
        config.write_text(json.dumps(CONFIG))
        self.log = self.root / "docker.log"
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "APP_DIR": str(self.root / "app"),
            "REGENERATE_ENV": "false",
            "DEPLOY_SETTLE_SECONDS": "0",
            "FAKE_LOG": str(self.log),
            "FAKE_CONFIG": str(config),
        }
        self.env.pop("EPICSTAFF_SLICE", None)
        self.env.pop("NUKE_DB", None)

    def deploy(self, **env: str) -> list[str]:
        result = subprocess.run(
            ["bash", str(DEPLOY_SCRIPT)],
            env={**self.env, **env},
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return self.log.read_text().splitlines()

    def test_without_slice_no_override_is_passed(self):
        calls = self.deploy()
        compose_calls = [call for call in calls if call.startswith("compose ")]
        self.assertTrue(compose_calls)
        for call in compose_calls:
            self.assertEqual(call.split().count("-f"), 1, call)

    def test_with_slice_every_service_gets_the_cgroup_parent(self):
        self.deploy(EPICSTAFF_SLICE="epicstaff-dev.slice")
        override = json.loads(Path(f"{self.log}.override").read_text())
        self.assertEqual(
            override,
            {
                "services": {
                    "crewdb": {"cgroup_parent": "epicstaff-dev.slice"},
                    "django_app": {"cgroup_parent": "epicstaff-dev.slice"},
                }
            },
        )

    def test_creates_every_missing_external_volume_by_its_resolved_name(self):
        created = [call.split()[-1] for call in self.deploy() if call.startswith("volume create ")]
        self.assertEqual(sorted(created), ["dev_crew_pgdata", "dev_opensearch_data"])

    def test_nuke_db_recreates_only_this_instance_database_volume(self):
        calls = self.deploy(NUKE_DB="true")
        removed = [call.split()[-1] for call in calls if call.startswith("volume rm ")]
        self.assertEqual(removed, ["dev_crew_pgdata"])
        removal = calls.index("volume rm dev_crew_pgdata")
        self.assertIn("volume create dev_crew_pgdata", calls[removal + 1 :])

    def test_nuke_db_runs_after_down(self):
        calls = self.deploy(NUKE_DB="true")
        down = next(i for i, call in enumerate(calls) if "down --remove-orphans" in call)
        self.assertLess(down, calls.index("volume rm dev_crew_pgdata"))


if __name__ == "__main__":
    unittest.main()
