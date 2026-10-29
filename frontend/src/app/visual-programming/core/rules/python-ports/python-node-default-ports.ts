import { NODE_COLORS, NodeType } from '@shared/models';

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
            'start-start',
            'table-out',
            'file-extractor-out',
            'subgraph-out',
            'audio-to-text-out',
            'webhook-trigger-out',
            'telegram-trigger-out',
            'schedule-trigger-out',
            'task-out',
            'decision-default',
            'decision-error',
            'agent-out',
            'knowledge-retriever-out',
            'key-value-out',
        ],
        position: 'left',
        color: NODE_COLORS[NodeType.PYTHON],
    },

    {
        port_type: 'output',
        role: 'python-out',
        multiple: false,
        label: 'Out',
        allowedConnections: [
            'project-in',
            'python-in',
            'table-in',
            'file-extractor-in',
            'end-in',
            'subgraph-in',
            'audio-to-text-in',
            'task-in',
            'agent-in',
            'knowledge-retriever-in',
            'key-value-in',
        ],
        position: 'right',
        color: NODE_COLORS[NodeType.PYTHON],
    },
];
// MERGE_COMMENT: merged line 42. check and remove comment
