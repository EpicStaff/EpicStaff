import { BasePort } from '../../models/port.model';

// Simple Task node (NodeType.TASK) — single In/Out ports, mirrors the
// Python node's port layout. This replaced the old crew-task multi-port
// layout (Prev. Task / Agent / Tools / Next task / Output log file etc.),
// which is no longer used by any live node type.
export const DEFAULT_TASK_NODE_PORTS: BasePort[] = [
    {
        port_type: 'input',
        role: 'task-in',
        multiple: true,
        label: 'In',
        allowedConnections: [
            'project-out',
            'python-out',
            'edge-out',
            'start-start',
            'table-out',
            'llm-out-right',
            'file-extractor-out',
            'subgraph-out',
            'audio-to-text-out',
            'webhook-trigger-out',
            'telegram-trigger-out',
            'schedule-trigger-out',
            'code-agent-out',
            'task-out',
            'decision-default',
            'decision-error',
        ],
        position: 'left',
        color: '#2aba6b',
    },
    {
        port_type: 'output',
        role: 'task-out',
        multiple: false,
        label: 'Out',
        allowedConnections: [
            'project-in',
            'python-in',
            'edge-in',
            'table-in',
            'llm-out-left',
            'file-extractor-in',
            'end-in',
            'subgraph-in',
            'audio-to-text-in',
            'code-agent-in',
            'task-in',
        ],
        position: 'right',
        color: '#2aba6b',
    },
];
