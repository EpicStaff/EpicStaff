import { BasePort } from '../../models/port.model';

export const DEFAULT_END_NODE_PORTS: BasePort[] = [
    {
        port_type: 'input',
        role: 'end-in',
        multiple: true,
        label: 'In',
        allowedConnections: [
            'project-out',
            'python-out',
            'file-extractor-out',
            'edge-out',
            'table-out',
            'llm-out-right',
            'subgraph-out',
            'webhook-trigger-out',
        ],
        position: 'left',
        color: '#d3d3d3',
    },
];
