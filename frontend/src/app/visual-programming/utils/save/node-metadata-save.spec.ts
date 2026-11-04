import { NodeType } from '@shared/models';

import { FlowModel } from '../../core/models/flow.model';
import { GraphNoteModel, NodeModel } from '../../core/models/node.model';
import { getNodeDiff } from './diff';
import { toNodeMetadata, toNoteMetadata } from './metadata';
import { buildBulkSavePayload } from './payload';

const POSITION = { x: 10, y: 20 };

function baseNode(overrides: Record<string, unknown>): NodeModel {
    return {
        id: 'node-1',
        backendId: null,
        position: POSITION,
        ports: null,
        node_name: 'Node',
        color: '#123456',
        icon: 'ui/some-icon',
        size: { width: 311, height: 122 },
        input_map: {},
        output_variable_path: null,
        ...overrides,
    } as unknown as NodeModel;
}

function agentNode(): NodeModel {
    return baseNode({ type: NodeType.AGENT, data: { agent: null } });
}

function noteNode(size: { width: number; height: number }, backendId: number | null = 5): GraphNoteModel {
    return baseNode({
        type: NodeType.NOTE,
        backendId,
        size,
        data: { content: 'hello', backgroundColor: '#ffd1d1' },
    }) as GraphNoteModel;
}

function cdtNode(): NodeModel {
    return baseNode({
        type: NodeType.CLASSIFICATION_TABLE,
        data: {
            table: { condition_groups: [], node_name: 'Triage' },
            pre_computation: {},
            post_computation: {},
            prompts: {},
            default_llm_config: null,
        },
        explanations: {},
    });
}

function flow(nodes: NodeModel[]): FlowModel {
    return { nodes, connections: [] };
}

function bulkPayloadFor(current: FlowModel): Record<string, unknown> {
    return buildBulkSavePayload(
        1,
        getNodeDiff(flow([]), current),
        { toCreate: [], toDelete: [], toUpdate: [] },
        current,
        new Map(),
        1
    );
}

function metadataKeys(payload: Record<string, unknown>, listKey: string): string[] {
    const [item] = payload[listKey] as { metadata: Record<string, unknown> }[];
    return Object.keys(item.metadata).sort();
}

describe('node metadata save', () => {
    it('toNodeMetadata writes only position', () => {
        const metadata = toNodeMetadata(agentNode());

        expect(Object.keys(metadata)).toEqual(['position']);
        expect(metadata['position']).toEqual(POSITION);
    });

    it('toNoteMetadata keeps size and backgroundColor', () => {
        const metadata = toNoteMetadata(noteNode({ width: 420, height: 260 }));

        expect(metadata).toEqual({
            position: POSITION,
            size: { width: 420, height: 260 },
            backgroundColor: '#ffd1d1',
        });
    });

    it('resizing a note is a diff', () => {
        const before = noteNode({ width: 420, height: 260 });
        const after = noteNode({ width: 500, height: 260 });

        const diff = getNodeDiff(flow([before]), flow([after]));

        expect(diff.noteNodes.toUpdate).toHaveLength(1);
    });

    it('bulk payload: agent metadata is position only; CDT metadata is position + explanations', () => {
        const payload = bulkPayloadFor(flow([agentNode(), cdtNode()]));

        expect(metadataKeys(payload, 'agent_node_list')).toEqual(['position']);
        expect(metadataKeys(payload, 'classification_decision_table_node_list')).toEqual(['explanations', 'position']);
    });
});
