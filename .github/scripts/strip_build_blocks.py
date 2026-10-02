#!/usr/bin/env python3
"""Strip `build:` blocks from a docker-compose.yaml so it ships with only registry refs.

Usage: strip_build_blocks.py <source> <dest>
"""

from __future__ import annotations

import sys

from ruamel.yaml import YAML


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: strip_build_blocks.py <source> <dest>", file=sys.stderr)
        return 2

    src, dst = sys.argv[1], sys.argv[2]

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096

    with open(src, encoding="utf-8") as f:
        data = yaml.load(f)

    services = (data.get("services") or {}) if isinstance(data, dict) else {}
    for _, svc in services.items():
        if isinstance(svc, dict):
            svc.pop("build", None)

    with open(dst, "w", encoding="utf-8") as f:
        yaml.dump(data, f)

    print(f"wrote {dst} (stripped build blocks from {len(services)} services)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
