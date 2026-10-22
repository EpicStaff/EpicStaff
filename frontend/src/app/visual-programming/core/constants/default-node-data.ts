import { NODE_COLORS, NodeType } from '@shared/models';

import { AgentNodeData } from '../models/agent-node.model';
import { KeyValueMode, KeyValueNodeData } from '../models/key-value-node.model';
import { TelegramTriggerNodeModel } from '../models/node.model';
import { ScheduleTriggerNodeData } from '../models/schedule-trigger.model';
import { TaskNodeData } from '../models/task-node.model';

/**
 * The End node output map assumed when a node has none (save payload, save comparable, version diff).
 * Not the map a new End node starts with (see `DEFAULT_NODE_DATA`).
 */
export const MISSING_END_OUTPUT_MAP: Readonly<Record<string, string>> = Object.freeze({ context: 'variables.context' });

/** The Key-Value node mode when none is set. */
export const DEFAULT_KEY_VALUE_MODE: KeyValueMode = 'read';

export const DEFAULT_NODE_DATA: Partial<Record<NodeType, () => unknown>> = {
    [NodeType.AGENT]: (): AgentNodeData => ({
        name: 'Agent Node',
        agent_definition: null,
        surface_list: [],
        inline_surface: null,
        tasks: [],
    }),
    [NodeType.PYTHON]: () => ({
        name: 'Python Code Node',
        libraries: [],
        code: 'def main():\n    return\n',
        entrypoint: 'main',
    }),
    [NodeType.TASK]: (): TaskNodeData => ({
        name: 'Task Node',
        instructions: '',
        output_schema: {},
        output_schema_invalid: false,
        remember_output: false,
        agent_definition: null,
        surface_list: [],
        inline_surface: null,
    }),
    [NodeType.TABLE]: () => ({
        name: 'Decision Table',
        table: {
            graph: null,
            condition_groups: [
                {
                    group_name: 'Condition 1',
                    group_type: 'complex',
                    expression: null,
                    conditions: [],
                    manipulation: null,
                    next_node: null,
                    order: 1,
                    valid: false,
                },
            ],
            node_name: '',
            default_next_node: null,
            next_error_node: null,
        },
    }),
    [NodeType.CLASSIFICATION_TABLE]: () => ({
        table: {
            pre_computation_code: '',
            condition_groups: [],
            prompts: {},
            output_variables: [],
            route_variable_name: 'route_code',
            default_next_node: null,
            next_error_node: null,
        },
    }),
    [NodeType.NOTE]: () => ({
        content: 'Add your note here...',
        backgroundColor: NODE_COLORS[NodeType.NOTE],
    }),
    [NodeType.WEBHOOK_TRIGGER]: () => ({
        webhook_trigger: null,
        python_code: {
            name: 'Webhook trigger Node',
            libraries: [],
            code:
                '# Replace this comment with your implementation.\n' +
                '#\n' +
                '# Purpose   : <describe what this webhook handler should do with the incoming event>\n' +
                '# Inputs    : trigger_payload (dict) - payload from the webhook; **kwargs - additional domain variables\n' +
                '# Output    : <the domain variables this handler should update, and their new values>\n' +
                '# Libraries : list any pip packages this code needs in the Libraries field\n' +
                "# Secrets   : declare secrets in the Secrets field, then read them via get_secret('name')\n" +
                '#\n' +
                '# Required signature:\n' +
                '#   def main(trigger_payload: dict, **kwargs) -> ...:\n' +
                '#       ...\n' +
                "#       return ...  # updated values applied to the flow's domain variables\n",
            entrypoint: 'main',
        },
        test_payload: {},
        use_storage: false,
    }),
    [NodeType.TELEGRAM_TRIGGER]: (): TelegramTriggerNodeModel['data'] => ({
        telegram_bot_api_key_secret_id: null,
        webhook_trigger: null,
        fields: [],
        test_payload: {},
    }),
    [NodeType.SCHEDULE_TRIGGER]: (): ScheduleTriggerNodeData => {
        const rawTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        return {
            isActive: false,
            runMode: 'once',
            startDateTime: '',
            intervalEvery: null,
            intervalUnit: null,
            weekdays: [],
            endType: 'never',
            endDateTime: null,
            maxRuns: null,
            currentRuns: 0,
            timezone: rawTz === 'Europe/Kiev' ? 'Europe/Kyiv' : rawTz,
        };
    },
    [NodeType.END]: () => ({
        output_map: { context: 'variables' },
    }),
    [NodeType.KNOWLEDGE_RETRIEVER]: () => ({
        source_collection: null,
        rag_type: null,
        query: '',
        search_method: null,
        search_configs: null,
    }),
    [NodeType.KEY_VALUE]: (): KeyValueNodeData => ({
        key_value_table: null,
        mode: DEFAULT_KEY_VALUE_MODE,
        entries: [],
    }),
};
