import { NODE_COLORS, NodeType } from '@shared/models';

import { BasePort } from '../../models/port.model';

export const DEFAULT_TOOL_NODE_PORTS: BasePort[] = [
    {
        port_type: 'output',
        role: 'tool-out-top',
        multiple: true,
        label: 'Out Top',
        allowedConnections: ['agent-out-tools'],
        position: 'top',
        color: NODE_COLORS[NodeType.TOOL],
    },
    {
        port_type: 'output',
        role: 'tool-out-right',
        multiple: true,
        label: 'Out Right',
        allowedConnections: ['agent-out-tools'],
        position: 'right',
        color: NODE_COLORS[NodeType.TOOL],
    },
    {
        port_type: 'output',
        role: 'tool-out-bottom',
        multiple: true,
        label: 'Out Bottom',
        allowedConnections: ['agent-out-tools'],
        position: 'bottom',
        color: NODE_COLORS[NodeType.TOOL],
    },
    {
        port_type: 'output',
        role: 'tool-out-left',
        multiple: true,
        label: 'Out Left',
        allowedConnections: ['agent-out-tools'],
        position: 'left',
        color: NODE_COLORS[NodeType.TOOL],
    },
];
