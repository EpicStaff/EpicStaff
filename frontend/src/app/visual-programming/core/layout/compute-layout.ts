import { IPoint } from '@foblex/2d';

import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';
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
 */

const CANVAS_START_X = 100;
const CANVAS_START_Y = 100;
const COMPONENT_VERTICAL_GAP = 500;
const ISOLATED_HORIZONTAL_GAP = 180;
const GRID = 20;

export function computeLayout(nodes: NodeModel[], connections: ConnectionModel[]): Map<string, IPoint> {
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
        componentTop = Math.ceil((bottom + COMPONENT_VERTICAL_GAP) / GRID) * GRID;
    }
    let isolatedLeft = CANVAS_START_X;
    for (const id of isolated) {
        positions.set(id, { x: isolatedLeft, y: componentTop });
        isolatedLeft = Math.ceil((isolatedLeft + graph.nodes.get(id)!.width + ISOLATED_HORIZONTAL_GAP) / GRID) * GRID;
    }
    return positions;
}
