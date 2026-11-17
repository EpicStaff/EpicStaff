#!/usr/bin/env python3
"""Delete stale image versions from the EpicStaff container packages on GHCR.

Run by .github/workflows/ghcr-cleanup.yml. A version is kept when any of its tags is:
  - a release (v*), latest or developer;
  - one of the newest KEEP_MAIN_BUILDS main-<sha> builds;
  - the slug of a branch that still exists (as deploy.yaml and build-and-push.yml slug it);
or when it is younger than KEEP_DAYS. Signature tags (sha256-<digest>.sig/.att) follow the
image they sign. An untagged version older than KEEP_DAYS goes, unless a kept image index
lists it: every image is an index whose platform and provenance manifests are untagged
versions of their own, and deleting those would break the kept image.

DRY_RUN=true (the default) only reports what would be deleted.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.shared.envtools import Env

GH = "https://api.github.com"
REGISTRY = "https://ghcr.io"
KEEP_DAYS = 14
KEEP_MAIN_BUILDS = 10
ALWAYS_KEPT_TAGS = frozenset({"latest", "developer"})
RELEASE_TAG_RE = re.compile(r"^v\d")
MAIN_TAG_RE = re.compile(r"^main-[0-9a-f]{7}$")
# cosign 2 tags .sig/.att/.sbom; cosign 3 falls back to a bare digest tag without the referrers API.
SIGNATURE_TAG_RE = re.compile(r"^sha256-(?P<hex>[0-9a-f]{64})(?:\.(?:sig|att|sbom))?$")
INDEX_MEDIA_TYPES = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
)
MANIFEST_ACCEPT = ", ".join(
    (
        *INDEX_MEDIA_TYPES,
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)


@dataclass(frozen=True)
class Version:
    id: int
    digest: str
    tags: tuple[str, ...]
    created: datetime


def slugify(branch: str) -> str:
    slug = re.sub(r"[^a-z0-9.]", "-", branch.lower())
    return re.sub(r"-+", "-", slug).strip("-")


def plan_deletions(
    versions: Iterable[Version],
    *,
    children_of: Callable[[str], set[str]],
    branch_slugs: set[str],
    now: datetime,
) -> list[Version]:
    # A build pushed while the versions are listed shifts the pages and repeats a version.
    versions = list({v.id: v for v in versions}.values())
    cutoff = now - timedelta(days=KEEP_DAYS)
    main_builds = sorted(
        (v for v in versions if any(MAIN_TAG_RE.match(tag) for tag in v.tags)),
        key=lambda v: v.created,
        reverse=True,
    )
    recent_main_ids = {v.id for v in main_builds[:KEEP_MAIN_BUILDS]}

    def signed_digests(v: Version) -> set[str]:
        return {
            f"sha256:{match['hex']}" for tag in v.tags if (match := SIGNATURE_TAG_RE.match(tag))
        }

    def is_signature(v: Version) -> bool:
        return bool(v.tags) and all(SIGNATURE_TAG_RE.match(tag) for tag in v.tags)

    signatures = [v for v in versions if is_signature(v)]
    # Only release builds are signed, and a release's compose file pins the signed digest: it
    # stays even after its tag moves to a rebuild.
    signed = set().union(*(signed_digests(v) for v in signatures))

    def keeps_image(v: Version) -> bool:
        return (
            v.created >= cutoff
            or v.id in recent_main_ids
            or v.digest in signed
            or any(
                tag in ALWAYS_KEPT_TAGS or RELEASE_TAG_RE.match(tag) or tag in branch_slugs
                for tag in v.tags
            )
        )

    images = [v for v in versions if not is_signature(v)]
    kept_images = {v.digest for v in images if keeps_image(v)}
    candidates = {v.id for v in images if v.digest not in kept_images}
    candidates |= {
        v.id for v in signatures if v.created < cutoff and not signed_digests(v) & kept_images
    }
    if versions and len(candidates) == len(versions):
        # GitHub refuses to delete a package's last version.
        candidates.discard(max(versions, key=lambda v: v.created).id)

    # Every version that stays keeps its platform and provenance manifests, however old.
    by_digest = {v.digest: v for v in versions}
    checked: set[str] = set()
    while pending := {v.digest for v in versions if v.id not in candidates} - checked:
        for digest in pending:
            checked.add(digest)
            for child in children_of(digest):
                if child in by_digest:
                    candidates.discard(by_digest[child].id)
    return [v for v in versions if v.id in candidates]


def retrying_session() -> requests.Session:
    """Reads retry a dropped connection or a 429/5xx with backoff; deletes are never retried."""
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


class Ghcr:
    def __init__(self, token: str, org: str):
        self.org = org
        self.session = retrying_session()
        self.registry = retrying_session()
        self.session.headers.update(
            {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        )
        self.token = token

    def _pages(self, url: str, params: dict | None = None) -> Iterable[dict]:
        params = {"per_page": 100, **(params or {})}
        while url:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            yield from response.json()
            url, params = response.links.get("next", {}).get("url"), None

    def packages(self, repository: str) -> list[str]:
        return sorted(
            package["name"]
            for package in self._pages(
                f"{GH}/orgs/{self.org}/packages", {"package_type": "container"}
            )
            if (package.get("repository") or {}).get("full_name") == repository
        )

    def branch_slugs(self, repository: str) -> set[str]:
        return {
            slugify(branch["name"]) for branch in self._pages(f"{GH}/repos/{repository}/branches")
        }

    def versions(self, package: str) -> list[Version]:
        url = f"{GH}/orgs/{self.org}/packages/container/{quote(package, safe='')}/versions"
        return [
            Version(
                id=item["id"],
                digest=item["name"],
                tags=tuple(item["metadata"]["container"]["tags"]),
                created=datetime.fromisoformat(item["created_at"]),
            )
            for item in self._pages(url)
        ]

    def children_of(self, package: str) -> Callable[[str], set[str]]:
        repository = f"{self.org.lower()}/{package}"
        token = self.registry.get(
            f"{REGISTRY}/token",
            params={"service": "ghcr.io", "scope": f"repository:{repository}:pull"},
            auth=("token", self.token),
            timeout=30,
        )
        token.raise_for_status()
        headers = {"Authorization": f"Bearer {token.json()['token']}", "Accept": MANIFEST_ACCEPT}

        def children(digest: str) -> set[str]:
            response = self.registry.get(
                f"{REGISTRY}/v2/{repository}/manifests/{digest}", headers=headers, timeout=30
            )
            response.raise_for_status()
            # An index lists manifests; mediaType is optional in OCI, so it is not relied on.
            return {child["digest"] for child in response.json().get("manifests", [])}

        return children

    def delete(self, package: str, version: Version) -> None:
        url = f"{GH}/orgs/{self.org}/packages/container/{quote(package, safe='')}/versions/{version.id}"
        self.session.delete(url, timeout=30).raise_for_status()


def describe(version: Version) -> str:
    tags = ",".join(version.tags) or "untagged"
    return f"{version.created:%Y-%m-%d} {version.digest[:19]} {tags}"


def main() -> int:
    token = os.environ["GITHUB_TOKEN"]
    repository = os.environ["GITHUB_REPOSITORY"]
    org = repository.split("/")[0]
    dry_run = Env().bool("DRY_RUN", True)
    ghcr = Ghcr(token, org)
    branch_slugs = ghcr.branch_slugs(repository)
    now = datetime.now(UTC)
    failures = 0
    summary = [
        f"## GHCR cleanup ({'dry run' if dry_run else 'deleting'})",
        "",
        "| Package | Versions | Delete |",
        "|---|---|---|",
    ]
    for package in ghcr.packages(repository):
        versions = ghcr.versions(package)
        doomed = plan_deletions(
            versions, children_of=ghcr.children_of(package), branch_slugs=branch_slugs, now=now
        )
        summary.append(f"| {package} | {len(versions)} | {len(doomed)} |")
        print(f"== {package}: {len(doomed)} of {len(versions)} versions to delete")
        for version in doomed:
            print(f"   {'would delete' if dry_run else 'delete'} {describe(version)}")
            if dry_run:
                continue
            try:
                ghcr.delete(package, version)
            except requests.HTTPError as error:
                failures += 1
                print(f"   ! failed: {error.response.status_code} {error.response.text[:200]}")
    if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary_path, "a", encoding="utf-8") as summary_file:
            summary_file.write("\n".join(summary) + "\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
