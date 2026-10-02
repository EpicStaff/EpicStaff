import { computeLayout } from '../layout/compute-layout';
import {
    countStackedGapCases,
    isBackwardRoutedWire,
    measure,
    QualityReport,
    RoutedWire,
    wiresFromRoutes,
} from '../layout/quality/metrics';
import {
    flow6PortAlignedTable,
    flow6RelocatesPinned,
    flow6RowPinnedChildren,
    flow8,
    FlowFixture,
    isolatedNodes,
    selfLoop,
    stackedPair,
    threeCycle,
    twoComponents,
    withPositions,
} from '../layout/testing/fixtures';
import { randomGraph, scatteredPositions } from '../layout/testing/random-graphs';
import { routeAll } from './route-all';

/**
 * Router quality gates: routeAll on the golden fixtures (raw and arranged) and on the seeded
 * corpus (seeds 1..200 arranged, 201..300 scattered). The rules are defined in
 * ../layout/quality/metrics.ts.
 * - The routing hard rules (no wire through a node, no collinear overlap, no self-intersection,
 *   stubs of at least 20 px, stacked pairs returning through their gap, no kinks) are 0 in every
 *   corpus part and on every golden fixture.
 * - Per part and per golden fixture: crossings and bends at most their ceiling + 2%, straight
 *   wires at least their floor − 2%; backward wires (isBackwardRoutedWire) bend at most 5 times
 *   on average (the minimum is 4).
 * A regression fails; after a real improvement, move the limit to the new number so it is
 * protected too.
 */

const HARD_RULES = [
    'wireThroughNode',
    'collinearOverlaps',
    'selfIntersections',
    'badStubs',
    'stackedGapViolations',
    'shortSegments',
] as const;

// Backward wires need at least 4 bends (out, down or up, back, down or up, in).
const MAX_BACKWARD_MEAN_BENDS = 5;
// On scattered canvases a return wire goes over the top of both its nodes, round whatever stands
// between them, so it bends more: the corpus mean + 2%.
const MAX_SCATTERED_BACKWARD_MEAN_BENDS = 5.12;
const TOLERANCE = 0.02;

interface Pinned {
    crossings: number;
    bends: number;
    straightAdjacent: number;
}

// Regression limits per corpus part: crossings and bends are ceilings, straight wires a floor,
// each with the 2% TOLERANCE. `wires` is exact: every drawable wire is routed.
const PINNED_PARTS: Record<string, Pinned & { wires: number }> = {
    'fixtures, raw positions': { wires: 24, crossings: 0, bends: 24, straightAdjacent: 15 },
    'fixtures, arranged': { wires: 48, crossings: 0, bends: 42, straightAdjacent: 29 },
    'seeds 1..200, arranged': { wires: 2165, crossings: 323, bends: 3198, straightAdjacent: 638 },
    'seeds 201..300, scattered': { wires: 1066, crossings: 1493, bends: 4172, straightAdjacent: 2 },
};

const PINNED_GOLDEN: Record<string, Pinned> = {
    'flow8 (raw)': { crossings: 0, bends: 12, straightAdjacent: 6 },
    'stackedPair (raw)': { crossings: 0, bends: 4, straightAdjacent: 0 },
    'selfLoop (raw)': { crossings: 0, bends: 4, straightAdjacent: 1 },
    'threeCycle (raw)': { crossings: 0, bends: 4, straightAdjacent: 3 },
    'twoComponents (raw)': { crossings: 0, bends: 0, straightAdjacent: 4 },
    'isolatedNodes (raw)': { crossings: 0, bends: 0, straightAdjacent: 1 },
    'flow8 (arranged)': { crossings: 0, bends: 10, straightAdjacent: 7 },
    'stackedPair (arranged)': { crossings: 0, bends: 0, straightAdjacent: 1 },
    'selfLoop (arranged)': { crossings: 0, bends: 4, straightAdjacent: 1 },
    'threeCycle (arranged)': { crossings: 0, bends: 4, straightAdjacent: 3 },
    'twoComponents (arranged)': { crossings: 0, bends: 0, straightAdjacent: 4 },
    'isolatedNodes (arranged)': { crossings: 0, bends: 0, straightAdjacent: 1 },
    'flow6PortAlignedTable (arranged)': { crossings: 0, bends: 8, straightAdjacent: 3 },
    'flow6RowPinnedChildren (arranged)': { crossings: 0, bends: 12, straightAdjacent: 4 },
    'flow6RelocatesPinned (arranged)': { crossings: 0, bends: 4, straightAdjacent: 5 },
};

interface PartResult {
    name: string;
    cases: number;
    stackedGapCases: number;
    routed: QualityReport;
    backward: { wires: number; routedBends: number };
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

// Only the fixtures whose raw positions are a real canvas; the flow-6 shapes all sit at (0, 0).
const PLACED_FIXTURES: [string, () => FlowFixture][] = [
    ['flow8', flow8],
    ['stackedPair', () => stackedPair()],
    ['selfLoop', selfLoop],
    ['threeCycle', threeCycle],
    ['twoComponents', twoComponents],
    ['isolatedNodes', isolatedNodes],
];
const ALL_FIXTURES: [string, () => FlowFixture][] = [
    ...PLACED_FIXTURES,
    ['flow6PortAlignedTable', flow6PortAlignedTable],
    ['flow6RowPinnedChildren', flow6RowPinnedChildren],
    ['flow6RelocatesPinned', flow6RelocatesPinned],
];

function arranged({ nodes, connections }: FlowFixture): FlowFixture {
    return { nodes: withPositions(nodes, computeLayout(nodes, connections)), connections };
}

function scattered({ nodes, connections }: FlowFixture, seed: number): FlowFixture {
    return { nodes: withPositions(nodes, scatteredPositions(nodes, seed)), connections };
}

function bendsOf(wire: RoutedWire): number {
    return Math.max(wire.points.length - 2, 0);
}

function routedReport({ nodes, connections }: FlowFixture): QualityReport {
    return measure(nodes, wiresFromRoutes(nodes, connections, routeAll(nodes, connections), true));
}

function measurePart(name: string, fixtures: [string, FlowFixture][]): PartResult {
    const part: PartResult = {
        name,
        cases: fixtures.length,
        stackedGapCases: 0,
        routed: EMPTY_REPORT,
        backward: { wires: 0, routedBends: 0 },
    };
    for (const [, { nodes, connections }] of fixtures) {
        const wires = wiresFromRoutes(nodes, connections, routeAll(nodes, connections), true);
        part.routed = add(part.routed, measure(nodes, wires));
        part.stackedGapCases += countStackedGapCases(nodes, wires);
        const nodesById = new Map(nodes.map((node) => [node.id, node]));
        for (const wire of wires) {
            if (!isBackwardRoutedWire(nodesById, wire)) continue;
            part.backward.wires++;
            part.backward.routedBends += bendsOf(wire);
        }
    }
    return part;
}

function seeds(from: number, to: number): number[] {
    return Array.from({ length: to - from + 1 }, (_, index) => from + index);
}

function hardRules(report: QualityReport): Record<string, number> {
    return Object.fromEntries(HARD_RULES.map((rule) => [rule, report[rule]]));
}

function pinnedOf({ crossings, bends, straightAdjacent }: QualityReport): Pinned {
    return { crossings, bends, straightAdjacent };
}

function expectWithinPin(report: QualityReport, pinned: Pinned): void {
    expect(report.crossings, `crossings (pin ${pinned.crossings})`).toBeLessThanOrEqual(
        pinned.crossings * (1 + TOLERANCE)
    );
    expect(report.bends, `bends (pin ${pinned.bends})`).toBeLessThanOrEqual(pinned.bends * (1 + TOLERANCE));
    expect(report.straightAdjacent, `straight wires (pin ${pinned.straightAdjacent})`).toBeGreaterThanOrEqual(
        pinned.straightAdjacent * (1 - TOLERANCE)
    );
}

describe('routeAll quality gates', () => {
    const parts: PartResult[] = [
        measurePart(
            'fixtures, raw positions',
            PLACED_FIXTURES.map(([name, build]) => [name, build()])
        ),
        measurePart(
            'fixtures, arranged',
            ALL_FIXTURES.map(([name, build]) => [name, arranged(build())])
        ),
        measurePart(
            'seeds 1..200, arranged',
            seeds(1, 200).map((seed) => [`seed${seed}`, arranged(randomGraph(seed, { withTables: seed <= 100 }))])
        ),
        measurePart(
            'seeds 201..300, scattered',
            seeds(201, 300).map((seed) => [
                `seed${seed}`,
                scattered(randomGraph(seed, { withTables: seed % 2 === 0 }), seed),
            ])
        ),
    ];

    it('logs the per-part numbers', () => {
        for (const part of parts) {
            // eslint-disable-next-line no-console -- the numbers to update the limits with are read from the test log
            console.log(
                `ROUTER_QUALITY ${part.name} (${part.cases} cases, ${part.stackedGapCases} stacked-gap cases)\n` +
                    `  routeAll ${JSON.stringify({ ...hardRules(part.routed), ...pinnedOf(part.routed), wires: part.routed.wires })}` +
                    ` backward ${JSON.stringify(part.backward)}`
            );
        }
        expect(parts.map((part) => part.name)).toEqual(Object.keys(PINNED_PARTS));
    });

    it('contains stacked cases, so zero stacked-gap violations means something', () => {
        expect(parts.reduce((sum, part) => sum + part.stackedGapCases, 0)).toBeGreaterThan(0);
    });

    for (const [partIndex, name] of parts.map((part, index) => [index, part.name] as const)) {
        it(`keeps every hard rule at 0: ${name}`, () => {
            expect(hardRules(parts[partIndex].routed)).toEqual(Object.fromEntries(HARD_RULES.map((rule) => [rule, 0])));
        });

        it(`routes every drawable wire: ${name}`, () => {
            expect(parts[partIndex].routed.wires).toBe(PINNED_PARTS[name].wires);
        });

        it(`stays within the crossings, bends and straight-wire limits: ${name}`, () => {
            expectWithinPin(parts[partIndex].routed, PINNED_PARTS[name]);
        });

        const maxBackwardMeanBends = name.endsWith('scattered')
            ? MAX_SCATTERED_BACKWARD_MEAN_BENDS
            : MAX_BACKWARD_MEAN_BENDS;
        it(`bends backward wires ≤ ${maxBackwardMeanBends} times on average: ${name}`, () => {
            const { backward } = parts[partIndex];
            if (backward.wires > 0) {
                expect(backward.routedBends / backward.wires).toBeLessThanOrEqual(maxBackwardMeanBends);
            }
        });
    }
});

describe('routeAll golden fixtures: hard rules 0, never worse than the limits', () => {
    const cases: [string, FlowFixture][] = [
        ...PLACED_FIXTURES.map(([name, build]): [string, FlowFixture] => [`${name} (raw)`, build()]),
        ...ALL_FIXTURES.map(([name, build]): [string, FlowFixture] => [`${name} (arranged)`, arranged(build())]),
    ];
    const reports = new Map(cases.map(([name, fixture]) => [name, routedReport(fixture)]));

    it('logs the per-golden numbers', () => {
        // eslint-disable-next-line no-console -- the numbers to update the limits with are read from the test log
        console.log(
            'ROUTER_GOLDEN ' + JSON.stringify(Object.fromEntries([...reports].map(([name, r]) => [name, pinnedOf(r)])))
        );
        expect(Object.keys(PINNED_GOLDEN).sort()).toEqual([...reports.keys()].sort());
    });

    for (const [name] of cases) {
        it(`${name}: no hard rule broken; crossings, bends and straight wires within the limits`, () => {
            const report = reports.get(name)!;
            expect(hardRules(report)).toEqual(Object.fromEntries(HARD_RULES.map((rule) => [rule, 0])));
            expectWithinPin(report, PINNED_GOLDEN[name]);
        });
    }
});
