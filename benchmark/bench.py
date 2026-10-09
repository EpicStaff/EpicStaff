#!/usr/bin/env python3
"""EpicStaff benchmark CLI. See benchmark/README.md.

python benchmark/bench.py preflight cases/server.toml
python benchmark/bench.py plan cases/server.toml
python benchmark/bench.py run cases/server.toml --note "after the agent fix"
python benchmark/bench.py dev --note "before fix"
python benchmark/bench.py compare <run-folder> <run-folder> ...
python benchmark/bench.py push <run-folder> ...
python benchmark/bench.py flow import
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
import flows
import push
import runner
import stack
from api import Api
from config import CaseError, load_case, parse_assignments, select_variants

HERE = Path(__file__).resolve().parent
PAYLOAD_PHASE = "payload"
PAYLOAD_EXPORT = flows.PAYLOAD_EXPORT
BENCH_ENV_FILE_NAME = ".epicstaff-bench.env"
# Only these are taken from the bench env file; anything else in it is ignored.
BENCH_ENV_NAMES = ("DJANGO_API_KEY", "BENCH_ORG_ID", "BENCH_API", "BENCH_RESULTS_REPO")


def load_bench_env(path: Path, environ) -> None:
    """Fill the benchmark settings missing from `environ` from the private env file at `path`.

    Each of BENCH_ENV_NAMES is taken from the file only when the environment does not set it,
    so an exported value (an exported DJANGO_API_KEY, say) always wins while the file still
    supplies the others. Never src/.env: that holds the stack's secrets, not the benchmark's.
    """
    if not path.is_file():
        return
    if os.name == "posix" and path.stat().st_mode & 0o077:
        print(f"warning: {path} is readable by other users: chmod 600 {path}", file=sys.stderr)
    values = stack.read_env_file(path)
    for name in BENCH_ENV_NAMES:
        if values.get(name) and not environ.get(name):
            environ[name] = values[name]


def flow_exports() -> dict[str, Path]:
    """Phases whose graph id may come from a committed flow export instead of the case."""
    return {PAYLOAD_PHASE: PAYLOAD_EXPORT}


def case_path(value: str) -> Path:
    path = Path(value)
    # is_file, not exists: the repo root has a `dev/` folder, which `bench dev` must not open
    return (
        path
        if path.is_file()
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
        flow_exports=flow_exports(),
    )


def api_of(run_options: runner.Options) -> Api:
    return Api(run_options.api_base, run_options.api_key, run_options.org_id)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    load_bench_env(Path.home() / BENCH_ENV_FILE_NAME, os.environ)
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
    flow_parser = commands.add_parser("flow").add_subparsers(dest="flow_command", required=True)
    flow_import = flow_parser.add_parser(
        "import", help=f"import {flows.display_path(PAYLOAD_EXPORT)}"
    )
    flow_import.add_argument("--quiet", action="store_true", help="print only the graph id")
    args = parser.parse_args(argv)

    try:
        if args.command == "flow":
            # the explicit import always imports, so it also refreshes the flow cache
            flow = flows.import_flow(api_of(options(args)), PAYLOAD_EXPORT)
            print(flow.id if args.quiet else flows.describe(PAYLOAD_PHASE, flow))
            return 0
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
        graph_overrides = parse_assignments(args.graph, int)
        # the runner imports a missing payload flow after its host and .env checks
        if args.command == "dev":
            case = load_case(case_path(args.case), graph_overrides, flow_exports())
            runner.run_dev(
                case,
                options(args),
                args.sessions or case.dev.sessions,
                args.concurrency or case.dev.concurrency,
            )
            return 0
        case = load_case(case_path(args.case), graph_overrides, flow_exports())
        variants = select_variants(
            case, [v for v in args.variant.split(",") if v], parse_assignments(args.set), args.ref
        )
        if args.command == "plan":  # never touches the stack, so never imports
            print(runner.plan_text(case, variants))
            return 0
        run_options = options(args)
        if args.command == "preflight":
            return runner.preflight_only(case, run_options)
        if args.command == "smoke":
            variants = variants[:1]
        for variant in variants:
            if args.command == "smoke":
                case = replace(
                    case, ladder=replace(case.ladder, bisect_steps=0, max=case.ladder.start)
                )
            runner.run_variant(case, variant, run_options)
        return 0
    except CaseError as error:
        print(f"case error: {error}", file=sys.stderr)
        return 2
    except flows.FlowImportError as error:
        print(f"flow import error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted — remaining variants skipped", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
