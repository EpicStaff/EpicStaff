from __future__ import annotations

from rbac.access.effective import EffectivePermissions
from rbac.models.enums import Permission, ResourceType
from tables.models.graph_models import AgentNode, TaskNode

from agents.models.agent_models import AgentDefaultSurface, SurfacePlace
from agents.models.surface_models import Surface

NODE_TYPE_TASK = "task"
NODE_TYPE_AGENT = "agent"


class SurfaceUsageService:
    """Answers "where is this surface used?" for one surface of one organization."""

    @classmethod
    def usage(cls, *, surface: Surface, effective: EffectivePermissions) -> dict:
        """Agents defaulting to the surface and flow nodes referencing it directly.

        Flow usage is direct only: the runtime attaches a surface to a node from
        the node's own `surface_list`, never from the agent's default surfaces.
        Names are limited to what the caller may read; everything else is only
        counted, so no name leaks through a permission the caller lacks.
        Soft-deleted agents, default-surface rows, nodes and graphs are skipped.

        Args:
            surface: Surface already resolved inside the caller's organization.
            effective: The caller's resolved permissions in that organization.
        """
        can_read_agents = effective.can(ResourceType.AGENTS, Permission.READ)
        can_read_flows = effective.can(ResourceType.FLOWS, Permission.READ)

        agent_rows = cls._agent_rows(surface)
        flows = cls._flows(surface, can_read_agents=can_read_agents)

        return {
            "agents": agent_rows if can_read_agents else [],
            "flows": flows if can_read_flows else [],
            "hidden_agent_count": 0 if can_read_agents else len({row["id"] for row in agent_rows}),
            "hidden_flow_count": 0 if can_read_flows else len(flows),
        }

    @staticmethod
    def _agent_rows(surface: Surface) -> list[dict]:
        """One row per (agent, place), including the owner's implicit "all" row."""
        rows = [
            {
                "id": row["agent_definition_id"],
                "name": row["agent_definition__name"],
                "place": row["place"],
            }
            for row in AgentDefaultSurface.objects.filter(
                surface=surface,
                agent_definition__active=True,
                agent_definition__org_id=surface.org_id,
            ).values("agent_definition_id", "agent_definition__name", "place")
        ]

        # Mirrors AgentDefinitionSurfaceService.get_default_surfaces: an owner without
        # an explicit row for its own surface still applies it in every place.
        owner = surface.owner_agent
        if (
            owner is not None
            and owner.active
            and owner.org_id == surface.org_id
            and not any(row["id"] == owner.pk for row in rows)
        ):
            rows.append({"id": owner.pk, "name": owner.name, "place": SurfacePlace.ALL.value})

        return sorted(rows, key=lambda row: (row["name"], row["place"], row["id"]))

    @staticmethod
    def _flows(surface: Surface, *, can_read_agents: bool) -> list[dict]:
        flows: dict[int, dict] = {}
        for node_type, model in ((NODE_TYPE_TASK, TaskNode), (NODE_TYPE_AGENT, AgentNode)):
            nodes = model.objects.filter(
                surface_list=surface,
                graph__active=True,
                graph__org_id=surface.org_id,
            ).values(
                "id",
                "node_name",
                "graph_id",
                "graph__name",
                "agent_definition_id",
                "agent_definition__name",
                "agent_definition__active",
            )
            for node in nodes:
                # A soft-deleted agent is shown as no agent, like a node without one.
                shows_agent = (
                    can_read_agents
                    and node["agent_definition_id"] is not None
                    and node["agent_definition__active"]
                )
                flow = flows.setdefault(
                    node["graph_id"],
                    {"id": node["graph_id"], "name": node["graph__name"], "nodes": []},
                )
                flow["nodes"].append(
                    {
                        "id": node["id"],
                        "node_name": node["node_name"],
                        "node_type": node_type,
                        "agent_id": node["agent_definition_id"] if shows_agent else None,
                        "agent_name": node["agent_definition__name"] if shows_agent else None,
                    }
                )

        for flow in flows.values():
            flow["nodes"].sort(key=lambda node: (node["node_name"], node["id"]))
        return sorted(flows.values(), key=lambda flow: (flow["name"], flow["id"]))
