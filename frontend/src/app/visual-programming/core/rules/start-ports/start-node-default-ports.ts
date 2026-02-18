import { BasePort } from '../../models/port.model';

export const DEFAULT_START_NODE_PORTS: BasePort[] = [
    {
        port_type: 'output',
        role: 'start-start',
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
        ],
        position: 'right',
        color: '#d3d3d3',
    },
];
