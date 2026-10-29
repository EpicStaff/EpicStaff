import { NodeType } from '@shared/models';

import { GraphDto } from '../../../features/flows/models/graph.model';
import { NodeModel, ScheduleTriggerNodeModel } from '../../core/models/node.model';
import { ScheduleTriggerNodeData } from '../../core/models/schedule-trigger.model';
import { buildFlowModelFromGraphDto } from '../load';
import { getNodeDiff } from '../save';
import { liveAgent, liveClassificationTable, liveGraph, liveTask } from '../testing/live-graph.fixture';
import { diffProjections } from './diff-fields';
import { FIELD_DISPLAY } from './field-display';
import {
    IGNORED_NODE_PATHS,
    isNestedField,
    keyPrefixOf,
    Projection,
    ProjectionContext,
    projectNode,
    SEMANTIC_PROJECTIONS,
} from './semantic-projections';

/**
 * Drift guard. The save comparables in `utils/save/diff.ts` are private, so they are observed from
 * outside: each node is wrapped in a proxy that records every node-model path read while
 * `getNodeDiff` compares it (`data.fields[].id`, …). The projection is recorded the same way. Every
 * path the save path reads must also be read by the projection, or be listed as ignored on purpose
 * (`IGNORED_NODE_PATHS`, or the type's `ignored`). A new saved field therefore fails here until it
 * is projected or ignored.
 */

// Every list and optional block filled, so their inner fields are read too.
const richGraph: GraphDto = {
    ...liveGraph,
    agent_node_list: [
        {
            ...liveAgent,
            agent_definition: 41,
            surface_list: [52],
            inline_surface: liveTask.inline_surface,
            tasks: [
                { id: 1, name: 'Plan', order: 1, instructions: 'Plan it', output_schema: {}, context_tasks: [] },
                { id: 2, name: 'Do', order: 2, instructions: 'Do it', output_schema: {}, context_tasks: [1] },
            ],
        },
    ],
    classification_decision_table_node_list: [
        {
            ...liveClassificationTable,
            post_python_code: liveClassificationTable.pre_python_code,
            prompt_configs: [
                {
                    id: 7,
                    prompt_key: 'classify',
                    prompt_text: 'Which?',
                    llm_config: 3,
                    output_schema: {},
                    result_variable: 'answer',
                    variable_mappings: {},
                },
            ],
            sections: [{ id: 'section-1', name: 'Main', metadata: { color: '#685FFF' } }],
            condition_groups: liveClassificationTable.condition_groups.map((group) => ({
                ...group,
                prompt: 7,
                section: 'section-1',
            })),
        },
    ],
};

/** A path each save comparable must read, so an empty recording (a broken proxy) cannot pass. */
function expectedSavedPath(type: NodeType): string {
    if (type === NodeType.START) return 'data.initialState';
    if (type === NodeType.END) return 'data.output_map';
    if (type === NodeType.NOTE) return 'data.content';
    return 'node_name';
}

const stubContext: ProjectionContext = {
    nodeKey: (canvasId) => (canvasId ? `key:${canvasId}` : null),
};

function recordReads<T extends object>(target: T, reads: Set<string>, path = ''): T {
    return new Proxy(target, {
        get(object, property, receiver) {
            const value: unknown = Reflect.get(object, property, receiver);
            if (typeof property === 'symbol' || property === 'toJSON') return value;
            const isArray = Array.isArray(object);
            const isIndex = isArray && /^\d+$/.test(property);
            // Array methods and `length` are not data.
            if (isArray && !isIndex) return value;
            const childPath = isIndex ? `${path}[]` : path ? `${path}.${property}` : property;
            if (!isIndex) reads.add(childPath);
            return value !== null && typeof value === 'object' ? recordReads(value, reads, childPath) : value;
        },
    });
}

function readsOfSaveComparable(node: NodeModel): Set<string> {
    const reads = new Set<string>();
    const flow = (): { nodes: NodeModel[]; connections: [] } => ({
        nodes: [recordReads(structuredClone(node), reads)],
        connections: [],
    });
    getNodeDiff(flow(), flow());
    return reads;
}

function readsOfProjection(node: NodeModel): Set<string> {
    const reads = new Set<string>();
    const projection = projectNode(recordReads(structuredClone(node), reads), stubContext);
    // A value taken whole is compared whole: serialising it records its inner paths.
    JSON.stringify(projection);
    return reads;
}

/** Every `FieldChange.field` a projection can produce (item keys removed). */
function fieldNamesOf(projection: Projection, parent = ''): string[] {
    return Object.entries(projection).flatMap(([key, value]) => {
        const field = parent ? `${parent}.${key}` : key;
        if (keyPrefixOf(field) !== undefined) {
            const items = Object.values(value as Record<string, Projection>);
            return [field, `${field}[]`, ...items.flatMap((item) => fieldNamesOf(item, `${field}[]`))];
        }
        if (isNestedField(field) && value) return [field, ...fieldNamesOf(value as Projection, field)];
        return [field];
    });
}

function isIgnored(path: string, ignored: Readonly<Record<string, string>>): boolean {
    return Object.keys(ignored).some(
        (prefix) => path === prefix || path.startsWith(`${prefix}.`) || path.startsWith(`${prefix}[`)
    );
}

describe('semantic projections', () => {
    const flow = buildFlowModelFromGraphDto(richGraph);

    it('cover every node type of the save path (one fixture node each)', () => {
        const savedTypes = Object.values(NodeType).filter((type) => type !== NodeType.TOOL);
        expect(new Set(flow.nodes.map((node) => node.type))).toEqual(new Set(savedTypes));
        expect(Object.keys(SEMANTIC_PROJECTIONS).sort()).toEqual(Object.values(NodeType).sort());
    });

    it.each(Object.values(NodeType).filter((type) => type !== NodeType.TOOL))(
        '%s: every field the save comparable reads is projected or ignored on purpose',
        (type) => {
            const node = flow.nodes.find((candidate) => candidate.type === type)!;
            const ignored = { ...IGNORED_NODE_PATHS, ...SEMANTIC_PROJECTIONS[type].ignored };
            const projected = readsOfProjection(node);
            const saved = readsOfSaveComparable(node);
            expect(saved).toContain(expectedSavedPath(type));
            expect(projected).toContain(expectedSavedPath(type));

            const uncovered = [...saved].filter((path) => !projected.has(path) && !isIgnored(path, ignored));

            expect(uncovered).toEqual([]);
        }
    );

    it('detects a saved field the projection does not read', () => {
        const python = flow.nodes.find((node) => node.type === NodeType.PYTHON)!;
        const projected = readsOfProjection(python);
        projected.delete('data.code');

        const uncovered = [...readsOfSaveComparable(python)].filter(
            (path) => !projected.has(path) && !isIgnored(path, { ...IGNORED_NODE_PATHS })
        );

        expect(uncovered).toContain('data.code');
    });

    it('has a display entry for every field, nested field and item the projections produce', () => {
        const fieldNames = flow.nodes.flatMap((node) => fieldNamesOf(projectNode(node, stubContext)));

        expect([...new Set(fieldNames)].filter((fieldName) => !Object.hasOwn(FIELD_DISPLAY, fieldName))).toEqual([]);
    });
});

describe('schedule projection', () => {
    const schedule = buildFlowModelFromGraphDto(liveGraph).nodes.find(
        (node): node is ScheduleTriggerNodeModel => node.type === NodeType.SCHEDULE_TRIGGER
    )!;
    const once: Partial<ScheduleTriggerNodeData> = {
        runMode: 'once',
        intervalEvery: null,
        intervalUnit: null,
        weekdays: [],
        endType: 'never',
        endDateTime: null,
        maxRuns: null,
    };
    const repeat: Partial<ScheduleTriggerNodeData> = {
        runMode: 'repeat',
        intervalEvery: 1,
        intervalUnit: 'hours',
        weekdays: [],
        endType: 'never',
        endDateTime: null,
        maxRuns: null,
    };

    function changedFields(current: Partial<ScheduleTriggerNodeData>, version: Partial<ScheduleTriggerNodeData>) {
        const project = (data: Partial<ScheduleTriggerNodeData>) =>
            projectNode({ ...schedule, data: { ...schedule.data, ...data } }, stubContext);
        return diffProjections(project(current), project(version)).map((change) => change.field);
    }

    it.each<[string, Partial<ScheduleTriggerNodeData>, Partial<ScheduleTriggerNodeData>, string[]]>([
        [
            'once: stale interval and end settings',
            {
                ...once,
                intervalEvery: 5,
                intervalUnit: 'days',
                weekdays: ['mon'],
                endType: 'after_n_runs',
                endDateTime: '2026-12-01T12:00:00',
                maxRuns: 3,
            },
            once,
            [],
        ],
        ['once → repeat', once, repeat, ['run_mode', 'interval_every', 'interval_unit', 'end_type']],
        [
            'repeat "on date": stale max runs',
            { ...repeat, endType: 'on_date', endDateTime: '2026-12-01T12:00:00', maxRuns: 4 },
            { ...repeat, endType: 'on_date', endDateTime: '2026-12-01T12:00:00' },
            [],
        ],
        [
            'repeat "on date": other end date',
            { ...repeat, endType: 'on_date', endDateTime: '2026-12-01T12:00:00' },
            { ...repeat, endType: 'on_date', endDateTime: '2026-12-02T12:00:00' },
            ['end_date_time'],
        ],
        [
            'repeat "after N runs": stale end date',
            { ...repeat, endType: 'after_n_runs', maxRuns: 3, endDateTime: '2026-12-01T12:00:00' },
            { ...repeat, endType: 'after_n_runs', maxRuns: 3 },
            [],
        ],
        [
            'repeat "after N runs": other max runs',
            { ...repeat, endType: 'after_n_runs', maxRuns: 3 },
            { ...repeat, endType: 'after_n_runs', maxRuns: 4 },
            ['max_runs'],
        ],
        [
            'repeat "never": stale end date and max runs',
            { ...repeat, endDateTime: '2026-12-01T12:00:00', maxRuns: 3 },
            repeat,
            [],
        ],
        ['repeat in hours: stale weekdays', { ...repeat, weekdays: ['mon'] }, repeat, []],
        [
            'repeat in days: other weekdays',
            { ...repeat, intervalUnit: 'days', weekdays: ['mon'] },
            { ...repeat, intervalUnit: 'days', weekdays: ['tue'] },
            ['weekdays'],
        ],
        [
            'repeat in weeks: other weekdays',
            { ...repeat, intervalUnit: 'weeks', weekdays: ['mon'] },
            { ...repeat, intervalUnit: 'weeks', weekdays: ['mon', 'fri'] },
            ['weekdays'],
        ],
    ])('%s', (_case, current, version, expected) => {
        expect(changedFields(current, version)).toEqual(expected);
    });
});
