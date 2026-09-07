#!/usr/bin/env python3
"""Prune ghcr.io container package versions for an organization per the EpicStaff retention policy.

Policy per package:
- KEEP forever: 'latest' tag, any tag matching strict semver ^v\\d+\\.\\d+\\.\\d+$,
  or a cosign sig/attestation/sbom tag ^sha256-[0-9a-f]{64}\\.(sig|att|sbom)$
- KEEP top N (default 10): tags matching ^main-[0-9a-f]+$ (CI builds from main), most-recent by created_at
- KEEP if recent: anything else (branch slugs, untagged) created within the last N days (default 30)
- DELETE: everything else

Usage:
  cleanup_ghcr.py --org epicstaff --package django_app [--package crew ...] [--apply]

Without --apply, prints what would be deleted (dry-run).
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys

import requests

GH = "https://api.github.com"
SEMVER_RE = re.compile(r"^v\d+\.\d+\.\d+$")
MAIN_SHA_RE = re.compile(r"^main-[0-9a-f]{4,40}$")
SIG_ATT_RE = re.compile(r"^sha256-[0-9a-f]{64}\.(sig|att|sbom)$")
KEEP_TAGS = {"latest"}


def make_session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {token}"
    s.headers["Accept"] = "application/vnd.github+json"
    s.headers["X-GitHub-Api-Version"] = "2022-11-28"
    return s


def list_versions(s: requests.Session, org: str, pkg: str) -> list[dict]:
    versions: list[dict] = []
    page = 1
    while True:
        r = s.get(
            f"{GH}/orgs/{org}/packages/container/{pkg}/versions",
            params={"per_page": 100, "page": page},
            timeout=30,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        versions.extend(batch)
        page += 1
    return versions


def classify(
    versions: list[dict],
    retain_main_sha: int,
    branch_max_age_days: int,
) -> tuple[list[tuple], list[tuple]]:
    now = datetime.datetime.now(datetime.timezone.utc)
    threshold = now - datetime.timedelta(days=branch_max_age_days)

    keep: list[tuple] = []
    delete: list[tuple] = []
    main_sha_versions: list[tuple] = []

    for v in versions:
        tags = ((v.get("metadata") or {}).get("container") or {}).get("tags") or []
        created_str = v["created_at"].replace("Z", "+00:00")
        created = datetime.datetime.fromisoformat(created_str)

        is_keep = any(
            t in KEEP_TAGS or SEMVER_RE.match(t) or SIG_ATT_RE.match(t) for t in tags
        )
        if is_keep:
            keep.append((v, tags, "protected tag"))
            continue

        if any(MAIN_SHA_RE.match(t) for t in tags):
            main_sha_versions.append((v, tags, created))
            continue

        # branch-slug or untagged
        if created < threshold:
            delete.append(
                (v, tags, f"older than {branch_max_age_days}d ({created.date()})")
            )
        else:
            keep.append((v, tags, f"recent ({created.date()})"))

    main_sha_versions.sort(key=lambda x: x[2], reverse=True)
    for i, (v, tags, created) in enumerate(main_sha_versions):
        if i < retain_main_sha:
            keep.append((v, tags, f"main-sha top-{i + 1}"))
        else:
            delete.append(
                (v, tags, f"main-sha beyond top-{retain_main_sha} ({created.date()})")
            )

    return keep, delete


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--org", required=True)
    p.add_argument(
        "--package",
        required=True,
        action="append",
        help="Container package name (repeatable).",
    )
    p.add_argument(
        "--apply", action="store_true", help="Actually delete (default: dry-run)."
    )
    p.add_argument("--retain-main-sha", type=int, default=10)
    p.add_argument("--branch-max-age-days", type=int, default=30)
    args = p.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN env var not set", file=sys.stderr)
        return 2

    s = make_session(token)

    total_kept = 0
    total_deleted = 0
    failures = 0

    for pkg in args.package:
        print(f"\n=== {pkg} ===")
        try:
            versions = list_versions(s, args.org, pkg)
        except requests.HTTPError as e:
            print(f"  ERROR listing versions: {e}")
            failures += 1
            continue

        keep, delete = classify(
            versions,
            retain_main_sha=args.retain_main_sha,
            branch_max_age_days=args.branch_max_age_days,
        )
        print(f"  total={len(versions)} keep={len(keep)} delete={len(delete)}")

        for v, tags, reason in delete:
            label = ",".join(tags) if tags else "<untagged>"
            print(f"  - DELETE id={v['id']} tags=[{label}] reason={reason}")
            if args.apply:
                r = s.delete(
                    f"{GH}/orgs/{args.org}/packages/container/{pkg}/versions/{v['id']}",
                    timeout=30,
                )
                if r.status_code not in (200, 204):
                    print(f"      FAILED: {r.status_code} {r.text}")
                    failures += 1

        total_kept += len(keep)
        total_deleted += len(delete)

    mode = "applied" if args.apply else "dry-run"
    print(
        f"\nSummary [{mode}]: kept={total_kept} delete-candidates={total_deleted} failures={failures}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
