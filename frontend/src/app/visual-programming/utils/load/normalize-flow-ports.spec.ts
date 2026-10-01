import { NodeType } from '@shared/models';

import { generatePortsForDecisionTableNode } from '../../core/helpers/helpers';
import { ConditionGroup } from '../../core/models/decision-table.model';
import { FlowModel } from '../../core/models/flow.model';
import { NodeModel } from '../../core/models/node.model';
import { normalizeFlowPorts } from './normalize-flow-ports';

function conditionGroup(groupName: string, valid: boolean | undefined): ConditionGroup {
    return {
        group_name: groupName,
        group_type: 'simple',
        expression: null,
        conditions: [],
        manipulation: null,
        next_node: null,
        valid,
    };
}

function node(id: string, type: NodeType, data: unknown, ports: NodeModel['ports']): NodeModel {
    return {
        id,
        backendId: null,
        type,
        node_name: id,
        data,
        position: { x: 0, y: 0 },
        ports,
        color: '',
        icon: '',
        size: { width: 100, height: 100 },
        input_map: {},
        output_variable_path: null,
    } as NodeModel;
}

function tableNode(id: string, groups: ConditionGroup[], ports: NodeModel['ports']): NodeModel {
    return node(id, NodeType.TABLE, { name: id, table: { condition_groups: groups } }, ports);
}

describe('normalizeFlowPorts', () => {
    // A flow covering every branch: ports missing, decision-table ports out of sync, and a decision
    // table whose groups leave `valid` unset (the generator treats those as valid).
    const groups = [conditionGroup('Yes', true), conditionGroup('Maybe', undefined), conditionGroup('No', false)];
    const flow: FlowModel = {
        nodes: [
            node('start', NodeType.START, { initialState: {} }, null),
            node('python', NodeType.PYTHON, {}, null),
            tableNode('table-null-ports', groups, null),
            tableNode('table-stale-ports', groups, generatePortsForDecisionTableNode('table-stale-ports', [])),
        ],
        connections: [],
    };

    it('is idempotent: a second pass deep-equals the first', () => {
        const once = normalizeFlowPorts(flow);
        expect(normalizeFlowPorts(once)).toEqual(once);
    });

    it('returns an already-normalised flow unchanged (same reference)', () => {
        const once = normalizeFlowPorts(flow);
        expect(normalizeFlowPorts(once)).toBe(once);
    });

    it('gives a decision table one output per group that is not explicitly invalid', () => {
        const table = normalizeFlowPorts(flow).nodes.find((n) => n.id === 'table-stale-ports')!;
        expect(table.ports!.map((port) => port.role)).toEqual([
            'table-in',
            'decision-out-Yes',
            'decision-out-Maybe',
            'decision-default',
            'decision-error',
        ]);
    });
});
