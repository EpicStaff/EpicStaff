import { inject, Injectable } from '@angular/core';
import { NODE_COLORS, NODE_ICONS, NodeType } from '@shared/models';
import { generateUuid } from '@shared/utils';

import { DEFAULT_NODE_DATA } from '../core/constants/default-node-data';
import { generateNodeDisplayName } from '../core/helpers/generate-node-display-name.util';
import { generatePortsForNode } from '../core/helpers/helpers';
import { isNumberedNodeType } from '../core/helpers/node-number.util';
import { findNearestFreePosition, getCollisionBounds, snapPointToGrid } from '../core/helpers/node-placement.utils';
import { getDefaultNodeSize } from '../core/helpers/node-size.util';
import { defaultScheduleStartDateTime, generateScheduleName } from '../core/helpers/schedule-trigger-defaults.util';
import { NodeModel } from '../core/models/node.model';
import { ViewPort } from '../core/models/port.model';
import { ScheduleTriggerNodeData } from '../core/models/schedule-trigger.model';
import { FlowService } from './flow.service';
import { FlowSettingsService } from './flow-settings.service';

@Injectable({ providedIn: 'root' })
export class NodeFactoryService {
    private readonly flowService = inject(FlowService);
    private readonly flowSettings = inject(FlowSettingsService);

    createNode(type: NodeType, overrides?: Partial<NodeModel>): NodeModel {
        const id = generateUuid();
        const nodeData = overrides?.data ?? this.createDefaultData(type);

        if (type === NodeType.SCHEDULE_TRIGGER && nodeData) {
            (nodeData as ScheduleTriggerNodeData).timezone = this.flowSettings.timezone();
        }
        const color = NODE_COLORS[type] || '#ddd';
        const icon = NODE_ICONS[type] || 'ti ti-help';
        const size = getDefaultNodeSize(type, nodeData);
        const ports: ViewPort[] = type === NodeType.NOTE ? [] : generatePortsForNode(id, type, nodeData);
        const nodeNumber = isNumberedNodeType(type) ? this.flowService.getNextNodeNumber() : undefined;
        const nodeName =
            type === NodeType.SCHEDULE_TRIGGER && !overrides?.data
                ? generateScheduleName(nodeData as ScheduleTriggerNodeData)
                : generateNodeDisplayName(type);
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

    /**
     * A new schedule already proposes its first run, the one its panel would offer, so the canvas shows
     * the schedule's name ("Once on … at …") before the panel is ever opened. It stays inactive.
     */
    private createDefaultData(type: NodeType): NodeModel['data'] {
        const data = DEFAULT_NODE_DATA[type]?.() ?? {};
        if (type === NodeType.SCHEDULE_TRIGGER) {
            return { ...(data as ScheduleTriggerNodeData), startDateTime: defaultScheduleStartDateTime() };
        }
        return data as NodeModel['data'];
    }
}
