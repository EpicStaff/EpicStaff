import { NodeType } from '../enums/node-type';
import { ConnectionModel } from './connection.model';
import { ViewPort } from './port.model';

export interface ConnectionData {
  inputs: ConnectionModel[];
  outputs: ConnectionModel[];
  internal: ConnectionModel[];
}

export interface GroupData {
  name: string;
  connectionData: ConnectionData | null;
}

export interface GroupNodeModel {
  id: string;
  category: 'web';
  type: NodeType.GROUP;
  data: GroupData;
  collapsed: boolean;
  position: { x: number; y: number };
  collapsedPosition: { x: number; y: number };
  ports: ViewPort[] | null;
  parentId: string | null;
  size: { width: number; height: number };
  color: string;
  backgroundColor: string;
  icon?: string;
  childPositions?: Map<string, { x: number; y: number }>;
  node_name: string;
}
