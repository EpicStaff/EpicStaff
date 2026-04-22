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
            'code-agent-out',
            'decision-default',
            'decision-error',
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
            'code-agent-in',
        ],
        position: 'right',
        color: '#ffcf3f',
    },
];
// MERGE_COMMENT: merged line 42. check and remove comment
