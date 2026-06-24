"""Resolve filesystem paths for GraphRag output artefacts (parquet files).

The on-disk layout contract lives in `src.shared.utils.graph_data_paths`,
shared with the knowledge worker that writes these files. This module only
adds the django_app-specific, read-only path helpers on top of it.
"""

from pathlib import Path

from src.shared.utils.graph_data_paths import resolve_graph_data_dir

__all__ = ["resolve_graph_data_dir", "text_units_parquet_path"]


def text_units_parquet_path(graph_rag_id: int) -> Path:
    """Absolute path to the `text_units.parquet` file for a given GraphRag."""
    return (
        resolve_graph_data_dir()
        / f"graph_rag_{graph_rag_id}"
        / "output"
        / "text_units.parquet"
    )
