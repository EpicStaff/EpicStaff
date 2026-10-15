import { WIRE_CLEARANCE } from '../routing/obstacles';
import { LayoutEdge } from './layout-graph';
import { LayeredGraph } from './long-edges';

/**
 * Node tops by the priority method. Each layer starts as a stack; then sweeps down,
 * up, down, up, down move every node, highest priority first, as close as it can get to the
 * median of the ports it is wired to in the layer just placed (a straight wire when it gets
 * there). A node may push lower-priority neighbours along, keeping the gaps; an equal or higher
 * one stops it. Tops sit on the 20-px grid unless being off it makes a wire straight, or puts the
 * input port on the median of the feeding ports. Children straight on consecutive rows of one
 * table may touch.
 *
 * Priority: nodes fed straight from a table row (those of the table with more row wires first),
 * then by incident edges (a dummy counts its two), then rank. Dummies do not rank first: a long
 * edge only reserves a slot (the router finds its own corridor), and letting it outrank a table's
 * input alignment bends the flow-8 fixture (CDT#6 off Py#3).
 */

const GRID = 20;
// As dense as the wires allow: one wire fits between two stacked nodes,
// WIRE_CLEARANCE from each; on the grid that is a pitch of height + 20. A dummy is a
// long edge's wire: next to a node it keeps the clearance plus a lane (so a riser leaving that node
// has a row of its own beside it), and one lane (10) from another dummy. On the seeded corpus the
// bare clearance next to a dummy gives more crossings (342 against 335).
const REAL_GAP = 2 * WIRE_CLEARANCE;
const DUMMY_REAL_GAP = 2 * WIRE_CLEARANCE;
const DUMMY_GAP = 10;
const EPSILON = 1e-6;
const SWEEPS: ('down' | 'up')[] = ['down', 'up', 'down', 'up', 'down'];
const MAX_LAYER_PASSES = 4;
// Priority bands, far apart so a lower band never adds up to the next: degrees stay below 1000.
const ROW_CHILD_TIER = 1_000_000;
const TABLE_RANK_STEP = 1000;
// An input port this close to another wire's output row in the layer before reads as its continuation.
const FALSE_CONTINUATION_TOLERANCE = 1;

const snapUp = (value: number): number => Math.ceil(value / GRID - EPSILON) * GRID;
const snapDown = (value: number): number => Math.floor(value / GRID + EPSILON) * GRID;
const onGrid = (value: number): boolean => Math.abs(value - Math.round(value / GRID) * GRID) < EPSILON;
const same = (first: number, second: number): boolean => Math.abs(first - second) < EPSILON;

function median(values: number[]): number {
    const sorted = [...values].sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);
    return sorted.length % 2 === 1 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

export function assignTops(layered: LayeredGraph, order: string[][], startY: number): Map<string, number> {
    return new TopAssignment(layered, order).run(startY);
}

class TopAssignment {
    private readonly tops = new Map<string, number>();
    private readonly incoming = new Map<string, LayoutEdge[]>();
    private readonly outgoing = new Map<string, LayoutEdge[]>();
    private readonly backIncoming = new Set<string>();
    private readonly priority = new Map<string, number>();
    private readonly dummyChains = new Map<string, string[]>(); // long edge id → its dummies, left to right
    private readonly gapsBelow = new Map<string, number>(); // planned gap to the next node down the layer
    private readonly positionInLayer = new Map<string, number>();

    constructor(
        private readonly layered: LayeredGraph,
        private readonly order: string[][]
    ) {
        for (const id of layered.nodes.keys()) {
            this.incoming.set(id, []);
            this.outgoing.set(id, []);
        }
        for (const edge of layered.edges) {
            this.outgoing.get(edge.source)!.push(edge);
            this.incoming.get(edge.target)!.push(edge);
        }
        const backDegree = new Map<string, number>();
        for (const edge of layered.backEdges) {
            this.backIncoming.add(edge.target);
            for (const id of [edge.source, edge.target]) backDegree.set(id, (backDegree.get(id) ?? 0) + 1);
        }
        for (const [dummyId, edge] of layered.dummyOrigins) {
            if (!this.dummyChains.has(edge.id)) this.dummyChains.set(edge.id, []);
            this.dummyChains.get(edge.id)!.push(dummyId);
        }
        for (const chain of this.dummyChains.values()) {
            chain.sort((a, b) => layered.layerOf.get(a)! - layered.layerOf.get(b)!);
        }
        // One number sorts it all: fed straight from a table row first, the children of the table
        // with more row wires ahead (so they push a smaller table's child out of the way instead of
        // being stuck behind it), then the incident edges.
        const rowWires = (tableId: string): number =>
            this.outgoing.get(tableId)!.filter((edge) => edge.fromTableRow).length;
        for (const id of layered.nodes.keys()) {
            const rowEdges = this.isDummy(id) ? [] : this.incoming.get(id)!.filter((edge) => edge.fromTableRow);
            const tableRank = Math.max(0, ...rowEdges.map((edge) => rowWires(edge.source)));
            const degree = this.incoming.get(id)!.length + this.outgoing.get(id)!.length + (backDegree.get(id) ?? 0);
            this.priority.set(id, (rowEdges.length > 0 ? ROW_CHILD_TIER + tableRank * TABLE_RANK_STEP : 0) + degree);
        }
        for (const layer of order) {
            layer.forEach((id, position) => {
                this.positionInLayer.set(id, position);
                if (position + 1 < layer.length) this.gapsBelow.set(id, this.plannedGap(id, layer[position + 1]));
            });
        }
    }

    run(startY: number): Map<string, number> {
        for (const layer of this.order) this.stack(layer);
        for (const direction of SWEEPS) {
            const layerIndexes = this.order.map((_, index) => index);
            if (direction === 'up') layerIndexes.reverse();
            for (const layerIndex of layerIndexes) {
                const hasNeighbourLayer = direction === 'down' ? layerIndex > 0 : layerIndex < this.order.length - 1;
                if (!hasNeighbourLayer) continue;
                this.placeLayer(this.order[layerIndex], direction);
                this.legalize(this.order[layerIndex]);
            }
        }
        this.avoidFalseContinuations();
        // The topmost real node lands on startY's grid row; a multiple of 20 keeps every top's grid.
        const realTops = [...this.tops].filter(([id]) => !this.isDummy(id)).map(([, top]) => top);
        const shift = startY - snapDown(Math.min(...realTops));
        return new Map([...this.tops].map(([id, top]) => [id, top + shift]));
    }

    private isDummy(id: string): boolean {
        return this.layered.nodes.get(id)!.isDummy;
    }

    private height(id: string): number {
        return this.layered.nodes.get(id)!.height;
    }

    private bottom(id: string): number {
        return this.tops.get(id)! + this.height(id);
    }

    private baseGap(upper: string, lower: string): number {
        const dummies = Number(this.isDummy(upper)) + Number(this.isDummy(lower));
        return dummies === 0 ? REAL_GAP : dummies === 1 ? DUMMY_REAL_GAP : DUMMY_GAP;
    }

    // Consecutive rows (r, r + 1) of one table feeding `upper` and `lower`, the pairs allowed to touch.
    private rowPairs(upper: string, lower: string): [LayoutEdge, LayoutEdge][] {
        if (this.isDummy(upper) || this.isDummy(lower)) return [];
        const pairs: [LayoutEdge, LayoutEdge][] = [];
        for (const upperEdge of this.incoming.get(upper)!) {
            if (upperEdge.sourceRow === null) continue;
            for (const lowerEdge of this.incoming.get(lower)!) {
                if (lowerEdge.source === upperEdge.source && lowerEdge.sourceRow === upperEdge.sourceRow + 1) {
                    pairs.push([upperEdge, lowerEdge]);
                }
            }
        }
        return pairs;
    }

    // The gap placement plans with: 0 for row siblings, which may end up touching; legalize()
    // pushes them apart again unless both really are straight on their rows.
    private plannedGap(upper: string, lower: string): number {
        return this.rowPairs(upper, lower).length > 0 ? 0 : this.baseGap(upper, lower);
    }

    private isStraight(edge: LayoutEdge): boolean {
        return same(this.tops.get(edge.source)! + edge.sourceOffsetY, this.tops.get(edge.target)! + edge.targetOffsetY);
    }

    private legalGap(upper: string, lower: string): number {
        if (this.gapsBelow.get(upper) !== 0) return this.baseGap(upper, lower);
        const straightPair = this.rowPairs(upper, lower).some(
            ([upperEdge, lowerEdge]) => this.isStraight(upperEdge) && this.isStraight(lowerEdge)
        );
        return straightPair ? 0 : this.baseGap(upper, lower);
    }

    // Every layer as a stack with the full gaps, centred on 0, on the grid.
    private stack(layer: string[]): void {
        let top = 0;
        layer.forEach((id, index) => {
            if (index > 0) top = snapUp(this.bottom(layer[index - 1]) + this.baseGap(layer[index - 1], id));
            this.tops.set(id, top);
        });
        const extent = layer.length > 0 ? this.bottom(layer[layer.length - 1]) : 0;
        const shift = -snapDown(extent / 2);
        for (const id of layer) this.tops.set(id, this.tops.get(id)! + shift);
    }

    // The source port y of an edge, followed back through a dummy chain to the real source.
    private originPortY(edge: LayoutEdge): number {
        const origin = this.isDummy(edge.source) ? this.layered.dummyOrigins.get(edge.source)! : edge;
        return this.tops.get(origin.source)! + origin.sourceOffsetY;
    }

    // A dummy whose whole chain so far runs at its source port's y: the long wire is straight to it.
    private chainIsStraight(dummyId: string): boolean {
        const origin = this.layered.dummyOrigins.get(dummyId)!;
        const originY = this.tops.get(origin.source)! + origin.sourceOffsetY;
        const chain = this.dummyChains.get(origin.id)!;
        return chain.slice(0, chain.indexOf(dummyId) + 1).every((id) => same(this.tops.get(id)!, originY));
    }

    // A top may leave the 20-px grid only for a straight input wire or a port on the feeding median.
    private mayLeaveGrid(id: string, top: number): boolean {
        if (onGrid(top) || this.isDummy(id)) return true;
        const edges = this.incoming.get(id)!;
        const straight = edges.some(
            (edge) =>
                same(this.tops.get(edge.source)! + edge.sourceOffsetY, top + edge.targetOffsetY) &&
                (!this.isDummy(edge.source) || this.chainIsStraight(edge.source))
        );
        if (straight) return true;
        const inputOffsets = new Set(edges.map((edge) => edge.targetOffsetY));
        if (edges.length === 0 || inputOffsets.size > 1 || this.backIncoming.has(id)) return false;
        if (this.layered.nodes.get(id)!.hasSelfLoop) return false;
        return same(top + edges[0].targetOffsetY, median(edges.map((edge) => this.originPortY(edge))));
    }

    private candidateTops(id: string, direction: 'down' | 'up'): number[] {
        if (direction === 'down') {
            return this.incoming
                .get(id)!
                .map((edge) => this.tops.get(edge.source)! + edge.sourceOffsetY - edge.targetOffsetY);
        }
        return this.outgoing
            .get(id)!
            .map((edge) => this.tops.get(edge.target)! + edge.targetOffsetY - edge.sourceOffsetY);
    }

    /**
     * A long edge whose dummies had to leave its source port's y (the order put them below or
     * above other nodes) arrives from that side: the target may not sit back between, or the
     * router takes the straight line at the source's y instead and crosses what the detour avoided
     * (flow 8: CDT#2 Error → End under Py#7/Py#8). So the desired top is kept at or beyond the last
     * dummy; when detours pull both ways, the median stands.
     */
    private followDetours(id: string, desired: number): number {
        let lowest = -Infinity;
        let highest = Infinity;
        for (const edge of this.incoming.get(id)!) {
            if (!this.isDummy(edge.source)) continue;
            const dummyY = this.tops.get(edge.source)!;
            const originY = this.originPortY(edge);
            const alignedTop = dummyY - edge.targetOffsetY;
            if (dummyY > originY + EPSILON) lowest = Math.max(lowest, alignedTop);
            if (dummyY < originY - EPSILON) highest = Math.min(highest, alignedTop);
        }
        if (lowest > highest) return desired;
        return Math.min(Math.max(desired, lowest), highest);
    }

    // Passes repeat until nothing moves: a node an equal-priority neighbour stopped gets another
    // try once that neighbour has moved out of the way (row siblings settling onto their rows).
    private placeLayer(layer: string[], direction: 'down' | 'up'): void {
        const processing = layer
            .map((id, rank) => ({ id, rank }))
            .sort((a, b) => this.priority.get(b.id)! - this.priority.get(a.id)! || a.rank - b.rank);
        for (let pass = 0; pass < MAX_LAYER_PASSES; pass++) {
            let moved = false;
            for (const { id } of processing) {
                const candidates = this.candidateTops(id, direction);
                if (candidates.length === 0) continue;
                const index = this.positionInLayer.get(id)!;
                const [lowest, highest] = this.reach(layer, index);
                const desired = direction === 'down' ? this.followDetours(id, median(candidates)) : median(candidates);
                const target = this.chooseTop(id, desired, candidates, lowest, highest);
                if (target === null || same(target, this.tops.get(id)!)) continue;
                this.moveTo(layer, index, target);
                moved = true;
            }
            if (!moved) break;
        }
    }

    private chooseTop(
        id: string,
        desired: number,
        candidates: number[],
        lowest: number,
        highest: number
    ): number | null {
        const reachable = (top: number): boolean => top >= lowest - EPSILON && top <= highest + EPSILON;
        if (reachable(desired)) {
            if (this.mayLeaveGrid(id, desired)) return desired;
            const rounded = Math.round(desired / GRID) * GRID;
            const onGridTop = [rounded, rounded - GRID, rounded + GRID].find(reachable);
            if (onGridTop !== undefined) return onGridTop;
        }
        // Out of reach: the nearest candidate that is still a straight wire, else the grid row nearest.
        const straight = candidates
            .filter((top) => reachable(top) && this.mayLeaveGrid(id, top))
            .sort((a, b) => Math.abs(a - desired) - Math.abs(b - desired) || a - b);
        if (straight.length > 0) return straight[0];
        const clamped = Math.min(Math.max(desired, lowest), highest);
        const gridTop = clamped > desired - EPSILON ? snapUp(clamped) : snapDown(clamped);
        if (reachable(gridTop)) return gridTop;
        const otherGridTop = clamped > desired - EPSILON ? snapDown(clamped) : snapUp(clamped);
        return reachable(otherGridTop) ? otherGridTop : null;
    }

    /**
     * How far layer[index] can move: up to the nearest equal-or-higher-priority node each way,
     * pushing the lower-priority ones between as a chain (each pushed node lands on the grid).
     */
    private reach(layer: string[], index: number): [number, number] {
        const id = layer[index];
        const blocks = (other: string): boolean => {
            const difference = this.priority.get(other)! - this.priority.get(id)!;
            if (difference !== 0) return difference > 0;
            // Equal row children of one table would stop each other and both bend: the upper row wins.
            return !(this.positionInLayer.get(other)! > index && this.shareTable(id, other));
        };

        let highest = Infinity;
        let lowerBlocker = -1;
        for (let position = index + 1; position < layer.length; position++) {
            if (blocks(layer[position])) {
                lowerBlocker = position;
                break;
            }
        }
        if (lowerBlocker !== -1) {
            // The most a pushed node's top may become, from the blocker back up to layer[index + 1].
            let pressure = this.tops.get(layer[lowerBlocker])!;
            for (let position = lowerBlocker - 1; position > index; position--) {
                const node = layer[position];
                const maximumTop = pressure - this.gapsBelow.get(node)! - this.height(node);
                pressure = Math.max(this.tops.get(node)!, snapDown(maximumTop));
            }
            highest = pressure - this.gapsBelow.get(id)! - this.height(id);
        }

        let lowest = -Infinity;
        let upperBlocker = -1;
        for (let position = index - 1; position >= 0; position--) {
            if (blocks(layer[position])) {
                upperBlocker = position;
                break;
            }
        }
        if (upperBlocker !== -1) {
            // The least a pushed node's bottom may become, from the blocker down to layer[index - 1].
            let pressure = this.bottom(layer[upperBlocker]);
            for (let position = upperBlocker + 1; position < index; position++) {
                const node = layer[position];
                const minimumTop = pressure + this.gapsBelow.get(layer[position - 1])!;
                pressure = Math.min(this.tops.get(node)!, snapUp(minimumTop)) + this.height(node);
            }
            lowest = pressure + this.gapsBelow.get(layer[index - 1])!;
        }
        return [lowest, highest];
    }

    private shareTable(first: string, second: string): boolean {
        const tables = new Set(
            this.incoming
                .get(first)!
                .filter((edge) => edge.fromTableRow)
                .map((edge) => edge.source)
        );
        return this.incoming.get(second)!.some((edge) => edge.fromTableRow && tables.has(edge.source));
    }

    private moveTo(layer: string[], index: number, top: number): void {
        this.tops.set(layer[index], top);
        for (let position = index + 1; position < layer.length; position++) {
            const minimumTop = this.bottom(layer[position - 1]) + this.gapsBelow.get(layer[position - 1])!;
            if (this.tops.get(layer[position])! >= minimumTop - EPSILON) break;
            this.tops.set(layer[position], snapUp(minimumTop));
        }
        for (let position = index - 1; position >= 0; position--) {
            const maximumBottom = this.tops.get(layer[position + 1])! - this.gapsBelow.get(layer[position])!;
            if (this.bottom(layer[position]) <= maximumBottom + EPSILON) break;
            this.tops.set(layer[position], snapDown(maximumBottom - this.height(layer[position])));
        }
    }

    /**
     * A node whose input wire bends, with its input port on the row where another wire leaves the
     * layer before and bends in the same gap, gets the two wires drawn end to end on one line: it
     * reads as that other wire running into the node (flow 6: #1's wire into Audio#9). Such a node
     * moves one or two grid rows, towards its feeding median first, when its neighbours leave the
     * room and no input port lands on such a row again. Left to right, so each layer sees the
     * moves before it. Nodes with a straight wire, and tops off the grid, stay put.
     */
    private avoidFalseContinuations(): void {
        this.order.forEach((layer, layerIndex) => {
            if (layerIndex === 0) return;
            const inLayer = new Set(layer);
            const bentEdgesIn = this.layered.edges.filter((edge) => inLayer.has(edge.target) && !this.isStraight(edge));
            const clashes = (id: string, top: number): boolean => {
                const otherRows = bentEdgesIn
                    .filter((edge) => edge.target !== id)
                    .map((edge) => this.tops.get(edge.source)! + edge.sourceOffsetY);
                return this.incoming
                    .get(id)!
                    .some((edge) =>
                        otherRows.some((row) => Math.abs(top + edge.targetOffsetY - row) < FALSE_CONTINUATION_TOLERANCE)
                    );
            };
            // Not a node with a straight wire, nor one feeding a node centred off the grid on its
            // feeding ports (moving would take that node off its feeding median).
            const movable = (id: string): boolean =>
                !this.isDummy(id) &&
                onGrid(this.tops.get(id)!) &&
                ![...this.incoming.get(id)!, ...this.outgoing.get(id)!].some((edge) => this.isStraight(edge)) &&
                this.outgoing.get(id)!.every((edge) => onGrid(this.tops.get(edge.target)!));
            layer.forEach((id, position) => {
                const top = this.tops.get(id)!;
                if (this.incoming.get(id)!.length === 0 || !movable(id) || !clashes(id, top)) return;
                const desired = median(this.candidateTops(id, 'down'));
                const moves = [GRID, -GRID, 2 * GRID, -2 * GRID].sort(
                    (first, second) =>
                        Math.abs(top + first - desired) - Math.abs(top + second - desired) || second - first
                );
                for (const move of moves) {
                    const shifted = this.shiftInLayer(layer, position, top + move, movable);
                    if (!shifted || [...shifted].some(([other, otherTop]) => clashes(other, otherTop))) continue;
                    for (const [other, otherTop] of shifted) this.tops.set(other, otherTop);
                    break;
                }
            });
        });
    }

    // New tops for layer[position] at `top` and for the neighbours it pushes along (each to the
    // grid, keeping the gaps), or null when a neighbour that has to move may not.
    private shiftInLayer(
        layer: string[],
        position: number,
        top: number,
        movable: (id: string) => boolean
    ): Map<string, number> | null {
        const shifted = new Map([[layer[position], top]]);
        for (let index = position - 1; index >= 0; index--) {
            const [upper, below] = [layer[index], layer[index + 1]];
            const maximumTop = shifted.get(below)! - this.legalGap(upper, below) - this.height(upper);
            if (this.tops.get(upper)! <= maximumTop + EPSILON) break;
            if (!movable(upper)) return null;
            shifted.set(upper, snapDown(maximumTop));
        }
        for (let index = position + 1; index < layer.length; index++) {
            const [above, lower] = [layer[index - 1], layer[index]];
            const minimumTop =
                (shifted.get(above) ?? this.tops.get(above)!) + this.height(above) + this.legalGap(above, lower);
            if (this.tops.get(lower)! >= minimumTop - EPSILON) break;
            if (!movable(lower)) return null;
            shifted.set(lower, snapUp(minimumTop));
        }
        return shifted;
    }

    /**
     * After a layer is placed, top to bottom: a top left off the grid by an earlier sweep whose
     * wire is no longer straight goes to the grid, and row siblings planned to touch stay
     * touching only if both really are straight on their rows; any other pair gets its full gap.
     * Only ever moves nodes down, so every gap above stays intact.
     */
    private legalize(layer: string[]): void {
        layer.forEach((id, position) => {
            if (!this.mayLeaveGrid(id, this.tops.get(id)!)) this.tops.set(id, snapUp(this.tops.get(id)!));
            if (position === 0) return;
            const upper = layer[position - 1];
            if (this.tops.get(id)! >= this.bottom(upper) + this.legalGap(upper, id) - EPSILON) return;
            this.tops.set(id, snapUp(this.bottom(upper) + this.baseGap(upper, id)));
        });
    }
}
