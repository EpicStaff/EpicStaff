import { byId, LayoutGraph } from './layout-graph';

/**
 * Layers of one component: longest path from the sources on the DAG left when the
 * back edges are reversed, then tightening: a node whose every successor
 * is more than one layer away moves right to the nearest successor's layer − 1 (descending layer
 * order, so successors are final first). Triggers never leave layer 0. No layer ends up empty:
 * the longest path's critical chain has a successor exactly one layer on at every step, so none
 * of its nodes moves.
 * Upgrade path: network simplex (Gansner) if long spans stay common.
 */
export function assignLayers(graph: LayoutGraph, componentIds: string[], backEdges: Set<string>): Map<string, number> {
    const members = new Set(componentIds);
    const successors = new Map<string, string[]>(componentIds.map((id) => [id, []]));
    const inDegree = new Map<string, number>(componentIds.map((id) => [id, 0]));
    for (const edge of graph.edges) {
        if (!members.has(edge.source) || !members.has(edge.target)) continue;
        const [from, to] = backEdges.has(edge.id) ? [edge.target, edge.source] : [edge.source, edge.target];
        successors.get(from)!.push(to);
        inDegree.set(to, inDegree.get(to)! + 1);
    }

    // Longest path, in topological order (Kahn).
    const layers = new Map<string, number>(componentIds.map((id) => [id, 0]));
    const remaining = new Map(inDegree);
    const queue = componentIds.filter((id) => remaining.get(id) === 0).sort(byId);
    for (let index = 0; index < queue.length; index++) {
        const id = queue[index];
        for (const successor of successors.get(id)!) {
            layers.set(successor, Math.max(layers.get(successor)!, layers.get(id)! + 1));
            remaining.set(successor, remaining.get(successor)! - 1);
            if (remaining.get(successor) === 0) queue.push(successor);
        }
    }

    const byLayerDescending = [...componentIds].sort((a, b) => layers.get(b)! - layers.get(a)! || byId(a, b));
    for (const id of byLayerDescending) {
        if (graph.nodes.get(id)!.isTrigger) continue;
        const next = successors.get(id)!;
        if (next.length === 0) continue;
        const nearest = Math.min(...next.map((successor) => layers.get(successor)!));
        if (nearest - 1 > layers.get(id)!) layers.set(id, nearest - 1);
    }
    return layers;
}
