import { IPoint } from '@foblex/2d';
import { NodeType } from '@shared/models';

import { getRowPortCenterYFromTop } from '../helpers/cdt-row-snap.util';
import { CDT_INPUT_PORT_CENTER_Y_OFFSET, DT_INPUT_PORT_CENTER_Y_OFFSET } from '../helpers/node-size.util';
import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';
import { routeAll } from '../routing/route-all';
import { computeLayout } from './compute-layout';
import { measure, QualityReport, wiresFromRoutes } from './quality/metrics';
import {
    connect,
    flow6PortAlignedTable,
    flow6RelocatesPinned,
    flow6RowPinnedChildren,
    FlowFixture,
    makeNode,
    tableNode,
    tableRowRole,
    withPorts,
    withPositions,
} from './testing/fixtures';

/**
 * Auto-arrange intents on small hand-built flows. Tables are fed through their real `table-in`
 * port and have their rendered (visual) height, and every connection's ports exist on its nodes.
 */

type TableType = NodeType.TABLE | NodeType.CLASSIFICATION_TABLE;

const TABLE_TYPES: TableType[] = [NodeType.TABLE, NodeType.CLASSIFICATION_TABLE];

interface Arranged {
    nodes: NodeModel[]; // at their arranged positions
    positions: Map<string, IPoint>;
    report: QualityReport; // measured with routeAll's wires
    y: (id: string) => number;
    x: (id: string) => number;
    height: (id: string) => number;
}

function arrange(nodes: NodeModel[], connections: ConnectionModel[]): Arranged {
    const ported = withPorts(nodes, connections);
    const positions = computeLayout(ported, connections);
    const placed = withPositions(ported, positions);
    const report = measure(placed, wiresFromRoutes(placed, connections, routeAll(placed, connections), true));
    const nodeOf = (id: string): NodeModel => placed.find((node) => node.id === id)!;
    return {
        nodes: placed,
        positions,
        report,
        y: (id) => positions.get(id)!.y,
        x: (id) => positions.get(id)!.x,
        height: (id) => nodeOf(id).size.height,
    };
}

function arrangeFixture({ nodes, connections }: FlowFixture): Arranged {
    return arrange(nodes, connections);
}

const agent = (id: string, options: { width?: number; height?: number } = {}): NodeModel =>
    makeNode(id, NodeType.AGENT, options);
const python = (id: string, height = 60): NodeModel => makeNode(id, NodeType.PYTHON, { height });
const start = (id = 'start'): NodeModel => makeNode(id, NodeType.START);

function rowPortY(arranged: Arranged, tableId: string, row: number, type: TableType): number {
    return arranged.y(tableId) + getRowPortCenterYFromTop(0, row, type);
}

function expectNoOverlap(arranged: Arranged): void {
    expect(arranged.report.nodeOverlaps).toBe(0);
}

describe('computeLayout (auto-arrange intents)', () => {
    it('places a linear chain strictly left-to-right at a constant y', () => {
        const arranged = arrange(
            [start(), agent('a'), agent('b'), agent('c')],
            [connect('c1', 'start', 'out', 'a'), connect('c2', 'a', 'out', 'b'), connect('c3', 'b', 'out', 'c')]
        );

        expect(arranged.x('start')).toBeLessThan(arranged.x('a'));
        expect(arranged.x('a')).toBeLessThan(arranged.x('b'));
        expect(arranged.x('b')).toBeLessThan(arranged.x('c'));
        for (const id of ['a', 'b', 'c']) expect(arranged.y(id)).toBe(arranged.y('start'));
    });

    it('orders fan-out children top-to-bottom by row order, not by connection array order', () => {
        // Wired out of row order on purpose: a = row 2, b = row 0, c = row 1.
        const arranged = arrange(
            [start(), tableNode('p', NodeType.TABLE, 3), agent('a'), agent('b'), agent('c')],
            [
                connect('c0', 'start', 'out', 'p', 'table-in'),
                connect('c1', 'p', tableRowRole(NodeType.TABLE, 2), 'a'),
                connect('c2', 'p', tableRowRole(NodeType.TABLE, 0), 'b'),
                connect('c3', 'p', tableRowRole(NodeType.TABLE, 1), 'c'),
            ]
        );

        expect(arranged.y('b')).toBeLessThan(arranged.y('c'));
        expect(arranged.y('c')).toBeLessThan(arranged.y('a'));
    });

    it.each(TABLE_TYPES)("puts each %s row's direct child straight on that row", (tableType) => {
        const arranged = arrange(
            [start(), tableNode('table', tableType, 3), python('child0'), python('child1'), python('child2')],
            [
                connect('c0', 'start', 'out', 'table', 'table-in'),
                ...[0, 1, 2].map((row) => connect(`c${row + 1}`, 'table', tableRowRole(tableType, row), `child${row}`)),
            ]
        );

        for (let row = 0; row < 3; row++) {
            expect(arranged.y(`child${row}`) + 30).toBe(rowPortY(arranged, 'table', row, tableType));
        }
    });

    it('keeps a tall table and ordinary siblings from overlapping in the same layer', () => {
        const arranged = arrange(
            [
                start(),
                tableNode('table', NodeType.TABLE, 3),
                ...['nodeX', 'nodeY', 'child0', 'child1', 'child2', 'childX', 'childY'].map((id) => agent(id)),
            ],
            [
                connect('c1', 'start', 'out1', 'table', 'table-in'),
                connect('c2', 'start', 'out2', 'nodeX'),
                connect('c3', 'start', 'out3', 'nodeY'),
                ...[0, 1, 2].map((row) =>
                    connect(`c${row + 4}`, 'table', tableRowRole(NodeType.TABLE, row), `child${row}`)
                ),
                connect('c7', 'nodeX', 'out', 'childX'),
                connect('c8', 'nodeY', 'out', 'childY'),
            ]
        );

        expectNoOverlap(arranged);
    });

    it('is a fixed point: re-running on its own output returns identical positions', () => {
        const nodes = withPorts(
            [
                start(),
                tableNode('table', NodeType.TABLE, 3),
                ...['nodeX', 'child0', 'child1', 'child2', 'childX'].map((id) => agent(id)),
            ],
            []
        );
        const connections = [
            connect('c1', 'start', 'out1', 'table', 'table-in'),
            connect('c2', 'start', 'out2', 'nodeX'),
            ...[0, 1, 2].map((row) =>
                connect(`c${row + 4}`, 'table', tableRowRole(NodeType.TABLE, row), `child${row}`)
            ),
            connect('c7', 'nodeX', 'out', 'childX'),
        ];
        const ported = withPorts(nodes, connections);

        const first = computeLayout(ported, connections);
        const second = computeLayout(withPositions(ported, first), connections);

        expect(second).toEqual(first);
    });

    it('reports a reference bounding width for a fixed 4-node chain', () => {
        // 150 (start) + 3 × 330, each 100-px layer gap rounded up so the next left is on the 20-px grid.
        const EXPECTED_CHAIN_WIDTH_PX = 1470;
        const arranged = arrange(
            [
                makeNode('start', NodeType.START, { width: 150, height: 80 }),
                agent('a', { width: 330 }),
                agent('b', { width: 330 }),
                agent('c', { width: 330 }),
            ],
            [connect('c1', 'start', 'out', 'a'), connect('c2', 'a', 'out', 'b'), connect('c3', 'b', 'out', 'c')]
        );

        const right = Math.max(...arranged.nodes.map((node) => node.position.x + node.size.width));
        const left = Math.min(...arranged.nodes.map((node) => node.position.x));
        expect(right - left).toBe(EXPECTED_CHAIN_WIDTH_PX);
    });

    it('places a merge node with parents in different layers right of both, and between them', () => {
        const arranged = arrange(
            [makeNode('root', NodeType.START), ...['a', 'bMid', 'b', 'merge'].map((id) => agent(id))],
            [
                connect('c1', 'root', 'out1', 'a'),
                connect('c2', 'root', 'out2', 'bMid'),
                connect('c3', 'bMid', 'out', 'b'),
                connect('c4', 'a', 'out', 'merge'),
                connect('c5', 'b', 'out', 'merge'),
            ]
        );

        expect(arranged.x('merge')).toBeGreaterThan(arranged.x('b'));
        expect(arranged.x('merge')).toBeGreaterThan(arranged.x('a'));
        const centre = (id: string): number => arranged.y(id) + 50;
        expect(centre('merge')).toBeGreaterThan(Math.min(centre('a'), centre('b')));
        expect(centre('merge')).toBeLessThan(Math.max(centre('a'), centre('b')));
    });

    it('diamond: places the merge node one column right of the deepest-path parent', () => {
        const arranged = arrange(
            [makeNode('root', NodeType.START), ...['a', 'b1', 'b2', 'merge', 'after'].map((id) => agent(id))],
            [
                connect('c1', 'root', 'out1', 'a'),
                connect('c2', 'a', 'out', 'merge'),
                connect('c3', 'root', 'out2', 'b1'),
                connect('c4', 'b1', 'out', 'b2'),
                connect('c5', 'b2', 'out', 'merge'),
                connect('c6', 'b2', 'out2', 'after'),
            ]
        );

        expect(arranged.x('merge')).toBe(arranged.x('after'));
        expect(arranged.x('merge')).toBeGreaterThan(arranged.x('b2'));
        // Tightening: the shallow-path node moves next to the merge, so no wire spans a column.
        expect(arranged.x('a')).toBe(arranged.x('b2'));
    });

    it('terminates on a genuine cycle, lays it out left to right, with no overlap and no wire through a node', () => {
        const arranged = arrange(
            [start(), agent('x'), agent('y'), agent('z')],
            [
                connect('c1', 'start', 'out', 'x'),
                connect('c2', 'x', 'out', 'y'),
                connect('c3', 'y', 'back', 'x'),
                connect('c4', 'y', 'out', 'z'),
            ]
        );

        expect(arranged.x('start')).toBeLessThan(arranged.x('x'));
        expect(arranged.x('x')).toBeLessThan(arranged.x('y'));
        expect(arranged.x('y')).toBeLessThan(arranged.x('z'));
        expectNoOverlap(arranged);
        expect(arranged.report.wireThroughNode).toBe(0);
    });

    it('keeps two disconnected components and an isolated node in separate vertical bands', () => {
        const arranged = arrange(
            [start('c1-start'), agent('c1-a'), start('c2-start'), agent('c2-a'), agent('solo')],
            [connect('e1', 'c1-start', 'out', 'c1-a'), connect('e2', 'c2-start', 'out', 'c2-a')]
        );

        const band = (ids: string[]): [number, number] => [
            Math.min(...ids.map((id) => arranged.y(id))),
            Math.max(...ids.map((id) => arranged.y(id) + arranged.height(id))),
        ];
        const bands = [band(['c1-start', 'c1-a']), band(['c2-start', 'c2-a']), band(['solo'])].sort(
            (a, b) => a[0] - b[0]
        );
        for (let index = 1; index < bands.length; index++)
            expect(bands[index][0]).toBeGreaterThanOrEqual(bands[index - 1][1]);
    });

    it('keeps the feasible rows straight when one sibling is too tall for its row', () => {
        const arranged = arrange(
            [start(), tableNode('table', NodeType.TABLE, 3), python('child0'), python('child1', 200), python('child2')],
            [
                connect('c0', 'start', 'out', 'table', 'table-in'),
                ...[0, 1, 2].map((row) =>
                    connect(`c${row + 1}`, 'table', tableRowRole(NodeType.TABLE, row), `child${row}`)
                ),
            ]
        );

        expect(arranged.y('child0') + 30).toBe(rowPortY(arranged, 'table', 0, NodeType.TABLE));
        expect(arranged.y('child1') + 100).not.toBe(rowPortY(arranged, 'table', 1, NodeType.TABLE));
        expectNoOverlap(arranged);
    });

    it('does not force a child two layers past its table onto the row: no overlap, no crossing', () => {
        // mergeChild has a second, deeper parent (mid2), so it sits two layers past the table.
        const arranged = arrange(
            [
                start(),
                tableNode('table', NodeType.TABLE, 2),
                python('rowChild'),
                python('mergeChild'),
                agent('mid1'),
                agent('mid2'),
            ],
            [
                connect('c1', 'start', 'out', 'table', 'table-in'),
                connect('c2', 'table', tableRowRole(NodeType.TABLE, 0), 'rowChild'),
                connect('c3', 'table', tableRowRole(NodeType.TABLE, 1), 'mergeChild'),
                connect('c4', 'start', 'out2', 'mid1'),
                connect('c5', 'mid1', 'out', 'mid2'),
                connect('c6', 'mid2', 'out', 'mergeChild'),
            ]
        );

        expect(arranged.y('rowChild') + 30).toBe(rowPortY(arranged, 'table', 0, NodeType.TABLE));
        expect(arranged.x('mergeChild')).toBeGreaterThan(arranged.x('rowChild'));
        expectNoOverlap(arranged);
        expect(arranged.report.crossings).toBe(0);
    });

    it("keeps row children's own children in order, one straight, the rest 20 clear", () => {
        // Only siblings straight on consecutive rows of one table may touch, and these aren't row
        // children, so they keep the gap. The one whose parent row is on top stays straight.
        const arranged = arrange(
            [
                start(),
                tableNode('table', NodeType.TABLE, 3),
                ...['row0', 'row1', 'row2', 'child0', 'child1', 'child2'].map((id) => python(id)),
            ],
            [
                connect('c0', 'start', 'out', 'table', 'table-in'),
                ...[0, 1, 2].map((row) =>
                    connect(`c${row + 1}`, 'table', tableRowRole(NodeType.TABLE, row), `row${row}`)
                ),
                ...[0, 1, 2].map((row) => connect(`c${row + 4}`, `row${row}`, 'out', `child${row}`)),
            ]
        );

        for (let row = 0; row < 3; row++)
            expect(arranged.y(`row${row}`) + 30).toBe(rowPortY(arranged, 'table', row, NodeType.TABLE));
        expect(arranged.y('child0')).toBeLessThan(arranged.y('child1'));
        expect(arranged.y('child1')).toBeLessThan(arranged.y('child2'));
        expect([0, 1, 2].some((row) => arranged.y(`child${row}`) === arranged.y(`row${row}`))).toBe(true);
        expectNoOverlap(arranged);
        expect(arranged.report.crossings).toBe(0);
    });

    it('separates two siblings by the gap when they would genuinely overlap', () => {
        const arranged = arrange(
            [
                start(),
                agent('a', { height: 100 }),
                agent('b', { height: 100 }),
                agent('merge', { height: 300 }),
                agent('other', { height: 60 }),
            ],
            [
                connect('c1', 'start', 'out1', 'a'),
                connect('c2', 'start', 'out2', 'b'),
                connect('c3', 'a', 'out', 'merge'),
                connect('c4', 'b', 'out2', 'merge'),
                connect('c5', 'b', 'out3', 'other'),
            ]
        );

        const [upper, lower] = ['merge', 'other'].sort((first, second) => arranged.y(first) - arranged.y(second));
        expect(arranged.y(lower)).toBeGreaterThanOrEqual(arranged.y(upper) + arranged.height(upper) + 20);
        expectNoOverlap(arranged);
    });

    it('gives Classification-Decision-Table layers the same gap as Decision-Table layers, no extra', () => {
        const gapAfterTable = (tableType: TableType): number => {
            const arranged = arrange(
                [start(), tableNode('table', tableType, 1), agent('child')],
                [
                    connect('c0', 'start', 'out', 'table', 'table-in'),
                    connect('c1', 'table', tableRowRole(tableType, 0), 'child'),
                ]
            );
            return arranged.x('child') - (arranged.x('table') + 330);
        };

        // A table layer gets the plain 100-px gap, up to the grid.
        expect(gapAfterTable(NodeType.CLASSIFICATION_TABLE)).toBe(gapAfterTable(NodeType.TABLE));
        expect(gapAfterTable(NodeType.CLASSIFICATION_TABLE)).toBe(110);
    });

    it.each(TABLE_TYPES)(
        "aligns a %s's input port with its parent's output port instead of centring the box",
        (tableType) => {
            const arranged = arrange(
                [start(), python('mid'), tableNode('table', tableType, 3)],
                [connect('c0', 'start', 'out', 'mid'), connect('c1', 'mid', 'out', 'table', 'table-in')]
            );

            const inputOffset =
                tableType === NodeType.TABLE ? DT_INPUT_PORT_CENTER_Y_OFFSET : CDT_INPUT_PORT_CENTER_Y_OFFSET;
            expect(arranged.y('table') + inputOffset).toBe(arranged.y('mid') + 30);
        }
    );

    it.each(TABLE_TYPES)(
        "keeps a %s's own row children exactly on their rows once the table is port-aligned",
        (tableType) => {
            const arranged = arrange(
                [
                    start(),
                    python('mid'),
                    tableNode('table', tableType, 3),
                    python('child0'),
                    python('child1'),
                    python('child2'),
                ],
                [
                    connect('c0', 'start', 'out', 'mid'),
                    connect('cIn', 'mid', 'out', 'table', 'table-in'),
                    ...[0, 1, 2].map((row) =>
                        connect(`c${row + 1}`, 'table', tableRowRole(tableType, row), `child${row}`)
                    ),
                ]
            );

            for (let row = 0; row < 3; row++) {
                expect(arranged.y(`child${row}`) + 30).toBe(rowPortY(arranged, 'table', row, tableType));
            }
        }
    );

    it('right-aligns nodes within a layer so different widths share the same right edge', () => {
        const arranged = arrange(
            [start(), agent('narrow', { width: 200 }), agent('wide', { width: 400 })],
            [connect('c1', 'start', 'out1', 'narrow'), connect('c2', 'start', 'out2', 'wide')]
        );

        expect(arranged.x('narrow') + 200).toBe(arranged.x('wide') + 400);
        expect(arranged.x('narrow')).toBeGreaterThan(arranged.x('wide'));
    });

    describe('flow-6 regression shapes: no overlap, no crossing, table rows straight where feasible', () => {
        const CDT = NodeType.CLASSIFICATION_TABLE;

        it('a port-aligned table gives way to the row-pinned pair sharing its column', () => {
            const arranged = arrangeFixture(flow6PortAlignedTable());

            expectNoOverlap(arranged);
            expect(arranged.report.crossings).toBe(0);
            expect(arranged.y('py1') + 30).toBe(rowPortY(arranged, 'T', 0, CDT));
            expect(arranged.y('py2') + 30).toBe(rowPortY(arranged, 'T', 1, CDT));
            expect(arranged.y('cdt') + arranged.height('cdt')).toBeLessThanOrEqual(arranged.y('py1'));
        });

        it('keeps the rows straight and the table on its input alignment, clear of `big`', () => {
            const arranged = arrangeFixture(flow6RowPinnedChildren());

            expectNoOverlap(arranged);
            expect(arranged.report.crossings).toBe(0);
            expect(arranged.y('py1') + 30).toBe(rowPortY(arranged, 'cdt', 0, CDT));
            expect(arranged.y('py2') + 30).toBe(rowPortY(arranged, 'cdt', 1, CDT));
            expect(arranged.y('cdt') + CDT_INPUT_PORT_CENTER_Y_OFFSET).toBe(arranged.y('p') + 30);
        });

        it('a row child of another table relocates below the settled table, at least 20 clear', () => {
            const arranged = arrangeFixture(flow6RelocatesPinned());

            expectNoOverlap(arranged);
            expect(arranged.report.crossings).toBe(0);
            ['pn12', 'pn5', 'pn11'].forEach((id, row) =>
                expect(arranged.y(id) + 30).toBe(rowPortY(arranged, 'cdt8', row, CDT))
            );
            expect(arranged.y('python13')).toBeGreaterThanOrEqual(arranged.y('cdt10') + arranged.height('cdt10') + 20);
        });
    });

    it('lays out a group the roots cannot reach in the same layers, the table left of its children', () => {
        // `t` is only entered from its own loop (p4 → t, p6 → t) and p5 leads out to `a`. Cycle
        // breaking joins the group to the component instead of a separate band below it.
        const arranged = arrange(
            [
                makeNode('start', NodeType.START, { width: 125, height: 60 }),
                python('a'),
                python('p4'),
                python('p5'),
                python('p6'),
                tableNode('t', NodeType.TABLE, 3),
            ],
            [
                connect('c1', 'start', 'out', 'a'),
                connect('c2', 't', tableRowRole(NodeType.TABLE, 0), 'p4'),
                connect('c3', 't', tableRowRole(NodeType.TABLE, 1), 'p5'),
                connect('c4', 't', tableRowRole(NodeType.TABLE, 2), 'p6'),
                connect('c5', 'p4', 'out', 't', 'table-in'),
                connect('c6', 'p6', 'out', 't', 'table-in'),
                connect('c7', 'p5', 'out', 'a'),
            ]
        );

        expect(arranged.x('t')).toBeLessThan(arranged.x('p4'));
        expect(arranged.x('p5')).toBe(arranged.x('p4'));
        expect(arranged.x('p6')).toBe(arranged.x('p4'));
        expectNoOverlap(arranged);
        expect(arranged.report.wireThroughNode).toBe(0);
    });

    it('puts every node top on the 20-px grid, a table included, with its input wire straight', () => {
        const arranged = arrange(
            [
                makeNode('start', NodeType.START, { width: 125, height: 60 }),
                python('a'),
                tableNode('table', NodeType.TABLE, 2),
                python('b'),
                python('c'),
            ],
            [
                connect('c1', 'start', 'out', 'a'),
                connect('c2', 'a', 'out', 'table', 'table-in'),
                connect('c3', 'table', tableRowRole(NodeType.TABLE, 0), 'b'),
                connect('c4', 'table', tableRowRole(NodeType.TABLE, 1), 'c'),
            ]
        );

        for (const node of arranged.nodes) expect(node.position.y % 20).toBe(0);
        expect(arranged.report.offGrid).toBe(0);
        expect(arranged.y('table') + DT_INPUT_PORT_CENTER_Y_OFFSET).toBe(arranged.y('a') + 30);
    });

    it('centres a node fed by two rows of one table exactly between them, off the grid if need be', () => {
        const arranged = arrange(
            [
                makeNode('start', NodeType.START, { width: 125, height: 60 }),
                tableNode('table', NodeType.TABLE, 2),
                makeNode('end', NodeType.END, { height: 60 }),
            ],
            [
                connect('c1', 'start', 'out', 'table', 'table-in'),
                connect('c2', 'table', tableRowRole(NodeType.TABLE, 0), 'end'),
                connect('c3', 'table', tableRowRole(NodeType.TABLE, 1), 'end'),
            ]
        );

        const midpoint =
            (rowPortY(arranged, 'table', 0, NodeType.TABLE) + rowPortY(arranged, 'table', 1, NodeType.TABLE)) / 2;
        expect(arranged.y('end') + 30).toBe(midpoint);
        expect(arranged.report.offGrid).toBe(0);
    });

    it('orders a column by input port, not box centre; the merge node sits below the long wire, crossing-free', () => {
        // Flow 8's shape. With `end` on the median of its feeding ports (t1's row 3, t2's rows 1
        // and 2) routeAll crosses 2 wires; below the corridor t1's row-3 wire takes under p7/p8, none.
        // So end follows the long wire's detour, as in the flow-8 golden (0 crossings, End below Py#9).
        const cdt = NodeType.CLASSIFICATION_TABLE;
        const arranged = arrange(
            [
                makeNode('start', NodeType.START, { width: 125, height: 60 }),
                tableNode('t1', cdt, 4),
                python('a'),
                python('b'),
                python('c'),
                tableNode('t2', cdt, 3),
                python('p7'),
                python('p8'),
                python('p9'),
                makeNode('end', NodeType.END, { height: 60 }),
            ],
            [
                connect('c1', 'start', 'out', 't1', 'table-in'),
                connect('c2', 't1', tableRowRole(cdt, 0), 'a'),
                connect('c3', 't1', tableRowRole(cdt, 1), 'b'),
                connect('c4', 't1', tableRowRole(cdt, 2), 'c'),
                connect('c5', 't1', tableRowRole(cdt, 3), 'end'),
                connect('c6', 'a', 'out', 't2', 'table-in'),
                connect('c7', 'b', 'out', 'p7'),
                connect('c8', 'c', 'out', 'p8'),
                connect('c9', 't2', tableRowRole(cdt, 0), 'p9'),
                connect('c10', 't2', tableRowRole(cdt, 1), 'end'),
                connect('c11', 't2', tableRowRole(cdt, 2), 'end'),
            ]
        );

        expect(arranged.y('t2')).toBeLessThan(arranged.y('p7'));
        expect(arranged.y('p7')).toBeLessThan(arranged.y('p8'));
        expect(arranged.y('t2') + CDT_INPUT_PORT_CENTER_Y_OFFSET).toBe(arranged.y('a') + 30);
        expect(arranged.y('end')).toBeGreaterThanOrEqual(arranged.y('p9') + 60);
        expect(arranged.report.crossings).toBe(0);
        expectNoOverlap(arranged);
    });
});
