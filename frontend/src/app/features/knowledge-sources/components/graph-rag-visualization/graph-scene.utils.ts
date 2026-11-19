import type { Simulation } from 'd3-force-3d';

import {
    COMMUNITY_CLUSTER_STRENGTH,
    COMMUNITY_COLOR_LIGHTNESS,
    COMMUNITY_COLOR_SATURATION,
    COMMUNITY_EXCLUDED_HUE_END_DEGREES,
    COMMUNITY_EXCLUDED_HUE_START_DEGREES,
    COMMUNITY_HUE_STEP_DEGREES,
    INITIAL_LAYOUT_SPREAD,
    INTER_COMMUNITY_LINK_STRENGTH_FACTOR,
    NO_COMMUNITY_COLOR,
    SIMULATION_CHARGE_STRENGTH,
    SIMULATION_COLLISION_PADDING,
    SIMULATION_LINK_DISTANCE,
} from './graph-scene.constants';
import { ColorTuple, ForceLayoutNode } from './graph-scene.model';

type ForceModule = typeof import('d3-force-3d');

interface LayoutLink {
    sourceIndex: number;
    targetIndex: number;
}

/** Computes a stable index from a string — used for type-to-color mapping. */
export function stableHash(value: string): number {
    let hash = 0;
    for (let i = 0; i < value.length; i++) {
        hash = (hash << 5) - hash + value.charCodeAt(i);
        hash |= 0;
    }
    return Math.abs(hash);
}

/** Hex string to [r,g,b] in 0..1 range. */
export function hexToRgb(hex: string): ColorTuple {
    const num = parseInt(hex.slice(1), 16);
    return [(num >> 16) / 255, ((num >> 8) & 0xff) / 255, (num & 0xff) / 255];
}

/** The color a community is drawn in — always the same for the same id; neutral gray for no community. */
export function getCommunityColor(communityId: string | null): ColorTuple {
    if (communityId === null) return NO_COMMUNITY_COLOR;
    // Spread over the wheel minus the excluded band, then skip the band, so no community reads as a search match.
    const excludedWidth = COMMUNITY_EXCLUDED_HUE_END_DEGREES - COMMUNITY_EXCLUDED_HUE_START_DEGREES;
    const wheelHue = (stableHash(communityId) * COMMUNITY_HUE_STEP_DEGREES) % 360;
    const allowedHue = (wheelHue * (360 - excludedWidth)) / 360;
    const hue = allowedHue < COMMUNITY_EXCLUDED_HUE_START_DEGREES ? allowedHue : allowedHue + excludedWidth;
    return hslToRgb(hue, COMMUNITY_COLOR_SATURATION, COMMUNITY_COLOR_LIGHTNESS);
}

/**
 * Where each node starts when the layout (re)starts, indexed like `nodes`; `z` is undefined in 2D.
 * A 3D layout with every node at z = 0 — new data, or a switch from 2D — starts over from random positions in
 * the INITIAL_LAYOUT_SPREAD cube: a settled 2D layout is a stable minimum, and given only random depth it stays
 * a flat disc, so x and y are reseeded too. A restart within 3D keeps the laid-out positions; 2D keeps x and y.
 * `random` returns values in [0, 1), like `Math.random`.
 */
export function getLayoutStartPositions(
    nodes: ReadonlyArray<{ x: number; y: number; z: number }>,
    is3D: boolean,
    random: () => number = Math.random
): Array<{ x: number; y: number; z: number | undefined }> {
    if (!is3D) return nodes.map((node) => ({ x: node.x, y: node.y, z: undefined }));
    if (nodes.some((node) => node.z !== 0)) return nodes.map((node) => ({ x: node.x, y: node.y, z: node.z }));
    const randomCoordinate = (): number => (random() - 0.5) * INITIAL_LAYOUT_SPREAD;
    return nodes.map(() => ({ x: randomCoordinate(), y: randomCoordinate(), z: randomCoordinate() }));
}

/**
 * The force-directed layout of the graph: links, node repulsion, collision and centering, plus — when grouping
 * by community — the community cluster force and weaker links between communities. Starts running immediately.
 * `communityIds` and `nodeRadii` are indexed like `nodes`; a node keeps `nodeRadii[i] + COLLISION_PADDING`
 * clear of every other node.
 */
export function createLayoutSimulation<N extends ForceLayoutNode>(
    d3: ForceModule,
    nodes: N[],
    graph: {
        links: readonly LayoutLink[];
        communityIds: ReadonlyArray<string | null>;
        nodeRadii: readonly number[];
    },
    options: { dimensions: 2 | 3; groupByCommunity: boolean }
): Simulation<N> {
    const { links, communityIds, nodeRadii } = graph;
    const { dimensions, groupByCommunity } = options;
    const linkForce = d3.forceLink<N>(links.map((link) => ({ source: link.sourceIndex, target: link.targetIndex })));
    linkForce.distance(SIMULATION_LINK_DISTANCE);
    if (groupByCommunity) {
        const linkStrengths = getCommunityLinkStrengths(links, communityIds, INTER_COMMUNITY_LINK_STRENGTH_FACTOR);
        linkForce.strength((_link, linkIndex) => linkStrengths[linkIndex]);
    }

    const newSimulation = d3
        .forceSimulation(nodes, dimensions)
        .force('link', linkForce)
        .force('charge', d3.forceManyBody().strength(SIMULATION_CHARGE_STRENGTH))
        .force(
            'collide',
            d3.forceCollide<N>((_node, nodeIndex) => nodeRadii[nodeIndex] + SIMULATION_COLLISION_PADDING)
        )
        .force('center', d3.forceCenter(0, 0, dimensions === 3 ? 0 : undefined));
    if (groupByCommunity) {
        newSimulation.force(
            'community',
            createCommunityClusterForce(nodes, communityIds, COMMUNITY_CLUSTER_STRENGTH, dimensions)
        );
    }
    return newSimulation;
}

/**
 * A d3 force that pulls every node toward the current centroid of its community:
 * `velocity += (centroid − position) × strength × alpha`, per axis (z only in three dimensions).
 * Nodes without a community (`null`) and communities of a single node are left alone.
 */
export function createCommunityClusterForce(
    nodes: ForceLayoutNode[],
    communityIds: ReadonlyArray<string | null>,
    strength: number,
    dimensions: 2 | 3
): (alpha: number) => void {
    const membersByCommunity = new Map<string, number[]>();
    communityIds.forEach((communityId, nodeIndex) => {
        if (communityId === null) return;
        const members = membersByCommunity.get(communityId);
        if (members) {
            members.push(nodeIndex);
        } else {
            membersByCommunity.set(communityId, [nodeIndex]);
        }
    });
    const clusters = [...membersByCommunity.values()].filter((members) => members.length > 1);
    const includeDepth = dimensions === 3;

    return (alpha: number): void => {
        const pull = strength * alpha;
        for (const members of clusters) {
            let centroidX = 0;
            let centroidY = 0;
            let centroidZ = 0;
            for (const nodeIndex of members) {
                const node = nodes[nodeIndex];
                centroidX += node.x ?? 0;
                centroidY += node.y ?? 0;
                centroidZ += node.z ?? 0;
            }
            centroidX /= members.length;
            centroidY /= members.length;
            centroidZ /= members.length;

            for (const nodeIndex of members) {
                const node = nodes[nodeIndex];
                node.vx = (node.vx ?? 0) + (centroidX - (node.x ?? 0)) * pull;
                node.vy = (node.vy ?? 0) + (centroidY - (node.y ?? 0)) * pull;
                if (includeDepth) {
                    node.vz = (node.vz ?? 0) + (centroidZ - (node.z ?? 0)) * pull;
                }
            }
        }
    };
}

/**
 * Per-link strengths for d3's link force: d3's default `1 / min(degree(source), degree(target))`, multiplied by
 * `interCommunityFactor` for a link whose two ends belong to different communities. A link touching a node
 * without a community keeps the default, so such nodes stay attached to their neighbors.
 */
export function getCommunityLinkStrengths(
    links: readonly LayoutLink[],
    communityIds: ReadonlyArray<string | null>,
    interCommunityFactor: number
): number[] {
    const degrees = new Array<number>(communityIds.length).fill(0);
    for (const link of links) {
        degrees[link.sourceIndex]++;
        degrees[link.targetIndex]++;
    }
    return links.map((link) => {
        const defaultStrength = 1 / Math.min(degrees[link.sourceIndex], degrees[link.targetIndex]);
        const sourceCommunity = communityIds[link.sourceIndex];
        const targetCommunity = communityIds[link.targetIndex];
        const crossesCommunities =
            sourceCommunity !== null && targetCommunity !== null && sourceCommunity !== targetCommunity;
        return crossesCommunities ? defaultStrength * interCommunityFactor : defaultStrength;
    });
}

/** HSL (hue in degrees, saturation and lightness in 0..1) to [r,g,b] in 0..1 range. */
function hslToRgb(hue: number, saturation: number, lightness: number): ColorTuple {
    const amplitude = saturation * Math.min(lightness, 1 - lightness);
    const channel = (offset: number): number => {
        const position = (offset + hue / 30) % 12;
        return lightness - amplitude * Math.max(-1, Math.min(position - 3, 9 - position, 1));
    };
    return [channel(0), channel(8), channel(4)];
}
