#!/usr/bin/env python3
"""Tests for the GHCR cleanup rules in ghcr_cleanup.py.

No pytest dependency, run directly:
    python3 .github/scripts/test_ghcr_cleanup.py
"""

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import ghcr_cleanup as cleanup

NOW = datetime(2026, 11, 17, tzinfo=UTC)
OLD = NOW - timedelta(days=30)
YOUNG = NOW - timedelta(days=3)


def version(identifier: int, *tags: str, created: datetime = OLD) -> cleanup.Version:
    return cleanup.Version(
        id=identifier, digest=f"sha256:{identifier:064x}", tags=tags, created=created
    )


def kept_latest() -> "cleanup.Version":
    """A version that always stays, so a test's package never runs into the last-version rule."""
    return version(999, "latest", created=YOUNG)


def deleted_ids(versions, children=None, branch_slugs=()) -> set[int]:
    children = children or {}
    plan = cleanup.plan_deletions(
        versions,
        children_of=lambda digest: children.get(digest, set()),
        branch_slugs=set(branch_slugs),
        now=NOW,
    )
    return {deleted.id for deleted in plan}


class SlugTest(unittest.TestCase):
    def test_branch_names_slug_like_the_deploy_workflows(self):
        self.assertEqual(cleanup.slugify("ci/Dual--Deployment_"), "ci-dual-deployment")
        self.assertEqual(cleanup.slugify("release/v1.2.x"), "release-v1.2.x")


class PlanTest(unittest.TestCase):
    def test_releases_latest_and_developer_are_kept_however_old(self):
        versions = [version(1, "v1.4.1"), version(2, "latest"), version(3, "developer")]
        self.assertEqual(deleted_ids(versions), set())

    def test_only_the_newest_ten_main_builds_are_kept(self):
        versions = [
            version(day, f"main-{day:07x}", created=OLD - timedelta(days=day))
            for day in range(1, 13)
        ]
        self.assertEqual(deleted_ids(versions), {11, 12})

    def test_a_main_build_that_is_also_latest_is_kept(self):
        versions = [
            version(day, f"main-{day:07x}", created=OLD - timedelta(days=day))
            for day in range(1, 12)
        ]
        versions[-1] = version(11, "main-000000b", "latest", created=OLD - timedelta(days=11))
        self.assertEqual(deleted_ids(versions), set())

    def test_a_tag_of_an_existing_branch_is_kept(self):
        versions = [version(1, "feat-est-1-thing")]
        self.assertEqual(deleted_ids(versions, branch_slugs={"feat-est-1-thing"}), set())

    def test_a_tag_of_a_deleted_branch_goes_after_fourteen_days(self):
        versions = [version(1, "feat-est-1-gone"), version(2, "feat-est-2-gone", created=YOUNG)]
        self.assertEqual(deleted_ids(versions), {1})

    def test_old_e2e_tags_go(self):
        self.assertEqual(deleted_ids([version(1, "e2e-c12e0b2"), kept_latest()]), {1})

    def test_untagged_versions_go_after_fourteen_days(self):
        versions = [version(1), version(2, created=YOUNG)]
        self.assertEqual(deleted_ids(versions), {1})

    def test_platform_and_provenance_manifests_of_a_kept_image_are_kept(self):
        index, platform, provenance, orphan = (
            version(1, "developer"),
            version(2),
            version(3),
            version(4),
        )
        children = {index.digest: {platform.digest, provenance.digest}}
        self.assertEqual(deleted_ids([index, platform, provenance, orphan], children), {4})

    def test_manifests_of_a_deleted_image_go_with_it(self):
        index, platform = version(1, "feat-est-1-gone"), version(2)
        children = {index.digest: {platform.digest}}
        self.assertEqual(deleted_ids([index, platform, kept_latest()], children), {1, 2})

    def test_signatures_follow_the_image_they_sign(self):
        release, gone = version(1, "v1.5.0"), version(2, "feat-est-1-gone")
        signatures = [
            version(3, f"{release.digest.replace(':', '-')}.sig"),
            version(4, f"{release.digest.replace(':', '-')}.att"),
            version(5, f"{gone.digest.replace(':', '-')}.sig"),
        ]
        # The image the last signature signs is already gone from the package.
        self.assertEqual(deleted_ids([release, *signatures]), {5})


class ReviewFindingsTest(unittest.TestCase):
    def test_a_signed_build_is_kept_after_its_release_tag_moves(self):
        retagged = version(1)
        signature = version(2, f"{retagged.digest.replace(':', '-')}.sig")
        self.assertEqual(deleted_ids([retagged, signature]), set())

    def test_the_parts_of_a_young_untagged_image_are_kept(self):
        young_index, old_part = version(1, created=YOUNG), version(2)
        children = {young_index.digest: {old_part.digest}}
        self.assertEqual(deleted_ids([young_index, old_part], children), set())

    def test_bare_digest_and_sbom_tags_count_as_signatures(self):
        release = version(1, "v1.5.0")
        hex_digest = release.digest.removeprefix("sha256:")
        signatures = [version(2, f"sha256-{hex_digest}"), version(3, f"sha256-{hex_digest}.sbom")]
        self.assertEqual(deleted_ids([release, *signatures]), set())

    def test_a_version_listed_twice_is_deleted_once(self):
        stale = version(1, "feat-est-1-gone")
        plan = cleanup.plan_deletions(
            [stale, stale, kept_latest()],
            children_of=lambda digest: set(),
            branch_slugs=set(),
            now=NOW,
        )
        self.assertEqual([deleted.id for deleted in plan], [1])

    def test_the_last_version_of_a_package_is_never_deleted(self):
        versions = [
            version(1, "feat-est-1-gone"),
            version(2, "feat-est-1-gone", created=OLD - timedelta(days=1)),
        ]
        self.assertEqual(deleted_ids(versions), {2})


class FakeGhcr:
    deleted: list[int] = []

    def __init__(self, token, org):
        FakeGhcr.deleted = []

    def branch_slugs(self, repository):
        return set()

    def versions(self, package):
        return [version(1), kept_latest()]

    def children_of(self, package):
        return lambda digest: set()

    def delete(self, package, stale):
        FakeGhcr.deleted.append(stale.id)


class MainTest(unittest.TestCase):
    def run_main(self, **env):
        environ = {
            "GITHUB_TOKEN": "token",
            "GITHUB_REPOSITORY": "EpicStaff/EpicStaff",
            "PACKAGES": "django_app",
            **env,
        }
        with (
            mock.patch.object(cleanup, "Ghcr", FakeGhcr),
            mock.patch.dict(os.environ, environ, clear=True),
            mock.patch("sys.stdout"),
        ):
            return cleanup.main()

    def test_without_dry_run_set_nothing_is_deleted(self):
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(FakeGhcr.deleted, [])

    def test_dry_run_false_deletes(self):
        self.assertEqual(self.run_main(DRY_RUN="false"), 0)
        self.assertEqual(FakeGhcr.deleted, [1])

    def test_an_empty_package_list_fails(self):
        with self.assertRaises(SystemExit):
            self.run_main(PACKAGES="", DRY_RUN="false")
        self.assertEqual(FakeGhcr.deleted, [])


if __name__ == "__main__":
    unittest.main()
