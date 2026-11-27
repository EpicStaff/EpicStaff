#!/usr/bin/env python3
"""Standalone tests for build_release_bundle.py.

No pytest dependency — run directly (needs ruamel.yaml, and PyYAML for the envtool test):
    python .github/scripts/test_build_release_bundle.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIRECTORY.parents[1]
sys.path.insert(0, str(SCRIPT_DIRECTORY))

from build_release_bundle import (
    ENVTOOL_KIT,
    INSTALL_DOC,
    BundleError,
    build_bundle,
    collect_bind_sources,
)


def compose_with_volumes(*volumes) -> dict:
    return {"services": {"service": {"volumes": list(volumes)}}}


class CollectBindSourcesTest(unittest.TestCase):
    def test_short_syntax_bind_is_collected(self):
        compose = compose_with_volumes("./redis.conf:/usr/local/etc/redis/redis.conf:ro")
        self.assertEqual(collect_bind_sources(compose), ["redis.conf"])

    def test_named_volumes_are_ignored(self):
        compose = compose_with_volumes(
            "media_data:/media", {"type": "volume", "source": "data", "target": "/data"}
        )
        self.assertEqual(collect_bind_sources(compose), [])

    def test_long_syntax_bind_is_collected(self):
        compose = compose_with_volumes(
            {
                "type": "bind",
                "source": "./nginx/docker-entrypoint.d/16-check-ssl-mode.envsh",
                "target": "/x",
            }
        )
        self.assertEqual(
            collect_bind_sources(compose), ["nginx/docker-entrypoint.d/16-check-ssl-mode.envsh"]
        )

    def test_directory_source_keeps_no_trailing_slash(self):
        compose = compose_with_volumes("./nginx/templates/:/etc/nginx/templates:ro")
        self.assertEqual(collect_bind_sources(compose), ["nginx/templates"])

    def test_every_service_counts(self):
        compose = {
            "services": {
                "redis": {"volumes": ["./redis.conf:/r"]},
                "plugins_db": {"profiles": ["plugins"], "volumes": ["./plugins_db/init:/i:ro"]},
            }
        }
        self.assertEqual(collect_bind_sources(compose), ["plugins_db/init", "redis.conf"])

    def test_duplicates_are_collapsed(self):
        compose = compose_with_volumes("./redis.conf:/a", "./redis.conf:/b")
        self.assertEqual(collect_bind_sources(compose), ["redis.conf"])

    def test_absolute_source_fails(self):
        with self.assertRaises(BundleError):
            collect_bind_sources(compose_with_volumes("/etc/hosts:/etc/hosts:ro"))

    def test_absolute_long_syntax_source_fails(self):
        with self.assertRaises(BundleError):
            collect_bind_sources(
                compose_with_volumes({"type": "bind", "source": "/srv/x", "target": "/x"})
            )

    def test_home_relative_source_fails(self):
        with self.assertRaises(BundleError):
            collect_bind_sources(compose_with_volumes("~/certs:/certs"))

    def test_interpolated_source_fails(self):
        with self.assertRaises(BundleError):
            collect_bind_sources(compose_with_volumes("./${CERTS_DIRECTORY}:/certs"))

    def test_source_outside_compose_directory_fails(self):
        with self.assertRaises(BundleError):
            collect_bind_sources(compose_with_volumes("../frontend/dist:/dist"))


def run_git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
    )


COMPOSE_TEXT = """\
services:
  redis:
    volumes:
      - ./redis.conf:/usr/local/etc/redis/redis.conf:ro
  nginx:
    volumes:
      - type: bind
        source: ./nginx
        target: /etc/nginx/extra
"""


class BuildBundleTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        base = Path(self.temporary_directory.name)
        self.repository = base / "repository"
        self.output = base / "output"
        self.output.mkdir()
        self.repository.mkdir()
        files = {path: f"content of {path}\n" for path in ENVTOOL_KIT}
        files[INSTALL_DOC] = "# Install\n"
        files["src/redis.conf"] = "maxmemory 1gb\n"
        files["src/nginx/entry.envsh"] = "echo entry\n"
        files["src/docker-compose.yaml"] = COMPOSE_TEXT
        for relative_path, text in files.items():
            path = self.repository / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        (self.repository / "src/nginx/entry.envsh").chmod(0o755)
        run_git(self.repository, "init", "-q")
        run_git(self.repository, "add", ".")
        run_git(self.repository, "commit", "-q", "-m", "fixture")
        self.compose_file = self.repository / "src/docker-compose.yaml"

    def build(self, compose_file: Path | None = None) -> tarfile.TarFile:
        archive_path = build_bundle(
            self.repository, compose_file or self.compose_file, "v9.9.9", self.output
        )
        self.assertEqual(archive_path, self.output / "epicstaff-v9.9.9.tar.gz")
        return self.enterContext(tarfile.open(archive_path, "r:gz"))

    def test_archive_contains_kit_install_doc_and_mounts(self):
        names = set(self.build().getnames())
        expected = {
            "epicstaff-v9.9.9/INSTALL.md",
            "epicstaff-v9.9.9/src/docker-compose.yaml",
            "epicstaff-v9.9.9/src/redis.conf",
            "epicstaff-v9.9.9/src/nginx/entry.envsh",
        } | {f"epicstaff-v9.9.9/{path}" for path in ENVTOOL_KIT}
        self.assertLessEqual(expected, names)

    def test_install_doc_is_not_shipped_under_its_repository_path(self):
        self.assertNotIn(f"epicstaff-v9.9.9/{INSTALL_DOC}", self.build().getnames())

    def test_executable_bit_is_kept(self):
        member = self.build().getmember("epicstaff-v9.9.9/src/nginx/entry.envsh")
        self.assertTrue(member.mode & 0o111)

    def test_members_are_owned_by_root_with_normalized_modes(self):
        (self.repository / "src/redis.conf").chmod(0o664)
        members = {member.name: member for member in self.build().getmembers()}
        for member in members.values():
            self.assertEqual(
                (member.uid, member.gid, member.uname, member.gname), (0, 0, "root", "root")
            )
        self.assertEqual(members["epicstaff-v9.9.9/src/redis.conf"].mode, 0o644)
        self.assertEqual(members["epicstaff-v9.9.9/src/nginx/entry.envsh"].mode, 0o755)

    def test_untracked_file_in_mounted_directory_is_excluded(self):
        (self.repository / "src/nginx/secret.key").write_text("private\n", encoding="utf-8")
        self.assertNotIn("epicstaff-v9.9.9/src/nginx/secret.key", self.build().getnames())

    def test_untracked_mount_source_fails(self):
        self.compose_file.write_text(
            COMPOSE_TEXT + "  extra:\n    volumes:\n      - ./missing.conf:/m\n"
        )
        with self.assertRaises(BundleError) as caught:
            self.build()
        self.assertIn("missing.conf", str(caught.exception))

    def test_given_compose_file_is_packed(self):
        outside = Path(self.temporary_directory.name) / "pinned-compose.yaml"
        outside.write_text(COMPOSE_TEXT + "# pinned\n", encoding="utf-8")
        member = self.build(outside).extractfile("epicstaff-v9.9.9/src/docker-compose.yaml")
        self.assertEqual(member.read(), outside.read_bytes())

    def test_tag_with_path_separator_fails(self):
        with self.assertRaises(BundleError):
            build_bundle(self.repository, self.compose_file, "v1/../x", self.output)

    def test_empty_tag_fails(self):
        with self.assertRaises(BundleError):
            build_bundle(self.repository, self.compose_file, "", self.output)


class RealRepositoryTest(unittest.TestCase):
    """Run against this checkout, so a new bind mount without its file fails the PR, not the release."""

    def test_every_mount_in_the_real_compose_file_is_tracked(self):
        from ruamel.yaml import YAML

        compose = YAML(typ="safe").load(
            (REPOSITORY_ROOT / "src/docker-compose.yaml").read_text(encoding="utf-8")
        )
        for source in collect_bind_sources(compose):
            tracked = subprocess.run(
                ["git", "ls-files", "--", f"src/{source}"],
                cwd=REPOSITORY_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertTrue(tracked.strip(), f"src/{source} is mounted but not tracked")

    def test_envtool_runs_from_the_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            archive_path = build_bundle(
                REPOSITORY_ROOT, REPOSITORY_ROOT / "src/docker-compose.yaml", "test", temporary_path
            )
            with tarfile.open(archive_path, "r:gz") as archive:
                archive.extractall(temporary_path, filter="data")
            bundle = temporary_path / "epicstaff-test"
            result = subprocess.run(
                [sys.executable, "scripts/envtool.py", "--dev"],
                cwd=bundle,
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((bundle / "src/.env").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
