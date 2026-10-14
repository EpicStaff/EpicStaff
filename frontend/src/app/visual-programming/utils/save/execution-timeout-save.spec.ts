import { NodeType } from '@shared/models';

import { GraphDto } from '../../../features/flows/models/graph.model';
import { ExecutionTimeoutNodeType } from '../../core/constants/execution-timeout';
import { FlowModel } from '../../core/models/flow.model';
import { NodeModel } from '../../core/models/node.model';
import { buildFlowModelFromGraphDto } from '../load/build-flow-model-from-graph-dto';
import { mapAudioToTextNodeToModel } from '../load/nodes/audio-to-text-node.mapper';
import { mapClassificationDecisionTableNodeToModel } from '../load/nodes/classification-decision-table-node.mapper';
import { mapFileExtractorNodeToModel } from '../load/nodes/file-extractor-node.mapper';
import { mapPythonNodeToModel } from '../load/nodes/python-node.mapper';
import { mapWebhookTriggerNodeToModel } from '../load/nodes/webhook-trigger-node.mapper';
import {
    liveAudio,
    liveClassificationTable,
    liveFileExtractor,
    liveGraph,
    livePython,
    liveWebhook,
} from '../testing/live-graph.fixture';
import { buildUuidToBackendIdMap, getConnectionDiff, getNodeDiff } from './diff';
import { buildBulkSavePayload } from './payload';
import { NodeDiffByType } from './types';

interface TimeoutNodeCase {
    type: ExecutionTimeoutNodeType;
    listKey: keyof GraphDto & string;
    diffKey: keyof NodeDiffByType;
    /** The loader of the node type, fed its fixture DTO with `execution_timeout` replaced. */
    load(executionTimeout: number | undefined): { execution_timeout: number | null };
}

const CASES: TimeoutNodeCase[] = [
    {
        type: NodeType.PYTHON,
        listKey: 'python_node_list',
        diffKey: 'pythonNodes',
        load: (minutes) => mapPythonNodeToModel({ ...livePython, execution_timeout: minutes }),
    },
    {
        type: NodeType.WEBHOOK_TRIGGER,
        listKey: 'webhook_trigger_node_list',
        diffKey: 'webhookNodes',
        load: (minutes) => mapWebhookTriggerNodeToModel({ ...liveWebhook, execution_timeout: minutes }),
    },
    {
        type: NodeType.CLASSIFICATION_TABLE,
        listKey: 'classification_decision_table_node_list',
        diffKey: 'classificationDecisionTableNodes',
        load: (minutes) =>
            mapClassificationDecisionTableNodeToModel({ ...liveClassificationTable, execution_timeout: minutes }),
    },
    {
        type: NodeType.FILE_EXTRACTOR,
        listKey: 'file_extractor_node_list',
        diffKey: 'fileExtractorNodes',
        load: (minutes) => mapFileExtractorNodeToModel({ ...liveFileExtractor, execution_timeout: minutes }),
    },
    {
        type: NodeType.AUDIO_TO_TEXT,
        listKey: 'audio_transcription_node_list',
        diffKey: 'audioToTextNodes',
        load: (minutes) => mapAudioToTextNodeToModel({ ...liveAudio, execution_timeout: minutes }),
    },
];

const loadedFlow: FlowModel = buildFlowModelFromGraphDto(liveGraph, [{ id: 99 }]);
const emptyFlow: FlowModel = { nodes: [], connections: [] };

function nodeOf(flow: FlowModel, type: NodeType): NodeModel {
    const found = flow.nodes.find((node) => node.type === type);
    if (!found) throw new Error(`The live graph fixture has no ${type} node`);
    return found;
}

function withTimeout(flow: FlowModel, type: NodeType, minutes: number | null): FlowModel {
    return {
        ...flow,
        nodes: flow.nodes.map((node) =>
            node.type === type ? ({ ...node, execution_timeout: minutes } as NodeModel) : node
        ),
    };
}

function bulkSavePayload(previous: FlowModel, current: FlowModel): Record<string, unknown> {
    const idMap = buildUuidToBackendIdMap(current.nodes);
    return buildBulkSavePayload(
        liveGraph.id,
        getNodeDiff(previous, current),
        getConnectionDiff(previous, current, idMap),
        current,
        idMap,
        liveGraph.save_version
    );
}

describe.each(CASES)('execution timeout of a $type node', ({ type, listKey, diffKey, load }) => {
    it('loads the stored timeout', () => {
        expect(load(7).execution_timeout).toBe(7);
    });

    it('loads a node from a version saved before nodes had a timeout without one', () => {
        expect(load(undefined).execution_timeout).toBeNull();
    });

    it('saves a node whose only change is its timeout', () => {
        const edited = withTimeout(loadedFlow, type, 9);

        const diff = getNodeDiff(loadedFlow, edited);

        expect(diff[diffKey].toUpdate.map((update) => update.current.backendId)).toEqual([
            nodeOf(loadedFlow, type).backendId,
        ]);
    });

    it('does not save an unchanged timeout', () => {
        const diff = getNodeDiff(loadedFlow, { ...loadedFlow, nodes: loadedFlow.nodes.map((node) => ({ ...node })) });

        expect(diff[diffKey].toUpdate).toEqual([]);
    });

    it('sends the timeout of an updated node', () => {
        const payload = bulkSavePayload(loadedFlow, withTimeout(loadedFlow, type, 9));

        expect(payload[listKey]).toEqual([
            expect.objectContaining({ id: nodeOf(loadedFlow, type).backendId, execution_timeout: 9 }),
        ]);
    });

    it('sends the timeout of a new node', () => {
        const payload = bulkSavePayload(emptyFlow, withTimeout(loadedFlow, type, 4));

        expect(payload[listKey]).toEqual([expect.objectContaining({ execution_timeout: 4 })]);
    });

    it('refuses to build a payload for a node without a timeout instead of sending none', () => {
        expect(() => bulkSavePayload(loadedFlow, withTimeout(loadedFlow, type, null))).toThrow(
            /has no execution timeout/
        );
    });
});
