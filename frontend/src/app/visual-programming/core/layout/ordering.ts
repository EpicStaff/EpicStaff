import { byId } from './layout-graph';
import { LayeredGraph } from './long-edges';

/**
 * Crossing minimisation. A port sits at `rank + offset / height` in its layer, so the
 * rows of a table keep their top-to-bottom order and a child of row 1 sorts above a child of row 2.
 * Sweeps alternate down and up; a node moves to the median of its neighbours' port positions
 * (a node fed by several rows lands at the median of those rows), then transpose swaps adjacent
 * pairs while that strictly removes crossings. The best order seen wins. Ties: previous rank, id.
 * Works on integer indices and typed arrays: this is the layout's hot loop.
 */

const MAX_SWEEPS = 24;
const SWEEPS_WITHOUT_IMPROVEMENT = 4;
// Keeps a port's fraction below 1, so it never reaches the next node's rank.
const MAX_PORT_FRACTION = 0.999;

function portFraction(offset: number, height: number): number {
    return Math.min(Math.max(offset / Math.max(height, 1), 0), MAX_PORT_FRACTION);
}

function median(values: number[]): number {
    values.sort((a, b) => a - b);
    const middle = Math.floor(values.length / 2);
    return values.length % 2 === 1 ? values[middle] : (values[middle - 1] + values[middle]) / 2;
}

// The layered graph as index arrays: node i, edge e from edgeSource[e] down to edgeTarget[e].
class IndexedLayers {
    readonly ids: string[]; // sorted, so an index comparison is the id tie-break
    readonly layerOf: Int32Array;
    readonly edgeSource: Int32Array;
    readonly edgeTarget: Int32Array;
    readonly sourceFraction: Float64Array;
    readonly targetFraction: Float64Array;
    readonly incoming: number[][]; // edge indices per node
    readonly outgoing: number[][];
    readonly edgesByGap: number[][]; // edge indices per gap (the upper layer's index)
    readonly rank: Int32Array;
    readonly layerCount: number;

    constructor(layered: LayeredGraph) {
        this.ids = [...layered.nodes.keys()].sort(byId);
        const indexOf = new Map(this.ids.map((id, index) => [id, index]));
        this.layerOf = Int32Array.from(this.ids, (id) => layered.layerOf.get(id)!);
        this.layerCount = this.ids.length === 0 ? 0 : Math.max(...this.layerOf) + 1;
        const edgeCount = layered.edges.length;
        this.edgeSource = new Int32Array(edgeCount);
        this.edgeTarget = new Int32Array(edgeCount);
        this.sourceFraction = new Float64Array(edgeCount);
        this.targetFraction = new Float64Array(edgeCount);
        this.incoming = this.ids.map(() => []);
        this.outgoing = this.ids.map(() => []);
        this.edgesByGap = Array.from({ length: this.layerCount }, () => []);
        layered.edges.forEach((edge, index) => {
            const source = indexOf.get(edge.source)!;
            const target = indexOf.get(edge.target)!;
            this.edgeSource[index] = source;
            this.edgeTarget[index] = target;
            this.sourceFraction[index] = portFraction(edge.sourceOffsetY, layered.nodes.get(edge.source)!.height);
            this.targetFraction[index] = portFraction(edge.targetOffsetY, layered.nodes.get(edge.target)!.height);
            this.outgoing[source].push(index);
            this.incoming[target].push(index);
            this.edgesByGap[this.layerOf[source]].push(index);
        });
        this.rank = new Int32Array(this.ids.length);
    }

    upperPosition(edge: number): number {
        return this.rank[this.edgeSource[edge]] + this.sourceFraction[edge];
    }

    lowerPosition(edge: number): number {
        return this.rank[this.edgeTarget[edge]] + this.targetFraction[edge];
    }

    setRanks(layer: number[]): void {
        for (let index = 0; index < layer.length; index++) this.rank[layer[index]] = index;
    }

    // Crossings between the edges of `first` and `second` when `first` sits directly above.
    pairCrossings(first: number, second: number): number {
        let count = 0;
        for (const firstEdge of this.incoming[first]) {
            const position = this.upperPosition(firstEdge);
            for (const secondEdge of this.incoming[second]) if (position > this.upperPosition(secondEdge)) count++;
        }
        for (const firstEdge of this.outgoing[first]) {
            const position = this.lowerPosition(firstEdge);
            for (const secondEdge of this.outgoing[second]) if (position > this.lowerPosition(secondEdge)) count++;
        }
        return count;
    }

    totalCrossings(): number {
        let count = 0;
        for (const edges of this.edgesByGap) {
            for (let first = 0; first < edges.length; first++) {
                const upper = this.upperPosition(edges[first]);
                const lower = this.lowerPosition(edges[first]);
                for (let second = first + 1; second < edges.length; second++) {
                    if ((upper - this.upperPosition(edges[second])) * (lower - this.lowerPosition(edges[second])) < 0) {
                        count++;
                    }
                }
            }
        }
        return count;
    }
}

export function orderLayers(layered: LayeredGraph): string[][] {
    const graph = new IndexedLayers(layered);
    const order: number[][] = Array.from({ length: graph.layerCount }, () => []);
    graph.ids.forEach((_, node) => order[graph.layerOf[node]].push(node));

    const sortLayer = (layerIndex: number, key: (node: number) => number): void => {
        const layer = order[layerIndex];
        const keys = new Map(layer.map((node) => [node, key(node)]));
        layer.sort((a, b) => keys.get(a)! - keys.get(b)! || graph.rank[a] - graph.rank[b] || a - b);
        graph.setRanks(layer);
    };
    const medianKey = (edges: number[], position: (edge: number) => number): number => median(edges.map(position));

    // Initial order: triggers first on layer 0, then a down pass by the median of the parents.
    // A node nobody in the layer above feeds goes last, by id, until an up sweep places it.
    if (graph.layerCount > 0) {
        sortLayer(0, (node) => (layered.nodes.get(graph.ids[node])!.isTrigger ? 0 : 1));
    }
    for (let layer = 1; layer < graph.layerCount; layer++) {
        sortLayer(layer, (node) =>
            graph.incoming[node].length > 0
                ? medianKey(graph.incoming[node], (edge) => graph.upperPosition(edge))
                : Number.MAX_SAFE_INTEGER
        );
    }

    const transpose = (): void => {
        let improved = true;
        while (improved) {
            improved = false;
            for (const layer of order) {
                for (let index = 0; index + 1 < layer.length; index++) {
                    const first = layer[index];
                    const second = layer[index + 1];
                    if (graph.pairCrossings(second, first) < graph.pairCrossings(first, second)) {
                        layer[index] = second;
                        layer[index + 1] = first;
                        graph.rank[second] = index;
                        graph.rank[first] = index + 1;
                        improved = true;
                    }
                }
            }
        }
    };

    transpose();
    let best = order.map((layer) => [...layer]);
    let bestCrossings = graph.totalCrossings();
    let sweepsWithoutImprovement = 0;
    for (let sweep = 0; sweep < MAX_SWEEPS && bestCrossings > 0; sweep++) {
        const down = sweep % 2 === 0;
        for (let step = 1; step < graph.layerCount; step++) {
            const layer = down ? step : graph.layerCount - 1 - step;
            sortLayer(layer, (node) => {
                const edges = down ? graph.incoming[node] : graph.outgoing[node];
                if (edges.length === 0) return graph.rank[node];
                return down
                    ? medianKey(edges, (edge) => graph.upperPosition(edge))
                    : medianKey(edges, (edge) => graph.lowerPosition(edge));
            });
        }
        transpose();
        const crossings = graph.totalCrossings();
        if (crossings < bestCrossings) {
            best = order.map((layer) => [...layer]);
            bestCrossings = crossings;
            sweepsWithoutImprovement = 0;
        } else if (++sweepsWithoutImprovement >= SWEEPS_WITHOUT_IMPROVEMENT) {
            break;
        }
    }
    return best.map((layer) => layer.map((node) => graph.ids[node]));
}

/** Crossings of the layered edges drawn between port positions `rank + offset / height`. */
export function countCrossings(layered: LayeredGraph, order: string[][]): number {
    const graph = new IndexedLayers(layered);
    const indexOf = new Map(graph.ids.map((id, index) => [id, index]));
    for (const layer of order) graph.setRanks(layer.map((id) => indexOf.get(id)!));
    return graph.totalCrossings();
}
