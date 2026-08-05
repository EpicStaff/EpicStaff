import { BasePort } from '../../models/port.model';

export const DEFAULT_SCHEDULE_TRIGGER_NODE_PORTS: BasePort[] = [
    {
        port_type: 'output',
        role: 'schedule-trigger-out',
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
            'knowledge-retriever-in',
        ],
        position: 'right',
        color: '#FF5C00',
    },
];
