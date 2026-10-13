import { BasePort } from '../../models/port.model';

// Simple Agent node (NodeType.AGENT) — single In/Out ports, mirrors the
// Task/Python node port layout.
export const DEFAULT_AGENT_NODE_PORTS: BasePort[] = [
    {
        port_type: 'input',
        role: 'agent-in',
        multiple: true,
        label: 'In',
        allowedConnections: [
            'project-out',
            'python-out',
            'start-start',
            'table-out',
            'file-extractor-out',
            'subgraph-out',
            'audio-to-text-out',
            'webhook-trigger-out',
            'telegram-trigger-out',
            'schedule-trigger-out',
            'task-out',
            'decision-default',
            'decision-error',
            'agent-out',
            'knowledge-retriever-out',
            'key-value-out',
        ],
        position: 'left',
        color: '#685fff',
    },
    {
        port_type: 'output',
        role: 'agent-out',
        multiple: false,
        label: 'Out',
        allowedConnections: [
            'project-in',
            'python-in',
            'table-in',
            'file-extractor-in',
            'end-in',
            'subgraph-in',
            'audio-to-text-in',
            'task-in',
            'agent-in',
            'knowledge-retriever-in',
            'key-value-in',
        ],
        position: 'right',
        color: '#685fff',
    },
];
