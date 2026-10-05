import { ConditionGroup } from '../../../../core/models/decision-table.model';
import { CdtRouteTargetSources, resolveRouteTargetId, routePortIdsWithTarget } from './cdt-decision-tree.builder';

function row(overrides: Partial<ConditionGroup>): ConditionGroup {
    return {
        group_name: 'Condition 1',
        group_type: 'complex',
        expression: null,
        conditions: [],
        manipulation: null,
        next_node: null,
        ...overrides,
    };
}

function sources(overrides: Partial<CdtRouteTargetSources> = {}): CdtRouteTargetSources {
    return { nodeId: 'table', canvasRows: [], connections: [], ...overrides };
}

describe('resolveRouteTargetId', () => {
    it('reads the canvas row first, then the grid row', () => {
        const gridRow = row({ route_code: 'approve', next_node: 'grid-target' });

        expect(
            resolveRouteTargetId(
                gridRow,
                sources({ canvasRows: [row({ route_code: 'approve', next_node: 'canvas-target' })] })
            )
        ).toBe('canvas-target');
        expect(resolveRouteTargetId(gridRow, sources())).toBe('grid-target');
    });

    it('falls back to a connection on the route code port', () => {
        const connections = [
            { sourceNodeId: 'table', sourcePortId: 'table_decision-route-needs-review', targetNodeId: 'review' },
        ];

        expect(resolveRouteTargetId(row({ route_code: 'Needs Review' }), sources({ connections }))).toBe('review');
    });

    it('finds the connection of a saved route code with trailing whitespace on its own port', () => {
        const connections = [{ sourceNodeId: 'table', sourcePortId: 'table_decision-route-a-', targetNodeId: 'next' }];

        expect(resolveRouteTargetId(row({ route_code: 'A ' }), sources({ connections }))).toBe('next');
        expect(resolveRouteTargetId(row({ route_code: 'A' }), sources({ connections }))).toBeNull();
    });

    it('does not borrow the canvas target of a different port that trims to the same code', () => {
        const canvasRows = [row({ route_code: 'A ', next_node: 'next' })];

        expect(resolveRouteTargetId(row({ route_code: 'A' }), sources({ canvasRows }))).toBeNull();
    });

    it('is null without a route code or a target', () => {
        expect(resolveRouteTargetId(row({ route_code: '  ', next_node: 'x' }), sources())).toBeNull();
        expect(resolveRouteTargetId(row({ route_code: 'approve' }), sources())).toBeNull();
    });
});

describe('routePortIdsWithTarget', () => {
    it('collects the port ids that lead to a node, once each', () => {
        const rows = [
            row({ route_code: 'approve', next_node: 'a' }),
            row({ route_code: 'approve' }),
            row({ route_code: 'reject' }),
            row({ route_code: '' }),
        ];

        expect([...routePortIdsWithTarget(rows, sources())]).toEqual(['table_decision-route-approve']);
    });
});
