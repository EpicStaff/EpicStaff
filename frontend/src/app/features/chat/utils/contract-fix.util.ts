import { GraphDto } from '../../flows/models/graph.model';
import { ChatContractMissing } from '../models/chat.model';

// What the chat service sends to a flow's start node on each run (`run_variables` in
// src/chat/application/orchestrators/conversation.py) and reads from its end node (`parse_end_node_result`), with the
// starting value the fix declares for each.
const CHAT_START_VARIABLES: Readonly<Record<string, unknown>> = {
    chat_history: [],
    user_message: '',
    action: null,
    chat_extra_data: {},
    chat_user_id: null,
    reply: '',
    actions: [],
    request_human: false,
};
const CHAT_END_OUTPUTS: Readonly<Record<string, string>> = {
    reply: 'variables.reply',
    actions: 'variables.actions',
    request_human: 'variables.request_human',
};

/** The names the fix adds where missing, for the panel to list. */
export const CHAT_START_VARIABLE_NAMES = Object.keys(CHAT_START_VARIABLES);
export const CHAT_END_OUTPUT_NAMES = Object.keys(CHAT_END_OUTPUTS);

/** A bulk save (`POST /graphs/{id}/save/`) of only the start and end nodes: the other nodes and edges stay as they are. */
export type ContractFixPayload = {
    save_version: number;
    start_node_list: Record<string, unknown>[];
    end_node_list: Record<string, unknown>[];
};

/** True when the flow lacks anything the chat contract needs. */
export function hasContractGaps(missing: ChatContractMissing): boolean {
    return (
        missing.missing_start_node ||
        missing.missing_end_node ||
        missing.start_variables.length > 0 ||
        missing.end_outputs.length > 0
    );
}

/** True when both nodes exist and every gap is a name the fix adds; anything else is fixed in the flow editor. */
export function isAutoFixable(missing: ChatContractMissing): boolean {
    return (
        !missing.missing_start_node &&
        !missing.missing_end_node &&
        missing.start_variables.every((name) => Object.hasOwn(CHAT_START_VARIABLES, name)) &&
        missing.end_outputs.every((name) => Object.hasOwn(CHAT_END_OUTPUTS, name))
    );
}

/**
 * Adds every chat variable and output the flow lacks to its start and end nodes, checked against the graph as
 * fetched. Nothing that is there is changed or removed: an existing Domain variable or output keeps its value, other
 * Domain keys (`persistent_variables`) stay. Null when there is nothing to add (or no node to add it to).
 */
export function contractFixPayload(graph: GraphDto): ContractFixPayload | null {
    const start = graph.start_node_list[0];
    const end = graph.end_node_list[0];
    const startList: Record<string, unknown>[] = [];
    const endList: Record<string, unknown>[] = [];

    if (start) {
        const domain = start.variables ?? {};
        // A flat Domain (keys but no `variables` object) is read whole by the backend, so the chat names go beside its
        // keys; an empty one gets the editor's nested shape.
        const nested = nestedVariables(domain) ?? (Object.keys(domain).length ? null : {});
        const added = withMissing(nested ?? domain, CHAT_START_VARIABLES);
        if (added) {
            startList.push({
                id: start.id,
                graph: graph.id,
                variables: nested ? { ...domain, variables: added } : added,
                metadata: start.metadata,
            });
        }
    }

    const outputMap = end ? withMissing(end.output_map, CHAT_END_OUTPUTS) : null;
    if (end && outputMap) {
        endList.push({ id: end.id, graph: graph.id, output_map: outputMap, metadata: end.metadata });
    }

    if (!startList.length && !endList.length) return null;
    return { save_version: graph.save_version, start_node_list: startList, end_node_list: endList };
}

// `current` with each key of `additions` it lacks; null when it lacks none.
function withMissing(
    current: Record<string, unknown>,
    additions: Readonly<Record<string, unknown>>
): Record<string, unknown> | null {
    const missing = Object.entries(additions).filter(([key]) => !Object.hasOwn(current, key));
    return missing.length ? { ...current, ...Object.fromEntries(missing) } : null;
}

// The start node's `variables` is the Domain, normally `{ variables: {...}, persistent_variables: {...} }`; null when
// it has no `variables` object (a flat Domain).
function nestedVariables(domain: Record<string, unknown>): Record<string, unknown> | null {
    const variables = domain['variables'];
    return typeof variables === 'object' && variables !== null && !Array.isArray(variables)
        ? (variables as Record<string, unknown>)
        : null;
}
