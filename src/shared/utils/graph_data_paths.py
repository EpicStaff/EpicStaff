"""Shared GraphRag on-disk layout resolution.

Single source of truth for locating the `graph_data` base directory, used by
both the knowledge worker (which writes parquet artifacts during indexing) and
the django_app (which reads them). The two run as separate containers and never
import each other's code, but both can import `src.shared`, so the layout
contract lives here to keep them from drifting apart.
"""

import os
from pathlib import Path


def find_src_dir() -> Path:
    """Walk up from this file to locate the project's `src/` directory.

    Falls back to the current working directory if `src` is not found.
    """
    for parent in Path(__file__).resolve().parents:
        if parent.name == "src":
            return parent
    return Path.cwd()


def resolve_graph_data_dir(explicit_base: str | Path | None = None) -> Path:
    """Return the base directory under which `graph_rag_{id}/` folders live.

    Resolution order:
      1. `explicit_base` (absolute → used as-is; relative → joined under `src/`).
      2. `GRAPH_DATA_DIR` env var (Docker volume mount).
      3. `<src>/knowledge/graph_data` (local dev fallback).
    """
    if explicit_base is not None:
        base = Path(explicit_base)
        if base.is_absolute():
            return base.resolve()
        return (find_src_dir() / base).resolve()

    env_dir = os.environ.get("GRAPH_DATA_DIR")
    if env_dir:
        return Path(env_dir).resolve()

    return (find_src_dir() / "knowledge" / "graph_data").resolve()
