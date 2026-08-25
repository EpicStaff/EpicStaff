const NODE_TYPE_INDEX: Record<string, number> = {
    start: 1,
    end: 2,
    project: 3,
    task: 4,
    tool: 5,
    llm: 6,
    python: 7,
    edge: 8,
    table: 9,
    note: 10,
    'file-extractor': 11,
    'webhook-trigger': 12,
    'telegram-trigger': 13,
    subgraph: 14,
    'audio-to-text-node': 15,
    'schedule-trigger': 16,
    'code-agent': 17,
    agent: 18,
    'classification-decision-table': 19,
};

/**
 * Returns a deterministic UUID-shaped string for a DB-persisted node.
 * All users loading the same graph get the same ID for the same node,
 * which makes cross-session WS messages (node_updated, nodes_deleted, etc.) work correctly.
 *
 * Format: 00000000-0000-4000-{4-hex-type-index}-{12-hex-backendId}
 */
export function stableNodeId(nodeType: string, backendId: number): string {
    const t = (NODE_TYPE_INDEX[nodeType] ?? 0).toString(16).padStart(4, '0');
    const n = backendId.toString(16).padStart(12, '0');
    return `00000000-0000-4000-${t}-${n}`;
}
