import { AgentNodeData } from '../../../pages/flows-page/components/flow-visual-programming/models/agent-node.model';
import { ScheduleTriggerNodeData } from '../../../pages/flows-page/components/flow-visual-programming/models/schedule-trigger.model';
import { TaskNodeData } from '../../../pages/flows-page/components/flow-visual-programming/models/task-node.model';
import { NODE_COLORS } from '../enums/node-config';
import { NodeType } from '../enums/node-type';

export const DEFAULT_NODE_DATA: Partial<Record<NodeType, () => unknown>> = {
    [NodeType.AGENT]: (): AgentNodeData => ({
        name: 'Agent Node',
        agent_definition: null,
        surface_list: [],
        inline_surface: null,
        tasks: [],
    }),
    [NodeType.EDGE]: () => ({
        source: null,
        then: null,
        python_code: {
            libraries: [],
            code: 'def main(arg1: str, arg2: str) -> dict:\n    return {\n        "result": arg1 + arg2,\n    }\n',
            entrypoint: 'main',
        },
    }),
    [NodeType.PYTHON]: () => ({
        name: 'Python Code Node',
        libraries: [],
        code: 'def main(arg1: str, arg2: str) -> dict:\n    return {\n        "result": arg1 + arg2,\n    }\n',
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
    [NodeType.NOTE]: () => ({
        content: 'Add your note here...',
        backgroundColor: NODE_COLORS[NodeType.NOTE],
    }),
    [NodeType.WEBHOOK_TRIGGER]: () => ({
        webhook_trigger: 0,
        python_code: {
            name: 'Webhook trigger Node',
            libraries: [],
            code: 'def main(trigger_payload: dict, **kwargs: dict) -> dict:\n    """\n    Main handler for processing webhook-triggered events.\n\n    Parameters\n    ----------\n    trigger_payload : dict\n        The data received from a third-party service via a webhook.\n    **kwargs : dict\n        Additional domain variables passed to the function.\n\n    Returns\n    -------\n    dict\n        A dictionary containing the updated values for domain variables.\n        The returned structure must include all changes that should be\n        applied to the domain.\n    """\n    return {\n        "new_data": trigger_payload,\n    }\n',
            entrypoint: 'main',
        },
    }),
    [NodeType.TELEGRAM_TRIGGER]: () => ({
        telegram_bot_api_key: '',
        fields: [],
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
};
