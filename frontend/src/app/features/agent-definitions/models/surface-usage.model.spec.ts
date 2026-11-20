import { SurfaceUsageDto, surfaceUsageTotal, toSurfaceUsage } from './surface-usage.model';

const DTO: SurfaceUsageDto = {
    agents: [
        { id: 1, name: 'Researcher', place: 'all' },
        { id: 1, name: 'Researcher', place: 'realtime' },
    ],
    flows: [
        {
            id: 7,
            name: 'My flow',
            nodes: [
                { id: 42, node_name: 'Summarize', node_type: 'task', agent_id: 1, agent_name: 'Researcher' },
                { id: 43, node_name: 'Writer', node_type: 'agent', agent_id: null, agent_name: null },
            ],
        },
    ],
    hidden_agent_count: 2,
    hidden_flow_count: 1,
};

describe('toSurfaceUsage', () => {
    it('labels each agent row by its place and maps flows with their nodes', () => {
        const usage = toSurfaceUsage(DTO);

        expect(usage.agents).toEqual([
            { agentId: 1, agentName: 'Researcher', placeLabel: 'Every-Place Surface' },
            { agentId: 1, agentName: 'Researcher', placeLabel: 'Realtime (Voice)' },
        ]);
        expect(usage.flows).toEqual([
            {
                flowId: 7,
                flowName: 'My flow',
                nodes: [
                    { nodeId: 42, nodeName: 'Summarize', agentName: 'Researcher' },
                    { nodeId: 43, nodeName: 'Writer', agentName: null },
                ],
            },
        ]);
        expect(usage.hiddenAgentCount).toBe(2);
        expect(usage.hiddenFlowCount).toBe(1);
    });
});

describe('surfaceUsageTotal', () => {
    it('counts an agent once however many places it holds, and adds flows and the rows hidden from the user', () => {
        expect(surfaceUsageTotal(toSurfaceUsage(DTO))).toBe(1 + 1 + 2 + 1);
    });
});
