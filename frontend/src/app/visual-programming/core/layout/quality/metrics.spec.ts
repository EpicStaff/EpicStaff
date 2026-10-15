import { IPoint } from '@foblex/2d';
import { NodeType } from '@shared/models';

import { NodeModel } from '../../models/node.model';
import { connect, FlowFixture, makeNode, stackedPair, tableNode, tableRowRole, withPorts } from '../testing/fixtures';
import { countStackedGapCases, measure, QualityReport, wiresFromRoutes } from './metrics';

// Every counter that reports a violation (a hard rule or a crossing). The synthetic cases below
// each break exactly one of them, so a test also proves the others stay silent.
const VIOLATION_COUNTERS = [
    'nodeOverlaps',
    'wireThroughNode',
    'collinearOverlaps',
    'selfIntersections',
    'badStubs',
    'offGrid',
    'stackedGapViolations',
    'shortSegments',
    'crossings',
] as const;

type ViolationCounter = (typeof VIOLATION_COUNTERS)[number];

function expectOnly(report: QualityReport, counter: ViolationCounter | null, expected = 1): void {
    for (const name of VIOLATION_COUNTERS) {
        expect({ [name]: report[name] }).toEqual({ [name]: name === counter ? expected : 0 });
    }
}

function python(id: string, x: number, y: number): NodeModel {
    return makeNode(id, NodeType.PYTHON, { height: 60, position: { x, y } });
}

// Measures hand-drawn full routes (port to port) keyed by connection id.
function measureRoutes(fixture: FlowFixture, routes: Record<string, IPoint[]>): QualityReport {
    const routeMap = new Map(Object.entries(routes));
    return measure(fixture.nodes, wiresFromRoutes(fixture.nodes, fixture.connections, routeMap, false));
}

function withWires(nodes: NodeModel[], links: [string, string, string][]): FlowFixture {
    const connections = links.map(([id, source, target]) => connect(id, source, 'out', target, 'in'));
    return { nodes: withPorts(nodes, connections), connections };
}

describe('quality metrics — synthetic cases, one counter each', () => {
    it('counts two intersecting node boxes as one overlap', () => {
        const report = measure([python('a', 0, 0), python('b', 100, 20)], []);

        expectOnly(report, 'nodeOverlaps');
    });

    it('counts two stacked nodes 10 px apart that are not row siblings as one overlap', () => {
        const tall = makeNode('a', NodeType.PYTHON, { height: 70, position: { x: 0, y: 0 } });
        const report = measure([tall, python('b', 0, 80)], []);

        expectOnly(report, 'nodeOverlaps');
    });

    it('accepts two stacked nodes 20 px apart: the gap one wire fits in', () => {
        const report = measure([python('a', 0, 0), python('b', 0, 80)], []);

        expectOnly(report, null);
    });

    it('lets children straight on consecutive rows of one table touch', () => {
        // CDT rows at y 90 and 150; the 60-px children sit on them with no gap between them.
        const table = tableNode('cdt', NodeType.CLASSIFICATION_TABLE, 2, { x: 0, y: 0 });
        const connections = [
            connect('r0', 'cdt', tableRowRole(NodeType.CLASSIFICATION_TABLE, 0), 'c1', 'in'),
            connect('r1', 'cdt', tableRowRole(NodeType.CLASSIFICATION_TABLE, 1), 'c2', 'in'),
        ];
        const nodes = withPorts([table, python('c1', 600, 60), python('c2', 600, 120)], connections);

        const report = measureRoutes(
            { nodes, connections },
            {
                r0: [
                    { x: 337, y: 90 },
                    { x: 595, y: 90 },
                ],
                r1: [
                    { x: 337, y: 150 },
                    { x: 595, y: 150 },
                ],
            }
        );

        expectOnly(report, null);
    });

    it('still counts row siblings whose boxes overlap', () => {
        // A 100-px child straight on row 0 (top 40, bottom 140) and a 60-px one on row 1 (top 120).
        const table = tableNode('cdt', NodeType.CLASSIFICATION_TABLE, 2, { x: 0, y: 0 });
        const tall = makeNode('c1', NodeType.PYTHON, { height: 100, position: { x: 600, y: 40 } });
        const connections = [
            connect('r0', 'cdt', tableRowRole(NodeType.CLASSIFICATION_TABLE, 0), 'c1', 'in'),
            connect('r1', 'cdt', tableRowRole(NodeType.CLASSIFICATION_TABLE, 1), 'c2', 'in'),
        ];
        const nodes = withPorts([table, tall, python('c2', 600, 120)], connections);

        const report = measureRoutes(
            { nodes, connections },
            {
                r0: [
                    { x: 337, y: 90 },
                    { x: 595, y: 90 },
                ],
                r1: [
                    { x: 337, y: 150 },
                    { x: 595, y: 150 },
                ],
            }
        );

        // The boxes overlap, so each wire's stub end also sits in the other child's padding (a wire through a node).
        expect(report.nodeOverlaps).toBe(1);
    });

    it('counts a wire through a third node', () => {
        const fixture = withWires(
            [python('a', 0, 0), python('middle', 400, 0), python('b', 800, 0)],
            [['w', 'a', 'b']]
        );

        const report = measureRoutes(fixture, {
            w: [
                { x: 335, y: 30 },
                { x: 795, y: 30 },
            ],
        });

        expectOnly(report, 'wireThroughNode');
    });

    it('counts two wires from different ports sharing a vertical riser', () => {
        const fixture = withWires(
            [python('s1', 0, 0), python('s2', 0, 200), python('t1', 800, 300), python('t2', 800, 420)],
            [
                ['a', 's1', 't1'],
                ['b', 's2', 't2'],
            ]
        );

        const report = measureRoutes(fixture, {
            a: [
                { x: 335, y: 30 },
                { x: 560, y: 30 },
                { x: 560, y: 330 },
                { x: 795, y: 330 },
            ],
            b: [
                { x: 335, y: 230 },
                { x: 560, y: 230 },
                { x: 560, y: 450 },
                { x: 795, y: 450 },
            ],
        });

        expectOnly(report, 'collinearOverlaps');
    });

    it('counts an X crossing between two wires', () => {
        const fixture = withWires(
            [python('s1', 0, 0), python('s2', 0, 200), python('t1', 800, 300), python('t2', 800, 100)],
            [
                ['a', 's1', 't1'],
                ['b', 's2', 't2'],
            ]
        );

        const report = measureRoutes(fixture, {
            a: [
                { x: 335, y: 30 },
                { x: 500, y: 30 },
                { x: 500, y: 330 },
                { x: 795, y: 330 },
            ],
            b: [
                { x: 335, y: 230 },
                { x: 600, y: 230 },
                { x: 600, y: 130 },
                { x: 795, y: 130 },
            ],
        });

        expectOnly(report, 'crossings');
    });

    it('counts a 10-px source stub as a bad stub', () => {
        const fixture = withWires([python('s', 0, 0), python('t', 800, 300)], [['w', 's', 't']]);

        const report = measureRoutes(fixture, {
            w: [
                { x: 335, y: 30 },
                { x: 345, y: 30 },
                { x: 345, y: 330 },
                { x: 795, y: 330 },
            ],
        });

        expectOnly(report, 'badStubs');
    });

    it('counts a 4-px jog between two bends as a short interior segment', () => {
        const fixture = withWires([python('s', 0, 0), python('t', 800, 300)], [['w', 's', 't']]);

        const report = measureRoutes(fixture, {
            w: [
                { x: 335, y: 30 },
                { x: 560, y: 30 },
                { x: 560, y: 180 },
                { x: 564, y: 180 },
                { x: 564, y: 330 },
                { x: 795, y: 330 },
            ],
        });

        expectOnly(report, 'shortSegments');
    });

    it('does not count the lone segment between two stubs whose ports are under 10 px apart', () => {
        // A 75-px-high target at y 0 puts its port at 37.5, 7.5 px below the source's: the riser can't be longer.
        const nodes = [python('s', 0, 0), makeNode('t', NodeType.PYTHON, { height: 75, position: { x: 800, y: 0 } })];
        const fixture = withWires(nodes, [['w', 's', 't']]);

        const report = measureRoutes(fixture, {
            w: [
                { x: 335, y: 30 },
                { x: 560, y: 30 },
                { x: 560, y: 37.5 },
                { x: 795, y: 37.5 },
            ],
        });

        expectOnly(report, null);
    });

    it('counts the stacked pair (60-px unpadded gap) routed over the top as a stacked-gap violation', () => {
        const report = measureRoutes(stackedPair(), {
            'c14-15': [
                { x: 335, y: 30 },
                { x: 355, y: 30 },
                { x: 355, y: -40 },
                { x: -25, y: -40 },
                { x: -25, y: 150 },
                { x: -5, y: 150 },
            ],
        });

        expectOnly(report, 'stackedGapViolations');
    });

    it('accepts the stacked pair routed through the gap', () => {
        const report = measureRoutes(stackedPair(), {
            'c14-15': [
                { x: 335, y: 30 },
                { x: 355, y: 30 },
                { x: 355, y: 90 },
                { x: -25, y: 90 },
                { x: -25, y: 150 },
                { x: -5, y: 150 },
            ],
        });

        expectOnly(report, null);
        expect(report.bends).toBe(4);
    });

    it('applies the stacked-gap rule to a stacked pair 20 px apart: over the top is a violation', () => {
        const report = measureRoutes(stackedPair(80), {
            'c14-15': [
                { x: 335, y: 30 },
                { x: 355, y: 30 },
                { x: 355, y: -40 },
                { x: -25, y: -40 },
                { x: -25, y: 110 },
                { x: -5, y: 110 },
            ],
        });

        expectOnly(report, 'stackedGapViolations');
    });

    it('accepts the stacked pair 20 px apart routed through the gap, 10 px from each node', () => {
        const report = measureRoutes(stackedPair(80), {
            'c14-15': [
                { x: 335, y: 30 },
                { x: 355, y: 30 },
                { x: 355, y: 70 },
                { x: -25, y: 70 },
                { x: -25, y: 110 },
                { x: -5, y: 110 },
            ],
        });

        expectOnly(report, null);
    });

    it('counts a return leg 5 px under the upper node as a wire through its padding', () => {
        const report = measureRoutes(stackedPair(80), {
            'c14-15': [
                { x: 335, y: 30 },
                { x: 355, y: 30 },
                { x: 355, y: 65 },
                { x: -25, y: 65 },
                { x: -25, y: 110 },
                { x: -5, y: 110 },
            ],
        });

        expectOnly(report, 'wireThroughNode');
    });

    it('treats two port ids drawn at the same point as one port: their shared stub is a trunk', () => {
        // `out0` and `out1` both sit on s's right edge centre, as in the random graphs.
        const nodes = [python('s', 0, 0), python('t1', 800, 0), python('t2', 800, 300)];
        const connections = [connect('a', 's', 'out0', 't1', 'in'), connect('b', 's', 'out1', 't2', 'in')];
        const fixture = { nodes: withPorts(nodes, connections), connections };

        const report = measureRoutes(fixture, {
            a: [
                { x: 335, y: 30 },
                { x: 795, y: 30 },
            ],
            b: [
                { x: 335, y: 30 },
                { x: 560, y: 30 },
                { x: 560, y: 330 },
                { x: 795, y: 330 },
            ],
        });

        expectOnly(report, null);
    });

    it('accepts stubs level within the half-pixel tolerance simplify() calls straight', () => {
        // A 75-px-high target puts its port at y 30.5; the wire jogs by half a pixel.
        const nodes = [python('s', 0, 0), makeNode('t', NodeType.PYTHON, { height: 75, position: { x: 800, y: -7 } })];
        const fixture = withWires(nodes, [['w', 's', 't']]);

        const report = measureRoutes(fixture, {
            w: [
                { x: 335, y: 30 },
                { x: 560, y: 30 },
                { x: 560, y: 30.5 },
                { x: 795, y: 30.5 },
            ],
        });

        expectOnly(report, null);
    });

    it('does not apply the stacked-gap rule when a third node fills the gap between the stacked pair', () => {
        // Py15 at y 260 leaves a 200-px gap; a 60-px node sits in it, 60 px below Py14.
        const { nodes, connections } = stackedPair(260);
        const filled = { nodes: [...nodes, python('middle', 0, 120)], connections };
        const overTheTop = {
            'c14-15': [
                { x: 335, y: 30 },
                { x: 355, y: 30 },
                { x: 355, y: -40 },
                { x: -25, y: -40 },
                { x: -25, y: 290 },
                { x: -5, y: 290 },
            ],
        };

        expect(measureRoutes(stackedPair(260), overTheTop).stackedGapViolations).toBe(1);
        expectOnly(measureRoutes(filled, overTheTop), null);
        const wires = wiresFromRoutes(filled.nodes, connections, new Map(Object.entries(overTheTop)), false);
        expect(countStackedGapCases(filled.nodes, wires)).toBe(0);
        expect(countStackedGapCases(nodes, wires)).toBe(1);
    });
});
