#!/usr/bin/env python3
"""EpicStaff benchmark CLI. See benchmark/README.md.

python benchmark/bench.py preflight cases/server.toml
python benchmark/bench.py plan cases/server.toml
python benchmark/bench.py run cases/server.toml --note "after EST-1234"
python benchmark/bench.py dev --graph payload=17 --note "before fix"
python benchmark/bench.py compare <run-folder> <run-folder> ...
python benchmark/bench.py push <run-folder> ...
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from pathlib import Path

if sys.version_info < (3, 11):  # noqa: UP036 (ruff targets 3.12; the tool supports 3.11)
    sys.exit("benchmark needs Python 3.11+ (tomllib)")

import compare
import push
import runner
from config import CaseError, load_case, parse_assignments, select_variants

HERE = Path(__file__).resolve().parent


def case_path(value: str) -> Path:
    path = Path(value)
    return (
        path
        if path.exists()
        else HERE / "cases" / (value if value.endswith(".toml") else f"{value}.toml")
    )


def options(args) -> runner.Options:
    api_key = os.environ.get("DJANGO_API_KEY")
    if not api_key:
        sys.exit("DJANGO_API_KEY is not set: export DJANGO_API_KEY='<org API key>'")
    return runner.Options(
        api_base=os.environ.get("BENCH_API", "http://localhost"),
        api_key=api_key,
        org_id=os.environ.get("BENCH_ORG_ID", "1"),
        note=getattr(args, "note", ""),
        build=not getattr(args, "no_build", False),
        smoke=not getattr(args, "no_smoke", False),
        restart=not getattr(args, "no_restart", False),
    )


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "plan", "smoke", "run"):
        command = commands.add_parser(name)
        command.add_argument("case")
        command.add_argument("--graph", action="append", default=[], metavar="PHASE=ID")
        command.add_argument("--variant", default="")
        command.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
        command.add_argument("--ref")
        command.add_argument("--note", default="")
        command.add_argument("--no-build", action="store_true")
        command.add_argument("--no-smoke", action="store_true")
    dev = commands.add_parser("dev")
    dev.add_argument("--case", default="dev")
    dev.add_argument("--graph", action="append", default=[], metavar="PHASE=ID")
    dev.add_argument("--sessions", type=int)
    dev.add_argument("--concurrency", type=int)
    dev.add_argument("--note", default="")
    dev.add_argument("--no-restart", action="store_true")
    dev.add_argument("--no-build", action="store_true")
    compare_parser = commands.add_parser("compare")
    compare_parser.add_argument("runs", nargs="+", type=Path)
    push_parser = commands.add_parser("push")
    push_parser.add_argument("runs", nargs="+", type=Path)
    push_parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    try:
        if args.command == "compare":
            print(compare.compare_runs(args.runs))
            return 0
        if args.command == "push":
            if not os.environ.get("DJANGO_API_KEY"):
                sys.exit(
                    "DJANGO_API_KEY is not set: the secret scan needs it. export DJANGO_API_KEY='<org API key>'"
                )
            push.push(
                args.runs,
                os.environ.get("BENCH_RESULTS_REPO"),
                HERE / "viewer.html",
                os.environ.get("DJANGO_API_KEY"),
                args.yes,
            )
            return 0
        if args.command == "dev":
            case = load_case(case_path(args.case), parse_assignments(args.graph, int))
            runner.run_dev(
                case,
                options(args),
                args.sessions or case.dev.sessions,
                args.concurrency or case.dev.concurrency,
            )
            return 0
        case = load_case(case_path(args.case), parse_assignments(args.graph, int))
        variants = select_variants(
            case, [v for v in args.variant.split(",") if v], parse_assignments(args.set), args.ref
        )
        if args.command == "plan":
            print(runner.plan_text(case, variants))
            return 0
        if args.command == "preflight":
            return runner.preflight_only(case, options(args))
        if args.command == "smoke":
            variants = variants[:1]
        for variant in variants:
            run_options = options(args)
            if args.command == "smoke":
                case = replace(
                    case, ladder=replace(case.ladder, bisect_steps=0, max=case.ladder.start)
                )
            runner.run_variant(case, variant, run_options)
        return 0
    except CaseError as error:
        print(f"case error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
