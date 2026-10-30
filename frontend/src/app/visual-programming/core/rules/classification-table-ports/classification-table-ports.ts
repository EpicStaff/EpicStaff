import { NODE_COLORS, NodeType } from '@shared/models';

import { BasePort } from '../../models/port.model';
import { DEFAULT_TABLE_NODE_PORTS } from '../table-ports/table-ports';

/**
 * The classification decision table connects exactly like the decision table, so it reuses those
 * roles and rules and only takes its own colour. It stays out of PORTS_DICTIONARY: the roles are
 * the decision table's, already registered there.
 */
export const DEFAULT_CLASSIFICATION_TABLE_NODE_PORTS: BasePort[] = DEFAULT_TABLE_NODE_PORTS.map((port) => ({
    ...port,
    color: NODE_COLORS[NodeType.CLASSIFICATION_TABLE],
}));
