import { NodeType } from '../enums/node-type';
import { DecisionTableNodeModel, NodeModel } from '../models/node.model';

const HEADER_HEIGHT = 62;
const ROW_HEIGHT = 46;
const BASE_ROWS = 2;
const MIN_TABLE_HEIGHT = 200;

export function getDecisionTableVisualHeight(conditionGroups: { valid?: boolean }[]): number {
    const validGroupsCount = conditionGroups.filter((g) => g.valid !== false).length;
    const totalRows = Math.max(validGroupsCount + BASE_ROWS, BASE_ROWS);
    return Math.max(HEADER_HEIGHT + ROW_HEIGHT * totalRows, MIN_TABLE_HEIGHT);
}

export function getDefaultNodeSize(type: NodeType, data?: unknown): { width: number; height: number } {
    switch (type) {
        case NodeType.NOTE:
            return { width: 200, height: 150 };

        case NodeType.TABLE: {
            const tableData = (data as DecisionTableNodeModel['data'] | undefined)?.table;
            return {
                width: 330,
                height: getDecisionTableVisualHeight(tableData?.condition_groups ?? []),
            };
        }

        case NodeType.EDGE:
            return { width: 300, height: 180 };

        case NodeType.START:
            return { width: 125, height: 60 };

        default:
            return { width: 330, height: 60 };
    }
}

export function normalizeTableNodeSize(node: NodeModel): NodeModel {
    if (node.type !== NodeType.TABLE) return node;

    const tableData = (node as DecisionTableNodeModel).data.table;
    return {
        ...node,
        size: {
            ...node.size,
            width: node.size?.width ?? 330,
            height: getDecisionTableVisualHeight(tableData?.condition_groups ?? []),
        },
    };
}
