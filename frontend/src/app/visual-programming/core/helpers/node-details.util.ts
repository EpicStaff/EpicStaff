import { AuthorshipDetailsSource } from '@shared/components';
import { NodeType } from '@shared/models';

import { GraphDto } from '../../../features/flows/models/graph.model';

/** A `GraphDto` node list whose rows carry the four authorship fields the details dialog shows. */
export type AuthoredNodeListKey = {
    [TKey in keyof GraphDto]-?: NonNullable<GraphDto[TKey]> extends ReadonlyArray<infer TRow>
        ? TRow extends AuthorshipDetailsSource & { id: number }
            ? TKey
            : never
        : never;
}[keyof GraphDto];

/**
 * The single opt-in list of node types whose authorship (owner / last editor) the editor shows, with the `GraphDto`
 * node list it is read from (the key its load mapper and bulk save use too). To switch another type on, add it here.
 *
 * Where it shows depends on how the type opens: a type with a side panel shows it behind the panel's "Node details"
 * button; Start and Note have no side panel (no `PANEL_COMPONENT_MAP` entry, so the shell never renders for them)
 * and open their own window instead, which shows it in a footer.
 */
export const NODE_DETAILS_LIST_KEY = {
    [NodeType.PYTHON]: 'python_node_list',
    [NodeType.END]: 'end_node_list',
    [NodeType.AGENT]: 'agent_node_list',
    [NodeType.TASK]: 'task_node_list',
    [NodeType.KNOWLEDGE_RETRIEVER]: 'knowledge_node_list',
    [NodeType.FILE_EXTRACTOR]: 'file_extractor_node_list',
    [NodeType.KEY_VALUE]: 'key_value_node_list',
    [NodeType.AUDIO_TO_TEXT]: 'audio_transcription_node_list',
    [NodeType.TABLE]: 'decision_table_node_list',
    [NodeType.CLASSIFICATION_TABLE]: 'classification_decision_table_node_list',
    [NodeType.WEBHOOK_TRIGGER]: 'webhook_trigger_node_list',
    [NodeType.TELEGRAM_TRIGGER]: 'telegram_trigger_node_list',
    [NodeType.SCHEDULE_TRIGGER]: 'schedule_trigger_node_list',
    [NodeType.SUBGRAPH]: 'subgraph_node_list',
    [NodeType.START]: 'start_node_list',
    [NodeType.NOTE]: 'graph_note_list',
} as const satisfies Partial<Record<NodeType, AuthoredNodeListKey>>;

/** Every node type whose authorship the editor shows, wherever it shows it. */
export const NODE_TYPES_WITH_DETAILS: ReadonlySet<NodeType> = new Set(
    Object.keys(NODE_DETAILS_LIST_KEY) as (keyof typeof NODE_DETAILS_LIST_KEY)[]
);

/** Whether the editor shows the authorship of a node of this type (see {@link NODE_DETAILS_LIST_KEY} for where). */
export function hasNodeDetails(type: NodeType): boolean {
    return NODE_TYPES_WITH_DETAILS.has(type);
}
