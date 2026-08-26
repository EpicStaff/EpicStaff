#!/usr/bin/env python3
"""Pin EpicStaff-built service images in a docker-compose.yaml to their built digests.

Reads a `{service: digest}` JSON map (as produced by the build-and-push workflow's
digest aggregation job) and rewrites each matching service's `image:` field from a
tag-based reference (e.g. `ghcr.io/epicstaff/<svc>:${IMAGE_TAG:-latest}`) to a
digest-pinned reference (`ghcr.io/epicstaff/<svc>@sha256:<digest>`).

Services not present in the digest map (e.g. third-party images such as redis,
nginx, minio) are left completely untouched.

Usage: pin_image_digests.py <digest_map.json> <source_compose.yaml> <dest_compose.yaml>
"""

from __future__ import annotations

import json
import re
import sys

from ruamel.yaml import YAML

# Matches `ghcr.io/epicstaff/<service>:<anything>` or `ghcr.io/epicstaff/<service>@<anything>`,
# capturing the registry/owner/service prefix so the tag/digest suffix can be swapped out
# regardless of its exact current form.
IMAGE_PREFIX_RE = re.compile(r"^(ghcr\.io/epicstaff/(?P<service>[^:@]+))[:@].*$")


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "usage: pin_image_digests.py <digest_map.json> <source_compose.yaml> <dest_compose.yaml>",
            file=sys.stderr,
        )
        return 2

    digest_map_path, src, dst = sys.argv[1], sys.argv[2], sys.argv[3]

    with open(digest_map_path, "r", encoding="utf-8") as f:
        digest_map: dict[str, str] = json.load(f)

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096

    with open(src, "r", encoding="utf-8") as f:
        data = yaml.load(f)

    services = (data.get("services") or {}) if isinstance(data, dict) else {}

    pinned = 0
    for name, svc in services.items():
        if not isinstance(svc, dict):
            continue

        image = svc.get("image")
        if not isinstance(image, str):
            continue

        match = IMAGE_PREFIX_RE.match(image)
        if not match:
            continue

        service_name = match.group("service")
        digest = digest_map.get(service_name)
        if not digest:
            continue

        svc["image"] = f"{match.group(1)}@{digest}"
        pinned += 1

    with open(dst, "w", encoding="utf-8") as f:
        yaml.dump(data, f)

    print(f"wrote {dst} (pinned {pinned} of {len(services)} services to digests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
