import { NodeType } from '@shared/models';

import { GraphDto } from '../../../features/flows/models/graph.model';
import { SubGraphNode } from '../../core/models/subgraph-node.model';
import { buildFlowModelFromGraphDto } from './build-flow-model-from-graph-dto';

function subgraphNode(id: number, subgraph: number): SubGraphNode {
    return {
        id,
        node_name: `Subflow #${id}`,
        graph: 1,
        subgraph,
        input_map: {},
        output_variable_path: null,
        metadata: {},
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
    });

    it('flags a subgraph node whose flow is not available and keeps an available one unblocked', () => {
        const flow = buildFlowModelFromGraphDto(
            graph({ subgraph_node_list: [subgraphNode(10, 42), subgraphNode(11, 99)] }),
            [{ id: 42 }]
        );

        const blockedByBackendId = new Map(
            flow.nodes.filter((node) => node.type === NodeType.SUBGRAPH).map((node) => [node.backendId, node.isBlocked])
        );
        expect(blockedByBackendId.get(10)).toBe(false);
        expect(blockedByBackendId.get(11)).toBe(true);
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
