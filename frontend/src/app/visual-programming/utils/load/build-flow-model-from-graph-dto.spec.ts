import { NodeType } from '@shared/models';

import { GraphDto } from '../../../features/flows/models/graph.model';
import { FlowModel } from '../../core/models/flow.model';
import { SubGraphNode } from '../../core/models/subgraph-node.model';
import { LIVE_NODE_ID, LIVE_NODE_UUID, liveGraph } from '../testing/live-graph.fixture';
import { buildFlowModelFromGraphDto } from './build-flow-model-from-graph-dto';

function subgraphNode(id: number, subgraph: number | null): SubGraphNode {
    return {
        id,
        uuid: `subgraph-node-uuid-${id}`,
        created_at: '2026-01-01T00:00:00Z',
        node_name: `Subflow #${id}`,
        graph: 1,
        subgraph,
        input_map: {},
        output_variable_path: null,
        metadata: {},
        created_by: null,
        last_edited_by: null,
        last_edited_at: null,
    };
}

function graph(overrides: Partial<GraphDto> = {}): GraphDto {
    return { id: 1, uuid: 'graph-uuid', name: 'Flow', description: '', save_version: 1, ...overrides } as GraphDto;
}

describe('buildFlowModelFromGraphDto', () => {
    it('adds a Start node when the graph has none', () => {
        const flow = buildFlowModelFromGraphDto(graph(), []);

        const startNodes = flow.nodes.filter((node) => node.type === NodeType.START);
        expect(startNodes).toHaveLength(1);
        expect(startNodes[0].backendId).toBeNull();
        expect(startNodes[0].nodeUuid).toEqual(expect.any(String));
    });

    it('gives a Start node it adds a new uuid on every load', () => {
        const [first, second] = [buildFlowModelFromGraphDto(graph(), []), buildFlowModelFromGraphDto(graph(), [])].map(
            (flow) => flow.nodes.find((node) => node.type === NodeType.START)!.nodeUuid
        );

        expect(first).not.toBe(second);
    });

    it('keeps the uuid the API returns for every node type', () => {
        const flow = buildFlowModelFromGraphDto(liveGraph, [{ id: 99 }]);
        const nodeUuidByBackendId = new Map(flow.nodes.map((node) => [node.backendId, node.nodeUuid]));

        expect(flow.nodes).toHaveLength(Object.keys(LIVE_NODE_ID).length);
        for (const [nodeKey, backendId] of Object.entries(LIVE_NODE_ID)) {
            expect(nodeUuidByBackendId.get(backendId)).toBe(LIVE_NODE_UUID[nodeKey as keyof typeof LIVE_NODE_UUID]);
        }
    });

    it('gives a legacy LLM node no uuid, since the backend has no such node', () => {
        const flow = buildFlowModelFromGraphDto(
            graph({
                llm_node_list: [
                    {
                        id: 17,
                        graph: 1,
                        node_name: 'LLM',
                        llm_config: 71,
                        input_map: {},
                        output_variable_path: null,
                        metadata: {},
                    },
                ],
            }),
            []
        );

        expect(flow.nodes.find((node) => node.type === NodeType.LLM)!.nodeUuid).toBeNull();
    });

    function blockedByBackendId(flow: FlowModel): Map<number | null, boolean | undefined> {
        return new Map(
            flow.nodes.filter((node) => node.type === NodeType.SUBGRAPH).map((node) => [node.backendId, node.isBlocked])
        );
    }

    it('keeps a subgraph node with a target id unblocked when no flows list is given', () => {
        const flow = buildFlowModelFromGraphDto(
            graph({ subgraph_node_list: [subgraphNode(10, 42), subgraphNode(11, 99)] })
        );

        const blocked = blockedByBackendId(flow);
        expect(blocked.get(10)).toBe(false);
        expect(blocked.get(11)).toBe(false);
    });

    it('flags a subgraph node whose target id is null, with or without a flows list', () => {
        const subgraphNodes = [subgraphNode(10, null), subgraphNode(11, 42)];

        const withoutList = blockedByBackendId(
            buildFlowModelFromGraphDto(graph({ subgraph_node_list: subgraphNodes }))
        );
        const withList = blockedByBackendId(
            buildFlowModelFromGraphDto(graph({ subgraph_node_list: subgraphNodes }), [{ id: 42 }])
        );

        expect(withoutList.get(10)).toBe(true);
        expect(withoutList.get(11)).toBe(false);
        expect(withList.get(10)).toBe(true);
        expect(withList.get(11)).toBe(false);
    });

    it('flags a subgraph node whose target id is not in the given flows list', () => {
        const flow = buildFlowModelFromGraphDto(
            graph({ subgraph_node_list: [subgraphNode(10, 42), subgraphNode(11, 99)] }),
            [{ id: 42 }]
        );

        const blocked = blockedByBackendId(flow);
        expect(blocked.get(10)).toBe(false);
        expect(blocked.get(11)).toBe(true);
    });

    it('treats an empty flows list as "nothing available"', () => {
        const flow = buildFlowModelFromGraphDto(graph({ subgraph_node_list: [subgraphNode(10, 42)] }), []);

        expect(blockedByBackendId(flow).get(10)).toBe(true);
    });

    it('fills in ports for every node', () => {
        const flow = buildFlowModelFromGraphDto(graph({ subgraph_node_list: [subgraphNode(10, 42)] }), [{ id: 42 }]);

        expect(flow.nodes.length).toBeGreaterThan(0);
        for (const node of flow.nodes) {
            expect(node.ports).not.toBeNull();
            expect(node.ports!.every((port) => port.id.startsWith(`${node.id}_`))).toBe(true);
        }
    });
});
