import { CustomPythonCode, NodeType } from '@shared/models';

import { DEFAULT_KEY_VALUE_MODE, MISSING_END_OUTPUT_MAP } from '../../core/constants/default-node-data';
import { findCdtSection } from '../../core/models/cdt-section.model';
import { ComputationConfig } from '../../core/models/classification-decision-table.model';
import { ConditionGroup } from '../../core/models/decision-table.model';
import { AgentNodeModel, BaseNodeModel, NodeModel } from '../../core/models/node.model';
import { ScheduleTriggerNodeData } from '../../core/models/schedule-trigger.model';
import { InlineSurface } from '../../core/models/task-node.model';
import { FieldName } from './field-display';
import {
    emptyToNull,
    normalizeSearchConfigs,
    sortByCanonicalJson,
    sortedNumbers,
    sortedStrings,
    sortWeekdays,
    stripNodeNumberSuffix,
} from './normalize';

/**
 * Semantic projections: what of each node type counts as content in a version diff. A projection
 * turns a node into one plain, normalized object, like a serializer would. Layout, canvas ids and
 * backend ids are never projected, so two loads of the same node give equal objects.
 *
 * How `diff-fields.ts` walks a projection:
 * - every top-level key is a field;
 * - the value of a `NESTED_FIELDS` key is an object whose keys are fields too (`python_code.code`);
 * - the value of a `KEYED_COLLECTIONS` key is an object of items keyed by the item key; each item's
 *   keys are fields (`condition_groups[name=yes].next_node`), and an item on one side only is added
 *   or deleted as a whole;
 * - every other value (scalars, lists, maps like `input_map`) is compared whole.
 */

export type Projection = Readonly<Record<string, unknown>>;

/** Fields whose value is a fixed set of sub-fields, each compared on its own. `null` = absent. */
export const NESTED_FIELDS: ReadonlySet<FieldName> = new Set<FieldName>([
    'python_code',
    'pre_computation',
    'post_computation',
    'inline_surface',
]);

/** Keyed collections, and how an item key is written in a path: `condition_groups[name=yes]`, `tasks[2]`. */
export const KEYED_COLLECTIONS: Readonly<Partial<Record<FieldName, string>>> = {
    condition_groups: 'name=',
    prompts: 'key=',
    tasks: '',
};

export function isNestedField(field: string): boolean {
    return (NESTED_FIELDS as ReadonlySet<string>).has(field);
}

/** How an item key is written in a path, or `undefined` when `field` is not a keyed collection. */
export function keyPrefixOf(field: string): string | undefined {
    return Object.hasOwn(KEYED_COLLECTIONS, field)
        ? (KEYED_COLLECTIONS as Readonly<Record<string, string>>)[field]
        : undefined;
}

export interface ProjectionContext {
    /** Match key of the node with this canvas id on the same side; `null` when there is no such node. */
    nodeKey(canvasId: string | null | undefined): string | null;
}

export interface NodeProjection<TNode extends NodeModel> {
    project(node: TNode, context: ProjectionContext): Projection;
    /**
     * Node-model paths (`data.test_payload`, `data.fields[].id`) that the save comparables in
     * `utils/save/diff.ts` read but the diff leaves out on purpose, each with the reason.
     */
    ignored: Readonly<Record<string, string>>;
}

type NodeOfType<TType extends NodeType> = Extract<NodeModel, { type: TType }>;

export type SemanticProjectionRegistry = { [TType in NodeType]: NodeProjection<NodeOfType<TType>> };

/** Node-model paths no projection reads, for every node type. */
export const IGNORED_NODE_PATHS: Readonly<Record<string, string>> = {
    id: 'canvas id, new on every load',
    backendId: 'backend id, new after a restore or import',
    nodeUuid: 'the match key itself',
    type: 'part of the match',
    position: 'layout',
    size: 'layout',
    color: 'layout',
    icon: 'layout',
    nodeNumber: 'layout (the #N badge); restore renumbers it',
    ports: 'layout, rebuilt from the node data',
    isBlocked: 'derived from the subflow reference',
};

const PYTHON_CODE_IGNORED = {
    id: 'backend id of the code row',
    name: 'a copy of node_name',
    secret_ids: 'secrets are compared by their resolved names',
};

const INLINE_SURFACE_IGNORED = {
    'data.inline_surface.id': 'backend id of the surface row',
    'data.inline_surface.created_at': 'timestamp',
    'data.inline_surface.updated_at': 'timestamp',
    'data.inline_surface.storage_items': 'not stored in versions',
    'data.inline_surface.knowledge': 'not stored in versions',
};

const TEST_AID = 'a testing aid, not part of the flow';

export const SEMANTIC_PROJECTIONS = {
    [NodeType.START]: {
        project: (node) => ({ variables: node.data.initialState ?? {} }),
        ignored: {},
    },
    [NodeType.END]: {
        project: (node) => ({ output_map: node.data.output_map ?? MISSING_END_OUTPUT_MAP }),
        ignored: {},
    },
    [NodeType.NOTE]: {
        project: (node) => ({ content: node.data.content }),
        ignored: { node_name: 'notes are diffed by content only', 'data.backgroundColor': 'layout' },
    },
    [NodeType.PYTHON]: {
        project: (node) => ({
            node_name: nodeName(node),
            // Only here: the webhook and table load mappers drop the venv, so their models never hold one.
            python_code: { ...pythonCode(node.data), venv_id: node.data.venv_id ?? null },
            use_storage: node.data.use_storage ?? false,
            ...inputOutput(node),
        }),
        ignored: { test_input: TEST_AID, ...prefixKeys('data.', PYTHON_CODE_IGNORED) },
    },
    [NodeType.WEBHOOK_TRIGGER]: {
        project: (node) => ({
            node_name: nodeName(node),
            python_code: pythonCode(node.data.python_code),
            use_storage: node.data.use_storage ?? false,
            webhook_trigger: node.data.webhook_trigger,
        }),
        ignored: {
            'data.test_payload': TEST_AID,
            ...prefixKeys('data.python_code.', PYTHON_CODE_IGNORED),
            input_map: 'the run ignores it: the node always gets every flow variable',
            output_variable_path: 'the run ignores it: the node always writes its result to variables',
        },
    },
    [NodeType.TELEGRAM_TRIGGER]: {
        project: (node) => ({
            node_name: nodeName(node),
            telegram_bot_api_key_secret_id: node.data.telegram_bot_api_key_secret_id,
            webhook_trigger: node.data.webhook_trigger,
            fields: sortByCanonicalJson(
                (node.data.fields ?? []).map(({ parent, field_name, variable_path }) => ({
                    parent,
                    field_name,
                    variable_path,
                }))
            ),
        }),
        ignored: { 'data.test_payload': TEST_AID, 'data.fields[].id': 'backend id of the field row' },
    },
    [NodeType.SCHEDULE_TRIGGER]: {
        project: (node) => ({
            node_name: nodeName(node),
            is_active: node.data.isActive,
            run_mode: node.data.runMode,
            start_date_time: emptyToNull(node.data.startDateTime),
            ...scheduleSettings(node.data),
            timezone: node.data.timezone,
        }),
        ignored: {},
    },
    [NodeType.TASK]: {
        project: (node) => ({
            node_name: nodeName(node),
            instructions: node.data.instructions,
            output_schema: node.data.output_schema ?? {},
            remember_output: node.data.remember_output ?? false,
            agent_definition: node.data.agent_definition,
            ...inputOutput(node),
            surface_list: sortedNumbers(node.data.surface_list),
            inline_surface: inlineSurface(node.data.inline_surface),
        }),
        ignored: INLINE_SURFACE_IGNORED,
    },
    [NodeType.AGENT]: {
        project: (node) => ({
            node_name: nodeName(node),
            agent_definition: node.data.agent_definition,
            ...inputOutput(node),
            surface_list: sortedNumbers(node.data.surface_list),
            inline_surface: inlineSurface(node.data.inline_surface),
            tasks: agentTasks(node.data.tasks ?? []),
        }),
        ignored: INLINE_SURFACE_IGNORED,
    },
    [NodeType.FILE_EXTRACTOR]: {
        project: (node) => ({ node_name: nodeName(node), ...inputOutput(node) }),
        ignored: {},
    },
    [NodeType.AUDIO_TO_TEXT]: {
        project: (node) => ({ node_name: nodeName(node), ...inputOutput(node) }),
        ignored: {},
    },
    [NodeType.SUBGRAPH]: {
        project: (node) => ({ node_name: nodeName(node), subgraph: node.data.id, ...inputOutput(node) }),
        ignored: {},
    },
    [NodeType.KNOWLEDGE_RETRIEVER]: {
        project: (node) => ({
            node_name: nodeName(node),
            ...inputOutput(node),
            source_collection: node.data?.source_collection,
            rag_type: node.data?.rag_type,
            rag_id: node.data?.rag_id,
            query: node.data?.query ?? '',
            search_method: node.data?.search_method,
            search_configs: normalizeSearchConfigs(node.data?.search_configs),
        }),
        ignored: {},
    },
    [NodeType.KEY_VALUE]: {
        project: (node) => ({
            node_name: nodeName(node),
            key_value_table: node.data?.key_value_table,
            mode: node.data?.mode ?? DEFAULT_KEY_VALUE_MODE,
            // Entries run in order.
            entries: node.data?.entries ?? [],
        }),
        ignored: {
            input_map: 'the run ignores it: each entry names the flow state path it reads or writes',
            output_variable_path: 'always null: read values go to each entry’s own path',
        },
    },
    [NodeType.TABLE]: {
        project: (node, context) => {
            const table = node.data.table;
            return {
                node_name: nodeName(node),
                condition_groups: keyedBy(
                    comparedConditionGroups(NodeType.TABLE, table.condition_groups ?? []),
                    ({ key }) => key,
                    ({ group }, index) => ({
                        position: index + 1,
                        group_type: group.group_type,
                        expression: emptyToNull(group.expression),
                        conditions: (group.conditions ?? []).map(({ condition_name, condition }) => ({
                            condition_name,
                            condition,
                        })),
                        manipulation: emptyToNull(group.manipulation),
                        next_node: context.nodeKey(group.next_node),
                    })
                ),
                default_next_node: context.nodeKey(table.default_next_node),
                next_error_node: context.nodeKey(table.next_error_node),
            };
        },
        ignored: {},
    },
    [NodeType.CLASSIFICATION_TABLE]: {
        project: (node, context) => {
            const table = node.data.table;
            const sections = table.sections ?? [];
            const prompts = table.prompts ?? {};
            return {
                node_name: nodeName(node),
                pre_computation: computation(table.pre_computation, {
                    code: table.pre_computation_code,
                    inputMap: table.pre_input_map,
                    outputVariablePath: table.pre_output_variable_path,
                }),
                pre_use_storage: table.pre_use_storage ?? false,
                post_computation: computation(table.post_computation, {
                    code: table.post_computation_code,
                    inputMap: table.post_input_map,
                    outputVariablePath: table.post_output_variable_path,
                }),
                post_use_storage: table.post_use_storage ?? false,
                condition_groups: keyedBy(
                    comparedConditionGroups(NodeType.CLASSIFICATION_TABLE, table.condition_groups ?? []),
                    ({ key }) => key,
                    ({ group }, index) => ({
                        position: index + 1,
                        expression: emptyToNull(group.expression),
                        prompt_id: emptyToNull(group.prompt_id),
                        manipulation: emptyToNull(group.manipulation),
                        continue_flag: !!(group.continue_flag ?? group.continue),
                        route_code: emptyToNull(group.route_code),
                        // Section ids are internal; colour is layout.
                        section: findCdtSection(sections, group.section)?.name ?? null,
                        next_node: context.nodeKey(group.next_node),
                        dock_visible: group.dock_visible !== false,
                        field_expressions: group.field_expressions ?? {},
                        field_manipulations: group.field_manipulations ?? {},
                    })
                ),
                prompts: keyedBy(
                    Object.keys(prompts).sort(),
                    (promptKey) => promptKey,
                    (promptKey) => ({
                        prompt_text: prompts[promptKey].prompt_text ?? '',
                        llm_config: prompts[promptKey].llm_config,
                        output_schema: prompts[promptKey].output_schema,
                        result_variable: prompts[promptKey].result_variable ?? '',
                        variable_mappings: prompts[promptKey].variable_mappings ?? {},
                    })
                ),
                default_llm_config: table.default_llm_config,
                default_next_node: context.nodeKey(table.default_next_node),
                next_error_node: context.nodeKey(table.next_error_node),
            };
        },
        ignored: {
            'data.table.pre_computation.secret_ids': 'secrets are compared by their resolved names',
            'data.table.post_computation.secret_ids': 'secrets are compared by their resolved names',
            'data.table.sections[].metadata': 'section colour is layout; groups are compared by section name',
            explanations: 'generated step explanations shown in the editor, not part of how the table routes',
        },
    },
    // Never loaded from or saved to the backend; kept so the registry covers every node type.
    [NodeType.TOOL]: {
        project: (node) => ({ node_name: nodeName(node) }),
        ignored: {},
    },
} satisfies SemanticProjectionRegistry;

export function projectNode(node: NodeModel, context: ProjectionContext): Projection {
    const projection = SEMANTIC_PROJECTIONS[node.type] as NodeProjection<NodeModel>;
    return projection.project(node, context);
}

function prefixKeys(prefix: string, record: Readonly<Record<string, string>>): Record<string, string> {
    return Object.fromEntries(Object.entries(record).map(([key, value]) => [`${prefix}${key}`, value]));
}

/** Restore and import renumber nodes, so the ` #N` suffix is not part of the name. */
function nodeName(node: BaseNodeModel): string {
    return stripNodeNumberSuffix(node.node_name);
}

function inputOutput(node: BaseNodeModel): Projection {
    return { input_map: node.input_map ?? {}, output_variable_path: emptyToNull(node.output_variable_path) };
}

/**
 * Items keyed by user data (group names, prompt keys). The object has no prototype, so a key like
 * `__proto__` or `constructor` is just a key. A repeated key gets a `#2`, `#3`… suffix.
 */
function keyedBy<TItem>(
    items: readonly TItem[],
    keyOf: (item: TItem) => string,
    project: (item: TItem, index: number) => Projection
): Record<string, Projection> {
    const collection: Record<string, Projection> = Object.create(null);
    items.forEach((item, index) => {
        collection[uniqueKey(keyOf(item), (key) => key in collection)] = project(item, index);
    });
    return collection;
}

/** `baseKey`, or with a `#2`, `#3`… suffix when it is taken already. */
function uniqueKey(baseKey: string, isTaken: (key: string) => boolean): string {
    let key = baseKey;
    for (let repeat = 2; isTaken(key); repeat++) key = `${baseKey}#${repeat}`;
    return key;
}

/** Secrets are compared by their resolved names; on the version side, the names a restore re-links. */
function pythonCode(code: CustomPythonCode): Projection {
    return {
        code: code.code,
        entrypoint: code.entrypoint,
        secret_names: sortedStrings(code.secret_names),
        execution_timeout: code.execution_timeout ?? null,
    };
}

/**
 * The interval and end settings as the scheduler reads them. A setting it skips is projected as `null`, so a stale
 * value the panel hides (left by an import, the flow assistant or the API) is not a change. The save path drops the
 * same settings (`buildScheduleBlock`). They are read here, not listed as `ignored`, because whether they count
 * depends on the run mode, the unit and the end type.
 */
function scheduleSettings(data: ScheduleTriggerNodeData): Projection {
    const { runMode, intervalEvery, intervalUnit, weekdays, endType, endDateTime, maxRuns } = data;
    if (runMode === 'once') {
        // A one-off run reads only its start date and time.
        return {
            interval_every: null,
            interval_unit: null,
            weekdays: null,
            end_type: null,
            end_date_time: null,
            max_runs: null,
        };
    }
    return {
        interval_every: intervalEvery,
        interval_unit: intervalUnit,
        // Only the "days" and "weeks" units read weekdays. The panel shows them for "weeks" only.
        weekdays: intervalUnit === 'days' || intervalUnit === 'weeks' ? sortWeekdays(weekdays) : null,
        end_type: endType,
        end_date_time: endType === 'on_date' ? endDateTime : null,
        max_runs: endType === 'after_n_runs' ? maxRuns : null,
    };
}

/** Storage items and knowledge are not stored in versions, so they are not compared. */
function inlineSurface(surface: InlineSurface | null | undefined): Projection | null {
    if (!surface) return null;
    return {
        instructions: surface.instructions ?? '',
        python_tools: sortByCanonicalJson(surface.python_tools),
        mcp_tools: sortByCanonicalJson(surface.mcp_tools),
    };
}

/** Tasks run in order, so they are keyed by position; context refs become the positions of the referenced tasks. */
function agentTasks(tasks: AgentNodeModel['data']['tasks']): Record<string, Projection> {
    const positionOf = (reference: { id?: number; tempId?: string }): number | null => {
        const index = tasks.findIndex((task) =>
            reference.id != null ? task.id === reference.id : task.tempId === reference.tempId
        );
        return index === -1 ? null : index + 1;
    };
    return keyedBy(
        tasks.map((task, index) => ({ task, position: String(index + 1) })),
        ({ position }) => position,
        ({ task }) => ({
            name: task.name,
            instructions: task.instructions,
            output_schema: task.output_schema ?? {},
            context_tasks: sortedNumbers(
                (task.contextRefs ?? []).map(positionOf).filter((position): position is number => position !== null)
            ),
        })
    );
}

/** A condition group of a decision table, with its key in the diff. */
export interface KeyedConditionGroup<TGroup extends ConditionGroup> {
    group: TGroup;
    /**
     * Its item key in the diff (`condition_groups[name=<key>]`): its name as stored, with `#2`, `#3`… on a repeated
     * name, counted in evaluation order; `null` for a group the diff leaves out (an invalid Decision Table group: it is
     * never saved). A grid finds a group's row changes by this key, never by its name.
     */
    key: string | null;
}

/**
 * Every condition group of a decision table in evaluation order (`order`, then list position), each with its key in
 * the diff. A group's place in this list (from 1) is the row number the Decision Table grid shows.
 */
export function conditionGroupDiffKeys<TGroup extends ConditionGroup>(
    type: NodeType.TABLE | NodeType.CLASSIFICATION_TABLE,
    groups: readonly TGroup[]
): KeyedConditionGroup<TGroup>[] {
    const taken = new Set<string>();
    return sortedByOrder(groups).map((group) => {
        if (type === NodeType.TABLE && group.valid === false) return { group, key: null };
        const key = uniqueKey(group.group_name, (candidate) => taken.has(candidate));
        taken.add(key);
        return { group, key };
    });
}

/**
 * The condition groups the diff compares, in evaluation order, each with its key: their `position` in the diff is
 * their place in this list (from 1).
 */
function comparedConditionGroups<TGroup extends ConditionGroup>(
    type: NodeType.TABLE | NodeType.CLASSIFICATION_TABLE,
    groups: readonly TGroup[]
): { group: TGroup; key: string }[] {
    return conditionGroupDiffKeys(type, groups).filter(
        (keyed): keyed is { group: TGroup; key: string } => keyed.key !== null
    );
}

/** Condition groups in evaluation order (`order`, then list position). */
function sortedByOrder<TGroup extends { order?: number }>(groups: readonly TGroup[]): TGroup[] {
    return groups
        .map((group, index) => ({ group, index, order: group.order ?? Number.MAX_SAFE_INTEGER }))
        .sort((left, right) => left.order - right.order || left.index - right.index)
        .map(({ group }) => group);
}

/** The nested computation block wins over the flat legacy columns, as in the save comparable. */
function computation(
    block: ComputationConfig | undefined,
    flat: {
        code: string | null | undefined;
        inputMap: Record<string, string> | undefined;
        outputVariablePath: string | null | undefined;
    }
): Projection {
    return {
        code: block?.code || flat.code || null,
        input_map: block?.input_map || flat.inputMap || {},
        output_variable_path: block?.output_variable_path || flat.outputVariablePath || null,
        secret_names: sortedStrings(block?.secret_names),
        execution_timeout: block?.execution_timeout ?? null,
    };
}
