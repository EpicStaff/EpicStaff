"""Case files (TOML) → validated, hashed Case objects. See benchmark/README.md."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

ENV_ALLOWLIST = re.compile(
    r"^(\w+_LOG_LEVEL|CREW_MAX_CONCURRENT_SESSIONS|AGENT_MAX_CONCURRENT_RUNS|\w+_SGI_WORKERS"
    r"|KNOWLEDGE_MAX_PROCESS_WORKERS|\w+_CPUS|\w+_MEM_LIMIT)$"
)


class CaseError(ValueError):
    """A case file or a command-line override is invalid; the message says what to fix."""


@dataclass(frozen=True)
class Ladder:
    start: int = 25
    factor: float = 2.0
    max: int = 20000
    hold_s: float = 180
    settle_s: float = 30
    baseline_s: float = 20
    cooldown_s: float = 120
    bisect_steps: int = 2
    session_timeout_s: float = 900


@dataclass(frozen=True)
class PassRules:
    p95_e2e_s: float | None = None
    p95_queue_wait_s: float | None = None
    max_error_rate: float = 0.01


@dataclass(frozen=True)
class AbortRules:
    error_rate_30s: float = 0.05
    host_min_available_ram_pct: float = 5
    container_restart: bool = True
    generator_lag_p99_ms: float = 500


@dataclass(frozen=True)
class DevSettings:
    sessions: int = 100
    concurrency: int = 25


@dataclass(frozen=True)
class Phase:
    name: str
    graph_id: int
    variables: dict | None
    pass_rules: PassRules


@dataclass(frozen=True)
class Variant:
    name: str
    env: dict[str, str] = field(default_factory=dict)
    ref: str | None = None


@dataclass(frozen=True)
class Case:
    name: str
    kind: str
    env: dict[str, str]
    ladder: Ladder
    abort: AbortRules
    dev: DevSettings
    phases: tuple[Phase, ...]
    variants: tuple[Variant, ...]
    case_hash: str
    source_text: str


def load_case(path: Path, graph_overrides: dict[str, int] | None = None) -> Case:
    text = path.read_text(encoding="utf-8")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise CaseError(f"{path}: {error}") from error
    name = _require(data, "name", str, path)
    kind = data.get("kind", "capacity")
    if kind not in ("capacity", "dev"):
        raise CaseError(f"{path}: kind must be 'capacity' or 'dev', got {kind!r}")
    ladder = _build(Ladder, data.get("ladder", {}), "ladder", path)
    if ladder.start < 1 or ladder.factor <= 1 or ladder.max < ladder.start:
        raise CaseError(f"{path}: [ladder] needs start >= 1, factor > 1 and max >= start")
    overrides = graph_overrides or {}
    default_pass = data.get("pass", {})
    phases = []
    for raw in data.get("phase", []):
        phase_name = _require(raw, "name", str, path)
        graph_id = overrides.get(phase_name, raw.get("graph_id"))
        if not isinstance(graph_id, int) or isinstance(graph_id, bool) or graph_id < 1:
            raise CaseError(
                f"{path}: phase {phase_name!r} needs a positive integer graph_id "
                f"(or --graph {phase_name}=<id>)"
            )
        variables = raw.get("variables")
        if variables is not None and not isinstance(variables, dict):
            raise CaseError(f"{path}: phase {phase_name!r} variables must be a table")
        pass_rules = _build(
            PassRules, {**default_pass, **raw.get("pass", {})}, f"phase {phase_name} pass", path
        )
        phases.append(Phase(phase_name, graph_id, variables, pass_rules))
    names = [phase.name for phase in phases]
    if not phases:
        raise CaseError(f"{path}: at least one [[phase]] is required")
    if len(set(names)) != len(names):
        raise CaseError(f"{path}: phase names must be unique, got {names}")
    unknown = sorted(set(overrides) - set(names))
    if unknown:
        raise CaseError(f"--graph names unknown phases {unknown}; the case has {names}")
    variants = tuple(
        Variant(
            _require(raw, "name", str, path), _env_table(raw.get("env", {}), path), raw.get("ref")
        )
        for raw in data.get("variant", [])
    ) or (Variant("default"),)
    return Case(
        name=name,
        kind=kind,
        env=_env_table(data.get("env", {}), path),
        ladder=ladder,
        abort=_build(AbortRules, data.get("abort", {}), "abort", path),
        dev=_build(DevSettings, data.get("dev", {}), "dev", path),
        phases=tuple(phases),
        variants=variants,
        case_hash=case_hash(data),
        source_text=text,
    )


def case_hash(data: dict) -> str:
    """Same workload ⇒ same hash. Variants and graph ids (server-specific) are left out;
    the graph content is hashed separately per run (api.graph_hash)."""
    stripped = {key: value for key, value in data.items() if key != "variant"}
    stripped["phase"] = [
        {key: value for key, value in phase.items() if key != "graph_id"}
        for phase in data.get("phase", [])
    ]
    return hashlib.sha256(json.dumps(stripped, sort_keys=True).encode()).hexdigest()[:16]


def select_variants(
    case: Case, names: list[str] | None, set_env: dict[str, str], ref: str | None
) -> list[Variant]:
    chosen = list(case.variants)
    if names:
        by_name = {variant.name: variant for variant in case.variants}
        missing = [name for name in names if name not in by_name]
        if missing:
            raise CaseError(f"unknown variants {missing}; the case has {sorted(by_name)}")
        chosen = [by_name[name] for name in names]
    if set_env or ref:
        chosen = [
            replace(
                variant,
                name=f"{variant.name}-adhoc",
                env={**variant.env, **set_env},
                ref=ref or variant.ref,
            )
            for variant in chosen
        ]
    return chosen


def ladder_levels(ladder: Ladder) -> list[int]:
    levels, level = [], ladder.start
    while level <= ladder.max:
        levels.append(level)
        level = max(level + 1, round(level * ladder.factor))
    return levels


def bisect_next(last_pass: int | None, first_fail: int) -> int | None:
    """Next probe between the last passing and the first failing level, or None when the
    gap is already within 10 %."""
    low = last_pass or 0
    probe = (low + first_fail) // 2
    if probe <= low or probe >= first_fail or (first_fail - low) / max(low, 1) <= 0.10:
        return None
    return probe


def parse_assignments(items: list[str], value_type=str) -> dict:
    result = {}
    for item in items:
        key, separator, value = item.partition("=")
        if not separator or not key.strip():
            raise CaseError(f"expected KEY=VALUE, got {item!r}")
        try:
            result[key.strip()] = value_type(value.strip())
        except ValueError as error:
            raise CaseError(f"bad value in {item!r}: {error}") from error
    return result


def allowlisted(env: dict[str, str]) -> dict[str, str]:
    """Values safe to store in meta.json; other keys keep their name, never their value."""
    return {key: (value if ENV_ALLOWLIST.match(key) else "<set>") for key, value in env.items()}


def _require(table: dict, key: str, expected_type: type, path: Path):
    value = table.get(key)
    if not isinstance(value, expected_type):
        raise CaseError(f"{path}: {key!r} must be a {expected_type.__name__}")
    return value


def _build(cls, table: dict, section: str, path: Path):
    unknown = sorted(set(table) - {item.name for item in dataclasses.fields(cls)})
    if unknown:
        raise CaseError(f"{path}: unknown keys in [{section}]: {unknown}")
    return cls(**table)


def _env_table(table: dict, path: Path) -> dict[str, str]:
    env = {}
    for key, value in table.items():
        if isinstance(value, bool):
            env[key] = "true" if value else "false"
        elif isinstance(value, int | float | str):
            env[key] = str(value)
        else:
            raise CaseError(f"{path}: env value of {key} must be a string, number or boolean")
    return env
