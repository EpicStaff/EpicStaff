import { BasePort } from '../../models/port.model';

export const DEFAULT_FILE_EXTRACTOR_NODE_PORTS: BasePort[] = [
    {
        port_type: 'input',
        role: 'file-extractor-in',
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
            'audio-to-text-out',
            'webhook-trigger-out',
        ],
        position: 'left',
        color: '#2196F3',
    },

    {
        port_type: 'output',
        role: 'file-extractor-out',
        multiple: false,
        label: 'Out',
        allowedConnections: [
            'project-in',
            'python-in',
            'edge-in',
            'table-in',
            'llm-out-left',
            'file-extractor-in',
            'webhook-trigger-in',
            'end-in',
            'audio-to-text-in',
        ],
        position: 'right',
        color: '#2196F3',
    },
];
