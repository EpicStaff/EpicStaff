import { NodeType } from '@shared/models';

import { getPortsForType } from '../core/helpers/helpers';

export function getOutputPortRole(nodeType: NodeType): string {
    const port = getPortsForType(nodeType).find((p) => p.port_type === 'output');
    return port?.role ?? 'output';
}

export function getInputPortRole(nodeType: NodeType): string {
    const port = getPortsForType(nodeType).find((p) => p.port_type === 'input');
    return port?.role ?? 'input';
}
