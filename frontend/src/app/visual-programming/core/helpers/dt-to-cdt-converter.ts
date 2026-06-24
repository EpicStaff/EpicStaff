import { v4 as uuidv4 } from 'uuid';

import { NODE_COLORS, NODE_ICONS } from '../enums/node-config';
import { NodeType } from '../enums/node-type';
import { ClassificationDecisionTableData } from '../models/classification-decision-table.model';
import { ConditionGroup } from '../models/decision-table.model';
import { ClassificationDecisionTableNodeModel, DecisionTableNodeModel } from '../models/node.model';
import { generatePortsForClassificationDecisionTableNode } from './helpers';

/**
 * Pure conversion function: maps a DecisionTableNodeModel to a new
 * ClassificationDecisionTableNodeModel.
 *
 * - A fresh UUID is assigned so the diff/save layer creates a new backend record.
 * - backendId is null so the backend treats it as a new node.
 * - nodeNumber is preserved to maintain visual ordering.
 * - condition_groups, default_next_node, next_error_node are carried verbatim.
 * - CDT-only fields (prompts, pre/post_computation, default_llm_config,
 *   route_variable_name) are initialised to safe empty defaults.
 * - icon/color are set to the canonical CDT appearance (NODE_ICONS/NODE_COLORS), not carried over from the DT.
 * - Ports are regenerated for the new node id.
 * - Each condition group is auto-assigned a unique route_code (preserved if
 *   already set) so per-row CDT route ports are created correctly.
 * - portIdMap maps each DT per-rule output port id to the corresponding CDT
 *   route port id, allowing the caller to remap outgoing edges precisely.
 */
export function convertDecisionTableToCdt(dtNode: DecisionTableNodeModel): {
    node: ClassificationDecisionTableNodeModel;
    portIdMap: Record<string, string>;
} {
    const newId = uuidv4();
    const dtTable = dtNode.data.table;

    const slug = (s: string) => (s ?? '').toLowerCase().replace(/\s+/g, '-');

    const usedRouteCodes = new Set<string>();
    const usedGroupNames = new Set<string>();

    const conditionGroups: ConditionGroup[] = (dtTable.condition_groups ?? []).map((g, i) => {
        // group_name is NOT NULL on the CDT backend table; an empty/missing DT condition name
        // would violate the constraint (BE 500). Default it to a unique "Condition N",
        // deduped the same way route_code is below.
        const nameBase = g.group_name?.trim() ? g.group_name.trim() : `Condition ${i + 1}`;
        let groupName = nameBase;
        if (usedGroupNames.has(groupName)) {
            groupName = `${nameBase} ${i + 1}`;
        }
        usedGroupNames.add(groupName);

        const base = g.route_code?.trim()
            ? g.route_code.trim()
            : `Route code for ${g.group_name?.trim() || `condition ${i + 1}`}`;

        let routeCode = base;
        if (usedRouteCodes.has(routeCode)) {
            routeCode = `${base} ${i + 1}`;
        }
        usedRouteCodes.add(routeCode);

        return {
            ...g,
            group_name: groupName,
            // DT marks empty-name rows as valid:false; the CDT canvas node filters
            // groups where valid !== false, and the load mapper never sets valid
            // (→ undefined → passes the filter).  Force valid:true here so the
            // group is visible immediately after conversion, on par with reload.
            valid: true,
            route_code: routeCode,
            conditions: (g.conditions ?? []).map((c) => ({ ...c })),
            dock_visible: g.dock_visible ?? true,
            field_expressions: g.field_expressions ?? {},
            field_manipulations: g.field_manipulations ?? {},
            section: g.section ?? null,
        };
    });

    const tableData: ClassificationDecisionTableData = {
        pre_computation_code: '',
        pre_computation: {
            code: '',
            input_map: {},
            libraries: [],
        },
        post_computation: {
            code: '',
            input_map: {},
            libraries: [],
        },
        condition_groups: conditionGroups,
        route_variable_name: 'route_code',
        default_next_node: dtTable.default_next_node ?? null,
        next_error_node: dtTable.next_error_node ?? null,
        default_llm_config: null,
        prompts: {},
    };

    const ports = generatePortsForClassificationDecisionTableNode(newId, conditionGroups);

    const portIdMap: Record<string, string> = {};
    // Ports are generated for ALL groups (including originally-empty-name ones),
    // so the edge map must cover all groups too — skipping valid===false left
    // edges dangling (the old port id was still real on the DT canvas).
    (dtTable.condition_groups ?? []).forEach((g, i) => {
        const oldPortId = `${dtNode.id}_decision-out-${slug(g.group_name)}`;
        const routeCode = conditionGroups[i].route_code!;
        const newPortId = `${newId}_decision-route-${slug(routeCode)}`;
        portIdMap[oldPortId] = newPortId;
    });

    const node: ClassificationDecisionTableNodeModel = {
        id: newId,
        backendId: null,
        type: NodeType.CLASSIFICATION_TABLE,
        node_name: dtNode.node_name,
        position: { ...dtNode.position },
        size: { ...dtNode.size },
        color: NODE_COLORS[NodeType.CLASSIFICATION_TABLE],
        icon: NODE_ICONS[NodeType.CLASSIFICATION_TABLE],
        input_map: { ...dtNode.input_map },
        output_variable_path: dtNode.output_variable_path,
        nodeNumber: dtNode.nodeNumber,
        ports,
        data: {
            name: dtNode.node_name,
            table: tableData,
        },
    };

    return { node, portIdMap };
}
