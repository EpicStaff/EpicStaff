// Pins the layout and coloring rules of the graph: which nodes the cluster force pulls and how far, which links it
// weakens, that the assembled layout clusters communities only while grouping and never draws a node over another,
// when a 3D layout starts over from random positions, and that community colors are distinct, valid, never the
// search highlight, and neutral for none.
// Domain layer: pure functions and the real d3 force engine ticked synchronously, no test doubles.
import * as d3 from 'd3-force-3d';

import { HIGHLIGHT_COLOR, NO_COMMUNITY_COLOR, NODE_3D_BRIGHTNESS } from './graph-scene.constants';
import { ColorTuple, ForceLayoutNode } from './graph-scene.model';
import {
    createCommunityClusterForce,
    createLayoutSimulation,
    getCommunityColor,
    getCommunityLinkStrengths,
    getLayoutStartPositions,
} from './graph-scene.utils';

function colorDistance(first: ColorTuple, second: ColorTuple): number {
    return Math.hypot(first[0] - second[0], first[1] - second[1], first[2] - second[2]);
}

const MANY_COMMUNITY_IDS = [
    ...Array.from({ length: 500 }, (_, index) => String(index)),
    ...Array.from({ length: 500 }, (_, index) => `community-${index}`),
];

describe('createCommunityClusterForce', () => {
    it('moves the members of a community toward its centroid, scaled by strength and alpha', () => {
        const nodes: ForceLayoutNode[] = [
            { x: 0, y: 0, vx: 0, vy: 0 },
            { x: 10, y: 4, vx: 0, vy: 0 },
        ];
        const force = createCommunityClusterForce(nodes, ['a', 'a'], 0.5, 2);

        force(0.5);

        // Centroid (5, 2); pull = 0.5 × 0.5 = 0.25.
        expect(nodes[0]).toMatchObject({ vx: 1.25, vy: 0.5 });
        expect(nodes[1]).toMatchObject({ vx: -1.25, vy: -0.5 });
    });

    it('pulls along z in three dimensions', () => {
        const nodes: ForceLayoutNode[] = [
            { x: 0, y: 0, z: 0, vx: 0, vy: 0, vz: 0 },
            { x: 0, y: 0, z: 8, vx: 0, vy: 0, vz: 0 },
        ];
        const force = createCommunityClusterForce(nodes, ['a', 'a'], 1, 3);

        force(0.25);

        expect(nodes[0].vz).toBe(1);
        expect(nodes[1].vz).toBe(-1);
    });

    it('leaves nodes without a community and single-node communities where they are', () => {
        const nodes: ForceLayoutNode[] = [
            { x: 0, y: 0, vx: 0, vy: 0 },
            { x: 10, y: 0, vx: 0, vy: 0 },
            { x: 100, y: 100, vx: 0, vy: 0 },
            { x: -50, y: 30, vx: 0, vy: 0 },
        ];
        const force = createCommunityClusterForce(nodes, ['a', 'a', null, 'b'], 1, 2);

        force(1);

        expect(nodes[2]).toMatchObject({ vx: 0, vy: 0 });
        expect(nodes[3]).toMatchObject({ vx: 0, vy: 0 });
    });

    it('pulls each community toward its own centroid, not a shared one', () => {
        const nodes: ForceLayoutNode[] = [
            { x: 0, y: 0, vx: 0, vy: 0 },
            { x: 2, y: 0, vx: 0, vy: 0 },
            { x: 100, y: 0, vx: 0, vy: 0 },
            { x: 104, y: 0, vx: 0, vy: 0 },
        ];
        const force = createCommunityClusterForce(nodes, ['a', 'a', 'b', 'b'], 1, 2);

        force(1);

        expect(nodes.map((node) => node.vx)).toEqual([1, -1, 2, -2]);
    });
});

describe('getCommunityLinkStrengths', () => {
    // Node degrees below: 0 → 1, 1 → 2, 2 → 2, 3 → 1, so d3's default strength is 1 / min(degrees).
    const links = [
        { sourceIndex: 0, targetIndex: 1 },
        { sourceIndex: 1, targetIndex: 2 },
        { sourceIndex: 2, targetIndex: 3 },
    ];

    it.each<[string, ReadonlyArray<string | null>, number[]]>([
        ['same community keeps the default', ['a', 'a', 'a', 'a'], [1, 0.5, 1]],
        ['different communities are weakened', ['a', 'a', 'b', 'b'], [1, 0.05, 1]],
        ['a node without a community keeps the default', ['a', 'a', 'b', null], [1, 0.05, 1]],
        ['no communities at all keep the default', [null, null, null, null], [1, 0.5, 1]],
    ])('%s', (_label, communityIds, expected) => {
        const strengths = getCommunityLinkStrengths(links, communityIds, 0.1);

        expect(strengths).toEqual(expected.map((strength) => expect.closeTo(strength)));
    });
});

describe('createLayoutSimulation', () => {
    // Six nodes on a ring, alternating communities a/b; every link joins a node of `a` to one of `b`.
    const communityIds = ['a', 'b', 'a', 'b', 'a', 'b'];
    const links = [
        { sourceIndex: 0, targetIndex: 1 },
        { sourceIndex: 2, targetIndex: 3 },
        { sourceIndex: 4, targetIndex: 5 },
    ];

    function settledLayout(groupByCommunity: boolean): ForceLayoutNode[] {
        const nodes: ForceLayoutNode[] = communityIds.map((_, index) => ({
            x: 80 * Math.cos((index * Math.PI) / 3),
            y: 80 * Math.sin((index * Math.PI) / 3),
        }));
        const nodeRadii = communityIds.map(() => 4);
        const simulation = createLayoutSimulation(
            d3,
            nodes,
            { links, communityIds, nodeRadii },
            { dimensions: 2, groupByCommunity }
        );
        simulation.stop();
        simulation.tick(300);
        return nodes;
    }

    function distance(nodes: ForceLayoutNode[], first: number, second: number): number {
        return Math.hypot(
            (nodes[first].x ?? 0) - (nodes[second].x ?? 0),
            (nodes[first].y ?? 0) - (nodes[second].y ?? 0)
        );
    }

    function meanSameCommunityDistance(nodes: ForceLayoutNode[]): number {
        const pairs = [
            [0, 2],
            [0, 4],
            [2, 4],
            [1, 3],
            [1, 5],
            [3, 5],
        ];
        return pairs.reduce((sum, [first, second]) => sum + distance(nodes, first, second), 0) / pairs.length;
    }

    // Settled, the grouped layout keeps a community about 75 across against about 370 ungrouped.
    it('gathers each community together while grouping, even when links tie it to the other one', () => {
        const grouped = meanSameCommunityDistance(settledLayout(true));
        const ungrouped = meanSameCommunityDistance(settledLayout(false));

        expect(grouped).toBeLessThan(ungrouped / 2);
    });

    it('lays out by links alone while not grouping, leaving the members of a community apart', () => {
        const nodes = settledLayout(false);
        const meanLinkedDistance =
            links.reduce((sum, link) => sum + distance(nodes, link.sourceIndex, link.targetIndex), 0) / links.length;

        expect(meanLinkedDistance).toBeLessThan(meanSameCommunityDistance(nodes));
    });

    // Linked, nearly on top of each other: without collision the link and repulsion settle them about 46 apart,
    // which would draw a node of radius 50 over one of radius 10.
    it.each<[string, 2 | 3]>([
        ['in 2D', 2],
        ['in 3D', 3],
    ])('keeps every node its own radius plus padding clear of the others %s', (_label, dimensions) => {
        const nodes: ForceLayoutNode[] = [
            { x: 0, y: 0, z: dimensions === 3 ? 0 : undefined },
            { x: 1, y: 0.5, z: dimensions === 3 ? 0.3 : undefined },
        ];
        const simulation = createLayoutSimulation(
            d3,
            nodes,
            { links: [{ sourceIndex: 0, targetIndex: 1 }], communityIds: [null, null], nodeRadii: [50, 10] },
            { dimensions, groupByCommunity: false }
        );
        simulation.stop();
        simulation.tick(300);

        const separation = Math.hypot(
            (nodes[0].x ?? 0) - (nodes[1].x ?? 0),
            (nodes[0].y ?? 0) - (nodes[1].y ?? 0),
            (nodes[0].z ?? 0) - (nodes[1].z ?? 0)
        );
        // 50 + 2 padding around the large node, 10 + 2 around the small one.
        expect(separation).toBeGreaterThanOrEqual(63.9);
    });
});

describe('getLayoutStartPositions', () => {
    type Position = { x: number; y: number; z: number };
    // A fixed random draw of 0.75 lands at (0.75 − 0.5) × INITIAL_LAYOUT_SPREAD = 50 on every axis.
    const reseeded = { x: 50, y: 50, z: 50 };

    it.each<[string, Position[], boolean, Array<{ x: number; y: number; z: number | undefined }>]>([
        ['new data in 3D starts over in the cube', [{ x: 7, y: -9, z: 0 }], true, [reseeded]],
        [
            'a switch from 2D to 3D starts over in x and y too, not only in depth',
            [
                { x: 30, y: -40, z: 0 },
                { x: -12, y: 8, z: 0 },
            ],
            true,
            [reseeded, reseeded],
        ],
        [
            'a restart within 3D keeps the laid-out positions',
            [
                { x: 30, y: -40, z: 12.5 },
                { x: -12, y: 8, z: -3 },
            ],
            true,
            [
                { x: 30, y: -40, z: 12.5 },
                { x: -12, y: 8, z: -3 },
            ],
        ],
        [
            'a restart within 3D with one node still at z = 0 keeps the laid-out positions',
            [
                { x: 30, y: -40, z: 0 },
                { x: -12, y: 8, z: 7 },
            ],
            true,
            [
                { x: 30, y: -40, z: 0 },
                { x: -12, y: 8, z: 7 },
            ],
        ],
        [
            '2D, including a switch from 3D, keeps x and y and has no depth',
            [{ x: 30, y: -40, z: 0 }],
            false,
            [{ x: 30, y: -40, z: undefined }],
        ],
    ])('%s', (_label, nodes, is3D, expected) => {
        expect(getLayoutStartPositions(nodes, is3D, () => 0.75)).toEqual(expected);
    });
});

describe('getCommunityColor', () => {
    it('draws nodes without a community in the neutral color', () => {
        expect(getCommunityColor(null)).toEqual(NO_COMMUNITY_COLOR);
    });

    it('gives sequential community ids clearly different colors', () => {
        const colors = ['1', '2', '3', '4'].map(getCommunityColor);

        for (let first = 0; first < colors.length; first++) {
            for (let second = first + 1; second < colors.length; second++) {
                expect(colorDistance(colors[first], colors[second])).toBeGreaterThan(0.3);
            }
        }
    });

    it('always produces a valid RGB color', () => {
        for (const communityId of MANY_COMMUNITY_IDS) {
            for (const channel of getCommunityColor(communityId)) {
                expect(channel).toBeGreaterThanOrEqual(0);
                expect(channel).toBeLessThanOrEqual(1);
            }
        }
    });

    it('never looks like the search highlight, in 2D or in brightened 3D', () => {
        const brightenedHighlight = HIGHLIGHT_COLOR.map((channel) =>
            Math.min(1, channel * NODE_3D_BRIGHTNESS)
        ) as ColorTuple;

        for (const communityId of MANY_COMMUNITY_IDS) {
            const color = getCommunityColor(communityId);
            const brightened = color.map((channel) => Math.min(1, channel * NODE_3D_BRIGHTNESS)) as ColorTuple;

            expect(colorDistance(color, HIGHLIGHT_COLOR)).toBeGreaterThan(0.4);
            expect(colorDistance(brightened, brightenedHighlight)).toBeGreaterThan(0.15);
        }
    });
});
