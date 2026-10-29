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
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

for _name in ("LiteLLM", "LiteLLM Proxy", "LiteLLM Router"):
    _l = logging.getLogger(_name)
    _l.setLevel(logging.WARNING)
    _l.propagate = False
    _l.disabled = True

import httpx
import litellm
from apscheduler.schedulers.background import BackgroundScheduler
from filelock import FileLock, Timeout
from loguru import logger
from src.shared.litellm_model_names import litellm_lookup_name
from src.shared.models.ai_providers import REASONING_EFFORT_VALUES
from tables.exceptions import UnsupportedReasoningEffortError

if TYPE_CHECKING:
    from tables.models.llm_models import LLMModel

litellm.set_verbose = False
litellm.suppress_debug_info = True

FALLBACK_CONTEXT_WINDOW = 16_000

LITELLM_MODEL_PRICES_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
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
        _invalidate_litellm_model_cost_caches()
        _loaded_snapshot_mtime = mtime
        logger.info(f"Loaded litellm model_cost snapshot ({len(data)} models) from {path}")
    except Exception as exc:
        logger.warning(f"Failed to load litellm snapshot {path}: {exc}")


def _invalidate_litellm_model_cost_caches() -> None:
    # An in-place update of litellm.model_cost leaves litellm's lookups stale: the LRU
    # caches behind get_model_info and _get_model_info_helper, and its lowercase key
    # map. This private litellm function clears all three; it is relied on at the
    # pinned litellm version (1.100.5) and must be re-checked when litellm is upgraded.
    litellm.utils._invalidate_model_cost_lowercase_map()


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


# Providers for which litellm 1.100.x answers capability questions over HTTP:
# Ollama/Ollama Chat ask the Ollama server (`/api/show`) for models missing from the
# map, Lemonade asks its server for every model, and Hugging Face fetches the model's
# config from the Hub for every model. Their answers come from the static map only.
REMOTE_LOOKUP_PROVIDERS = frozenset({"ollama", "ollama_chat", "lemonade", "huggingface"})

# A lookup name without a provider prefix is an OpenAI model to litellm.
DEFAULT_LOOKUP_PROVIDER = "openai"

# OpenAI answers 400 to reasoning_effort="none" on models that predate it (gpt-5,
# gpt-5-mini, the o-series), and litellm flags `supports_none_reasoning_effort` on only
# some of its models. For these providers a model without the flag is refused "none".
NONE_EFFORT_FLAG_REQUIRED_PROVIDERS = frozenset({DEFAULT_LOOKUP_PROVIDER, "azure"})

# Providers serving OpenAI's models under their OpenAI names next to models of their
# own (Azure AI Foundry also hosts Claude, DeepSeek, Grok). litellm often puts the
# effort flags on the bare OpenAI entry only, and get_model_info raises for azure_ai
# OpenAI models, so a flag missing here is read from that bare entry.
OPENAI_MODEL_HOSTING_PROVIDERS = frozenset({"azure", "azure_ai"})

# litellm's map lists a model's levels outright when no set of flags can express them
# (Kimi K3 takes low, high and max, but not medium).
EFFORT_LEVELS_KEY = "reasoning_effort_levels"
NONE_EFFORT_FLAG = "supports_none_reasoning_effort"
# Unflagged levels every reasoning model takes. litellm refuses "low" itself where the
# map sets this flag to false (gpt-5.5-pro), so that one flag is honoured too.
UNFLAGGED_EFFORTS = frozenset({"low", "medium", "high"})
LOW_EFFORT_FLAG = "supports_low_reasoning_effort"
# Levels a model takes only when litellm flags it true, for every provider. For xhigh
# this matches litellm, which refuses it without the flag (Claude Sonnet 4.6, Gemini
# 2.5). For minimal, and for "none" on OpenAI models above, we are deliberately
# stricter than litellm: its router_utils/reasoning_effort_capability.py treats both as
# opt-out (allowed unless flagged false), yet OpenAI rejects them on unflagged models
# such as the o-series. Its resolve_supported_reasoning_efforts is not reused because
# its rules differ (also: an unflagged model is "unknown", not a set of levels), so
# re-check these rules against litellm on every litellm upgrade.
OPT_IN_EFFORT_FLAGS = {
    "minimal": "supports_minimal_reasoning_effort",
    "xhigh": "supports_xhigh_reasoning_effort",
    "max": "supports_max_reasoning_effort",
}


@dataclass(frozen=True)
class ReasoningSupport:
    """What a model accepts as `reasoning_effort`, per litellm's model map.

    `efforts` is empty when `supports_reasoning` is False.
    """

    supports_reasoning: bool
    efforts: frozenset[str]

    def ordered_efforts(self) -> list[str]:
        """Return the supported levels, weakest first."""
        return [effort for effort in REASONING_EFFORT_VALUES if effort in self.efforts]


NO_REASONING_SUPPORT = ReasoningSupport(supports_reasoning=False, efforts=frozenset())

# Answers per litellm lookup name (least recently used first), and litellm.model_cost
# keys by lowercase name, both valid for the snapshot they were built from. Model names
# are user input, so the answer cache is bounded in entries and in key length; the
# key index holds litellm.model_cost keys only.
REASONING_SUPPORT_CACHE_SIZE = 2048
MAX_CACHED_LOOKUP_LENGTH = 512
_reasoning_support_cache: OrderedDict[str, ReasoningSupport] = OrderedDict()
_reasoning_support_cache_lock = threading.Lock()
_model_cost_key_index: dict[str, str] = {}
_reasoning_support_cache_snapshot_mtime: float | None = None


def reasoning_support(provider_name: str | None, model_name: str) -> ReasoningSupport:
    """Return which `reasoning_effort` levels litellm reports the model accepts.

    Reads the daily snapshot when one exists, litellm's bundled map otherwise. An
    unknown model, or any litellm failure, answers NO_REASONING_SUPPORT: the caller
    then refuses a reasoning effort rather than sending one the provider may reject.

    Rules, first match wins, for a reasoning model:
      1. The entry lists `reasoning_effort_levels`: exactly those levels.
      2. low, medium, high: accepted (low unless flagged false).
      3. none: the `supports_none_reasoning_effort` flag decides; without it, refused
         for OpenAI models (openai, azure, and azure_ai models with an OpenAI bare
         entry) and accepted for every other provider.
      4. minimal, xhigh, max: accepted only when their flag is true.
    A model name without a provider prefix is treated as an OpenAI model, as litellm
    does. An Azure or Azure AI entry missing a field takes it from the bare-name entry
    when that one is an OpenAI model.

    Never does network I/O: models of REMOTE_LOOKUP_PROVIDERS are answered from the
    static map alone. Answers are cached (bounded LRU) until a newer snapshot is loaded.
    """
    global _reasoning_support_cache_snapshot_mtime
    _ensure_snapshot_loaded()
    lookup = litellm_lookup_name(provider_name, model_name)
    with _reasoning_support_cache_lock:
        if _reasoning_support_cache_snapshot_mtime != _loaded_snapshot_mtime:
            _reasoning_support_cache.clear()
            _model_cost_key_index.clear()
            _reasoning_support_cache_snapshot_mtime = _loaded_snapshot_mtime
        computed_for_snapshot_mtime = _reasoning_support_cache_snapshot_mtime
        if lookup in _reasoning_support_cache:
            _reasoning_support_cache.move_to_end(lookup)
            return _reasoning_support_cache[lookup]

    # Computed outside the lock: litellm's fallback lookups are not instant.
    if _lookup_provider(lookup) in REMOTE_LOOKUP_PROVIDERS:
        answer = _static_map_reasoning_support(lookup)
    else:
        answer = _ask_litellm_reasoning_support(lookup)

    if len(lookup) <= MAX_CACHED_LOOKUP_LENGTH:
        with _reasoning_support_cache_lock:
            # Another thread may have loaded a newer snapshot while this answer was
            # computed from the older map; caching it would outlive that snapshot.
            if _reasoning_support_cache_snapshot_mtime != computed_for_snapshot_mtime:
                return answer
            _reasoning_support_cache[lookup] = answer
            _reasoning_support_cache.move_to_end(lookup)
            while len(_reasoning_support_cache) > REASONING_SUPPORT_CACHE_SIZE:
                _reasoning_support_cache.popitem(last=False)
    return answer


def model_reasoning_support(model: "LLMModel") -> ReasoningSupport:
    """Return the `reasoning_effort` levels a stored LLM model accepts."""
    provider = model.llm_provider
    return reasoning_support(provider.name if provider else None, model.name)


def validate_reasoning_effort(model: "LLMModel | None", reasoning_effort: str | None) -> None:
    """Refuse a reasoning effort the model cannot take.

    Raises:
        UnsupportedReasoningEffortError: An effort is set and there is no model, the
            model is not a reasoning model, or it does not take this level.
    """
    if reasoning_effort is None:
        return
    if model is None:
        raise UnsupportedReasoningEffortError(
            reasoning_effort, "A reasoning effort needs a model. Select one or clear it."
        )
    support = model_reasoning_support(model)
    if not support.efforts:
        raise UnsupportedReasoningEffortError(
            reasoning_effort,
            f"Model '{model.name}' does not support a reasoning effort. "
            "Clear it or select a reasoning model.",
        )
    if reasoning_effort not in support.efforts:
        raise UnsupportedReasoningEffortError(
            reasoning_effort,
            f"Model '{model.name}' does not support reasoning effort '{reasoning_effort}'. "
            f"Supported: {', '.join(support.ordered_efforts())}.",
        )


def _lookup_provider(lookup: str) -> str:
    if "/" not in lookup:
        return DEFAULT_LOOKUP_PROVIDER
    return lookup.split("/", 1)[0].lower()


def _model_cost_entry(name: str) -> dict | None:
    entry = litellm.model_cost.get(name)
    if entry is not None:
        return entry
    with _reasoning_support_cache_lock:
        if not _model_cost_key_index:
            # list() copies the keys in one step: the daily refresh thread may
            # update litellm.model_cost while this runs.
            _model_cost_key_index.update((key.lower(), key) for key in list(litellm.model_cost))
        key = _model_cost_key_index.get(name.lower())
    return litellm.model_cost.get(key) if key else None


def _static_map_reasoning_support(lookup: str) -> ReasoningSupport:
    # Read the entry directly rather than through litellm: for Hugging Face and
    # Lemonade litellm goes remote even when the model is in the map.
    entry = _model_cost_entry(lookup)
    if not entry or entry.get("supports_reasoning") is not True:
        return NO_REASONING_SUPPORT
    return _reasoning_support_from(lookup, entry)


def _ask_litellm_reasoning_support(lookup: str) -> ReasoningSupport:
    # litellm.supports_reasoning, not get_model_info()["supports_reasoning"]: it also
    # consults the bare-name entry and provider-wide info, and answers differently
    # for over a hundred models in the map.
    try:
        if not litellm.supports_reasoning(model=lookup):
            return NO_REASONING_SUPPORT
    except Exception as exc:
        logger.debug("litellm.supports_reasoning({!r}) failed: {!r}", lookup, exc)
        return NO_REASONING_SUPPORT
    return _reasoning_support_from(lookup, _model_info(lookup))


def _model_info(lookup: str) -> dict:
    try:
        return litellm.get_model_info(lookup)
    except Exception as exc:
        # litellm 1.100.x resolves azure_ai/<OpenAI model> as an Azure model and
        # raises even when the azure_ai entry exists; that entry still carries flags.
        logger.debug("litellm.get_model_info({!r}) failed: {!r}", lookup, exc)
        return _model_cost_entry(lookup) or {}


def _openai_bare_entry(lookup: str) -> dict | None:
    """Return the bare-name OpenAI entry an Azure or Azure AI model is a copy of."""
    if _lookup_provider(lookup) not in OPENAI_MODEL_HOSTING_PROVIDERS:
        return None
    bare_entry = _model_cost_entry(lookup.split("/", 1)[1])
    if bare_entry and bare_entry.get("litellm_provider") == DEFAULT_LOOKUP_PROVIDER:
        return bare_entry
    return None


def _reasoning_support_from(lookup: str, info: dict) -> ReasoningSupport:
    openai_entry = _openai_bare_entry(lookup)

    def field(key: str) -> object:
        value = info.get(key)
        if value is None and openai_entry is not None:
            value = openai_entry.get(key)
        return value

    declared_levels = field(EFFORT_LEVELS_KEY)
    if isinstance(declared_levels, list):
        return ReasoningSupport(
            supports_reasoning=True,
            efforts=frozenset(declared_levels) & frozenset(REASONING_EFFORT_VALUES),
        )

    efforts = set(UNFLAGGED_EFFORTS)
    if field(LOW_EFFORT_FLAG) is False:
        efforts.discard("low")
    none_flag = field(NONE_EFFORT_FLAG)
    if none_flag is None:
        is_openai_model = (
            _lookup_provider(lookup) in NONE_EFFORT_FLAG_REQUIRED_PROVIDERS
            or openai_entry is not None
        )
        if not is_openai_model:
            efforts.add("none")
    elif none_flag is True:
        efforts.add("none")
    efforts.update(level for level, flag in OPT_IN_EFFORT_FLAGS.items() if field(flag) is True)
    return ReasoningSupport(supports_reasoning=True, efforts=frozenset(efforts))


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
        _invalidate_litellm_model_cost_caches()
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
        next_run_time=datetime.now(UTC) + timedelta(hours=1),
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
