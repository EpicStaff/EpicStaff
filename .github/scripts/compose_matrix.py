#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def load_json_auto(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except UnicodeDecodeError:
        pass

    with open(path, "r", encoding="utf-16") as f:
        return json.load(f)


def append_github_output(key: str, value: str) -> None:
    out_path = os.environ.get("GITHUB_OUTPUT")
    if not out_path:
        print(f"{key}={value}")
        return

    with open(out_path, "a", encoding="utf-8") as f:
        f.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate GitHub Actions matrix from docker compose config JSON."
    )
    parser.add_argument("--compose-json", default="compose.json")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-key", default="matrix")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    compose_json_path = Path(args.compose_json)
    if not compose_json_path.is_absolute():
        compose_json_path = (repo_root / compose_json_path).resolve()
    else:
        compose_json_path = compose_json_path.resolve()

    if not compose_json_path.exists():
        print(f"compose json not found: {compose_json_path}", file=sys.stderr)
        return 2

    cfg = load_json_auto(compose_json_path)
    services = cfg.get("services") or {}

    include: list[dict[str, str]] = []

    for name, svc in services.items():
        build = svc.get("build")
        if not build:
            continue

        context = build.get("context") or "."
        dockerfile = build.get("dockerfile") or "Dockerfile"

        # context abs
        context_path = Path(str(context))
        context_abs = (
            context_path if context_path.is_absolute() else (repo_root / context_path)
        ).resolve()

        # dockerfile abs: relative to context
        dockerfile_path = Path(str(dockerfile))
        dockerfile_abs = (
            dockerfile_path
            if dockerfile_path.is_absolute()
            else (context_abs / dockerfile_path)
        ).resolve()

        # safety: must be inside repo
        try:
            context_rel = context_abs.relative_to(repo_root).as_posix()
            dockerfile_rel = dockerfile_abs.relative_to(repo_root).as_posix()
        except ValueError:
            print(
                f"Path escapes repo root: context={context_abs}, dockerfile={dockerfile_abs}",
                file=sys.stderr,
            )
            return 3

        if not dockerfile_abs.exists():
            print(f"[{name}] Dockerfile not found: {dockerfile_abs}", file=sys.stderr)
            return 4

        include.append(
            {
                "service": str(name),
                "context": context_rel,
                "dockerfile": dockerfile_rel,
            }
        )

    matrix = {"include": include}
    matrix_json = json.dumps(matrix, ensure_ascii=False)

    append_github_output(args.output_key, matrix_json)
    print(json.dumps(matrix, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
