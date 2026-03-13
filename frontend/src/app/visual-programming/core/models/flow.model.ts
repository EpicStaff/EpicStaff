import { ConnectionModel } from './connection.model';

import { NodeModel } from './node.model';

export interface FlowModel {
  nodes: NodeModel[];
  connections: ConnectionModel[];
}
