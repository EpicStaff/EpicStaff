import { formatClockDuration } from '@shared/utils';

import { FieldKind } from './types';

/**
 * How each diffed field is shown, keyed by `FieldChange.field` (the path without item keys).
 * Display only: the diff engine never reads labels or kinds; the field panel calls `fieldKind`.
 * `kind` is set where the value alone cannot tell it (ids of linked entities and nodes, text that
 * may be short); otherwise `fieldKind` derives it.
 * `format` turns a stored value into the text the panel field shows for it (e.g. seconds as a clock), so the
 * hover tooltip reads like the field; such a value is shown and struck as a whole.
 */
interface FieldDisplay {
    label: string;
    kind?: FieldKind;
    format?: (value: unknown) => string;
}

/** Seconds as the execution timeout field shows them: `90` → `00:01:30`. */
function clockDuration(value: unknown): string {
    return typeof value === 'number' ? formatClockDuration(value) : String(value);
}

/**
 * A schedule's date and time as its date and time pickers show them, in the schedule's own timezone (the stored value
 * is the wall-clock time there): `2026-07-01T12:00:00` → `01.07.2026 at 12:00`, the words of the panel's "Next run".
 */
function scheduleDateTime(value: unknown): string {
    const parts = typeof value === 'string' ? /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value) : null;
    if (!parts) return String(value);
    const [, year, month, day, hour, minute] = parts;
    return `${day}.${month}.${year} at ${hour}:${minute}`;
}

export const FIELD_DISPLAY = {
    node_name: { label: 'Name' },
    input_map: { label: 'Input map' },
    output_variable_path: { label: 'Output variable path' },
    variables: { label: 'Variables' },
    output_map: { label: 'Output map' },
    content: { label: 'Content', kind: 'text' },
    python_code: { label: 'Python code' },
    'python_code.code': { label: 'Code', kind: 'text' },
    'python_code.entrypoint': { label: 'Entrypoint' },
    'python_code.venv_id': { label: 'Venv', kind: 'entityRef' },
    'python_code.secret_names': { label: 'Secrets' },
    'python_code.execution_timeout': { label: 'Execution timeout', format: clockDuration },
    use_storage: { label: 'Use storage' },
    webhook_trigger: { label: 'Webhook trigger', kind: 'entityRef' },
    telegram_bot_api_key_secret_id: { label: 'Bot API key secret', kind: 'entityRef' },
    fields: { label: 'Telegram fields' },
    is_active: { label: 'Active' },
    run_mode: { label: 'Run mode' },
    start_date_time: { label: 'Start', format: scheduleDateTime },
    interval_every: { label: 'Repeat every' },
    interval_unit: { label: 'Repeat unit' },
    weekdays: { label: 'Weekdays' },
    end_type: { label: 'Ends' },
    end_date_time: { label: 'End date', format: scheduleDateTime },
    max_runs: { label: 'Max runs' },
    timezone: { label: 'Timezone' },
    instructions: { label: 'Instructions', kind: 'text' },
    output_schema: { label: 'Output schema' },
    remember_output: { label: 'Remember output' },
    agent_definition: { label: 'Agent', kind: 'entityRef' },
    surface_list: { label: 'Surfaces' },
    inline_surface: { label: 'Local surface' },
    'inline_surface.instructions': { label: 'Local surface instructions', kind: 'text' },
    'inline_surface.python_tools': { label: 'Local surface Python tools' },
    'inline_surface.mcp_tools': { label: 'Local surface MCP tools' },
    tasks: { label: 'Tasks' },
    'tasks[]': { label: 'Task' },
    'tasks[].name': { label: 'Task name' },
    'tasks[].instructions': { label: 'Task instructions', kind: 'text' },
    'tasks[].output_schema': { label: 'Task output schema' },
    'tasks[].context_tasks': { label: 'Task context (task positions)' },
    subgraph: { label: 'Subflow', kind: 'entityRef' },
    source_collection: { label: 'Collection', kind: 'entityRef' },
    rag_type: { label: 'RAG type' },
    rag_id: { label: 'RAG', kind: 'entityRef' },
    query: { label: 'Query', kind: 'text' },
    search_method: { label: 'Search method' },
    search_configs: { label: 'Search settings' },
    key_value_table: { label: 'Key-value table', kind: 'entityRef' },
    mode: { label: 'Mode' },
    entries: { label: 'Entries' },
    condition_groups: { label: 'Condition groups' },
    'condition_groups[]': { label: 'Condition group' },
    'condition_groups[].position': { label: 'Condition group position' },
    'condition_groups[].group_type': { label: 'Condition group type' },
    'condition_groups[].expression': { label: 'Condition group expression', kind: 'text' },
    'condition_groups[].conditions': { label: 'Conditions' },
    'condition_groups[].manipulation': { label: 'Manipulation', kind: 'text' },
    'condition_groups[].next_node': { label: 'Route target', kind: 'nodeRef' },
    'condition_groups[].prompt_id': { label: 'Prompt' },
    'condition_groups[].continue_flag': { label: 'Continue' },
    'condition_groups[].route_code': { label: 'Route code' },
    'condition_groups[].section': { label: 'Section' },
    'condition_groups[].dock_visible': { label: 'Route port shown' },
    'condition_groups[].field_expressions': { label: 'Field expressions' },
    'condition_groups[].field_manipulations': { label: 'Field manipulations' },
    default_next_node: { label: 'Default route target', kind: 'nodeRef' },
    next_error_node: { label: 'Error route target', kind: 'nodeRef' },
    pre_computation: { label: 'Pre-computation' },
    'pre_computation.code': { label: 'Pre-computation code', kind: 'text' },
    'pre_computation.input_map': { label: 'Pre-computation input map' },
    'pre_computation.output_variable_path': { label: 'Pre-computation output variable path' },
    'pre_computation.secret_names': { label: 'Pre-computation secrets' },
    'pre_computation.execution_timeout': { label: 'Pre-computation execution timeout', format: clockDuration },
    pre_use_storage: { label: 'Pre-computation uses storage' },
    post_computation: { label: 'Post-computation' },
    'post_computation.code': { label: 'Post-computation code', kind: 'text' },
    'post_computation.input_map': { label: 'Post-computation input map' },
    'post_computation.output_variable_path': { label: 'Post-computation output variable path' },
    'post_computation.secret_names': { label: 'Post-computation secrets' },
    'post_computation.execution_timeout': { label: 'Post-computation execution timeout', format: clockDuration },
    post_use_storage: { label: 'Post-computation uses storage' },
    default_llm_config: { label: 'Default LLM', kind: 'entityRef' },
    prompts: { label: 'Prompts' },
    'prompts[]': { label: 'Prompt' },
    'prompts[].prompt_text': { label: 'Prompt text', kind: 'text' },
    'prompts[].llm_config': { label: 'Prompt LLM', kind: 'entityRef' },
    'prompts[].output_schema': { label: 'Prompt output schema' },
    'prompts[].result_variable': { label: 'Prompt result variable' },
    'prompts[].variable_mappings': { label: 'Prompt variable mappings' },
} as const satisfies Record<string, FieldDisplay>;

/** A field the diff can report. Code that names a field literally uses this type, so a typo does not build. */
export type FieldName = keyof typeof FIELD_DISPLAY;

const LONG_TEXT_LENGTH = 80;

/**
 * The kind from `FIELD_DISPLAY`, or one derived from the values of both sides: a list when either is
 * an array, json when either is an object, text when either is a long or multi-line string, else scalar.
 */
export function fieldKind(field: string, current: unknown, version: unknown): FieldKind {
    const display: FieldDisplay | undefined = Object.hasOwn(FIELD_DISPLAY, field)
        ? (FIELD_DISPLAY as Readonly<Record<string, FieldDisplay>>)[field]
        : undefined;
    if (display?.kind) return display.kind;
    const values = [current, version];
    if (values.some((value) => Array.isArray(value))) return 'list';
    if (values.some((value) => value !== null && typeof value === 'object')) return 'json';
    if (
        values.some((value) => typeof value === 'string' && (value.length > LONG_TEXT_LENGTH || value.includes('\n')))
    ) {
        return 'text';
    }
    return 'scalar';
}

/** The field's display formatter, or `undefined` when its values are shown as they are. */
export function fieldFormat(field: string): ((value: unknown) => string) | undefined {
    return Object.hasOwn(FIELD_DISPLAY, field)
        ? (FIELD_DISPLAY as Readonly<Record<string, FieldDisplay>>)[field].format
        : undefined;
}
