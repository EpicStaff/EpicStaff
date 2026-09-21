import { NodeType } from '../enums/node-type';
import { ClassificationDecisionTableNodeModel, DecisionTableNodeModel, NodeModel } from '../models/node.model';

// DT row height matches the default node height, for the same reason as CDT below: each
// row lines up with a same-sized node placed opposite it, producing a straight connection line.
export const DT_HEADER_HEIGHT = 60;
export const DT_ROW_HEIGHT = 60;
const BASE_ROWS = 2; // Default + Error, always rendered
// The condition-groups section always renders at least 1 row (its own rows, or the
// "No condition groups" placeholder), plus Default and Error.
export const DT_MIN_HEIGHT = DT_HEADER_HEIGHT + DT_ROW_HEIGHT * (1 + BASE_ROWS);

export function getDecisionTableVisualHeight(conditionGroups: { valid?: boolean }[]): number {
    const validGroupsCount = conditionGroups.filter((g) => g.valid !== false).length;
    const totalRows = Math.max(validGroupsCount, 1) + BASE_ROWS;
    return Math.max(DT_HEADER_HEIGHT + DT_ROW_HEIGHT * totalRows, DT_MIN_HEIGHT);
}

// CDT row height matches the default node height (getDefaultNodeSize's default branch,
// see below) so that each row is exactly as tall as a normal node — meaning row N's output
// port lines up horizontally with a same-sized target node placed opposite it, producing a
// straight connection line.
export const CDT_HEADER_HEIGHT = 60;
export const CDT_ROW_HEIGHT = 60;
// A CDT always renders at least 3 rows: the route-code section (either its route rows, or a
// single "No condition groups" placeholder row when there are none) plus the always-present
// Default and Error rows. This mirrors classification-decision-table-node.component.html.
const CDT_MIN_VISIBLE_ROWS = 3;

// The `.decision-table` container (classification-decision-table-node.component.scss) is drawn
// with an inset box-shadow (2px, hardcoded there) rather than a real border, so it is purely
// cosmetic: it paints inside the container's existing box without consuming any layout space or
// shifting the content box. It must NOT enter any geometry formula below (height, row pitch,
// port offsets).
export const CDT_MIN_HEIGHT = CDT_HEADER_HEIGHT + CDT_ROW_HEIGHT * CDT_MIN_VISIBLE_ROWS;

// The CDT's input port does NOT sit at the header's vertical center — it renders in its own
// `.input-port-wrapper` (classification-decision-table-node.component.scss: `top: 16px`,
// `width/height: 24px`), positioned above the header. So the true centre-y offset from the
// node's top edge is `top + height / 2`.
const CDT_INPUT_PORT_WRAPPER_TOP = 16;
const CDT_INPUT_PORT_WRAPPER_SIZE = 24;
export const CDT_INPUT_PORT_CENTER_Y_OFFSET = CDT_INPUT_PORT_WRAPPER_TOP + CDT_INPUT_PORT_WRAPPER_SIZE / 2;

// The plain DT's `.input-port-wrapper` (decision-table-node.component.scss) uses the exact
// same `top: 16px` / 24x24 geometry as the CDT's, so it renders near the top rather than at
// the header's vertical center too — same derivation as CDT_INPUT_PORT_CENTER_Y_OFFSET above.
const DT_INPUT_PORT_WRAPPER_TOP = 16;
const DT_INPUT_PORT_WRAPPER_SIZE = 24;
export const DT_INPUT_PORT_CENTER_Y_OFFSET = DT_INPUT_PORT_WRAPPER_TOP + DT_INPUT_PORT_WRAPPER_SIZE / 2;

/**
 * Computes the CDT node height from its condition groups, using the exact same
 * row-visibility rule as ClassificationDecisionTableNodeComponent.conditionGroups
 * (valid !== false && dock_visible && route_code) so the number of rows this
 * function counts always matches the number of rows actually rendered.
 */
export function getClassificationTableVisualHeight(
    conditionGroups: { valid?: boolean; dock_visible?: boolean; route_code?: string | null }[]
): number {
    const routeRowCount = conditionGroups.filter((g) => g.valid !== false && !!g.dock_visible && !!g.route_code).length;
    // The route-code section always renders at least one row (route rows, or the
    // "No condition groups" placeholder), plus the Default and Error rows.
    const totalRows = Math.max(routeRowCount, 1) + 2;
    return Math.max(CDT_HEADER_HEIGHT + CDT_ROW_HEIGHT * totalRows, CDT_MIN_HEIGHT);
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

        case NodeType.CLASSIFICATION_TABLE: {
            const tableData = (data as ClassificationDecisionTableNodeModel['data'] | undefined)?.table;
            return {
                width: 330,
                height: getClassificationTableVisualHeight(tableData?.condition_groups ?? []),
            };
        }

        case NodeType.EDGE:
            return { width: 300, height: 180 };

        case NodeType.START:
            return { width: 125, height: 60 };

        case NodeType.SCHEDULE_TRIGGER:
            return { width: 330, height: 60 };

        default:
            return { width: 330, height: 60 };
    }
}

export function normalizeTableNodeSize(node: NodeModel): NodeModel {
    if (node.type === NodeType.TABLE) {
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

    if (node.type === NodeType.CLASSIFICATION_TABLE) {
        const tableData = (node as ClassificationDecisionTableNodeModel).data.table;
        return {
            ...node,
            size: {
                ...node.size,
                width: node.size?.width ?? 330,
                height: getClassificationTableVisualHeight(tableData?.condition_groups ?? []),
            },
        };
    }

    return node;
}
