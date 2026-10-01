import { NodeType } from '@shared/models';

import { obstacleRect } from '../routing/obstacles';
import { routeAll } from '../routing/route-all';
import { computeLayout } from './compute-layout';
import { isBackwardRoutedWire, measure, QualityReport, RoutedWire, wiresFromRoutes } from './quality/metrics';
import {
    flow6PortAlignedTable,
    flow6RelocatesPinned,
    flow6RowPinnedChildren,
    flow8,
    flow9,
    FlowFixture,
    isolatedNodes,
    liveFlow6,
    selfLoop,
    stackedPair,
    threeCycle,
    twoComponents,
    withPositions,
} from './testing/fixtures';
import { randomGraph, shuffled } from './testing/random-graphs';

/**
 * Layout quality gates: computeLayout + routeAll on the golden fixtures and seeds 1..200 (1..100
 * with tables). The rules are defined in quality/metrics.ts.
 * - On the layout: no node overlap and every top on the 20-px grid; the layout is deterministic
 *   with shuffled input and idempotent on its own output. The overlap rule's row-sibling exemption
 *   and the grid rule's straight-wire exemption read the wires, so the layout is measured with
 *   routeAll's wires.
 * - After routeAll: no wire through a node, no collinear overlap, no self-intersection, stubs of
 *   at least 20 px, stacked pairs returning through their gap, no kinks.
 * - Crossings, bends and area over the corpus: at most their ceiling + 2%; backward wires bend at
 *   most 5 times on average.
 * - Straight wires and straight table-row wires (in total and on every golden fixture): at least
 *   their floor − 2%.
 * A regression fails; after a real improvement, move the limit to the new number so it is
 * protected too.
 */

const LAYOUT_RULES = ['nodeOverlaps', 'offGrid'] as const;
const ROUTER_RULES = [
    'wireThroughNode',
    'collinearOverlaps',
    'selfIntersections',
    'badStubs',
    'stackedGapViolations',
    'shortSegments',
] as const;
const MAX_BACKWARD_MEAN_BENDS = 5;
const TOLERANCE = 0.02;

// Regression limits for the aggregate over the seeded corpus (golden fixtures + 200 seeds):
// crossings, bends and area are ceilings, straight wires and straight table rows are floors, each
// with the 2% TOLERANCE. `wires` is exact: every drawable wire is routed.
const PINNED_TOTAL = {
    wires: 2262,
    crossings: 335,
    bends: 3292,
    straightAdjacent: 694,
    rowStraight: 83,
    area: 520547663,
};
// Floor of straight table-row wires per golden fixture. In liveFlow6, End, fed by CDT#11's Default
// and Error rows, sits on the median of the two instead of straight on Error.
const PINNED_GOLDEN_ROWS: Record<string, number> = {
    liveFlow6: 6,
    flow8: 4,
    flow9: 10,
    flow6PortAlignedTable: 2,
    flow6RowPinnedChildren: 2,
    flow6RelocatesPinned: 4,
    stackedPair: 0,
    selfLoop: 0,
    threeCycle: 0,
    twoComponents: 0,
    isolatedNodes: 0,
};

const TABLE_TYPES = new Set<string>([NodeType.TABLE, NodeType.CLASSIFICATION_TABLE]);

interface CaseResult {
    name: string;
    report: QualityReport;
    rowStraight: number;
    backward: { wires: number; bends: number };
    deterministic: boolean;
    idempotent: boolean;
}

const EMPTY_REPORT: QualityReport = {
    nodeOverlaps: 0,
    wireThroughNode: 0,
    collinearOverlaps: 0,
    selfIntersections: 0,
    badStubs: 0,
    offGrid: 0,
    stackedGapViolations: 0,
    shortSegments: 0,
    crossings: 0,
    bends: 0,
    straightAdjacent: 0,
    wires: 0,
    area: 0,
};

function add(total: QualityReport, report: QualityReport): QualityReport {
    const sum = { ...total };
    for (const key of Object.keys(sum) as (keyof QualityReport)[]) sum[key] += report[key];
    return sum;
}

const bends = (wire: RoutedWire): number => Math.max(wire.points.length - 2, 0);
const isStraight = (wire: RoutedWire): boolean => wire.points.length === 2;

function straightRowWires(nodes: FlowFixture['nodes'], wires: RoutedWire[]): number {
    const tables = new Set(nodes.filter((node) => TABLE_TYPES.has(node.type)).map((node) => node.id));
    return wires.filter((wire) => tables.has(wire.sourceNodeId) && isStraight(wire)).length;
}

function arrangeAndRoute({ nodes, connections }: FlowFixture): { nodes: FlowFixture['nodes']; wires: RoutedWire[] } {
    const arranged = withPositions(nodes, computeLayout(nodes, connections));
    return { nodes: arranged, wires: wiresFromRoutes(arranged, connections, routeAll(arranged, connections), true) };
}

function measureCase(name: string, fixture: FlowFixture, seed: number): CaseResult {
    const { nodes, connections } = fixture;
    const positions = computeLayout(nodes, connections);
    const { nodes: arranged, wires } = arrangeAndRoute(fixture);
    const result: CaseResult = {
        name,
        report: measure(arranged, wires),
        rowStraight: straightRowWires(arranged, wires),
        backward: { wires: 0, bends: 0 },
        deterministic: true,
        idempotent: true,
    };
    const arrangedById = new Map(arranged.map((node) => [node.id, node]));
    for (const wire of wires) {
        if (!isBackwardRoutedWire(arrangedById, wire)) continue;
        result.backward.wires++;
        result.backward.bends += bends(wire);
    }
    result.deterministic = equal(positions, computeLayout(shuffled(nodes, seed), shuffled(connections, seed + 1)));
    result.idempotent = equal(positions, computeLayout(withPositions(nodes, positions), connections));
    return result;
}

function equal(first: Map<string, { x: number; y: number }>, second: Map<string, { x: number; y: number }>): boolean {
    return (
        first.size === second.size &&
        [...first].every(([id, point]) => second.get(id)?.x === point.x && second.get(id)?.y === point.y)
    );
}

function rules(report: QualityReport, names: readonly (keyof QualityReport)[]): Record<string, number> {
    return Object.fromEntries(names.map((rule) => [rule, report[rule]]));
}

const zeros = (names: readonly string[]): Record<string, number> => Object.fromEntries(names.map((rule) => [rule, 0]));

const GOLDEN: [string, () => FlowFixture][] = [
    ['liveFlow6', liveFlow6],
    ['flow8', flow8],
    ['flow9', flow9],
    ['flow6PortAlignedTable', flow6PortAlignedTable],
    ['flow6RowPinnedChildren', flow6RowPinnedChildren],
    ['flow6RelocatesPinned', flow6RelocatesPinned],
    ['stackedPair', () => stackedPair()],
    ['selfLoop', selfLoop],
    ['threeCycle', threeCycle],
    ['twoComponents', twoComponents],
    ['isolatedNodes', isolatedNodes],
];

describe('computeLayout quality gates', () => {
    const golden = GOLDEN.map(([name, build], index) => measureCase(name, build(), index + 1));
    const seeds = Array.from({ length: 200 }, (_, index) =>
        measureCase(`seed${index + 1}`, randomGraph(index + 1, { withTables: index < 100 }), index + 1)
    );
    const all = [...golden, ...seeds];
    const total = all.reduce((sum, result) => add(sum, result.report), EMPTY_REPORT);
    const sum = (pick: (result: CaseResult) => number): number => all.reduce((acc, result) => acc + pick(result), 0);

    it('logs the aggregate numbers', () => {
        // eslint-disable-next-line no-console -- the numbers to update the limits with are read from the test log
        console.log(
            `LAYOUT_QUALITY ${all.length} cases\n  new    ${JSON.stringify(total)}\n` +
                `  backward ${sum((result) => result.backward.wires)} wires, ${sum((result) => result.backward.bends)} bends` +
                ` | row straight ${sum((result) => result.rowStraight)}` +
                `\n  golden rows ${JSON.stringify(Object.fromEntries(golden.map((result) => [result.name, result.rowStraight])))}`
        );
        expect(all.length).toBe(GOLDEN.length + 200);
        expect(Object.keys(PINNED_GOLDEN_ROWS).sort()).toEqual(golden.map((result) => result.name).sort());
    });

    it('routes every drawable wire', () => {
        expect(total.wires).toBe(PINNED_TOTAL.wires);
    });

    it('breaks no hard rule on the layout, nor after routeAll', () => {
        for (const result of all) {
            expect({ case: result.name, ...rules(result.report, LAYOUT_RULES) }).toEqual({
                case: result.name,
                ...zeros(LAYOUT_RULES),
            });
            expect({ case: result.name, ...rules(result.report, ROUTER_RULES) }).toEqual({
                case: result.name,
                ...zeros(ROUTER_RULES),
            });
        }
    });

    it('is deterministic with shuffled input and idempotent on its own output', () => {
        expect(all.filter((result) => !result.deterministic).map((result) => result.name)).toEqual([]);
        expect(all.filter((result) => !result.idempotent).map((result) => result.name)).toEqual([]);
    });

    it('crosses no more than the ceiling + 2%', () => {
        expect(total.crossings).toBeLessThanOrEqual(PINNED_TOTAL.crossings * (1 + TOLERANCE));
    });

    it('bends no more than the ceiling + 2%, backward wires ≤ 5 on average', () => {
        expect(total.bends).toBeLessThanOrEqual(PINNED_TOTAL.bends * (1 + TOLERANCE));
        const backwardWires = sum((result) => result.backward.wires);
        expect(backwardWires).toBeGreaterThan(0);
        expect(sum((result) => result.backward.bends) / backwardWires).toBeLessThanOrEqual(MAX_BACKWARD_MEAN_BENDS);
    });

    it('draws no fewer straight wires, nor straight table rows, than the floor − 2%', () => {
        expect(total.straightAdjacent).toBeGreaterThanOrEqual(PINNED_TOTAL.straightAdjacent * (1 - TOLERANCE));
        expect(sum((result) => result.rowStraight)).toBeGreaterThanOrEqual(PINNED_TOTAL.rowStraight * (1 - TOLERANCE));
        for (const result of golden) {
            expect(result.rowStraight, `${result.name} straight rows`).toBeGreaterThanOrEqual(
                PINNED_GOLDEN_ROWS[result.name] * (1 - TOLERANCE)
            );
        }
    });

    it('stays within the area ceiling + 2%', () => {
        expect(total.area).toBeLessThanOrEqual(PINNED_TOTAL.area * (1 + TOLERANCE));
    });
});

describe('straight-row floor catches row children knocked off their rows (mutation)', () => {
    // Proves the floor fails on the defect it guards: moving every node fed by a table row 20 px
    // down must drop below the golden fixture's floor.
    it.each([
        ['liveFlow6', liveFlow6],
        ['flow9', flow9],
    ] as const)('%s', (name, build) => {
        const { nodes, connections } = build();
        const tables = new Set(nodes.filter((node) => TABLE_TYPES.has(node.type)).map((node) => node.id));
        const rowFed = new Set(
            connections.filter((connection) => tables.has(connection.sourceNodeId)).map((c) => c.targetNodeId)
        );
        const positions = computeLayout(nodes, connections);
        const mutated = new Map(
            [...positions].map(([id, point]) => [id, rowFed.has(id) ? { ...point, y: point.y + 20 } : point])
        );
        const mutatedNodes = withPositions(nodes, mutated);
        const mutatedWires = wiresFromRoutes(mutatedNodes, connections, routeAll(mutatedNodes, connections), true);

        expect(straightRowWires(mutatedNodes, mutatedWires)).toBeLessThan(PINNED_GOLDEN_ROWS[name] * (1 - TOLERANCE));
    });
});

describe('computeLayout golden flows', () => {
    const nodeId = {
        py3: 'f8-06-py3',
        py9: 'f8-02-py9',
        end: 'f8-09-end',
        cdt6: 'f8-07-cdt6',
    };

    it('flow 8: no crossing, CDT#6 straight on Py#3, End below Py#9', () => {
        const { nodes, wires } = arrangeAndRoute(flow8());
        const at = (id: string) => nodes.find((node) => node.id === id)!;

        expect(measure(nodes, wires).crossings).toBe(0);
        const py3ToCdt6 = wires.find((wire) => wire.sourceNodeId === nodeId.py3 && wire.targetNodeId === nodeId.cdt6)!;
        expect(py3ToCdt6.points).toHaveLength(2);
        expect(at(nodeId.end).position.y).toBeGreaterThanOrEqual(
            at(nodeId.py9).position.y + at(nodeId.py9).size.height
        );
    });

    it('flow 6: Audio#9 does not enter on the row #1 leaves on, so #1 never reads as feeding it', () => {
        // Neither can be straight (DT#10 is, below them); with Audio#9's input on #1's output row
        // the two bent wires would line up end to end on one line.
        const { wires } = arrangeAndRoute(liveFlow6());
        const fromPython1 = wires.find((wire) => wire.sourceNodeId === 'f6-11-py1')!;
        const intoAudio9 = wires.find((wire) => wire.targetNodeId === 'f6-01-audio9')!;

        expect(fromPython1.points.length).toBeGreaterThan(2);
        expect(intoAudio9.points.length).toBeGreaterThan(2);
        expect(intoAudio9.points[intoAudio9.points.length - 1].y).not.toBe(fromPython1.points[0].y);
    });

    // Py#4, Py#5 and Py#6 are stacked on DT#10's rows and all three
    // return left. Each goes up and over the top of its own two ends; the risers nest, the lowest
    // source outermost, so no riser crosses another wire's stub.
    describe('flow 6: the return wires of the stacked Py#4/#5/#6', () => {
        const id = {
            py4: 'f6-10-py4',
            py5: 'f6-06-py5',
            py6: 'f6-02-py6',
            py7: 'f6-07-py7',
            dt10: 'f6-13-dt10',
            audio9: 'f6-01-audio9',
        };
        const { nodes, wires } = arrangeAndRoute(liveFlow6());
        const box = (nodeId: string) => obstacleRect(nodes.find((node) => node.id === nodeId)!);
        const wire = (source: string, target: string) =>
            wires.find((candidate) => candidate.sourceNodeId === source && candidate.targetNodeId === target)!;
        // Horizontal legs between the two stubs.
        const legYs = ({ points }: RoutedWire): number[] =>
            points.slice(1, -2).flatMap((point, index) => (point.y === points[index + 2].y ? [point.y] : []));
        const returns = [wire(id.py4, id.dt10), wire(id.py5, id.py7), wire(id.py6, id.dt10)];

        it('Py#5 → Py#7 runs over the top of both, never under', () => {
            const legs = legYs(returns[1]);
            expect(legs.length).toBeGreaterThan(0);
            expect(Math.max(...legs)).toBeLessThanOrEqual(Math.min(box(id.py5).top, box(id.py7).top));
        });

        it('Py#4 and Py#6 → DT#10 run just above the table, not above Audio#9 over it', () => {
            for (const returning of [returns[0], returns[2]]) {
                const legs = legYs(returning);
                expect(Math.max(...legs)).toBeLessThanOrEqual(box(id.dt10).top);
                expect(Math.min(...legs)).toBeGreaterThanOrEqual(box(id.audio9).bottom);
            }
        });

        // Nodes sit as close as the wires allow. File Extractor#8 and
        // Audio#9 can't be straight (DT#10 is, below them), so they stack on DT#10 20 px apart, and
        // the return legs into DT#10 run in the gap above it, 10 px from Audio#9 and from DT#10.
        it('File Extractor#8, Audio#9 and DT#10 stack 20 px apart, the return legs in the gap', () => {
            const top = (nodeId: string) => nodes.find((node) => node.id === nodeId)!.position.y;
            const fileExtractor8 = 'f6-12-file8';

            expect(top(id.audio9) - top(fileExtractor8)).toBe(60 + 20);
            expect(top(id.dt10) - top(id.audio9)).toBe(60 + 20);
            for (const returning of [returns[0], returns[2]]) {
                expect(legYs(returning)).toEqual([top(id.dt10) - 10]);
            }
        });

        it('the risers go up and nest: x(Py#4) < x(Py#5) < x(Py#6)', () => {
            const risers = returns.map(({ points }) => ({ x: points[1].x, up: points[2].y < points[1].y }));
            expect(risers.map((riser) => riser.up)).toEqual([true, true, true]);
            expect(risers[0].x).toBeLessThan(risers[1].x);
            expect(risers[1].x).toBeLessThan(risers[2].x);
        });
    });

    // Per-fixture ceilings for crossings and width. Flow 6's last crossing is forced: Py#5's port sits
    // between Py#4's and Py#6's, whose wires meet at DT#10's input, so Py#5's wire has to cross one
    // of them (Py#6's leg over Py#5's riser since the risers nest). Flow 9's 11 are the floor for
    // its interleaved rows (ordering.spec proves it). Widths get the same +2% as the corpus limits.
    it.each([
        ['liveFlow6', 1, 2370, liveFlow6],
        ['flow9', 11, 6170, flow9],
    ] as const)('%s: at most %i crossings, at most %i px wide', (_, crossings, width, build) => {
        const { nodes, wires } = arrangeAndRoute(build());
        const left = Math.min(...nodes.map((node) => node.position.x));
        const right = Math.max(...nodes.map((node) => node.position.x + node.size.width));

        expect(measure(nodes, wires).crossings).toBeLessThanOrEqual(crossings);
        expect(right - left).toBeLessThanOrEqual(width * (1 + TOLERANCE));
    });
});
