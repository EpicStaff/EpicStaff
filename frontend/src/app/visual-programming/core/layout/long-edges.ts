import { byId, LayoutEdge, LayoutGraph, LayoutNode } from './layout-graph';

/**
 * One component with every forward edge between adjacent layers: an edge spanning
 * k > 1 layers becomes a chain through k − 1 dummies (`~d:<edgeId>:<n>`, 0×0, ports at offset 0).
 * Back edges get no dummies; the router takes them around, and here they only add lane demand.
 */
export interface LayeredGraph {
    nodes: Map<string, LayoutNode>; // real nodes of the component + dummies
    edges: LayoutEdge[]; // forward, adjacent layers only, sorted by id
    layerOf: Map<string, number>;
    backEdges: LayoutEdge[]; // original direction, sorted by id
    dummyOrigins: Map<string, LayoutEdge>; // dummy id → the long edge it carries
}

export function splitLongEdges(
    graph: LayoutGraph,
    componentIds: string[],
    layers: Map<string, number>,
    backEdges: Set<string>
): LayeredGraph {
    const members = new Set(componentIds);
    const layered: LayeredGraph = {
        nodes: new Map(componentIds.map((id) => [id, graph.nodes.get(id)!])),
        edges: [],
        layerOf: new Map(componentIds.map((id) => [id, layers.get(id)!])),
        backEdges: [],
        dummyOrigins: new Map(),
    };
    for (const edge of graph.edges) {
        if (!members.has(edge.source) || !members.has(edge.target)) continue;
        const span = layers.get(edge.target)! - layers.get(edge.source)!;
        if (backEdges.has(edge.id) || span < 1) {
            layered.backEdges.push(edge);
            continue;
        }
        if (span === 1) {
            layered.edges.push(edge);
            continue;
        }
        let previous = edge.source;
        let previousOffset = edge.sourceOffsetY;
        for (let step = 1; step < span; step++) {
            const dummyId = `~d:${edge.id}:${step}`;
            layered.nodes.set(dummyId, {
                id: dummyId,
                width: 0,
                height: 0,
                inputOffsetY: 0,
                isTrigger: false,
                isTable: false,
                isDummy: true,
                hasSelfLoop: false,
            });
            layered.layerOf.set(dummyId, layers.get(edge.source)! + step);
            layered.dummyOrigins.set(dummyId, edge);
            layered.edges.push({
                id: `~e:${edge.id}:${step - 1}`,
                source: previous,
                target: dummyId,
                sourceOffsetY: previousOffset,
                targetOffsetY: 0,
                fromTableRow: step === 1 && edge.fromTableRow,
                sourceRow: step === 1 ? edge.sourceRow : null,
            });
            previous = dummyId;
            previousOffset = 0;
        }
        layered.edges.push({
            id: `~e:${edge.id}:${span - 1}`,
            source: previous,
            target: edge.target,
            sourceOffsetY: 0,
            targetOffsetY: edge.targetOffsetY,
            fromTableRow: false,
            sourceRow: null,
        });
    }
    layered.edges.sort((a, b) => byId(a.id, b.id));
    return layered;
}
