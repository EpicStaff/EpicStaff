import { IPoint } from '@foblex/2d';

import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';
import { obstacleRect, Rect, routingObstacles } from '../routing/obstacles';
import { assignLefts } from './columns';
import { assignTops } from './coordinates';
import { findBackEdges } from './cycles';
import { assignLayers } from './layering';
import { buildLayoutGraph } from './layout-graph';
import { splitLongEdges } from './long-edges';
import { orderLayers } from './ordering';

/**
 * Auto-arrange: per connected component, back edges → layers → dummy chains → order →
 * tops → lefts. Components are stacked top to bottom 500 px apart; nodes with no connection go in
 * one row below them all. NOTE nodes are not in the result (they keep their position). Pure and
 * deterministic: the input order and the current positions don't matter, so arranging its own
 * output changes nothing.
 *
 * Pinned nodes (ones the user may not move) are not in the result either. The other nodes are
 * arranged as if the pinned ones were not there, then shifted right as one block, past every
 * pinned node the block's box would come within PINNED_NODE_CLEARANCE of. Right, because the
 * nodes that get pinned (trigger nodes) only feed others: their wires then run left to right.
 */

const CANVAS_START_X = 100;
const CANVAS_START_Y = 100;
const COMPONENT_VERTICAL_GAP = 500;
const ISOLATED_HORIZONTAL_GAP = 180;
const GRID = 20;
// The gap between two layers (columns.ts), kept between the arranged block and a pinned node.
const PINNED_NODE_CLEARANCE = 100;

const snapUp = (value: number): number => Math.ceil(value / GRID) * GRID;

export function computeLayout(
    nodes: NodeModel[],
    connections: ConnectionModel[],
    pinnedNodeIds: ReadonlySet<string> = new Set()
): Map<string, IPoint> {
    const pinned = nodes.filter((node) => pinnedNodeIds.has(node.id));
    if (pinned.length === 0) return layoutFromCanvasStart(nodes, connections);
    const movable = nodes.filter((node) => !pinnedNodeIds.has(node.id));
    const positions = layoutFromCanvasStart(movable, connections);
    const shift = shiftClearOfPinned(blockRect(movable, positions), [...routingObstacles(pinned).values()]);
    return new Map([...positions].map(([id, { x, y }]) => [id, { x: x + shift, y }]));
}

function layoutFromCanvasStart(nodes: NodeModel[], connections: ConnectionModel[]): Map<string, IPoint> {
    const { graph, components, isolated } = buildLayoutGraph(nodes, connections);
    const positions = new Map<string, IPoint>();
    let componentTop = CANVAS_START_Y;
    for (const componentIds of components) {
        const backEdges = findBackEdges(graph, componentIds);
        const layered = splitLongEdges(graph, componentIds, assignLayers(graph, componentIds, backEdges), backEdges);
        const order = orderLayers(layered);
        const tops = assignTops(layered, order, componentTop);
        const lefts = assignLefts(layered, order, tops, CANVAS_START_X);
        let bottom = componentTop;
        for (const [id, x] of lefts) {
            positions.set(id, { x, y: tops.get(id)! });
            bottom = Math.max(bottom, tops.get(id)! + graph.nodes.get(id)!.height);
        }
        componentTop = snapUp(bottom + COMPONENT_VERTICAL_GAP);
    }
    let isolatedLeft = CANVAS_START_X;
    for (const id of isolated) {
        positions.set(id, { x: isolatedLeft, y: componentTop });
        isolatedLeft = snapUp(isolatedLeft + graph.nodes.get(id)!.width + ISOLATED_HORIZONTAL_GAP);
    }
    return positions;
}

// The box around the arranged nodes, each padded as the router pads it; null when none was arranged.
function blockRect(nodes: NodeModel[], positions: Map<string, IPoint>): Rect | null {
    const rects = nodes.flatMap((node) => {
        const position = positions.get(node.id);
        return position ? [obstacleRect({ ...node, position })] : [];
    });
    if (rects.length === 0) return null;
    return {
        left: Math.min(...rects.map((rect) => rect.left)),
        top: Math.min(...rects.map((rect) => rect.top)),
        right: Math.max(...rects.map((rect) => rect.right)),
        bottom: Math.max(...rects.map((rect) => rect.bottom)),
    };
}

/**
 * The smallest rightward shift, on the grid, that keeps the block PINNED_NODE_CLEARANCE clear of
 * every pinned box. Each step clears at least one more pinned box for good, so it ends.
 */
function shiftClearOfPinned(block: Rect | null, pinnedRects: Rect[]): number {
    if (!block) return 0;
    let shift = 0;
    for (;;) {
        const shifted = { ...block, left: block.left + shift, right: block.right + shift };
        const blocking = pinnedRects.filter((rect) => comesWithinClearance(shifted, rect));
        if (blocking.length === 0) return shift;
        const blockingRight = Math.max(...blocking.map((rect) => rect.right));
        shift = snapUp(blockingRight + PINNED_NODE_CLEARANCE - block.left);
    }
}

function comesWithinClearance(first: Rect, second: Rect): boolean {
    return (
        first.left < second.right + PINNED_NODE_CLEARANCE &&
        second.left < first.right + PINNED_NODE_CLEARANCE &&
        first.top < second.bottom + PINNED_NODE_CLEARANCE &&
        second.top < first.bottom + PINNED_NODE_CLEARANCE
    );
}
