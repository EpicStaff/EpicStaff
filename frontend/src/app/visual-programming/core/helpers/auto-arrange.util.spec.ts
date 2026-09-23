import { IPoint } from '@foblex/2d';

import { NodeType } from '../enums/node-type';
import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';
import { CustomPortId, ViewPort } from '../models/port.model';
import { computeAutoArrangePositions, computeAutoArrangePositionsWithDiagnostics } from './auto-arrange.util';
import { getRowPortCenterYFromTop } from './cdt-row-snap.util';
import { CDT_INPUT_PORT_CENTER_Y_OFFSET, DT_INPUT_PORT_CENTER_Y_OFFSET } from './node-size.util';

function port(nodeId: string, role: string, position: ViewPort['position'] = 'right'): ViewPort {
    return {
        id: `${nodeId}_${role}` as CustomPortId,
        port_type: 'output',
        role,
        multiple: true,
        label: role,
        allowedConnections: [],
        position,
    };
}

function makeNode(
    id: string,
    type: NodeType,
    opts: { width?: number; height?: number; data?: unknown; ports?: ViewPort[] } = {}
): NodeModel {
    return {
        id,
        type,
        position: { x: 0, y: 0 },
        size: { width: opts.width ?? 330, height: opts.height ?? 100 },
        ports: opts.ports ?? [],
        data: opts.data ?? null,
    } as unknown as NodeModel;
}

function conn(
    id: string,
    sourceId: string,
    sourceRole: string,
    targetId: string,
    targetRole = 'input'
): ConnectionModel {
    return {
        id,
        category: 'default',
        sourceNodeId: sourceId,
        targetNodeId: targetId,
        sourcePortId: `${sourceId}_${sourceRole}` as CustomPortId,
        targetPortId: `${targetId}_${targetRole}` as CustomPortId,
        behavior: 'floating',
        type: 'segment',
        data: null,
    };
}

function dtGroup(name: string, order: number) {
    return {
        group_name: name,
        group_type: 'simple' as const,
        expression: null,
        conditions: [],
        manipulation: null,
        next_node: null,
        valid: true,
        order,
        route_code: name,
        dock_visible: true,
    };
}

// Row-based table fixture (plain DT or CDT) with one output port per row, named `row-N` so the
// port role's slug matches the row's group_name/route_code slug exactly (see slugifyPortName).
function tableNode(id: string, type: NodeType.TABLE | NodeType.CLASSIFICATION_TABLE, rowCount: number): NodeModel {
    const height = 60 + 60 * rowCount;
    const rowNames = Array.from({ length: rowCount }, (_, i) => `row-${i}`);
    const rolePrefix = type === NodeType.TABLE ? 'decision-out-' : 'decision-route-';
    const ports = rowNames.map((name) => port(id, `${rolePrefix}${name}`));
    return makeNode(id, type, {
        height,
        ports,
        data: { name: id, table: { condition_groups: rowNames.map((name, i) => dtGroup(name, i)) } },
    });
}

function tableRowRole(type: NodeType.TABLE | NodeType.CLASSIFICATION_TABLE, rowIndex: number): string {
    return (type === NodeType.TABLE ? 'decision-out-' : 'decision-route-') + `row-${rowIndex}`;
}

function rect(id: string, positions: Map<string, IPoint>, nodeMap: Map<string, NodeModel>) {
    const p = positions.get(id)!;
    const n = nodeMap.get(id)!;
    return { x1: p.x, y1: p.y, x2: p.x + n.size.width, y2: p.y + n.size.height };
}

function verticalRangesOverlap(a: { y1: number; y2: number }, b: { y1: number; y2: number }): boolean {
    return a.y1 < b.y2 && b.y1 < a.y2;
}

// Groups all placed nodes by their (snapped) x column and asserts no two rects in the same
// column overlap vertically — this is what lets the router draw a clean lane between siblings.
function assertNoOverlapWithinAnyColumn(
    nodeIds: string[],
    positions: Map<string, IPoint>,
    nodeMap: Map<string, NodeModel>
): void {
    const byColumn = new Map<number, string[]>();
    for (const id of nodeIds) {
        const x = positions.get(id)!.x;
        if (!byColumn.has(x)) byColumn.set(x, []);
        byColumn.get(x)!.push(id);
    }
    for (const ids of byColumn.values()) {
        for (let i = 0; i < ids.length; i++) {
            for (let j = i + 1; j < ids.length; j++) {
                const ra = rect(ids[i], positions, nodeMap);
                const rb = rect(ids[j], positions, nodeMap);
                expect(verticalRangesOverlap(ra, rb)).toBe(false);
            }
        }
    }
}

function unionRect(ids: string[], positions: Map<string, IPoint>, nodeMap: Map<string, NodeModel>) {
    const rects = ids.map((id) => rect(id, positions, nodeMap));
    return {
        x1: Math.min(...rects.map((r) => r.x1)),
        y1: Math.min(...rects.map((r) => r.y1)),
        x2: Math.max(...rects.map((r) => r.x2)),
        y2: Math.max(...rects.map((r) => r.y2)),
    };
}

describe('computeAutoArrangePositions', () => {
    it('places a linear chain strictly left-to-right at a constant y', () => {
        const nodes = [
            makeNode('start', NodeType.START),
            makeNode('a', NodeType.AGENT),
            makeNode('b', NodeType.AGENT),
            makeNode('c', NodeType.AGENT),
        ];
        const connections = [conn('c1', 'start', 'out', 'a'), conn('c2', 'a', 'out', 'b'), conn('c3', 'b', 'out', 'c')];

        const positions = computeAutoArrangePositions(nodes, connections);

        expect(positions.get('start')!.x).toBeLessThan(positions.get('a')!.x);
        expect(positions.get('a')!.x).toBeLessThan(positions.get('b')!.x);
        expect(positions.get('b')!.x).toBeLessThan(positions.get('c')!.x);
        const y = positions.get('start')!.y;
        expect(positions.get('a')!.y).toBe(y);
        expect(positions.get('b')!.y).toBe(y);
        expect(positions.get('c')!.y).toBe(y);
    });

    it('orders fan-out children top-to-bottom by port order, not by connection array order', () => {
        const nodes = [
            makeNode('p', NodeType.AGENT),
            makeNode('a', NodeType.AGENT),
            makeNode('b', NodeType.AGENT),
            makeNode('c', NodeType.AGENT),
        ];
        // Wired out of port order on purpose: a=condition-2, b=condition-0, c=condition-1.
        const connections = [
            conn('c1', 'p', 'decision-out-condition-2', 'a'),
            conn('c2', 'p', 'decision-out-condition-0', 'b'),
            conn('c3', 'p', 'decision-out-condition-1', 'c'),
        ];

        const positions = computeAutoArrangePositions(nodes, connections);

        expect(positions.get('b')!.y).toBeLessThan(positions.get('c')!.y);
        expect(positions.get('c')!.y).toBeLessThan(positions.get('a')!.y);
    });

    const rowBasedTableTypes: (NodeType.TABLE | NodeType.CLASSIFICATION_TABLE)[] = [
        NodeType.TABLE,
        NodeType.CLASSIFICATION_TABLE,
    ];
    it.each(rowBasedTableTypes)("pins each %s row's direct child to that row's centre", (tableType) => {
        // Child height must fit within one row (60px) or the alignment feasibility check
        // (auto-arrange.util.ts:151) bails out and falls back to generic subtree spacing.
        const childHeight = 60;
        const rowCount = 3;
        const table = tableNode('table', tableType, rowCount);
        const nodes = [
            makeNode('start', NodeType.START),
            table,
            makeNode('child0', NodeType.AGENT, { height: childHeight }),
            makeNode('child1', NodeType.AGENT, { height: childHeight }),
            makeNode('child2', NodeType.AGENT, { height: childHeight }),
        ];
        const connections = [
            conn('c0', 'start', 'out', 'table'),
            conn('c1', 'table', tableRowRole(tableType, 0), 'child0'),
            conn('c2', 'table', tableRowRole(tableType, 1), 'child1'),
            conn('c3', 'table', tableRowRole(tableType, 2), 'child2'),
        ];

        const positions = computeAutoArrangePositions(nodes, connections);
        const tableTop = positions.get('table')!.y;

        for (let i = 0; i < rowCount; i++) {
            const childId = `child${i}`;
            const childCentreY = positions.get(childId)!.y + childHeight / 2;
            expect(childCentreY).toBe(tableTop + getRowPortCenterYFromTop(0, i, tableType));
        }
    });

    it('keeps a tall table and ordinary siblings from overlapping in the same layer', () => {
        const table = tableNode('table', NodeType.TABLE, 3);
        const nodes = [
            makeNode('start', NodeType.START),
            table,
            makeNode('nodeX', NodeType.AGENT),
            makeNode('nodeY', NodeType.AGENT),
            makeNode('child0', NodeType.AGENT),
            makeNode('child1', NodeType.AGENT),
            makeNode('child2', NodeType.AGENT),
            makeNode('childX', NodeType.AGENT),
            makeNode('childY', NodeType.AGENT),
        ];
        const connections = [
            conn('c1', 'start', 'out1', 'table'),
            conn('c2', 'start', 'out2', 'nodeX'),
            conn('c3', 'start', 'out3', 'nodeY'),
            conn('c4', 'table', tableRowRole(NodeType.TABLE, 0), 'child0'),
            conn('c5', 'table', tableRowRole(NodeType.TABLE, 1), 'child1'),
            conn('c6', 'table', tableRowRole(NodeType.TABLE, 2), 'child2'),
            conn('c7', 'nodeX', 'out', 'childX'),
            conn('c8', 'nodeY', 'out', 'childY'),
        ];

        const positions = computeAutoArrangePositions(nodes, connections);
        const nodeMap = new Map(nodes.map((n) => [n.id, n]));

        assertNoOverlapWithinAnyColumn(
            nodes.map((n) => n.id),
            positions,
            nodeMap
        );
    });

    it('is a fixed point: re-running on its own output returns identical positions', () => {
        const table = tableNode('table', NodeType.TABLE, 3);
        const nodes = [
            makeNode('start', NodeType.START),
            table,
            makeNode('nodeX', NodeType.AGENT),
            makeNode('child0', NodeType.AGENT),
            makeNode('child1', NodeType.AGENT),
            makeNode('child2', NodeType.AGENT),
            makeNode('childX', NodeType.AGENT),
        ];
        const connections = [
            conn('c1', 'start', 'out1', 'table'),
            conn('c2', 'start', 'out2', 'nodeX'),
            conn('c4', 'table', tableRowRole(NodeType.TABLE, 0), 'child0'),
            conn('c5', 'table', tableRowRole(NodeType.TABLE, 1), 'child1'),
            conn('c6', 'table', tableRowRole(NodeType.TABLE, 2), 'child2'),
            conn('c7', 'nodeX', 'out', 'childX'),
        ];

        const first = computeAutoArrangePositions(nodes, connections);
        const rearranged = nodes.map((n) => ({ ...n, position: { ...first.get(n.id)! } }) as NodeModel);
        const second = computeAutoArrangePositions(rearranged, connections);

        for (const n of nodes) {
            expect(second.get(n.id)).toEqual(first.get(n.id));
        }
    });

    it('reports a reference bounding width for a fixed 4-node linear chain', () => {
        // BASELINE — later steps of the auto-arrange plan (HORIZONTAL_GAP, DT gap, right-align)
        // deliberately change this number. Re-derive it on purpose, don't just bump the constant.
        // Step 4a: HORIZONTAL_GAP 360 -> 180 removes 180px per gap, 3 gaps: 2230 - 540 = 1690.
        const EXPECTED_BASELINE_WIDTH_PX = 1690;

        const nodes = [
            makeNode('start', NodeType.START, { width: 150, height: 80 }),
            makeNode('a', NodeType.AGENT, { width: 330, height: 100 }),
            makeNode('b', NodeType.AGENT, { width: 330, height: 100 }),
            makeNode('c', NodeType.AGENT, { width: 330, height: 100 }),
        ];
        const connections = [conn('c1', 'start', 'out', 'a'), conn('c2', 'a', 'out', 'b'), conn('c3', 'b', 'out', 'c')];

        const positions = computeAutoArrangePositions(nodes, connections);
        const nodeMap = new Map(nodes.map((n) => [n.id, n]));
        const bbox = unionRect(
            nodes.map((n) => n.id),
            positions,
            nodeMap
        );

        expect(bbox.x2 - bbox.x1).toBe(EXPECTED_BASELINE_WIDTH_PX);
    });

    it('places a merge node with parents in different layers to the right of the deeper parent, recognising both', () => {
        // Step 3 (rank repair): BFS "first-seen layer wins" used to lock `merge` to layer(a)+1 via
        // `a`'s edge before `b`'s deeper edge was considered, colliding `merge` with `b` and
        // dropping `b` from `allParents`. DFS + relax-to-fixed-point now recognises both.
        const nodes = [
            makeNode('root', NodeType.START),
            makeNode('a', NodeType.AGENT),
            makeNode('bMid', NodeType.AGENT),
            makeNode('b', NodeType.AGENT),
            makeNode('merge', NodeType.AGENT),
        ];
        const connections = [
            conn('c1', 'root', 'out1', 'a'),
            conn('c2', 'root', 'out2', 'bMid'),
            conn('c3', 'bMid', 'out', 'b'),
            conn('c4', 'a', 'out', 'merge'),
            conn('c5', 'b', 'out', 'merge'),
        ];

        const positions = computeAutoArrangePositions(nodes, connections);

        // `merge` now sits strictly right of both parents instead of sharing `b`'s column.
        expect(positions.get('merge')!.x).toBeGreaterThan(positions.get('b')!.x);
        expect(positions.get('merge')!.x).toBeGreaterThan(positions.get('a')!.x);

        // Both `a` and `b` are recognised: `merge`'s centre sits strictly between theirs, which
        // is only possible if it was averaged from both rather than copied from `a` alone.
        const centre = (id: string) => positions.get(id)!.y + 50;
        expect(centre('merge')).toBeGreaterThan(Math.min(centre('a'), centre('b')));
        expect(centre('merge')).toBeLessThan(Math.max(centre('a'), centre('b')));
    });

    it('diamond: places the merge node one column right of the deepest-path parent, not the shallowest', () => {
        // Short path root->a->merge vs long path root->b1->b2->merge. `after` (b2's only other
        // child) is a clean, tightening-unaffected marker for "exactly one column past b2".
        const nodes = [
            makeNode('root', NodeType.START),
            makeNode('a', NodeType.AGENT),
            makeNode('b1', NodeType.AGENT),
            makeNode('b2', NodeType.AGENT),
            makeNode('merge', NodeType.AGENT),
            makeNode('after', NodeType.AGENT),
        ];
        const connections = [
            conn('c1', 'root', 'out1', 'a'),
            conn('c2', 'a', 'out', 'merge'),
            conn('c3', 'root', 'out2', 'b1'),
            conn('c4', 'b1', 'out', 'b2'),
            conn('c5', 'b2', 'out', 'merge'),
            conn('c6', 'b2', 'out2', 'after'),
        ];

        const positions = computeAutoArrangePositions(nodes, connections);

        expect(positions.get('merge')!.x).toBe(positions.get('after')!.x);
        expect(positions.get('merge')!.x).toBeGreaterThan(positions.get('b2')!.x);
        // Tightening pulled the shallow-path node into `b2`'s column, eliminating the
        // multi-layer `a -> merge` span that used to pass over the intervening column.
        expect(positions.get('a')!.x).toBe(positions.get('b2')!.x);
    });

    it('terminates and lays out sensibly when the graph has a genuine cycle', () => {
        const nodes = [
            makeNode('start', NodeType.START),
            makeNode('x', NodeType.AGENT),
            makeNode('y', NodeType.AGENT),
            makeNode('z', NodeType.AGENT),
        ];
        const connections = [
            conn('c1', 'start', 'out', 'x'),
            conn('c2', 'x', 'out', 'y'),
            conn('c3', 'y', 'back', 'x'),
            conn('c4', 'y', 'out', 'z'),
        ];

        const positions = computeAutoArrangePositions(nodes, connections);

        expect(positions.get('start')!.x).toBeLessThan(positions.get('x')!.x);
        expect(positions.get('x')!.x).toBeLessThan(positions.get('y')!.x);
        expect(positions.get('y')!.x).toBeLessThan(positions.get('z')!.x);
    });

    it('keeps two disconnected components in non-overlapping vertical regions', () => {
        const nodes = [
            makeNode('c1-start', NodeType.START),
            makeNode('c1-a', NodeType.AGENT),
            makeNode('c2-start', NodeType.START),
            makeNode('c2-a', NodeType.AGENT),
            makeNode('solo', NodeType.AGENT),
        ];
        const connections = [conn('e1', 'c1-start', 'out', 'c1-a'), conn('e2', 'c2-start', 'out', 'c2-a')];

        const positions = computeAutoArrangePositions(nodes, connections);
        const nodeMap = new Map(nodes.map((n) => [n.id, n]));

        const comp1 = unionRect(['c1-start', 'c1-a'], positions, nodeMap);
        const comp2 = unionRect(['c2-start', 'c2-a'], positions, nodeMap);
        const solo = rect('solo', positions, nodeMap);

        expect(verticalRangesOverlap(comp1, comp2)).toBe(false);
        expect(verticalRangesOverlap(comp1, solo)).toBe(false);
        expect(verticalRangesOverlap(comp2, solo)).toBe(false);
    });

    it('row-pins the feasible children of a table even when one sibling is too tall for its row pitch', () => {
        // Verified against the pre-1b (all-or-nothing) function: child0/child2 would NOT match
        // their row centres there either, because a single infeasible pair (child1 vs its
        // neighbour) used to `return null` for the whole table, not just drop child1.
        //
        // CHANGED by the nearest-free-band fix: child1 (dropped) already overlapped child2's row
        // pre-fix, just unasserted — child2 now relocates off it instead of drawing over it. See
        // the hand-off report for the pre-fix values.
        const table = tableNode('table', NodeType.TABLE, 3);
        const nodes = [
            makeNode('start', NodeType.START),
            table,
            makeNode('child0', NodeType.AGENT, { height: 60 }),
            makeNode('child1', NodeType.AGENT, { height: 200 }),
            makeNode('child2', NodeType.AGENT, { height: 60 }),
        ];
        const connections = [
            conn('c0', 'start', 'out', 'table'),
            conn('c1', 'table', tableRowRole(NodeType.TABLE, 0), 'child0'),
            conn('c2', 'table', tableRowRole(NodeType.TABLE, 1), 'child1'),
            conn('c3', 'table', tableRowRole(NodeType.TABLE, 2), 'child2'),
        ];
        const nodeMap = new Map(nodes.map((n) => [n.id, n]));

        const positions = computeAutoArrangePositions(nodes, connections);
        const tableTop = positions.get('table')!.y;

        expect(positions.get('child0')!.y + 30).toBe(tableTop + getRowPortCenterYFromTop(0, 0, NodeType.TABLE));
        expect(positions.get('child1')!.y + 100).not.toBe(tableTop + getRowPortCenterYFromTop(0, 1, NodeType.TABLE));
        assertNoOverlapWithinAnyColumn(['child0', 'child1', 'child2'], positions, nodeMap);
    });

    it('drops a table child from row-pinning once rank repair pushes it past table+1', () => {
        // `rowChild` (single parent, exactly table+1) stays pinned; `mergeChild` gains a second,
        // deeper parent (`mid2`) so rank repair pushes it two layers past `table` — the Step 1a
        // single-parent/table+1 gate is what keeps it off the row now that ranking moved it.
        const table = tableNode('table', NodeType.TABLE, 2);
        const nodes = [
            makeNode('start', NodeType.START),
            table,
            makeNode('rowChild', NodeType.AGENT, { height: 60 }),
            makeNode('mergeChild', NodeType.AGENT, { height: 60 }),
            makeNode('mid1', NodeType.AGENT),
            makeNode('mid2', NodeType.AGENT),
        ];
        const connections = [
            conn('c1', 'start', 'out', 'table'),
            conn('c2', 'table', tableRowRole(NodeType.TABLE, 0), 'rowChild'),
            conn('c3', 'table', tableRowRole(NodeType.TABLE, 1), 'mergeChild'),
            conn('c4', 'start', 'out2', 'mid1'),
            conn('c5', 'mid1', 'out', 'mid2'),
            conn('c6', 'mid2', 'out', 'mergeChild'),
        ];

        const positions = computeAutoArrangePositions(nodes, connections);
        const tableTop = positions.get('table')!.y;

        expect(positions.get('rowChild')!.y + 30).toBe(tableTop + getRowPortCenterYFromTop(0, 0, NodeType.TABLE));
        expect(positions.get('mergeChild')!.y + 30).not.toBe(tableTop + getRowPortCenterYFromTop(0, 1, NodeType.TABLE));
        expect(positions.get('mergeChild')!.x).toBeGreaterThan(positions.get('table')!.x);
    });

    it('does not report a diagnostic when a pinned node only touches its pinned predecessor', () => {
        // childC's pinned top lands flush with childBottom's pinned bottom (touching, no box
        // overlap). CHANGED by this fix: was `[{ nodeId: 'childBottom', layer: 2, overlapPx: 50 }]`,
        // now `[]` — see the hand-off report for why the old value was a false positive.
        const tableA = tableNode('tableA', NodeType.TABLE, 2);
        const tableB = tableNode('tableB', NodeType.TABLE, 1);
        const nodes = [
            makeNode('start', NodeType.START),
            tableA,
            tableB,
            makeNode('childTop', NodeType.AGENT, { height: 60 }),
            makeNode('childBottom', NodeType.AGENT, { height: 60 }),
            makeNode('childC', NodeType.AGENT, { height: 300 }),
        ];
        const connections = [
            conn('c1', 'start', 'out1', 'tableA'),
            conn('c2', 'start', 'out2', 'tableB'),
            conn('c3', 'tableA', tableRowRole(NodeType.TABLE, 0), 'childTop'),
            conn('c4', 'tableA', tableRowRole(NodeType.TABLE, 1), 'childBottom'),
            conn('c5', 'tableB', tableRowRole(NodeType.TABLE, 0), 'childC'),
        ];

        const { diagnostics } = computeAutoArrangePositionsWithDiagnostics(nodes, connections);

        expect(diagnostics).toEqual([]);
    });

    it('keeps a row-pinned child aligned with its parent port when it only touches its sibling', () => {
        // Regression fixture: three row-pinned (flush, no gap) parents, each with one child of
        // its own in the next layer — reproduces the reported stepped-wire defect. See the
        // hand-off report for the pre-fix failing values.
        const table = tableNode('table', NodeType.TABLE, 3);
        const nodes = [
            makeNode('start', NodeType.START),
            table,
            makeNode('row0', NodeType.AGENT, { height: 60 }),
            makeNode('row1', NodeType.AGENT, { height: 60 }),
            makeNode('row2', NodeType.AGENT, { height: 60 }),
            makeNode('child0', NodeType.AGENT, { height: 60 }),
            makeNode('child1', NodeType.AGENT, { height: 60 }),
            makeNode('child2', NodeType.AGENT, { height: 60 }),
        ];
        const connections = [
            conn('c0', 'start', 'out', 'table'),
            conn('c1', 'table', tableRowRole(NodeType.TABLE, 0), 'row0'),
            conn('c2', 'table', tableRowRole(NodeType.TABLE, 1), 'row1'),
            conn('c3', 'table', tableRowRole(NodeType.TABLE, 2), 'row2'),
            conn('c4', 'row0', 'out', 'child0'),
            conn('c5', 'row1', 'out', 'child1'),
            conn('c6', 'row2', 'out', 'child2'),
        ];

        const positions = computeAutoArrangePositions(nodes, connections);

        const portY = (id: string) => positions.get(id)!.y + 30;
        expect(portY('child0')).toBe(portY('row0'));
        expect(portY('child1')).toBe(portY('row1'));
        expect(portY('child2')).toBe(portY('row2'));
    });

    it('separates two siblings with SIBLING_GAP when they would genuinely overlap', () => {
        // 'merge' averages its two parents' y, bypassing the subtree-span reservation that
        // normally keeps siblings apart — the one construction here with a REAL box overlap
        // (unlike the previous test's merely-touching case).
        const nodes = [
            makeNode('start', NodeType.START),
            makeNode('a', NodeType.AGENT, { height: 100 }),
            makeNode('b', NodeType.AGENT, { height: 100 }),
            makeNode('merge', NodeType.AGENT, { height: 300 }),
            makeNode('other', NodeType.AGENT, { height: 60 }),
        ];
        const connections = [
            conn('c1', 'start', 'out1', 'a'),
            conn('c2', 'start', 'out2', 'b'),
            conn('c3', 'a', 'out', 'merge'),
            conn('c4', 'b', 'out2', 'merge'),
            conn('c5', 'b', 'out3', 'other'),
        ];

        const positions = computeAutoArrangePositions(nodes, connections);
        const mergeBottom = positions.get('merge')!.y + 300;
        const otherTop = positions.get('other')!.y;
        // Without a push, 'other' (b's only owned child) would centre on b unchanged.
        const naiveOtherTop = positions.get('b')!.y + 50 - 30;

        expect(otherTop).toBeGreaterThanOrEqual(mergeBottom);
        expect(otherTop).toBeGreaterThan(naiveOtherTop);
    });

    it('extends the Decision-Table extra horizontal gap to Classification-Decision-Table layers too', () => {
        const gapAfterTable = (tableType: NodeType.TABLE | NodeType.CLASSIFICATION_TABLE): number => {
            const table = tableNode('table', tableType, 1);
            const nodes = [makeNode('start', NodeType.START), table, makeNode('child', NodeType.AGENT)];
            const connections = [
                conn('c0', 'start', 'out', 'table'),
                conn('c1', 'table', tableRowRole(tableType, 0), 'child'),
            ];
            const positions = computeAutoArrangePositions(nodes, connections);
            return positions.get('child')!.x - (positions.get('table')!.x + table.size.width);
        };

        const dtGap = gapAfterTable(NodeType.TABLE);
        const cdtGap = gapAfterTable(NodeType.CLASSIFICATION_TABLE);

        expect(cdtGap).toBe(dtGap);
        expect(cdtGap).toBeGreaterThan(180); // base HORIZONTAL_GAP alone; extra gap must be added
    });

    it.each(rowBasedTableTypes)(
        "aligns a %s's input port with its parent's output port instead of centring the box",
        (tableType) => {
            const table = tableNode('table', tableType, 3);
            const nodes = [makeNode('start', NodeType.START), makeNode('mid', NodeType.AGENT, { height: 60 }), table];
            const connections = [conn('c0', 'start', 'out', 'mid'), conn('c1', 'mid', 'out', 'table')];

            const positions = computeAutoArrangePositions(nodes, connections);

            const midPortY = positions.get('mid')!.y + 30;
            // The renderer draws the table's input port at top + 28 (getPortPosition), so that —
            // not headerHeight/2 — is what has to land on the parent's port for a straight wire.
            const inputPortOffset =
                tableType === NodeType.TABLE ? DT_INPUT_PORT_CENTER_Y_OFFSET : CDT_INPUT_PORT_CENTER_Y_OFFSET;
            const tableInputPortY = positions.get('table')!.y + inputPortOffset;

            expect(tableInputPortY).toBe(midPortY);
        }
    );

    it.each(rowBasedTableTypes)(
        "keeps a %s's own row-pinned children exactly on their rows once the table itself is port-aligned",
        (tableType) => {
            const rowCount = 3;
            const table = tableNode('table', tableType, rowCount);
            const nodes = [
                makeNode('start', NodeType.START),
                makeNode('mid', NodeType.AGENT, { height: 60 }),
                table,
                makeNode('child0', NodeType.AGENT, { height: 60 }),
                makeNode('child1', NodeType.AGENT, { height: 60 }),
                makeNode('child2', NodeType.AGENT, { height: 60 }),
            ];
            const connections = [
                conn('c0', 'start', 'out', 'mid'),
                conn('cIn', 'mid', 'out', 'table'),
                conn('c1', 'table', tableRowRole(tableType, 0), 'child0'),
                conn('c2', 'table', tableRowRole(tableType, 1), 'child1'),
                conn('c3', 'table', tableRowRole(tableType, 2), 'child2'),
            ];

            const positions = computeAutoArrangePositions(nodes, connections);
            const tableTop = positions.get('table')!.y;

            for (let i = 0; i < rowCount; i++) {
                const childId = `child${i}`;
                const childCentreY = positions.get(childId)!.y + 30;
                expect(childCentreY).toBe(tableTop + getRowPortCenterYFromTop(0, i, tableType));
            }
        }
    );

    it('right-aligns nodes within a layer so different widths share the same right edge', () => {
        const nodes = [
            makeNode('start', NodeType.START),
            makeNode('narrow', NodeType.AGENT, { width: 200 }),
            makeNode('wide', NodeType.AGENT, { width: 400 }),
        ];
        const connections = [conn('c1', 'start', 'out1', 'narrow'), conn('c2', 'start', 'out2', 'wide')];

        const positions = computeAutoArrangePositions(nodes, connections);

        const narrowRight = positions.get('narrow')!.x + 200;
        const wideRight = positions.get('wide')!.x + 400;
        expect(narrowRight).toBe(wideRight);
        expect(positions.get('narrow')!.x).toBeGreaterThan(positions.get('wide')!.x);
    });

    it('leaves a port-aligned table where the sweep put it rather than over row-pinned siblings', () => {
        // Regression (flow 6): `cdt` is port-aligned to `p`, whose Y the de-overlap sweep moved, so
        // the final re-derivation dropped the 360px table onto two row-pinned 60px nodes sharing
        // its column. Pre-fix: cdt y=932 (bottom 1292) over py1 1132-1192 and py2 1192-1252.
        const table = tableNode('T', NodeType.CLASSIFICATION_TABLE, 2);
        const cdt = tableNode('cdt', NodeType.CLASSIFICATION_TABLE, 5);
        const nodes = [
            makeNode('s1', NodeType.START, { height: 60 }),
            makeNode('s2', NodeType.START, { height: 60 }),
            makeNode('p', NodeType.AGENT, { height: 60 }),
            makeNode('w', NodeType.AGENT, { height: 700 }),
            table,
            cdt,
            makeNode('py1', NodeType.PYTHON, { height: 60 }),
            makeNode('py2', NodeType.PYTHON, { height: 60 }),
        ];
        const connections = [
            conn('c1', 's1', 'o1', 'p'),
            conn('c2', 's1', 'o2', 'w'),
            conn('c3', 's2', 'o1', 'p'),
            conn('c4', 's2', 'o2', 'T'),
            conn('c5', 'p', 'o1', 'cdt'),
            conn('c6', 'T', tableRowRole(NodeType.CLASSIFICATION_TABLE, 0), 'py1'),
            conn('c7', 'T', tableRowRole(NodeType.CLASSIFICATION_TABLE, 1), 'py2'),
        ];

        const positions = computeAutoArrangePositions(nodes, connections);
        const nodeMap = new Map(nodes.map((n) => [n.id, n]));

        assertNoOverlapWithinAnyColumn(
            nodes.map((n) => n.id),
            positions,
            nodeMap
        );

        const tableTop = positions.get('T')!.y;
        expect(positions.get('py1')!.y + 30).toBe(
            tableTop + getRowPortCenterYFromTop(0, 0, NodeType.CLASSIFICATION_TABLE)
        );
        expect(positions.get('py2')!.y + 30).toBe(
            tableTop + getRowPortCenterYFromTop(0, 1, NodeType.CLASSIFICATION_TABLE)
        );

        // The table is the one that gives way: clear of the pinned pair, its input wire kinked.
        expect(positions.get('cdt')!.y + cdt.size.height).toBeLessThanOrEqual(positions.get('py1')!.y);
        expect(positions.get('cdt')!.y + CDT_INPUT_PORT_CENTER_Y_OFFSET).not.toBe(positions.get('p')!.y + 30);
    });

    it('leaves row-pinned children where the sweep put them rather than over a settled sibling', () => {
        // Regression (flow 6): the sweep moved `p`, so `cdt` was port-aligned down onto it and its
        // row pins were re-derived down with it, onto `big`. Pre-fix: py1 1212-1272 and py2
        // 1272-1332 both inside big 1220-1580, same column.
        const cdt = tableNode('cdt', NodeType.CLASSIFICATION_TABLE, 2);
        const nodes = [
            makeNode('s1', NodeType.START, { height: 60 }),
            makeNode('s2', NodeType.START, { height: 60 }),
            makeNode('W', NodeType.AGENT, { height: 700 }),
            makeNode('p', NodeType.AGENT, { height: 60 }),
            makeNode('u', NodeType.AGENT, { height: 60 }),
            cdt,
            makeNode('v', NodeType.AGENT, { height: 60 }),
            makeNode('py1', NodeType.PYTHON, { height: 60 }),
            makeNode('py2', NodeType.PYTHON, { height: 60 }),
            makeNode('big', NodeType.AGENT, { height: 360 }),
            makeNode('small', NodeType.AGENT, { height: 60 }),
        ];
        const connections = [
            conn('c1', 's1', 'o1', 'p'),
            conn('c2', 's1', 'o2', 'W'),
            conn('c3', 's2', 'o1', 'p'),
            conn('c4', 's2', 'o2', 'u'),
            conn('c5', 'p', 'o1', 'cdt'),
            conn('c6', 'u', 'o1', 'v'),
            conn('c7', 'cdt', tableRowRole(NodeType.CLASSIFICATION_TABLE, 0), 'py1'),
            conn('c8', 'cdt', tableRowRole(NodeType.CLASSIFICATION_TABLE, 1), 'py2'),
            conn('c9', 'v', 'o1', 'big'),
            conn('c10', 'v', 'o2', 'small'),
        ];

        const positions = computeAutoArrangePositions(nodes, connections);
        const nodeMap = new Map(nodes.map((n) => [n.id, n]));

        assertNoOverlapWithinAnyColumn(
            nodes.map((n) => n.id),
            positions,
            nodeMap
        );

        // The pins are the ones that give way: they stay above `big`, off their rows, while the
        // table keeps the input-port alignment that dragged them.
        expect(positions.get('py2')!.y + 60).toBeLessThanOrEqual(positions.get('big')!.y);
        const cdtTop = positions.get('cdt')!.y;
        expect(positions.get('py1')!.y + 30).not.toBe(
            cdtTop + getRowPortCenterYFromTop(0, 0, NodeType.CLASSIFICATION_TABLE)
        );
        expect(cdtTop + CDT_INPUT_PORT_CENTER_Y_OFFSET).toBe(positions.get('p')!.y + 30);
    });

    it('relocates a pinned node to the nearest free band when it lands inside an unrelated settled table', () => {
        // Regression (flow 6): cdt10 (dropped from cdt8's row pinning, too tall for the pitch)
        // lands flush against pn11 with zero slack. python13, row-pinned from a DIFFERENT table
        // into the same layer, lands inside cdt10's band — see the hand-off report for pre-fix values.
        const cdt8 = tableNode('cdt8', NodeType.CLASSIFICATION_TABLE, 4);
        const cdt10 = tableNode('cdt10', NodeType.CLASSIFICATION_TABLE, 5);
        const tableY = tableNode('tableY', NodeType.CLASSIFICATION_TABLE, 3);
        const nodes = [
            makeNode('start', NodeType.START),
            cdt8,
            makeNode('pn12', NodeType.PYTHON, { height: 60 }),
            makeNode('pn5', NodeType.PYTHON, { height: 60 }),
            makeNode('pn11', NodeType.PYTHON, { height: 60 }),
            cdt10,
            tableY,
            makeNode('python13', NodeType.PYTHON, { height: 60 }),
        ];
        const connections = [
            conn('c1', 'start', 'out1', 'cdt8'),
            conn('c2', 'cdt8', tableRowRole(NodeType.CLASSIFICATION_TABLE, 0), 'pn12'),
            conn('c3', 'cdt8', tableRowRole(NodeType.CLASSIFICATION_TABLE, 1), 'pn5'),
            conn('c4', 'cdt8', tableRowRole(NodeType.CLASSIFICATION_TABLE, 2), 'pn11'),
            conn('c5', 'cdt8', tableRowRole(NodeType.CLASSIFICATION_TABLE, 3), 'cdt10'),
            conn('c6', 'start', 'out2', 'tableY'),
            conn('c7', 'tableY', tableRowRole(NodeType.CLASSIFICATION_TABLE, 0), 'python13'),
        ];
        const nodeMap = new Map(nodes.map((n) => [n.id, n]));

        const positions = computeAutoArrangePositions(nodes, connections);

        assertNoOverlapWithinAnyColumn(
            nodes.map((n) => n.id),
            positions,
            nodeMap
        );
        const cdt10Bottom = positions.get('cdt10')!.y + cdt10.size.height;
        expect(positions.get('python13')!.y).toBe(cdt10Bottom + 50);
    });
});
