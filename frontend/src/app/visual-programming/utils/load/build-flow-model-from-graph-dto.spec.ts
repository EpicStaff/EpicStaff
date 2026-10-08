import { NodeType } from '@shared/models';

import { GraphDto } from '../../../features/flows/models/graph.model';
import { FlowModel } from '../../core/models/flow.model';
import { SubGraphNode } from '../../core/models/subgraph-node.model';
import { buildFlowModelFromGraphDto } from './build-flow-model-from-graph-dto';

function subgraphNode(id: number, subgraph: number | null): SubGraphNode {
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
