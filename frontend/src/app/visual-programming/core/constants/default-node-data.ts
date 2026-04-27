import { NODE_COLORS } from '../enums/node-config';
import { NodeType } from '../enums/node-type';

export const DEFAULT_NODE_DATA: Partial<Record<NodeType, () => unknown>> = {
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
    [NodeType.END]: () => ({
        output_map: { context: 'variables' },
    }),
    [NodeType.CODE_AGENT]: () => ({
        agent_mode: 'build',
        session_id: 'variables.chat_id',
        system_prompt: '',
        stream_handler_code: `# ── Code Agent Stream Handler ──────────────────────────────────
# Define any of these functions to hook into the agent lifecycle.
# Each receives a 'context' dict containing all input_map fields
# plus 'session_id' and 'node_name'.
# Return a dict from any handler to persist state across calls
# (e.g. store a message ID in on_stream_start, read it in on_complete).

# def on_stream_start(context):
#     """Called once before the prompt is sent to OpenCode."""
#     pass

# def on_chunk(text, context):
#     """Called each time the agent's reasoning or tool output updates.
#     'text' contains the accumulated thinking/tool-call text so far."""
#     pass

# def on_complete(full_reply, context):
#     """Called when the agent finishes (or is stopped).
#     'full_reply' contains the agent's final response text."""
#     pass
`,
        libraries: [],
        polling_interval_ms: 1000,
        silence_indicator_s: 3,
        indicator_repeat_s: 5,
        chunk_timeout_s: 30,
        inactivity_timeout_s: 120,
        max_wait_s: 300,
    }),
};
