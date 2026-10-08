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
REDACTED = "<redacted>"


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


def redacted_case_text(text: str) -> str:
    """The case file to store in a run folder, which may be pushed to a shared repo.

    `text` itself, unless an `[env]` or variant `env` value is outside the allowlist (it may be
    a secret): then the parsed case written back as TOML with those values replaced by
    REDACTED. Comments and layout are lost in that case; the case hash in meta.json is
    always computed from the original file.
    """
    data = tomllib.loads(text)
    tables = [data.get("env", {}), *(variant.get("env", {}) for variant in data.get("variant", []))]
    secret_keys = [
        (table, key) for table in tables for key in table if not ENV_ALLOWLIST.match(key)
    ]
    if not secret_keys:
        return text
    for table, key in secret_keys:
        table[key] = REDACTED
    return (
        f'# Stored copy of the case: env values outside the allowlist are replaced by "{REDACTED}".\n'
        "# Comments and layout of the original file are not kept.\n"
        f"{_toml_document(data)}"
    )


def _toml_document(data: dict) -> str:
    """`data` as TOML: plain keys first, then tables, then arrays of tables (TOML's order)."""

    def is_table_array(value) -> bool:
        return (
            isinstance(value, list)
            and bool(value)
            and all(isinstance(item, dict) for item in value)
        )

    def assignments(table: dict) -> list[str]:
        return [f"{_toml_key(key)} = {_toml_value(value)}" for key, value in table.items()]

    plain = {
        key: value
        for key, value in data.items()
        if not isinstance(value, dict) and not is_table_array(value)
    }
    lines = assignments(plain)
    for key, value in data.items():
        if isinstance(value, dict):
            lines += ["", f"[{_toml_key(key)}]", *assignments(value)]
        elif is_table_array(value):
            for item in value:
                lines += ["", f"[[{_toml_key(key)}]]", *assignments(item)]
    return "\n".join(lines) + "\n"


def _toml_key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else _toml_value(key)


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)  # also inf and nan, which TOML spells the same way
    if isinstance(value, str):
        # JSON's escapes are valid TOML; TOML also needs DEL escaped, which JSON leaves raw
        return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")
    if isinstance(value, list):
        return f"[{', '.join(_toml_value(item) for item in value)}]"
    if isinstance(value, dict):
        pairs = ", ".join(f"{_toml_key(key)} = {_toml_value(item)}" for key, item in value.items())
        return f"{{ {pairs} }}"
    return value.isoformat()  # TOML dates and times


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
