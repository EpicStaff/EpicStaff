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
}
