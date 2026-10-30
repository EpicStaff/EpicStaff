from collections.abc import Iterable
from dataclasses import dataclass

from agents.models import (
    AgentDefinition,
    AgentInlineSurfaceStorageItem,
    InlineSurfaceStorageItem,
    Surface,
    SurfaceStorageItem,
)
from django.db.models import Q, QuerySet
from tables.models import Graph, GraphStorageFile, StorageFile


@dataclass(frozen=True)
class StorageUsage:
    """Live flows, surfaces and agents holding a link to the rows a delete would bin.

    Each list holds distinct `{"id", "name"}` dicts ordered by name, then id.
    """

    flows: list[dict]
    surfaces: list[dict]
    agents: list[dict]


def find_storage_usage(org_id: int, paths: Iterable[str]) -> StorageUsage:
    """Find what deleting `paths` would unlink, without changing anything.

    Mirrors StorageFileSync.on_soft_delete: a path naming a live file means that
    file only, any other path means the folder row and everything under it. Only live
    rows of `org_id` count. Session outputs are not reported. A flow is reported when
    it links an affected file directly or a live node of it owns an inline surface
    linked to one; an agent when such a node runs it.
    The number of queries does not depend on how many paths are given.
    """
    affected_files = _affected_files(org_id, list(paths))
    task_node_links = InlineSurfaceStorageItem.objects.filter(
        storage_file__in=affected_files,
        inline_surface__active=True,
        inline_surface__task_node__active=True,
    )
    agent_node_links = AgentInlineSurfaceStorageItem.objects.filter(
        storage_file__in=affected_files,
        agent_inline_surface__active=True,
        agent_inline_surface__agent_node__active=True,
    )
    return StorageUsage(
        flows=_named(
            Graph.objects.filter(org_id=org_id).filter(
                Q(
                    pk__in=GraphStorageFile.objects.filter(storage_file__in=affected_files).values(
                        "graph_id"
                    )
                )
                | Q(pk__in=task_node_links.values("inline_surface__task_node__graph_id"))
                | Q(pk__in=agent_node_links.values("agent_inline_surface__agent_node__graph_id"))
            )
        ),
        surfaces=_named(
            Surface.objects.filter(
                org_id=org_id,
                pk__in=SurfaceStorageItem.objects.filter(storage_file__in=affected_files).values(
                    "surface_id"
                ),
            )
        ),
        agents=_named(
            AgentDefinition.objects.filter(org_id=org_id).filter(
                Q(pk__in=task_node_links.values("inline_surface__task_node__agent_definition_id"))
                | Q(
                    pk__in=agent_node_links.values(
                        "agent_inline_surface__agent_node__agent_definition_id"
                    )
                )
            )
        ),
    )


def _affected_files(org_id: int, paths: list[str]) -> QuerySet:
    live_files = StorageFile.objects.filter(org_id=org_id)
    clean_paths = {path.rstrip("/") for path in paths}
    live_file_paths = set(
        live_files.filter(path__in=clean_paths, item_type="file").values_list("path", flat=True)
    )
    affected = Q(pk__in=[])
    for path in paths:
        clean_path = path.rstrip("/")
        if not path.endswith("/") and clean_path in live_file_paths:
            affected |= Q(path=clean_path)
        else:
            affected |= Q(path__startswith=clean_path + "/")
    return live_files.filter(affected)


def _named(queryset: QuerySet) -> list[dict]:
    return list(queryset.order_by("name", "id").values("id", "name"))
