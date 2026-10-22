import { findBackEdges } from '../cycles';
import { assignLayers } from '../layering';
import { buildLayoutGraph } from '../layout-graph';
import { LayeredGraph, splitLongEdges } from '../long-edges';
import { FlowFixture } from './builders';

/** Runs the layout pipeline (graph build, cycle detection, layering, long-edge splitting) on the fixture's first component. */
export function layeredComponent({ nodes, connections }: FlowFixture): LayeredGraph {
    const { graph, components } = buildLayoutGraph(nodes, connections);
    const backEdges = findBackEdges(graph, components[0]);
    return splitLongEdges(graph, components[0], assignLayers(graph, components[0], backEdges), backEdges);
}
