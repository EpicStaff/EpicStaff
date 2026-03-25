import { BasePort } from '../../models/port.model';

export const DEFAULT_PROJECT_NODE_PORTS: BasePort[] = [
    {
        port_type: 'input',
        role: 'project-in',
        multiple: true,
        label: 'In',
        allowedConnections: [
            'project-out',
            'python-out',
            'edge-out',
            'start-start',
            'table-out',
            'file-extractor-out',
            'llm-out-right',
            'subgraph-out',
            'audio-to-text-out',
            'webhook-trigger-out',
            'telegram-trigger-out',
            'code-agent-out',
        ],
        position: 'left',
        color: '#5672cd',
    },
    {
        port_type: 'output',
        role: 'project-out',
        multiple: false,
        label: 'Out',
        allowedConnections: [
            'project-in',
            'python-in',
            'edge-in',
            'llm-out-left',
            'table-in',
            'file-extractor-in',
            'end-in',
            'subgraph-in',
            'audio-to-text-in',
            'code-agent-in',
        ],
        position: 'right',
        color: '#5672cd',
    },
];
// MERGE_COMMENT: merged line 41. check and remove comment
