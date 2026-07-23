"""LLM context window resolver.

Single point of truth for mapping an LLM model name to its effective
context window. Delegates to litellm.get_model_info(), which bundles
model_prices_and_context_window.json with ~500+ models from major
providers (OpenAI, Anthropic, Google, Vertex, Bedrock, Mistral, Cohere,
Ollama, …) and is refreshed with each litellm release.

When the model is unknown to litellm, callers may provide a user override
(e.g., LLMConfig.context_window) which is preferred over the conservative
FALLBACK_CONTEXT_WINDOW. The third element of the returned tuple,
`is_trusted`, distinguishes the three resolution sources: True only for
litellm-known ctx; False for user-override or FALLBACK_CONTEXT_WINDOW. Callers
MUST use is_trusted to relax their own clamping accordingly — see
docs/knowledge_and_rag/ADAPTIVE_CONTEXT_MANAGEMENT.md.

Daily refresh / multi-worker: under gunicorn -w N a single worker is elected
(non-blocking file lock) to fetch the upstream JSON once a day and persist it
as a shared on-disk snapshot. Every worker — owner or not — lazily merges that
snapshot into its in-process `litellm.model_cost` via a cheap mtime-guarded
stat() inside `resolve_context_window`, so all workers converge on the same
once-a-day data without issuing any extra network requests on the hot path.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

for _name in ("LiteLLM", "LiteLLM Proxy", "LiteLLM Router"):
    _l = logging.getLogger(_name)
    _l.setLevel(logging.WARNING)
    _l.propagate = False
    _l.disabled = True

import httpx  # noqa: E402
import litellm  # noqa: E402
from apscheduler.schedulers.background import BackgroundScheduler  # noqa: E402
from filelock import FileLock, Timeout  # noqa: E402
from loguru import logger  # noqa: E402

litellm.set_verbose = False
litellm.suppress_debug_info = True

FALLBACK_CONTEXT_WINDOW = 16_000

LITELLM_MODEL_PRICES_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)


def _snapshot_path() -> Path:
    """Path of the daily model-cost snapshot shared by all web workers.

    Override with the `LITELLM_MODEL_COST_SNAPSHOT_PATH` env var when the
    default temp dir is not writable / not shared between workers.
    """
    env = os.environ.get("LITELLM_MODEL_COST_SNAPSHOT_PATH")
    if env:
        return Path(env)
    return Path(tempfile.gettempdir()) / "litellm_model_cost_snapshot.json"


# mtime of the snapshot the *current process* last merged into litellm.model_cost.
# Lets every worker converge on the once-a-day snapshot via a cheap stat() —
# no extra network calls on the hot path.
_loaded_snapshot_mtime: float | None = None


def _ensure_snapshot_loaded() -> None:
    """Merge the on-disk snapshot into this process's `litellm.model_cost`
    if the file changed since we last loaded it. Cheap stat(); no network.
    """
    global _loaded_snapshot_mtime
    path = _snapshot_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return  # no snapshot yet — bundled litellm data is used as-is.
    if _loaded_snapshot_mtime is not None and mtime <= _loaded_snapshot_mtime:
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        litellm.model_cost.update(data)
        _loaded_snapshot_mtime = mtime
        logger.info(
            f"Loaded litellm model_cost snapshot ({len(data)} models) from {path}"
        )
    except Exception as exc:
        logger.warning(f"Failed to load litellm snapshot {path}: {exc}")


def _write_snapshot(data: dict) -> None:
    """Atomically write the fetched model-cost JSON to the shared snapshot."""
    path = _snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def resolve_context_window(
    model_name: str,
    user_override: int | None = None,
) -> tuple[int, str | None, bool]:
    """Resolve an LLM model name to (effective_ctx, warning_or_none, is_trusted).

    Resolution order:
      1. litellm: if it recognises the model, use its reported ctx. is_trusted=True.
      2. user_override: when litellm doesn't know the model AND the caller
         supplied a positive override (e.g., LLMConfig.context_window changed
         from default 16000), use that override. is_trusted=False — caller
         may have mistyped, so safe_budget will apply MAX_TOKEN_FIELD_VALUE cap.
      3. FALLBACK_CONTEXT_WINDOW: last resort. is_trusted=False.

    All failures (bad override type, litellm crash, missing fields) are
    logged but never raised — this resolver MUST NOT take down a request.
    """
    # Converge on the once-a-day snapshot the owner worker fetched. Cheap
    # stat() guarded by mtime — no network, no extra GitHub requests here.
    _ensure_snapshot_loaded()
    try:
        info = litellm.get_model_info(model_name)
        ctx = info.get("max_input_tokens") or info.get("max_tokens")
        if ctx and int(ctx) > 0:
            return int(ctx), None, True
    except Exception as exc:
        logger.debug(
            f"litellm.get_model_info({model_name!r}) failed: {exc!r}; "
            f"continuing with user_override / fallback resolution."
        )

    if user_override is not None:
        try:
            override_int = int(user_override)
            if override_int >= 1000:
                return override_int, None, False
            logger.warning(
                f"LLMConfig.context_window={user_override} is below minimum (1000); "
                f"falling back to {FALLBACK_CONTEXT_WINDOW}."
            )
        except (TypeError, ValueError):
            logger.warning(
                f"LLMConfig.context_window={user_override!r} is not a valid int; "
                f"falling back to {FALLBACK_CONTEXT_WINDOW}."
            )

    return (
        FALLBACK_CONTEXT_WINDOW,
        (
            f"Unknown model '{model_name}', falling back to {FALLBACK_CONTEXT_WINDOW}. "
            f"Token clamping is relaxed for this request — your custom values are passed "
            f"through unchanged (save-side validator enforces MAX_TOKEN_FIELD_VALUE upper bound)."
        ),
        False,
    )


def refresh_litellm_model_cost() -> None:
    """Fetch the latest model_prices JSON from GitHub once, merge it into this
    process's `litellm.model_cost`, and persist it as the shared snapshot that
    sibling workers pick up via `_ensure_snapshot_loaded()`. Network errors are
    logged but never raised; runs only in the elected owner worker.
    """
    try:
        resp = httpx.get(LITELLM_MODEL_PRICES_URL, timeout=30)
        resp.raise_for_status()
        fresh = resp.json()
        fresh.pop("sample_spec", None)  # metadata key, not a real model
        litellm.model_cost.update(fresh)
        _write_snapshot(fresh)
        logger.info(f"litellm.model_cost refreshed from GitHub: {len(fresh)} models")
    except Exception as exc:
        logger.warning(f"Failed to refresh litellm.model_cost: {exc}")


def start_periodic_litellm_refresh() -> None:
    """Schedule a background refresh of litellm.model_cost.

    First run: 1 hour after startup (off gunicorn's critical path, so it can
    never cause WORKER TIMEOUT).
    Subsequent runs: every day.

    Idempotent on the job id, so repeated calls during dev autoreload are safe.
    """
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        refresh_litellm_model_cost,
        trigger="interval",
        days=1,
        next_run_time=datetime.now() + timedelta(hours=1),
        id="litellm_model_cost_refresh",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduled daily litellm.model_cost refresh from GitHub")


# Held for the lifetime of the owner process so the lock is never released
# while we own the scheduler (released automatically when the process exits).
_refresh_owner_lock: FileLock | None = None


def start_litellm_refresh_if_owner() -> bool:
    """Elect a single owner across all web workers to run the daily refresh.

    Every worker loads any existing snapshot immediately (no network). Exactly
    one worker wins a non-blocking file lock and starts the scheduler; the rest
    skip it and simply read the snapshot the owner produces. Returns True if
    this process became the owner.
    """
    global _refresh_owner_lock

    # All workers: adopt whatever snapshot already exists on disk right away.
    _ensure_snapshot_loaded()

    lock = FileLock(str(_snapshot_path()) + ".lock")
    try:
        lock.acquire(timeout=0)
    except Timeout:
        logger.info(
            "litellm model_cost refresh already owned by another worker; "
            "this worker will read the shared snapshot."
        )
        return False

    _refresh_owner_lock = lock  # keep alive for the process lifetime
    start_periodic_litellm_refresh()
    return True
