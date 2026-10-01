import { LayeredGraph } from './long-edges';

/**
 * Node lefts per layer. Every layer is right-aligned to its widest node, so all its
 * output ports share one x. The gap after a layer is 100 (a DT/CDT layer too), plus a lane
 * allowance of 20 per lane its vertical wire runs need, capped at 160. Layer lefts are snapped up
 * to the 20-px grid. Real nodes only.
 */

const GRID = 20;
const HORIZONTAL_GAP = 100;
const DT_EXTRA_HORIZONTAL_GAP = 0;
const LANE_ALLOWANCE = 20;
const MAX_LANE_ALLOWANCE = 160;
// Wires whose end ports are further apart than this vertically need a riser in the gap.
const RISER_THRESHOLD = 40;

const snapUp = (value: number): number => Math.ceil(value / GRID - 1e-6) * GRID;

/**
 * Lanes a gap needs. Forward wires that bend: wires sharing a source port share one riser, and
 * so do wires sharing a target port (a trunk), so min(distinct source ports, distinct target
 * ports) of them. Back edges: one riser each right of their source and left of their target,
 * one per port there. Counting every bending wire instead would over-reserve fan-in/fan-out
 * gaps, which a trunk draws as one line.
 */
function lanesPerGap(layered: LayeredGraph, tops: Map<string, number>, layerCount: number): number[] {
    const sources = Array.from({ length: layerCount }, () => new Set<string>());
    const targets = Array.from({ length: layerCount }, () => new Set<string>());
    const backRisers = Array.from({ length: layerCount }, () => new Set<string>());
    for (const edge of layered.edges) {
        const sourceY = tops.get(edge.source)! + edge.sourceOffsetY;
        const targetY = tops.get(edge.target)! + edge.targetOffsetY;
        if (Math.abs(targetY - sourceY) <= RISER_THRESHOLD) continue;
        const gap = layered.layerOf.get(edge.source)!;
        sources[gap].add(`${edge.source}:${edge.sourceOffsetY}`);
        targets[gap].add(`${edge.target}:${edge.targetOffsetY}`);
    }
    for (const edge of layered.backEdges) {
        const sourceLayer = layered.layerOf.get(edge.source)!;
        const targetLayer = layered.layerOf.get(edge.target)!;
        if (sourceLayer < layerCount - 1) backRisers[sourceLayer].add(`out:${edge.source}:${edge.sourceOffsetY}`);
        if (targetLayer > 0) backRisers[targetLayer - 1].add(`in:${edge.target}:${edge.targetOffsetY}`);
    }
    return sources.map((_, gap) => Math.min(sources[gap].size, targets[gap].size) + backRisers[gap].size);
}

export function assignLefts(
    layered: LayeredGraph,
    order: string[][],
    tops: Map<string, number>,
    startX: number
): Map<string, number> {
    const lanes = lanesPerGap(layered, tops, order.length);
    const lefts = new Map<string, number>();
    let layerLeft = startX;
    order.forEach((layer, layerIndex) => {
        const realNodes = layer.map((id) => layered.nodes.get(id)!).filter((node) => !node.isDummy);
        const layerRight = layerLeft + Math.max(0, ...realNodes.map((node) => node.width));
        for (const node of realNodes) lefts.set(node.id, layerRight - node.width);
        const tableExtra = realNodes.some((node) => node.isTable) ? DT_EXTRA_HORIZONTAL_GAP : 0;
        const laneAllowance = Math.min(MAX_LANE_ALLOWANCE, LANE_ALLOWANCE * lanes[layerIndex]);
        layerLeft = snapUp(layerRight + HORIZONTAL_GAP + tableExtra + laneAllowance);
    });
    return lefts;
}
