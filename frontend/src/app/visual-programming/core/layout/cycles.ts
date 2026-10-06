import { byId, LayoutEdge, LayoutGraph } from './layout-graph';

/**
 * Back edges of one component: a DFS marks every edge into a node still on its stack.
 * Reversing them leaves a DAG to layer. Roots are tried in order: triggers, then nodes nobody
 * feeds, then the rest by (out − in) descending (the likeliest entry of a pure cycle); ties by id.
 * Each node's children are visited in port order (the source port's offset, so table rows top to
 * bottom), then by edge id. An edge into a trigger always counts as a back edge, so no trigger is
 * ever layered right of another node.
 */
export function findBackEdges(graph: LayoutGraph, componentIds: string[]): Set<string> {
    const members = new Set(componentIds);
    const outgoing = new Map<string, LayoutEdge[]>(componentIds.map((id) => [id, []]));
    const inDegree = new Map<string, number>(componentIds.map((id) => [id, 0]));
    const backEdges = new Set<string>();
    for (const edge of graph.edges) {
        if (!members.has(edge.source) || !members.has(edge.target)) continue;
        if (graph.nodes.get(edge.target)!.isTrigger) {
            backEdges.add(edge.id);
            continue;
        }
        outgoing.get(edge.source)!.push(edge);
        inDegree.set(edge.target, inDegree.get(edge.target)! + 1);
    }
    for (const edges of outgoing.values()) {
        edges.sort((a, b) => a.sourceOffsetY - b.sourceOffsetY || byId(a.id, b.id));
    }

    const ids = [...componentIds].sort(byId);
    const isTrigger = (id: string): boolean => graph.nodes.get(id)!.isTrigger;
    const balance = (id: string): number => outgoing.get(id)!.length - inDegree.get(id)!;
    const roots = [
        ...ids.filter(isTrigger),
        ...ids.filter((id) => !isTrigger(id) && inDegree.get(id) === 0),
        ...ids
            .filter((id) => !isTrigger(id) && inDegree.get(id)! > 0)
            .sort((a, b) => balance(b) - balance(a) || byId(a, b)),
    ];

    const onStack = new Set<string>();
    const visited = new Set<string>();
    for (const root of roots) {
        if (visited.has(root)) continue;
        const stack: { id: string; next: number }[] = [{ id: root, next: 0 }];
        visited.add(root);
        onStack.add(root);
        while (stack.length > 0) {
            const frame = stack[stack.length - 1];
            const edges = outgoing.get(frame.id)!;
            if (frame.next === edges.length) {
                onStack.delete(frame.id);
                stack.pop();
                continue;
            }
            const edge = edges[frame.next++];
            if (onStack.has(edge.target)) {
                backEdges.add(edge.id);
            } else if (!visited.has(edge.target)) {
                visited.add(edge.target);
                onStack.add(edge.target);
                stack.push({ id: edge.target, next: 0 });
            }
        }
    }
    return backEdges;
}
