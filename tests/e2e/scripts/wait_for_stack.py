"""Wait until the e2e stack answers through nginx and the mock LLM is up (stdlib only).

Used locally and in CI before `pytest tests/e2e`:

    uv run --project tests/e2e python tests/e2e/scripts/wait_for_stack.py

The stack is ready when all of these pass in the same poll:
    django      GET {E2E_BASE_URL}/ht/ -> 200 (nginx proxies /ht/ to Django's health check)
    first-setup GET {E2E_BASE_URL}/api/auth/first-setup/ -> 200 with a `needs_setup` key
                (this one reads the database). Its value is printed, not checked: the
                "database is not fresh" failure belongs to the bootstrap fixture.
    mock-llm    GET {E2E_MOCK_LLM_URL}/health -> 200

Environment:
    E2E_BASE_URL       nginx base URL, default http://localhost
    E2E_MOCK_LLM_URL   mock LLM base URL as published on the host, default http://localhost:18080
    E2E_STACK_TIMEOUT  seconds to wait before giving up, default 600
    E2E_TIMINGS_DIR    where the elapsed time is written as stack_ready.json
                       ({"stack_ready_seconds": <float>}), default tests/e2e/.timings: the
                       same directory conftest.py reads and merges into timings.json

Requests bypass any configured HTTP proxy: the stack always runs on this machine.

Progress is printed when a check changes state and every 30 s while something still fails.
Exit code 0 when ready, 1 on timeout (with the last result of every check).
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

POLL_INTERVAL_SECONDS = 3
DEFAULT_TIMINGS_DIR = Path(__file__).resolve().parent.parent / ".timings"
REQUEST_TIMEOUT_SECONDS = 5
PROGRESS_INTERVAL_SECONDS = 30

HTTP_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def log(message: str) -> None:
    # Flushed so CI logs show progress live even when stdout is a pipe.
    print(f"[wait_for_stack] {message}", flush=True)


@dataclass(frozen=True)
class CheckResult:
    passed: bool
    detail: str


@dataclass(frozen=True)
class Check:
    name: str
    url: str
    evaluate: Callable[[bytes], CheckResult]


def status_ok(body: bytes) -> CheckResult:
    return CheckResult(True, "200")


def first_setup_ok(body: bytes) -> CheckResult:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return CheckResult(False, f"200 but not JSON: {body[:200]!r}")
    if not isinstance(payload, dict) or "needs_setup" not in payload:
        return CheckResult(False, f"200 but no `needs_setup`: {payload!r}")
    return CheckResult(True, f"200, needs_setup={payload['needs_setup']}")


def run_check(check: Check) -> CheckResult:
    """GET the check's URL; anything but a 200 that passes `evaluate` is a failure."""
    try:
        with HTTP_OPENER.open(check.url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return check.evaluate(response.read())
    except urllib.error.HTTPError as error:
        return CheckResult(False, f"HTTP {error.code}")
    except (urllib.error.URLError, OSError) as error:
        reason = getattr(error, "reason", error)
        return CheckResult(False, f"{type(error).__name__}: {reason}")


def build_checks(base_url: str, mock_llm_url: str) -> list[Check]:
    return [
        Check("django", f"{base_url}/ht/", status_ok),
        Check("first-setup", f"{base_url}/api/auth/first-setup/", first_setup_ok),
        Check("mock-llm", f"{mock_llm_url}/health", status_ok),
    ]


def format_results(results: dict[str, CheckResult]) -> str:
    return "; ".join(
        f"{name}: {'ok' if result.passed else 'FAIL'} ({result.detail})"
        for name, result in results.items()
    )


def write_timing(timings_dir: str, elapsed_seconds: float) -> None:
    directory = Path(timings_dir)
    directory.mkdir(parents=True, exist_ok=True)
    timing_file = directory / "stack_ready.json"
    timing_file.write_text(json.dumps({"stack_ready_seconds": round(elapsed_seconds, 1)}))
    log(f"wrote {timing_file}")


def wait_for_stack(checks: list[Check], timeout_seconds: float) -> dict[str, CheckResult] | None:
    """Poll every check until all pass in one round or the timeout runs out.

    Returns:
        The passing results, or None on timeout (the last results are printed first).
    """
    started = time.monotonic()
    previous: dict[str, CheckResult] = {}
    last_progress = started

    while True:
        results = {check.name: run_check(check) for check in checks}
        elapsed = time.monotonic() - started

        if all(result.passed for result in results.values()):
            log(f"ready after {elapsed:.1f}s: {format_results(results)}")
            return results

        now = time.monotonic()
        if results != previous or now - last_progress >= PROGRESS_INTERVAL_SECONDS:
            failing = {name: result for name, result in results.items() if not result.passed}
            log(f"{elapsed:.0f}s, waiting for {format_results(failing)}")
            previous = results
            last_progress = now

        if elapsed >= timeout_seconds:
            log(f"TIMEOUT after {elapsed:.0f}s. Last results: {format_results(results)}")
            return None

        time.sleep(min(POLL_INTERVAL_SECONDS, timeout_seconds - elapsed))


def main() -> int:
    base_url = os.environ.get("E2E_BASE_URL", "http://localhost").rstrip("/")
    mock_llm_url = os.environ.get("E2E_MOCK_LLM_URL", "http://localhost:18080").rstrip("/")
    timeout_seconds = float(os.environ.get("E2E_STACK_TIMEOUT", "600"))
    timings_dir = os.environ.get("E2E_TIMINGS_DIR") or str(DEFAULT_TIMINGS_DIR)

    log(f"base={base_url} mock_llm={mock_llm_url} timeout={timeout_seconds:.0f}s")
    started = time.monotonic()
    results = wait_for_stack(build_checks(base_url, mock_llm_url), timeout_seconds)
    if results is None:
        return 1
    write_timing(timings_dir, time.monotonic() - started)
    return 0


if __name__ == "__main__":
    sys.exit(main())
