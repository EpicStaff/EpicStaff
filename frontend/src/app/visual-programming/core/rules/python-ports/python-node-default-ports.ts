import { BasePort } from '../../models/port.model';

export const DEFAULT_PYTHON_NODE_PORTS: BasePort[] = [
    {
        port_type: 'input',
        role: 'python-in',
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
        ],
        position: 'left',
        color: '#ffcf3f',
    },

    {
        port_type: 'output',
        role: 'python-out',
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
            'webhook-trigger-in',
            'telegram-trigger-in',
        ],
        position: 'right',
        color: '#ffcf3f',
    },
];
