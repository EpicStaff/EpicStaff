import { inject, Injectable } from '@angular/core';
import { v4 as uuidv4 } from 'uuid';

import { ScheduleTriggerNodeData } from '../../pages/flows-page/components/flow-visual-programming/models/schedule-trigger.model';
import { DEFAULT_NODE_DATA } from '../core/constants/default-node-data';
import { NODE_COLORS, NODE_ICONS } from '../core/enums/node-config';
import { NodeType } from '../core/enums/node-type';
import { generateNodeDisplayName } from '../core/helpers/generate-node-display-name.util';
import { generatePortsForNode } from '../core/helpers/helpers';
import { findNearestFreePosition, getCollisionBounds, snapPointToGrid } from '../core/helpers/node-placement.utils';
import { getDefaultNodeSize } from '../core/helpers/node-size.util';
import { NodeModel } from '../core/models/node.model';
import { ViewPort } from '../core/models/port.model';
import { FlowService } from './flow.service';
import { FlowSettingsService } from './flow-settings.service';

@Injectable({ providedIn: 'root' })
export class NodeFactoryService {
    private readonly flowService = inject(FlowService);
    private readonly flowSettings = inject(FlowSettingsService);

    createNode(type: NodeType, overrides?: Partial<NodeModel>): NodeModel {
        const id = uuidv4();
        const nodeData = (overrides?.data ?? DEFAULT_NODE_DATA[type]?.() ?? {}) as NodeModel['data'];

        if (type === NodeType.SCHEDULE_TRIGGER && nodeData) {
            (nodeData as ScheduleTriggerNodeData).timezone = this.flowSettings.timezone();
        }
        const color = NODE_COLORS[type] || '#ddd';
        const icon = NODE_ICONS[type] || 'ti ti-help';
        const size = getDefaultNodeSize(type, nodeData);
        const ports: ViewPort[] = type === NodeType.NOTE ? [] : generatePortsForNode(id, type, nodeData);
        const nodeNumber =
            type === NodeType.START || type === NodeType.END ? undefined : this.flowService.getNextNodeNumber();
        const nodeName = generateNodeDisplayName(type, nodeData, nodeNumber);
        const snappedPosition = snapPointToGrid(overrides?.position ?? { x: 0, y: 0 });

        return {
            id,
            backendId: null,
            ports,
            type: type as NodeModel['type'],
            node_name: nodeName,
            nodeNumber,
            data: nodeData,
            color,
            icon,
            input_map: {},
            output_variable_path: null,
            size,
            ...overrides,
            position: findNearestFreePosition(
                snappedPosition,
                getCollisionBounds({ type: type as NodeModel['type'], size, data: nodeData }),
                this.flowService.nodes()
            ),
        } as NodeModel;
    }
}
