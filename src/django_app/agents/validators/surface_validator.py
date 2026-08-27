from __future__ import annotations

from collections import Counter

from agents.exceptions import SurfaceValidationError
from tables.models.knowledge_models.collection_models import BaseRagType


class SurfaceValidator:
    # NOTE: cross-org rejection for python_tool/mcp_tool/collection/storage_file
    # pks is enforced at the serializer layer (OrgScopedPrimaryKeyRelatedField /
    # OrgVisiblePrimaryKeyRelatedField in surface_serializers.py) — a cross-org
    # pk is rejected there before it ever reaches these validators. PythonCodeTool
    # and SourceCollection own an `org` FK (PythonCodeTool is hybrid via
    # `built_in`); McpTool and StorageFile own a strict `org` FK.

    @staticmethod
    def _find_duplicate_ids(ids: list) -> list:
        counts = Counter(ids)
        return [pk for pk, count in counts.items() if count > 1]

    @staticmethod
    def validate_python_tools(python_tools_data):
        ids = [item["python_tool"].pk for item in python_tools_data]
        duplicates = SurfaceValidator._find_duplicate_ids(ids)

        if duplicates:
            raise SurfaceValidationError(
                detail={
                    "python_tools": f"Duplicate python_tool ids: {sorted(duplicates)}"
                }
            )

    @staticmethod
    def validate_mcp_tools(mcp_tools_data):
        ids = [item["mcp_tool"].pk for item in mcp_tools_data]
        duplicates = SurfaceValidator._find_duplicate_ids(ids)

        if duplicates:
            raise SurfaceValidationError(
                detail={"mcp_tools": f"Duplicate mcp_tool ids: {sorted(duplicates)}"}
            )

    @staticmethod
    def validate_storage_items(storage_items_data, organization):
        ids = [item["storage_file"].pk for item in storage_items_data]
        duplicates = SurfaceValidator._find_duplicate_ids(ids)

        if duplicates:
            raise SurfaceValidationError(
                detail={
                    "storage_items": f"Duplicate storage_file ids: {sorted(duplicates)}"
                }
            )

        wrong_org = [
            item["storage_file"].pk
            for item in storage_items_data
            if item["storage_file"].org_id != organization.pk
        ]

        if wrong_org:
            raise SurfaceValidationError(
                detail={
                    "storage_items": f"storage_file ids do not belong to this organization: {sorted(wrong_org)}"
                }
            )

    @staticmethod
    def validate_knowledge(knowledge_data):
        ids = [item["collection"].pk for item in knowledge_data]
        duplicates = SurfaceValidator._find_duplicate_ids(ids)

        if duplicates:
            raise SurfaceValidationError(
                detail={"knowledge": f"Duplicate collection ids: {sorted(duplicates)}"}
            )

        collection_ids = list(dict.fromkeys(ids))
        rag_type_rows = BaseRagType.objects.filter(
            source_collection_id__in=collection_ids
        ).values_list("source_collection_id", "rag_type")

        rag_types_by_collection: dict[int, set[str]] = {}

        for collection_id, rag_type in rag_type_rows:
            rag_types_by_collection.setdefault(collection_id, set()).add(rag_type)

        for item in knowledge_data:
            SurfaceValidator._validate_knowledge_item_configs(
                item, rag_types_by_collection
            )

    @staticmethod
    def _validate_knowledge_item_configs(
        item, rag_types_by_collection: dict[int, set[str]]
    ):
        collection = item["collection"]
        rag_types = rag_types_by_collection.get(collection.pk, set())

        naive_config = item.get("naive_search_config")
        graph_basic_config = item.get("graph_basic_search_config")
        graph_local_config = item.get("graph_local_search_config")
        graph_global_config = item.get("graph_global_search_config")
        graph_drift_config = item.get("graph_drift_search_config")

        if naive_config is not None and BaseRagType.RagType.NAIVE not in rag_types:
            raise SurfaceValidationError(
                detail={
                    "knowledge": (
                        f"Collection {collection.pk} does not have a naive RAG type; "
                        "naive_search_config is not allowed."
                    )
                }
            )

        if (
            graph_basic_config is not None
            and BaseRagType.RagType.GRAPH not in rag_types
        ):
            raise SurfaceValidationError(
                detail={
                    "knowledge": (
                        f"Collection {collection.pk} does not have a graph RAG type; "
                        "graph_basic_search_config is not allowed."
                    )
                }
            )

        if (
            graph_local_config is not None
            and BaseRagType.RagType.GRAPH not in rag_types
        ):
            raise SurfaceValidationError(
                detail={
                    "knowledge": (
                        f"Collection {collection.pk} does not have a graph RAG type; "
                        "graph_local_search_config is not allowed."
                    )
                }
            )

        if (
            graph_global_config is not None
            and BaseRagType.RagType.GRAPH not in rag_types
        ):
            raise SurfaceValidationError(
                detail={
                    "knowledge": (
                        f"Collection {collection.pk} does not have a graph RAG type; "
                        "graph_global_search_config is not allowed."
                    )
                }
            )

        if (
            graph_drift_config is not None
            and BaseRagType.RagType.GRAPH not in rag_types
        ):
            raise SurfaceValidationError(
                detail={
                    "knowledge": (
                        f"Collection {collection.pk} does not have a graph RAG type; "
                        "graph_drift_search_config is not allowed."
                    )
                }
            )

    @staticmethod
    def validate_agent_default_surfaces(items, agent_definition, organization):
        """Validate surfaces attached to an AgentDefinition via `default_surfaces`.

        `agent_definition=None` is the create case (the instance doesn't exist
        yet), so only shared surfaces (`owner_agent=None`) may be attached.
        """

        errors = []

        for item in items:
            surface = item["surface"]

            if surface.organization_id != organization.pk:
                errors.append(
                    f"Surface {surface.pk} does not belong to this organization."
                )
                continue

            if surface.owner_agent_id is not None and (
                agent_definition is None
                or surface.owner_agent_id != agent_definition.pk
            ):
                errors.append(
                    f"Surface {surface.pk} is owned by agent {surface.owner_agent_id} "
                    f"and cannot be attached to this agent definition."
                )

        if errors:
            raise SurfaceValidationError(detail={"default_surfaces": errors})

    @staticmethod
    def validate_task_node_surfaces(surfaces, agent_definition, organization):
        """Validate surfaces attached to a TaskNode via `surface_list`.

        A surface owned by an agent may only be attached to a task node whose
        `agent_definition` matches that owner. A node with `agent_definition=None`
        may only attach shared surfaces (`owner_agent=None`).
        """

        ids = [s.pk for s in surfaces]
        duplicates = SurfaceValidator._find_duplicate_ids(ids)

        if duplicates:
            raise SurfaceValidationError(
                detail={"surface_list": f"Duplicate surface ids: {sorted(duplicates)}"}
            )

        errors = []

        for surface in surfaces:
            if surface.organization_id != organization.pk:
                errors.append(
                    f"Surface {surface.pk} does not belong to this organization."
                )
                continue

            if surface.owner_agent_id is not None and (
                agent_definition is None
                or surface.owner_agent_id != agent_definition.pk
            ):
                errors.append(
                    f"Surface {surface.pk} is owned by agent {surface.owner_agent_id} "
                    f"and cannot be attached to this task node."
                )

        if errors:
            raise SurfaceValidationError(detail={"surface_list": errors})

    @staticmethod
    def validate_agent_node_surfaces(surfaces, agent_definition, organization):
        """Validate surfaces attached to an AgentNode via `surface_list`.

        A surface owned by an agent may only be attached to an agent node whose
        `agent_definition` matches that owner. A node with `agent_definition=None`
        may only attach shared surfaces (`owner_agent=None`).
        """

        ids = [s.pk for s in surfaces]
        duplicates = SurfaceValidator._find_duplicate_ids(ids)

        if duplicates:
            raise SurfaceValidationError(
                detail={"surface_list": f"Duplicate surface ids: {sorted(duplicates)}"}
            )

        errors = []

        for surface in surfaces:
            if surface.organization_id != organization.pk:
                errors.append(
                    f"Surface {surface.pk} does not belong to this organization."
                )
                continue

            if surface.owner_agent_id is not None and (
                agent_definition is None
                or surface.owner_agent_id != agent_definition.pk
            ):
                errors.append(
                    f"Surface {surface.pk} is owned by agent {surface.owner_agent_id} "
                    f"and cannot be attached to this agent node."
                )

        if errors:
            raise SurfaceValidationError(detail={"surface_list": errors})
