"""Terminal comparison of run folders: first run is the baseline, the others as Δ %."""

from __future__ import annotations

import csv
import json
from pathlib import Path

HEADLINE = [
    "level",
    "throughput_per_min",
    "e2e_s_p50",
    "e2e_s_p95",
    "platform_overhead_s_p95",
    "queue_wait_s_p95",
    "error_rate",
    "cpu_s_per_session",
    "mb_per_concurrent",
]
META_FIELDS = [
    ("git", "ref"),
    ("git", "sha"),
    ("git", "dirty"),
    ("case", "hash"),
    ("case", "variant"),
    ("host", "hostname"),
]
TEXT_COLUMNS = {
    "phase",
    "kind",
    "verdict",
    "live_verdict",
    "fail_reasons",
    "bottleneck",
    "node_name",
    "node_type",
    "container",
}


def _number(value: str, column_name: str):
    if column_name in TEXT_COLUMNS:
        return value or None
    try:
        return float(value)
    except (TypeError, ValueError):
        return value or None


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        return [{key: _number(value, key) for key, value in row.items()} for row in reader]


def load_run(path: Path) -> dict:
    meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
    if int(meta.get("schema_version", 0)) != 1:
        raise SystemExit(f"{path}: schema_version {meta.get('schema_version')} is not supported")
    return {
        "path": path,
        "meta": meta,
        "steps": _read(path / "steps.csv"),
        "nodes": _read(path / "nodes.csv"),
        "containers": _read(path / "containers.csv"),
        "container_phases": _read(path / "container_phases.csv"),
    }


def headline(run: dict, phase: str) -> dict | None:
    steps = [step for step in run["steps"] if step["phase"] == phase]
    passes = [step for step in steps if step["verdict"] == "pass"]
    if run["meta"]["kind"] == "capacity" and passes:
        return max(passes, key=lambda step: step["level"])
    return steps[0] if steps else None


def _delta(value, base) -> str:
    if not isinstance(value, float) or not isinstance(base, float) or base == 0:
        return ""
    return f" ({(value - base) / abs(base) * 100:+.1f}%)"


def _cell(value) -> str:
    return "—" if value is None else (f"{value:g}" if isinstance(value, float) else str(value))


def compare_runs(paths: list[Path]) -> str:
    runs = [load_run(path) for path in paths]
    base = runs[0]
    lines = [
        "runs: "
        + " | ".join(f"{run['meta']['run_id']} ({run['meta'].get('note') or '-'})" for run in runs),
        "",
    ]
    for section, key in META_FIELDS:
        values = [str(run["meta"].get(section, {}).get(key)) for run in runs]
        if len(set(values)) > 1:
            lines.append(f"differs  {section}.{key}: " + " | ".join(values))
    graph_hashes = {
        tuple(phase.get("graph_hash") for phase in run["meta"]["phases"]) for run in runs
    }
    if len({run["meta"]["case"]["hash"] for run in runs}) > 1 or len(graph_hashes) > 1:
        lines.append("!! different workload — not comparable (case or graph hash differs)")
    for phase in [phase["name"] for phase in base["meta"]["phases"]]:
        lines += ["", f"== {phase}"]
        heads = [headline(run, phase) or {} for run in runs]
        verdicts = [
            next((p["verdict"] for p in run["meta"]["phases"] if p["name"] == phase), {})
            for run in runs
        ]
        rows = [
            (
                "max_pass_concurrency",
                [
                    float(v["max_pass_concurrency"])
                    if v.get("max_pass_concurrency") is not None
                    else None
                    for v in verdicts
                ],
            )
        ]
        rows += [(metric, [head.get(metric) for head in heads]) for metric in HEADLINE]
        nodes = sorted(
            {node["node_name"] for run in runs for node in run["nodes"] if node["phase"] == phase}
        )
        for node in nodes:
            values = []
            for run, head in zip(runs, heads, strict=True):
                match = [
                    n
                    for n in run["nodes"]
                    if n["phase"] == phase
                    and n["node_name"] == node
                    and n["level"] == head.get("level")
                ]
                values.append(match[0]["p50_s"] if match else None)
            rows.append((f"node p50 {node}", values))
        width = max(len(name) for name, _ in rows)
        for name, values in rows:
            cells = [_cell(values[0])] + [
                _cell(value) + _delta(value, values[0]) for value in values[1:]
            ]
            lines.append(f"{name:<{width}}  " + "  |  ".join(cells))
    return "\n".join(lines)
