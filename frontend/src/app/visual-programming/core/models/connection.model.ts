import { IPoint } from '@foblex/2d';

import { Edge } from '../../../pages/flows-page/components/flow-visual-programming/models/edge.model';
import { CustomPortId } from './port.model';

export interface ConnectionModel {
    id: string;
    category: 'default' | 'virtual';
    sourceNodeId: string;
    targetNodeId: string;
    sourcePortId: CustomPortId;
    targetPortId: CustomPortId;
    startColor?: string;
    endColor?: string;
    behavior: 'floating' | 'fixed';
    type: 'straight' | 'segment' | 'bezier';
    /** Backend edge record — null for connections not yet persisted. */
    data: Edge | null;
    waypoints?: IPoint[];
    userAdjustedWaypoints?: boolean;
}
