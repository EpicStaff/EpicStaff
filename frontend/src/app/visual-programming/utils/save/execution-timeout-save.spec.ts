import { NodeType } from '@shared/models';

import { GraphDto } from '../../../features/flows/models/graph.model';
import { FlowModel } from '../../core/models/flow.model';
import {
    ClassificationDecisionTableNodeModel,
    NodeModel,
    PythonNodeModel,
    WebhookTriggerNodeModel,
} from '../../core/models/node.model';
import { buildFlowModelFromGraphDto } from '../load/build-flow-model-from-graph-dto';
import { liveClassificationTable, liveGraph, livePython, liveWebhook } from '../testing/live-graph.fixture';
import { buildUuidToBackendIdMap, getConnectionDiff, getNodeDiff } from './diff';
import { buildBulkSavePayload } from './payload';
import { NodeDiffByType } from './types';

const STORED_SECONDS = 90;
const EDITED_SECONDS = 300;

/** One python code of a node: where the flow model keeps its timeout and where the bulk save sends it. */
interface TimedCodeCase {
    name: string;
    type: NodeType;
    listKey: keyof GraphDto & string;
    diffKey: keyof NodeDiffByType;
    timeoutOf(node: NodeModel): number | undefined;
    withTimeout(node: NodeModel, seconds: number | undefined): NodeModel;
    sentTimeout(item: Record<string, unknown>): unknown;
}

const POST_CODE = { code: 'def main(): return 1', entrypoint: 'main', libraries: [], global_kwargs: {}, secrets: [] };

function cdtWithComputation(
    node: NodeModel,
    key: 'pre_computation' | 'post_computation',
    seconds: number | undefined
): NodeModel {
    const table = (node as ClassificationDecisionTableNodeModel).data.table;
    return {
        ...node,
        data: {
            ...(node as ClassificationDecisionTableNodeModel).data,
            table: { ...table, [key]: { ...table[key], execution_timeout: seconds } },
        },
    } as NodeModel;
}

const CASES: TimedCodeCase[] = [
    {
        name: 'Python node code',
        type: NodeType.PYTHON,
        listKey: 'python_node_list',
        diffKey: 'pythonNodes',
        timeoutOf: (node) => (node as PythonNodeModel).data.execution_timeout,
        withTimeout: (node, seconds) =>
            ({ ...node, data: { ...(node as PythonNodeModel).data, execution_timeout: seconds } }) as NodeModel,
        sentTimeout: (item) => (item['python_code'] as Record<string, unknown>)['execution_timeout'],
    },
    {
        name: 'Webhook trigger code',
        type: NodeType.WEBHOOK_TRIGGER,
        listKey: 'webhook_trigger_node_list',
        diffKey: 'webhookNodes',
        timeoutOf: (node) => (node as WebhookTriggerNodeModel).data.python_code.execution_timeout,
        withTimeout: (node, seconds) => {
            const data = (node as WebhookTriggerNodeModel).data;
            return {
                ...node,
                data: { ...data, python_code: { ...data.python_code, execution_timeout: seconds } },
            } as NodeModel;
        },
        sentTimeout: (item) => (item['python_code'] as Record<string, unknown>)['execution_timeout'],
    },
    {
        name: 'classification table pre-computation',
        type: NodeType.CLASSIFICATION_TABLE,
        listKey: 'classification_decision_table_node_list',
        diffKey: 'classificationDecisionTableNodes',
        timeoutOf: (node) =>
            (node as ClassificationDecisionTableNodeModel).data.table.pre_computation?.execution_timeout,
        withTimeout: (node, seconds) => cdtWithComputation(node, 'pre_computation', seconds),
        sentTimeout: (item) => (item['pre_python_code'] as Record<string, unknown>)['execution_timeout'],
    },
    {
        name: 'classification table post-computation',
        type: NodeType.CLASSIFICATION_TABLE,
        listKey: 'classification_decision_table_node_list',
        diffKey: 'classificationDecisionTableNodes',
        timeoutOf: (node) =>
            (node as ClassificationDecisionTableNodeModel).data.table.post_computation?.execution_timeout,
        withTimeout: (node, seconds) => cdtWithComputation(node, 'post_computation', seconds),
        sentTimeout: (item) => (item['post_python_code'] as Record<string, unknown>)['execution_timeout'],
    },
];

/** The live graph with every code above stored with `seconds` (or without a timeout). */
function storedGraph(seconds: number | undefined): GraphDto {
    return {
        ...liveGraph,
        python_node_list: [{ ...livePython, python_code: { ...livePython.python_code, execution_timeout: seconds } }],
        webhook_trigger_node_list: [
            { ...liveWebhook, python_code: { ...liveWebhook.python_code, execution_timeout: seconds } },
        ],
        classification_decision_table_node_list: [
            {
                ...liveClassificationTable,
                pre_python_code: { ...liveClassificationTable.pre_python_code!, execution_timeout: seconds },
                post_python_code: { ...POST_CODE, execution_timeout: seconds },
            },
        ],
    };
}

function load(graph: GraphDto): FlowModel {
    return buildFlowModelFromGraphDto(graph, [{ id: 99 }]);
}

function nodeOf(flow: FlowModel, type: NodeType): NodeModel {
    const found = flow.nodes.find((node) => node.type === type);
    if (!found) throw new Error(`The live graph fixture has no ${type} node`);
    return found;
}

function edited(flow: FlowModel, testCase: TimedCodeCase, seconds: number | undefined): FlowModel {
    return {
        ...flow,
        nodes: flow.nodes.map((node) => (node.type === testCase.type ? testCase.withTimeout(node, seconds) : node)),
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

function sentItems(payload: Record<string, unknown>, testCase: TimedCodeCase): Record<string, unknown>[] {
    return payload[testCase.listKey] as Record<string, unknown>[];
}

describe.each(CASES)('execution timeout of a $name', (testCase) => {
    const timedFlow = load(storedGraph(STORED_SECONDS));
    const untimedFlow = load(storedGraph(undefined));
    const emptyFlow: FlowModel = { nodes: [], connections: [] };

    it('loads the stored timeout', () => {
        expect(testCase.timeoutOf(nodeOf(timedFlow, testCase.type))).toBe(STORED_SECONDS);
    });

    it('loads a code stored without a timeout without one', () => {
        expect(testCase.timeoutOf(nodeOf(untimedFlow, testCase.type))).toBeUndefined();
    });

    it('saves a node whose only change is the timeout', () => {
        const diff = getNodeDiff(timedFlow, edited(timedFlow, testCase, EDITED_SECONDS));

        expect(diff[testCase.diffKey].toUpdate.map((update) => update.current.backendId)).toEqual([
            nodeOf(timedFlow, testCase.type).backendId,
        ]);
    });

    it('does not save an unchanged timeout', () => {
        const copy: FlowModel = { ...timedFlow, nodes: timedFlow.nodes.map((node) => ({ ...node })) };

        expect(getNodeDiff(timedFlow, copy)[testCase.diffKey].toUpdate).toEqual([]);
    });

    it('sends the edited timeout of an updated node', () => {
        const payload = bulkSavePayload(timedFlow, edited(timedFlow, testCase, EDITED_SECONDS));

        const [item] = sentItems(payload, testCase);
        expect(item['id']).toBe(nodeOf(timedFlow, testCase.type).backendId);
        expect(testCase.sentTimeout(item)).toBe(EDITED_SECONDS);
    });

    it('sends the timeout of a new node', () => {
        const payload = bulkSavePayload(emptyFlow, timedFlow);

        expect(sentItems(payload, testCase).map((item) => testCase.sentTimeout(item))).toEqual([STORED_SECONDS]);
    });

    it('sends no timeout for a code without one, so the backend applies its default', () => {
        const payload = bulkSavePayload(emptyFlow, untimedFlow);

        const [item] = sentItems(payload, testCase);
        expect(testCase.sentTimeout(JSON.parse(JSON.stringify(item)) as Record<string, unknown>)).toBeUndefined();
    });
});
