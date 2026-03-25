import { BasePort } from '../../models/port.model';

export const DEFAULT_WEBHOOK_TRIGGER_NODE_PORTS: BasePort[] = [
    {
        port_type: 'output',
        role: 'webhook-trigger-out',
        multiple: false,
        label: 'Out',
        allowedConnections: [
            'project-in',
            'python-in',
            'edge-in',
            'table-in',
            'llm-out-left',
            'file-extractor-in',
            'subgraph-in',
            'audio-to-text-in',
            'end-in',
            'code-agent-in',
        ],
        position: 'right',
        color: '#21f367ff',
    },
];
