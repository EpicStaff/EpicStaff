import { BasePort } from '../../models/port.model';

export const DEFAULT_SUBGRAPH_NODE_PORTS: BasePort[] = [
    {
        port_type: 'input',
        role: 'subgraph-in',
        multiple: true,
        label: 'In',
        allowedConnections: [
            'project-out',
            'python-out',
            'file-extractor-out',
            'edge-out',
            'table-out',
            'llm-out-right',
            'start-start',
            'subgraph-out',
            'table-out',
        ],
        position: 'left',
        color: '#00bfa5',
    },
    {
        port_type: 'output',
        role: 'subgraph-out',
        multiple: false,
        label: 'Out',
        allowedConnections: [
            'project-in',
            'python-in',
            'edge-in',
            'table-out',
            'llm-out-left',
            'file-extractor-in',
            'end-in',
            'subgraph-in',
            'table-in',
        ],
        position: 'right',
        color: '#00bfa5',
    },
];

