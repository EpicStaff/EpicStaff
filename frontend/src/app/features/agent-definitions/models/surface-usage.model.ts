import { AgentSurfacePlace } from './agent-definition.model';
import { placeToCategory, SURFACE_CATEGORIES } from './surface-category.model';

export interface SurfaceUsageAgentDto {
    id: number;
    name: string;
    place: AgentSurfacePlace;
}

export interface SurfaceUsageNodeDto {
    id: number;
    node_name: string;
    node_type: 'task' | 'agent';
    agent_id: number | null;
    agent_name: string | null;
}

export interface SurfaceUsageFlowDto {
    id: number;
    name: string;
    nodes: SurfaceUsageNodeDto[];
}

export interface SurfaceUsageDto {
    agents: SurfaceUsageAgentDto[];
    flows: SurfaceUsageFlowDto[];
    /** Above 0 when the caller cannot read agents; `agents` is then empty. */
    hidden_agent_count: number;
    /** Above 0 when the caller cannot read flows; `flows` is then empty. */
    hidden_flow_count: number;
}

export interface SurfaceAgentUsage {
    agentId: number;
    agentName: string;
    placeLabel: string;
}

export interface SurfaceFlowNodeUsage {
    nodeId: number;
    nodeName: string;
    agentName: string | null;
}

export interface SurfaceFlowUsage {
    flowId: number;
    flowName: string;
    nodes: SurfaceFlowNodeUsage[];
}

export interface SurfaceUsage {
    agents: SurfaceAgentUsage[];
    flows: SurfaceFlowUsage[];
    hiddenAgentCount: number;
    hiddenFlowCount: number;
}

export function toSurfaceUsage(dto: SurfaceUsageDto): SurfaceUsage {
    return {
        agents: dto.agents.map((agent) => {
            const category = placeToCategory(agent.place);
            return {
                agentId: agent.id,
                agentName: agent.name,
                placeLabel: SURFACE_CATEGORIES.find((candidate) => candidate.id === category)?.label ?? category,
            };
        }),
        flows: dto.flows.map((flow) => ({
            flowId: flow.id,
            flowName: flow.name,
            nodes: flow.nodes.map((node) => ({
                nodeId: node.id,
                nodeName: node.node_name,
                agentName: node.agent_name,
            })),
        })),
        hiddenAgentCount: dto.hidden_agent_count,
        hiddenFlowCount: dto.hidden_flow_count,
    };
}

/** Agents using the surface: a list row is one (agent, place) pair, so rows are counted by distinct agent. */
export function surfaceUsageAgentCount(usage: SurfaceUsage): number {
    return new Set(usage.agents.map((agent) => agent.agentId)).size + usage.hiddenAgentCount;
}

export function surfaceUsageFlowCount(usage: SurfaceUsage): number {
    return usage.flows.length + usage.hiddenFlowCount;
}

/** Everything that uses the surface, hidden rows included, so the number never under-reports. */
export function surfaceUsageTotal(usage: SurfaceUsage): number {
    return surfaceUsageAgentCount(usage) + surfaceUsageFlowCount(usage);
}
