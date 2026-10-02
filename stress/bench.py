#!/usr/bin/env python3
"""Open-loop load generator + docker memory sampler. Standard library only.

Fires POST /api/run-session/ at fixed rates, samples `docker stats` every 2 s, and collects
the services' bench_mark() logs into stress/runs/<timestamp>/. See stress/README.md.
"""

import argparse
import concurrent.futures
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_INTERVAL_S = 2.0
REQUEST_TIMEOUT_S = 30
DRAIN_TIMEOUT_S = 60
WARMUP_TIMEOUT_S = 300
MAX_WORKERS = 256  # far above rate * timeout, so a slow API never delays the next send
SIZE_TO_MB = {
    "b": 1 / 1024**2,
    "kib": 1 / 1024,
    "mib": 1.0,
    "gib": 1024.0,
    "tib": 1024.0**2,
    "kb": 1e3 / 1024**2,
    "mb": 1e6 / 1024**2,
    "gb": 1e9 / 1024**2,
    "tb": 1e12 / 1024**2,
}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost")
    parser.add_argument("--graph-id", type=int, required=True)
    parser.add_argument("--rates", required=True, help="comma list, sessions per minute, e.g. 10,25,50")
    parser.add_argument("--step-minutes", type=float, default=5)
    parser.add_argument("--cooldown-minutes", type=float, default=5)
    parser.add_argument("--variables-file", type=Path,
                        help="JSON sent as run-session `variables` (deep-merged over the start node), "
                             "e.g. stress/chat/big_message.json")
    add_common_args(parser)
    args = parser.parse_args()
    rates = [float(rate) for rate in args.rates.split(",") if rate.strip()]
    if not rates or any(rate <= 0 for rate in rates):
        parser.error("--rates must be a comma list of positive numbers")
    args.rates = [int(rate) if rate.is_integer() else rate for rate in rates]
    args.variables = json.loads(args.variables_file.read_text(encoding="utf-8")) if args.variables_file else None
    check_common_args(parser, args)
    return args


def add_common_args(parser):
    parser.add_argument("--api-key", default=os.environ.get("DJANGO_API_KEY"))
    parser.add_argument("--bench-logs", type=Path, default=REPO_ROOT / "src" / "bench_logs")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "stress" / "runs")
    parser.add_argument("--label", default="", help="appended to the run folder name, e.g. flow17-simple")
    parser.add_argument("--warmup", action="store_true",
                        help="run one unlogged session and wait for it to finish before measuring")
    parser.add_argument("--baseline-seconds", type=float, default=20,
                        help="memory sampling with no load before the first session")


def check_common_args(parser, args):
    if not args.api_key:
        parser.error("--api-key or env DJANGO_API_KEY is required")
    if args.label and not re.fullmatch(r"[A-Za-z0-9._-]+", args.label):
        parser.error("--label may only contain letters, digits, '.', '_' and '-'")


# ---------------------------------------------------------------- config.json


def read_env_key(env_path, key):
    """Read exactly one key from a dotenv file; nothing else leaves the file."""
    try:
        lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        name, separator, value = line.partition("=")
        if separator and name.strip().removeprefix("export ").strip() == key:
            return value.split("#", 1)[0].strip().strip("'\"")
    return None


def total_ram_mb():
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return round(int(line.split()[1]) / 1024, 1)
    except (OSError, ValueError, IndexError):
        pass
    return None


def git_sha():
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def build_config(args):
    arguments = {key: (str(value) if isinstance(value, Path) else value) for key, value in vars(args).items()}
    arguments["api_key"] = "***"
    return {
        "args": arguments,
        "git_sha": git_sha(),
        "host_vcpu": os.cpu_count(),
        "host_ram_mb": total_ram_mb(),
        "crew_max_concurrent_sessions": read_env_key(REPO_ROOT / "src" / ".env", "CREW_MAX_CONCURRENT_SESSIONS"),
        "load_start_ts": None,
        "load_end_ts": None,
        "cooldown_end_ts": None,
    }


def write_config(run_dir, config):
    (run_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- memory sampler


def parse_size_mb(text):
    match = re.match(r"\s*([\d.]+)\s*([A-Za-z]+)", text or "")
    if not match:
        return None
    factor = SIZE_TO_MB.get(match.group(2).lower())
    return None if factor is None else float(match.group(1)) * factor


def sample_memory(csv_writer, csv_file):
    started = time.time()
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"[sampler] docker stats failed: {error}", file=sys.stderr)
        return
    if result.returncode != 0:
        print(f"[sampler] docker stats exit {result.returncode}: {result.stderr.strip()}", file=sys.stderr)
        return
    sample_ts = round((started + time.time()) / 2, 3)  # docker stats takes ~1-2 s; use the midpoint
    for line in result.stdout.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        mem_mb = parse_size_mb(row.get("MemUsage", "").split("/")[0])
        try:
            cpu_pct = float(row.get("CPUPerc", "").rstrip("%"))
        except ValueError:
            cpu_pct = None
        if mem_mb is None:
            continue
        csv_writer.writerow([sample_ts, row.get("Name") or row.get("Container"), round(mem_mb, 1), cpu_pct])
    csv_file.flush()


def run_sampler(csv_writer, csv_file, stop_event):
    next_sample_at = time.monotonic()
    while not stop_event.is_set():
        sample_memory(csv_writer, csv_file)
        next_sample_at += SAMPLE_INTERVAL_S
        stop_event.wait(max(0.0, next_sample_at - time.monotonic()))


# ---------------------------------------------------------------- load


class FiredLog:
    """fired.jsonl, one flushed line per request so Ctrl+C keeps everything already done."""

    def __init__(self, path):
        self._file = open(path, "a", encoding="utf-8")
        self._lock = threading.Lock()

    def write(self, record):
        with self._lock:
            self._file.write(json.dumps(record) + "\n")
            self._file.flush()

    def close(self):
        self._file.close()


def fire(run_index, step_rate, args, fired_log, variables=None, **extra):
    """POST run-session once, log it to fired.jsonl and return the record. `variables` defaults to args.variables."""
    record = {
        "run_index": run_index,
        "step_rate": step_rate,
        "graph_id": args.graph_id,
        **extra,
        "ts": time.time(),
        "session_id": None,
        "http_status": None,
        "api_latency_ms": None,
        "error": None,
    }
    payload = {"graph_id": args.graph_id}
    variables = variables if variables is not None else args.variables
    if variables:
        payload["variables"] = variables
    request = urllib.request.Request(
        args.api.rstrip("/") + "/api/run-session/",
        data=json.dumps(payload).encode(),
        headers={"X-Api-Key": args.api_key, "Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            record["http_status"] = response.status
            record["session_id"] = json.loads(response.read() or b"{}").get("session_id")
    except urllib.error.HTTPError as error:
        record["http_status"] = error.code
        record["error"] = error.read(500).decode("utf-8", errors="replace")
    except Exception as error:  # timeout, refused connection, bad JSON: a failed request is a data point
        record["error"] = f"{type(error).__name__}: {error}"
    record["api_latency_ms"] = round((time.monotonic() - started) * 1000, 1)
    fired_log.write(record)
    return record


def run_load(args, executor, fired_log, futures, run_dir):
    run_index = 0
    for step_rate in args.rates:
        interval_s = 60.0 / step_rate
        step_s = args.step_minutes * 60
        step_start = time.monotonic()
        print(f"[load] step {step_rate}/min for {args.step_minutes} min")
        send_number = 0
        # Send times are computed from the step start, never from the previous send: no drift.
        while send_number * interval_s < step_s:
            delay_s = step_start + send_number * interval_s - time.monotonic()
            if delay_s > 0:
                time.sleep(delay_s)
            run_index += 1
            futures.append(executor.submit(fire, run_index, step_rate, args, fired_log))
            send_number += 1
        remaining_s = step_start + step_s - time.monotonic()
        if remaining_s > 0:
            time.sleep(remaining_s)


def warm_up(args):
    """One session outside the measurement, so lazy imports and first-run caches are not counted as load.

    Retries the start for a minute (crew may still be subscribing after a restart), then waits for the
    session to leave pending/run. Exits when the flow cannot run at all: measuring a broken flow is pointless.
    """
    base_url = args.api.rstrip("/")
    headers = {"X-Api-Key": args.api_key, "Content-Type": "application/json"}
    payload = {"graph_id": args.graph_id, **({"variables": args.variables} if args.variables else {})}
    session_id, last_error = None, None
    for _ in range(12):
        request = urllib.request.Request(base_url + "/api/run-session/", data=json.dumps(payload).encode(),
                                         headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
                session_id = json.loads(response.read() or b"{}").get("session_id")
            break
        except Exception as error:
            last_error = error
            time.sleep(5)
    if session_id is None:
        sys.exit(f"[warmup] could not start a session for graph {args.graph_id}: {last_error}")
    deadline = time.monotonic() + WARMUP_TIMEOUT_S
    status = None
    while time.monotonic() < deadline:
        time.sleep(2)
        request = urllib.request.Request(f"{base_url}/api/sessions/{session_id}/?detailed=false", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
                status = json.loads(response.read()).get("status")
        except Exception as error:
            print(f"[warmup] status poll failed: {error}", file=sys.stderr)
            continue
        if status not in ("pending", "run"):
            break
    print(f"[warmup] session {session_id} -> {status}")
    if status in ("pending", "run"):
        print(f"[warmup] still {status} after {WARMUP_TIMEOUT_S} s, measuring anyway", file=sys.stderr)


# ---------------------------------------------------------------- exit


def collect_service_logs(bench_logs, run_dir):
    services_dir = run_dir / "services"
    services_dir.mkdir(exist_ok=True)
    log_paths = sorted(bench_logs.glob("*.jsonl"))
    if not log_paths:
        print(f"[collect] no *.jsonl in {bench_logs}", file=sys.stderr)
    for log_path in log_paths:
        shutil.copy2(log_path, services_dir / log_path.name)
        try:
            with open(log_path, "w"):
                pass
        except OSError as error:
            print(f"[collect] copied but could not truncate {log_path} ({error}); run: sudo truncate -s 0 {log_path}",
                  file=sys.stderr)


def main():
    run_benchmark(parse_args(), run_load)


def run_benchmark(args, load):
    """Run dir + memory sampler around `load(args, executor, fired_log, futures, run_dir)`, then cooldown and collect."""
    if args.warmup:
        warm_up(args)
    run_name = datetime.now().strftime("%Y%m%d-%H%M%S") + (f"-{args.label}" if args.label else "")
    run_dir = args.out / run_name
    run_dir.mkdir(parents=True)
    config = build_config(args)
    write_config(run_dir, config)

    memory_file = open(run_dir / "memory.csv", "w", newline="", encoding="utf-8")
    memory_writer = csv.writer(memory_file)
    memory_writer.writerow(["ts", "container", "mem_mb", "cpu_pct"])
    fired_log = FiredLog(run_dir / "fired.jsonl")
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)
    futures = []
    stop_sampler = threading.Event()
    sampler = threading.Thread(target=run_sampler, args=(memory_writer, memory_file, stop_sampler), daemon=True)

    try:
        print(f"[sampler] baseline: {args.baseline_seconds:g} s with no load")
        sample_memory(memory_writer, memory_file)
        sampler.start()
        time.sleep(args.baseline_seconds)
        config["load_start_ts"] = time.time()
        load(args, executor, fired_log, futures, run_dir)
        config["load_end_ts"] = time.time()
        print(f"[cooldown] {args.cooldown_minutes} min, sampling only")
        time.sleep(args.cooldown_minutes * 60)
        config["cooldown_end_ts"] = time.time()
    except KeyboardInterrupt:
        print("\n[interrupted] stopping load")
    finally:
        config["load_end_ts"] = config["load_end_ts"] or time.time()
        pending = [future for future in futures if not future.done()]
        if pending:
            print(f"[drain] waiting up to {DRAIN_TIMEOUT_S} s for {len(pending)} in-flight requests")
            concurrent.futures.wait(pending, timeout=DRAIN_TIMEOUT_S)
        executor.shutdown(wait=False, cancel_futures=True)
        stop_sampler.set()
        if sampler.is_alive():
            sampler.join(timeout=35)
        memory_file.close()
        fired_log.close()
        write_config(run_dir, config)
        collect_service_logs(args.bench_logs, run_dir)
        print(f"\nRun directory: {run_dir}")
        print(f"Analyze with:  python3 {REPO_ROOT / 'stress' / 'analyze.py'} {run_dir}")


if __name__ == "__main__":
    main()
