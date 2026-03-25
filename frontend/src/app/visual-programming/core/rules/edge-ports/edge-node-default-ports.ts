import { BasePort } from '../../models/port.model';

export const DEFAULT_EDGE_NODE_PORTS: BasePort[] = [
    {
        port_type: 'input',
        role: 'edge-in',
        multiple: true,
        label: 'In',
        allowedConnections: [
            'project-out',
            'edge-out',
            'python-out',
            'table-out',
            'start-start',
            'llm-out-right',
            'file-extractor-out',
            'subgraph-out',
            'audio-to-text-out',
            'webhook-trigger-out',
            'telegram-trigger-out',
            'code-agent-out',
        ],
        position: 'left',
        color: '#8e5cd9',
    },

    {
        port_type: 'output',
        role: 'edge-out',
        multiple: true,
        label: 'Out',
        allowedConnections: [
            'project-in',
            'edge-in',
            'python-in',
            'llm-out-left',
            'file-extractor-in',
            'table-in',
            'end-in',
            'subgraph-in',
            'audio-to-text-in',
            'code-agent-in',
        ],
        position: 'right',
        color: '#8e5cd9',
    },
];
