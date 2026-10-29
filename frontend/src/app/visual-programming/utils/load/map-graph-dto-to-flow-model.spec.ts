import { NODE_COLORS, NODE_ICONS, NodeType } from '@shared/models';

import { GraphDto } from '../../../features/flows/models/graph.model';
import { FlowModel } from '../../core/models/flow.model';
import { getNodeDiff } from '../save/diff';
import {
    LIVE_NODE_ID as ID,
    liveAgent,
    liveClassificationTable,
    liveGraph,
    liveNote,
    livePython,
    liveStart,
    liveTask,
} from '../testing/live-graph.fixture';
import { mapGraphDtoToFlowModel } from './map-graph-dto-to-flow-model';

/** Every node's badge number, keyed by its backend id. */
function numbersByBackendId(flow: FlowModel): Map<number | null, number | undefined> {
    return new Map(flow.nodes.map((node) => [node.backendId, node.nodeNumber]));
}

/** `liveGraph` with every node carrying a stale `metadata.nodeNumber`, as rows saved before numbers moved off metadata did. */
function withStaleMetadataNumbers(graph: GraphDto): GraphDto {
    const stale = Object.fromEntries(
        Object.entries(graph).map(([key, value]) => [
            key,
            key.endsWith('_list') && key !== 'edge_list'
                ? (value as { metadata: object }[]).map((node) => ({
                      ...node,
                      metadata: { ...node.metadata, nodeNumber: 99 },
                  }))
                : value,
        ])
    );
    return stale as unknown as GraphDto;
}

describe('mapGraphDtoToFlowModel node numbers', () => {
    let warn: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
        warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    });

    afterEach(() => {
        warn.mockRestore();
    });

    it.each([
        ['python_node_list', ID.python, 1],
        ['task_node_list', ID.task, 2],
        ['agent_node_list', ID.agent, 3],
        ['file_extractor_node_list', ID.fileExtractor, 4],
        ['audio_transcription_node_list', ID.audio, 5],
        ['subgraph_node_list', ID.subgraph, 6],
        ['webhook_trigger_node_list', ID.webhook, 7],
        ['telegram_trigger_node_list', ID.telegram, 8],
        ['schedule_trigger_node_list', ID.schedule, 9],
        ['decision_table_node_list', ID.decisionTable, 10],
        ['classification_decision_table_node_list', ID.classificationTable, 11],
        ['knowledge_node_list', ID.knowledge, 12],
        ['key_value_node_list', ID.keyValue, 13],
    ])('takes the %s badge from node_number, not from a stale metadata.nodeNumber', (_list, backendId, expected) => {
        const flow = mapGraphDtoToFlowModel(withStaleMetadataNumbers(liveGraph));

        expect(numbersByBackendId(flow).get(backendId)).toBe(expected);
    });

    it('reads node_number 7 even when metadata still says nodeNumber 2', () => {
        const graph: GraphDto = {
            ...liveGraph,
            python_node_list: [{ ...livePython, node_number: 7, metadata: { nodeNumber: 2 } }],
        };

        expect(numbersByBackendId(mapGraphDtoToFlowModel(graph)).get(ID.python)).toBe(7);
    });

    it.each([
        ['Start', ID.start],
        ['End', ID.end],
        ['Note', ID.note],
    ])('leaves the %s node without a number', (_type, backendId) => {
        const flow = mapGraphDtoToFlowModel(withStaleMetadataNumbers(liveGraph));

        const numbers = numbersByBackendId(flow);
        expect(numbers.has(backendId)).toBe(true);
        expect(numbers.get(backendId)).toBeUndefined();
    });

    it('keeps unique numbers as they are and warns about nothing', () => {
        const flow = mapGraphDtoToFlowModel(liveGraph);

        const numbered = flow.nodes.filter((node) => node.nodeNumber !== undefined);
        expect(numbered.map((node) => node.nodeNumber).sort((a, b) => a! - b!)).toEqual([
            1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
        ]);
        expect(warn).not.toHaveBeenCalled();
    });

    it('gives a duplicate number the next free one, keeps the first holder, and warns', () => {
        const graph: GraphDto = {
            ...liveGraph,
            python_node_list: [{ ...livePython, node_number: 2 }],
            task_node_list: [{ ...liveTask, node_number: 2 }],
        };

        const numbers = numbersByBackendId(mapGraphDtoToFlowModel(graph));

        expect(numbers.get(ID.python)).toBe(2);
        expect(numbers.get(ID.task)).toBe(14);
        expect(warn).toHaveBeenCalledTimes(1);
    });

    it('numbers a numbered node the backend sent without a number, and warns', () => {
        const graph: GraphDto = { ...liveGraph, python_node_list: [{ ...livePython, node_number: null }] };

        const flow = mapGraphDtoToFlowModel(graph);

        expect(numbersByBackendId(flow).get(ID.python)).toBe(14);
        expect(flow.nodes.find((node) => node.type === NodeType.START)?.nodeNumber).toBeUndefined();
        expect(warn).toHaveBeenCalledTimes(1);
    });
});

const STALE_METADATA = {
    position: { x: 10, y: 20 },
    color: '#ff0000',
    icon: 'ti ti-bug',
    size: { width: 999, height: 999 },
};

function loadedNode(graph: GraphDto, backendId: number) {
    return mapGraphDtoToFlowModel(graph).nodes.find((node) => node.backendId === backendId)!;
}

/** `liveGraph` with garbage position, colour, icon and size on every node. */
function withStaleStyles(graph: GraphDto): GraphDto {
    const stale = Object.fromEntries(
        Object.entries(graph).map(([key, value]) => [
            key,
            key.endsWith('_list') && key !== 'edge_list'
                ? (value as { metadata: object }[]).map((node) => ({
                      ...node,
                      metadata: { ...node.metadata, ...STALE_METADATA },
                  }))
                : value,
        ])
    );
    return stale as unknown as GraphDto;
}

describe('mapGraphDtoToFlowModel node style', () => {
    it('ignores backend color, icon and size, and keeps the position', () => {
        const graph: GraphDto = {
            ...liveGraph,
            agent_node_list: [{ ...liveAgent, metadata: STALE_METADATA }],
        };

        const node = loadedNode(graph, ID.agent);

        expect(node.color).toBe(NODE_COLORS[NodeType.AGENT]);
        expect(node.icon).toBe(NODE_ICONS[NodeType.AGENT]);
        expect(node.size).toEqual({ width: 330, height: 60 });
        expect(node.position).toEqual({ x: 10, y: 20 });
    });

    it('gives a start node without a stored size 125x60', () => {
        const graph: GraphDto = { ...liveGraph, start_node_list: [{ ...liveStart, metadata: {} }] };

        expect(loadedNode(graph, ID.start).size).toEqual({ width: 125, height: 60 });
    });

    it('loads a classification table stored 340 wide as 330 wide, with its height from the groups', () => {
        const graph: GraphDto = {
            ...liveGraph,
            classification_decision_table_node_list: [
                {
                    ...liveClassificationTable,
                    metadata: { position: { x: 0, y: 0 }, size: { width: 340, height: 500 } },
                },
            ],
        };

        const { size } = loadedNode(graph, ID.classificationTable);

        expect(size.width).toBe(330);
        expect(size.height).toBe(60 + 60 * 3);
    });

    it('keeps the valid size stored on a note', () => {
        const graph: GraphDto = {
            ...liveGraph,
            graph_note_list: [{ ...liveNote, metadata: { size: { width: 420, height: 260 } } }],
        };

        expect(loadedNode(graph, ID.note).size).toEqual({ width: 420, height: 260 });
    });

    it.each([
        ['a string width', { width: '300', height: 100 }],
        ['a negative width', { width: -5, height: 100 }],
        ['a zero height', { width: 300, height: 0 }],
        ['a NaN width', { width: NaN, height: 100 }],
        ['a null size', null],
        ['a height-less size', { width: 300 }],
    ])('loads a note with %s as 200x150', (_label, size) => {
        const graph: GraphDto = { ...liveGraph, graph_note_list: [{ ...liveNote, metadata: { size } }] };

        expect(loadedNode(graph, ID.note).size).toEqual({ width: 200, height: 150 });
    });

    it('loads a legacy note with only a position as 200x150', () => {
        const graph: GraphDto = {
            ...liveGraph,
            graph_note_list: [{ ...liveNote, metadata: { position: { x: 5, y: 6 } } }],
        };

        const node = loadedNode(graph, ID.note);

        expect(node.size).toEqual({ width: 200, height: 150 });
        expect(node.position).toEqual({ x: 5, y: 6 });
    });

    it('does not report a flow with stale styles as changed', () => {
        const loaded = mapGraphDtoToFlowModel(withStaleStyles(liveGraph));
        const savedWithOldStyles = {
            ...loaded,
            nodes: loaded.nodes.map((node) => ({
                ...node,
                color: STALE_METADATA.color,
                icon: STALE_METADATA.icon,
                size: STALE_METADATA.size,
            })),
        };

        const diff = getNodeDiff(savedWithOldStyles, loaded);

        for (const nodeDiff of Object.values(diff)) {
            expect(nodeDiff.toCreate).toEqual([]);
            expect(nodeDiff.toUpdate).toEqual([]);
            expect(nodeDiff.toDelete).toEqual([]);
        }
        for (const node of loaded.nodes) {
            expect(node.color).toBe(NODE_COLORS[node.type]);
            expect(node.icon).toBe(NODE_ICONS[node.type]);
        }
    });
});
