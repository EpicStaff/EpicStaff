import { NodeType } from '@shared/models';

import { GraphDto } from '../../../features/flows/models/graph.model';
import { TEST_EXECUTION_TIMEOUT_LIMITS } from '../../../shared/services/execution-timeout-limits/execution-timeout-limits.testing';
import { PromptConfig } from '../../core/models/classification-decision-table.model';
import {
    AgentNodeModel,
    ClassificationDecisionTableNodeModel,
    KnowledgeRetrieverNodeModel,
    NodeModel,
    ScheduleTriggerNodeModel,
    TaskNodeModel,
    TelegramTriggerNodeModel,
} from '../../core/models/node.model';
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
                    kind: 'llm',
                    system_one_config: null,
                    questions: {},
                    input_map: {},
                },
                {
                    id: 8,
                    prompt_key: 'check',
                    prompt_text: '',
                    llm_config: null,
                    output_schema: {},
                    result_variable: 'checked',
                    variable_mappings: {},
                    kind: 'system_one',
                    system_one_config: 4,
                    questions: {
                        correct: { type: 'noul', instructions: 'Is it correct?', criteria: { true: 'yes' } },
                        tone: { type: 'choice', instructions: 'Which tone?', criteria: { calm: 'Calm' } },
                        quality: { type: 'score', instructions: 'How good?', criteria: ['low', 'high'] },
                    },
                    input_map: { text: 'variables.text' },
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
    executionTimeoutLimits: TEST_EXECUTION_TIMEOUT_LIMITS,
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

describe('classification decision table prompt projection', () => {
    const table = buildFlowModelFromGraphDto(liveGraph).nodes.find(
        (node): node is ClassificationDecisionTableNodeModel => node.type === NodeType.CLASSIFICATION_TABLE
    )!;
    // As the editor creates them: an LLM prompt has no kind or System One fields; a System One entry has them all.
    const llmPrompt: PromptConfig = {
        prompt_text: 'Which team?',
        llm_config: 3,
        output_schema: null,
        result_variable: 'team',
        variable_mappings: {},
    };
    const systemOneEntry: PromptConfig = {
        kind: 'system_one',
        system_one_config: 4,
        questions: {
            correct: { type: 'noul', instructions: 'Is it correct?' },
            tone: { type: 'choice', instructions: 'Which tone?', criteria: { calm: 'Calm', angry: 'Angry' } },
            quality: { type: 'score', instructions: 'How good?', criteria: ['low', 'mid', 'high'] },
        },
        input_map: { text: 'variables.text' },
        prompt_text: '',
        llm_config: null,
        output_schema: null,
        result_variable: 'checked',
        variable_mappings: {},
    };

    /** The prompt fields a restore changes when the canvas prompt is `current` and the version's `version`. */
    function changedFields(current: PromptConfig, version: PromptConfig): string[] {
        const project = (prompt: PromptConfig) =>
            projectNode(
                { ...table, data: { ...table.data, table: { ...table.data.table, prompts: { check: prompt } } } },
                stubContext
            );
        return diffProjections(project(current), project(version)).map((change) => change.path);
    }

    const questionsWith = (changes: Record<string, unknown>): PromptConfig['questions'] =>
        ({ ...systemOneEntry.questions, ...changes }) as PromptConfig['questions'];

    it.each<[string, PromptConfig, PromptConfig, string[]]>([
        // Load paths and stored defaults: the same prompt, never a change.
        [
            'an LLM prompt saved before System One (no kind) and one the editor holds as llm',
            llmPrompt,
            { ...llmPrompt, kind: 'llm', system_one_config: null, questions: {}, input_map: {} },
            [],
        ],
        ['an output schema stored empty and one never set', llmPrompt, { ...llmPrompt, output_schema: {} }, []],
        [
            'stale System One values on an LLM prompt',
            llmPrompt,
            { ...llmPrompt, kind: 'llm', system_one_config: 9, questions: questionsWith({}), input_map: { a: 'b' } },
            [],
        ],
        [
            'stale LLM values on a System One entry',
            systemOneEntry,
            { ...systemOneEntry, prompt_text: 'Old prompt', llm_config: 5, output_schema: { type: 'object' } },
            [],
        ],
        [
            'an input map stored empty and one never set',
            { ...systemOneEntry, input_map: undefined },
            { ...systemOneEntry, input_map: {} },
            [],
        ],
        [
            'no config stored as null and one never set',
            { ...systemOneEntry, system_one_config: undefined },
            { ...systemOneEntry, system_one_config: null },
            [],
        ],
        [
            'Choice options in another order',
            systemOneEntry,
            questionsEntry({
                tone: { type: 'choice', instructions: 'Which tone?', criteria: { angry: 'Angry', calm: 'Calm' } },
            }),
            [],
        ],
        [
            'a Noul question without meanings: none, null, empty or blank',
            questionsEntry({ correct: { type: 'noul', instructions: 'Is it correct?', criteria: null } }),
            questionsEntry({ correct: { type: 'noul', instructions: 'Is it correct?', criteria: { true: ' ' } } }),
            [],
        ],
        // Real changes.
        [
            'the kind: an LLM prompt becomes a System One entry',
            llmPrompt,
            systemOneEntry,
            [
                'prompts[key=check].kind',
                'prompts[key=check].prompt_text',
                'prompts[key=check].llm_config',
                'prompts[key=check].result_variable',
                'prompts[key=check].system_one_config',
                'prompts[key=check].input_map',
                'prompts[key=check].questions',
            ],
        ],
        [
            'the kind: a System One entry becomes an LLM prompt',
            systemOneEntry,
            llmPrompt,
            [
                'prompts[key=check].kind',
                'prompts[key=check].prompt_text',
                'prompts[key=check].llm_config',
                'prompts[key=check].result_variable',
                'prompts[key=check].system_one_config',
                'prompts[key=check].input_map',
                'prompts[key=check].questions',
            ],
        ],
        [
            'the config',
            systemOneEntry,
            { ...systemOneEntry, system_one_config: 6 },
            ['prompts[key=check].system_one_config'],
        ],
        [
            'an input map row',
            systemOneEntry,
            { ...systemOneEntry, input_map: { text: 'variables.body' } },
            ['prompts[key=check].input_map'],
        ],
        [
            'the instructions of a question',
            systemOneEntry,
            questionsEntry({ correct: { type: 'noul', instructions: 'Is it right?' } }),
            ['prompts[key=check].questions'],
        ],
        [
            'a Noul meaning',
            systemOneEntry,
            questionsEntry({ correct: { type: 'noul', instructions: 'Is it correct?', criteria: { false: 'no' } } }),
            ['prompts[key=check].questions'],
        ],
        [
            'a Choice option',
            systemOneEntry,
            questionsEntry({ tone: { type: 'choice', instructions: 'Which tone?', criteria: { calm: 'Calm' } } }),
            ['prompts[key=check].questions'],
        ],
        [
            'the order of Score levels',
            systemOneEntry,
            questionsEntry({ quality: { type: 'score', instructions: 'How good?', criteria: ['high', 'mid', 'low'] } }),
            ['prompts[key=check].questions'],
        ],
    ])('%s', (_case, current, version, expected) => {
        expect(changedFields(current, version)).toEqual(expected);
    });

    function questionsEntry(changes: Record<string, unknown>): PromptConfig {
        return { ...systemOneEntry, questions: questionsWith(changes) };
    }
});

describe('text the backend stores trimmed', () => {
    const flow = buildFlowModelFromGraphDto(richGraph);
    const nodeOf = <TNode extends NodeModel>(type: NodeType): TNode =>
        flow.nodes.find((node) => node.type === type) as TNode;

    /** The fields a restore changes when the canvas node is `edit(node)` and the version the stored `node`. */
    function changedPaths(node: NodeModel, edit: (text: (value: string) => string) => NodeModel): string[] {
        const canvas = (append: string) => edit((value) => `${value}${append}`);
        const typed = diffProjections(projectNode(canvas('\n'), stubContext), projectNode(node, stubContext));
        const edited = diffProjections(projectNode(canvas(' edited'), stubContext), projectNode(node, stubContext));
        expect(edited.length, 'a real edit is still a change').toBeGreaterThan(0);
        return typed.map((change) => change.path);
    }

    const task = nodeOf<TaskNodeModel>(NodeType.TASK);
    const agent = nodeOf<AgentNodeModel>(NodeType.AGENT);
    const knowledge = nodeOf<KnowledgeRetrieverNodeModel>(NodeType.KNOWLEDGE_RETRIEVER);
    const telegram = nodeOf<TelegramTriggerNodeModel>(NodeType.TELEGRAM_TRIGGER);
    const classification = nodeOf<ClassificationDecisionTableNodeModel>(NodeType.CLASSIFICATION_TABLE);
    const withTable = (table: Partial<ClassificationDecisionTableNodeModel['data']['table']>): NodeModel => ({
        ...classification,
        data: { ...classification.data, table: { ...classification.data.table, ...table } },
    });
    const storedClassification = withTable({
        pre_output_variable_path: 'variables.pre',
        pre_computation: { ...classification.data.table.pre_computation!, output_variable_path: 'variables.pre' },
        condition_groups: classification.data.table.condition_groups.map((group) => ({
            ...group,
            expression: 'x > 1',
            manipulation: 'y = 1',
            route_code: 'A',
        })),
    }) as ClassificationDecisionTableNodeModel;
    const [group] = storedClassification.data.table.condition_groups;
    const prompt = storedClassification.data.table.prompts!['classify'];

    it.each<[string, NodeModel, (text: (value: string) => string) => NodeModel]>([
        ['a node name', task, (text) => ({ ...task, node_name: text(task.node_name) })],
        [
            'an output variable path',
            { ...task, output_variable_path: 'variables.out' },
            (text) => ({ ...task, output_variable_path: text('variables.out') }),
        ],
        ['Task instructions', task, (text) => ({ ...task, data: { ...task.data, instructions: text('Do it') } })],
        [
            'local surface instructions',
            task,
            (text) => ({
                ...task,
                data: {
                    ...task.data,
                    inline_surface: { ...task.data.inline_surface!, instructions: text('Be brief') },
                },
            }),
        ],
        [
            'an Agent task name and instructions',
            agent,
            (text) => ({
                ...agent,
                data: {
                    ...agent.data,
                    tasks: agent.data.tasks.map((agentTask) => ({
                        ...agentTask,
                        name: text(agentTask.name),
                        instructions: text(agentTask.instructions),
                    })),
                },
            }),
        ],
        ['a Knowledge query', knowledge, (text) => ({ ...knowledge, data: { ...knowledge.data, query: text('q') } })],
        [
            'a Telegram field',
            telegram,
            (text) => ({
                ...telegram,
                data: {
                    ...telegram.data,
                    fields: telegram.data.fields.map((field) => ({
                        ...field,
                        field_name: text(field.field_name),
                        variable_path: text(field.variable_path),
                    })),
                },
            }),
        ],
        [
            'a Classification table output path, expression, manipulation and route code',
            storedClassification,
            (text) =>
                withTable({
                    pre_output_variable_path: text('variables.pre'),
                    pre_computation: {
                        ...classification.data.table.pre_computation!,
                        output_variable_path: text('variables.pre'),
                    },
                    condition_groups: [
                        {
                            ...group,
                            expression: text('x > 1'),
                            manipulation: text('y = 1'),
                            route_code: text('A'),
                        },
                    ],
                }),
        ],
        [
            'a prompt text and result variable',
            storedClassification,
            (text) => ({
                ...storedClassification,
                data: {
                    ...storedClassification.data,
                    table: {
                        ...storedClassification.data.table,
                        prompts: {
                            ...storedClassification.data.table.prompts,
                            classify: {
                                ...prompt,
                                prompt_text: text(prompt.prompt_text),
                                result_variable: text(prompt.result_variable),
                            },
                        },
                    },
                },
            }),
        ],
    ])('%s typed with a trailing newline is not a change; an edit is', (_case, stored, edit) => {
        expect(changedPaths(stored, edit)).toEqual([]);
    });
});
