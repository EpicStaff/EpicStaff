from __future__ import annotations

from tables.exceptions import SurfaceValidationError
from tables.models.agent_models.surface_models import StorageAccess, ToolMode


_TOOL_MODE_PRECEDENCE: dict[str, int] = {
    ToolMode.DENY: 2,
    ToolMode.ALLOW: 1,
}

_STORAGE_ACCESS_PRECEDENCE: dict[str, int] = {
    StorageAccess.DENY: 3,
    StorageAccess.ALLOW: 2,
    StorageAccess.UNSET: 1,
}

_STORAGE_FLAGS = ("can_list", "can_view", "can_edit", "can_delete")


class SurfaceCombineService:
    @staticmethod
    def combine(surfaces: list[dict]) -> dict:
        return {
            "instructions": SurfaceCombineService._combine_instructions(surfaces),
            "allow_creation": SurfaceCombineService._combine_allow_creation(surfaces),
            "python_tools": SurfaceCombineService._combine_tools(
                surfaces, "python_tools", "python_tool"
            ),
            "mcp_tools": SurfaceCombineService._combine_tools(
                surfaces, "mcp_tools", "mcp_tool"
            ),
            "storage_items": SurfaceCombineService._combine_storage(surfaces),
            "knowledge": SurfaceCombineService._combine_knowledge(surfaces),
        }

    @staticmethod
    def _combine_instructions(surfaces: list[dict]) -> str:
        parts = [
            s["instructions"] for s in surfaces if s.get("instructions", "").strip()
        ]
        return "\n\n".join(parts)

    @staticmethod
    def _combine_tools(surfaces: list[dict], list_key: str, id_key: str) -> list[dict]:
        best: dict[int, str] = {}

        for surface in surfaces:
            for entry in surface.get(list_key, []):
                tool_id = entry[id_key]
                mode = entry["mode"]
                current = best.get(tool_id)

                if current is None or _TOOL_MODE_PRECEDENCE.get(
                    mode, 0
                ) > _TOOL_MODE_PRECEDENCE.get(current, 0):
                    best[tool_id] = mode

        return [{id_key: tool_id, "mode": mode} for tool_id, mode in best.items()]

    @staticmethod
    def _combine_storage(surfaces: list[dict]) -> list[dict]:
        best: dict[int, dict[str, str]] = {}

        for surface in surfaces:
            for entry in surface.get("storage_items", []):
                file_id = entry["storage_file"]

                if file_id not in best:
                    best[file_id] = {
                        flag: StorageAccess.UNSET for flag in _STORAGE_FLAGS
                    }

                for flag in _STORAGE_FLAGS:
                    incoming = entry.get(flag, StorageAccess.UNSET)
                    current = best[file_id][flag]

                    if _STORAGE_ACCESS_PRECEDENCE.get(
                        incoming, 0
                    ) > _STORAGE_ACCESS_PRECEDENCE.get(current, 0):
                        best[file_id][flag] = incoming

        return [{"storage_file": file_id, **flags} for file_id, flags in best.items()]

    @staticmethod
    def _combine_knowledge(surfaces: list[dict]) -> list[dict]:
        seen: dict[int, dict] = {}

        for surface in surfaces:
            for entry in surface.get("knowledge", []):
                collection_id = entry["collection"]
                incoming_config = {
                    "naive_search_config": entry.get("naive_search_config"),
                    "graph_basic_search_config": entry.get("graph_basic_search_config"),
                    "graph_local_search_config": entry.get("graph_local_search_config"),
                }

                if collection_id not in seen:
                    seen[collection_id] = {
                        "collection": collection_id,
                        **incoming_config,
                    }
                    continue

                existing_config = {
                    "naive_search_config": seen[collection_id].get(
                        "naive_search_config"
                    ),
                    "graph_basic_search_config": seen[collection_id].get(
                        "graph_basic_search_config"
                    ),
                    "graph_local_search_config": seen[collection_id].get(
                        "graph_local_search_config"
                    ),
                }

                if incoming_config != existing_config:
                    raise SurfaceValidationError(
                        detail=f"Collection {collection_id} appears with conflicting RAG configs across surfaces."
                    )

        return list(seen.values())

    @staticmethod
    def _combine_allow_creation(surfaces: list[dict]) -> bool:
        return all(s.get("allow_creation", False) for s in surfaces)
