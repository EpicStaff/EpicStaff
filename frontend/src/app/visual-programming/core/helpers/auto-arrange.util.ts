import { IPoint } from '@foblex/2d';
import { NodeType } from '@shared/models';

import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';
import { snapToGrid } from './node-placement.utils';

// Horizontal gap between a layer's right edge and the next layer's left edge
const HORIZONTAL_GAP = 360;
// Extra horizontal gap added after a Decision-Table layer so fan-out arrows have room to untangle
const DT_EXTRA_HORIZONTAL_GAP = 100;
// Uniform vertical gap between every pair of sibling nodes
const SIBLING_GAP = 50;
// Extra padding added between branches that fan out from one parent (makes lanes readable)
const BRANCH_GAP = 70;
// Where the canvas layout begins
const CANVAS_START_X = 100;
const CANVAS_START_Y = 100;
// Margin below the connected layout before placing disconnected / NOTE nodes
const DISCONNECTED_MARGIN = 250;
// Vertical gap between stacked connected components
const COMPONENT_VERTICAL_GAP = 500;

/**
 * Returns a numeric sort key for a port role so that ownedChildren are placed
 * in the same top-to-bottom order as the parent's output ports.
 * For Decision-Table condition ports the key equals the condition index (1-based);
 * for all other ports returns 0 (stable — no reordering).
 */
function getPortSortKey(portRole: string): number {
    if (portRole.startsWith('decision-out-')) {
        const suffix = portRole.slice('decision-out-'.length);
        const m = suffix.match(/condition-(\d+)$/i);
        if (m) return parseInt(m[1], 10);
        return 9_999;
    }
    if (portRole === 'decision-default') return 100_000;
    if (portRole === 'decision-error') return 100_001;
    return 0;
}

function nHeight(n: NodeModel | undefined): number {
    return n?.size.height ?? 60;
}

function nWidth(n: NodeModel | undefined): number {
    return n?.size.width ?? 330;
}

/**
 * Uses Union-Find to group non-note nodes by their connections (edges treated as
 * undirected). Returns one array of node IDs per connected component.
 */
function buildUndirectedComponents(nodes: NodeModel[], connections: ConnectionModel[]): string[][] {
    const parent = new Map<string, string>();
    const rank = new Map<string, number>();

    const find = (id: string): string => {
        if (parent.get(id) !== id) parent.set(id, find(parent.get(id)!));
        return parent.get(id)!;
    };

    const union = (a: string, b: string): void => {
        const ra = find(a);
        const rb = find(b);
        if (ra === rb) return;
        if ((rank.get(ra) ?? 0) < (rank.get(rb) ?? 0)) {
            parent.set(ra, rb);
        } else if ((rank.get(ra) ?? 0) > (rank.get(rb) ?? 0)) {
            parent.set(rb, ra);
        } else {
            parent.set(rb, ra);
            rank.set(ra, (rank.get(ra) ?? 0) + 1);
        }
    };

    for (const node of nodes) {
        parent.set(node.id, node.id);
        rank.set(node.id, 0);
    }

    const nodeIds = new Set(nodes.map((n) => n.id));
    for (const conn of connections) {
        if (nodeIds.has(conn.sourceNodeId) && nodeIds.has(conn.targetNodeId)) {
            union(conn.sourceNodeId, conn.targetNodeId);
        }
    }

    const groups = new Map<string, string[]>();
    for (const node of nodes) {
        const root = find(node.id);
        if (!groups.has(root)) groups.set(root, []);
        groups.get(root)!.push(node.id);
    }
    return [...groups.values()];
}

/**
 * Lays out a single connected component using the 3-pass algorithm.
 * Returns the computed positions and the bottomY (max y + node height) for stacking.
 */
function layoutSingleComponent(
    componentNodeIds: string[],
    nodeMap: Map<string, NodeModel>,
    connections: ConnectionModel[],
    startY: number
): { positions: Map<string, IPoint>; bottomY: number } {
    const componentSet = new Set(componentNodeIds);
    const componentNodes = componentNodeIds.map((id) => nodeMap.get(id)!);

    // ── Pass 0: build edge maps ─────────────────────────────────────────────
    const outEdges = new Map<string, string[]>();
    const inDegree = new Map<string, number>();
    for (const node of componentNodes) {
        outEdges.set(node.id, []);
        inDegree.set(node.id, 0);
    }
    for (const conn of connections) {
        if (!componentSet.has(conn.sourceNodeId) || !componentSet.has(conn.targetNodeId)) continue;
        outEdges.get(conn.sourceNodeId)!.push(conn.targetNodeId);
        inDegree.set(conn.targetNodeId, (inDegree.get(conn.targetNodeId) ?? 0) + 1);
    }

    // Prefer explicit trigger types; fall back to zero-in-degree; then all nodes.
    const triggerTypes = new Set<string>([NodeType.START, NodeType.WEBHOOK_TRIGGER, NodeType.TELEGRAM_TRIGGER]);
    let rootIds = componentNodes.filter((n) => triggerTypes.has(n.type)).map((n) => n.id);
    if (rootIds.length === 0) {
        rootIds = componentNodes.filter((n) => (inDegree.get(n.id) ?? 0) === 0).map((n) => n.id);
    }
    if (rootIds.length === 0) {
        rootIds = componentNodes.map((n) => n.id);
    }

    // ── Pass 1: cycle-safe BFS layer assignment ─────────────────────────────
    // First-seen layer wins; back-edges / cross-edges are silently skipped.
    const layerMap = new Map<string, number>();
    const bfsOrder: string[] = [];
    for (const id of rootIds) {
        if (!layerMap.has(id)) {
            layerMap.set(id, 0);
            bfsOrder.push(id);
        }
    }
    for (let qi = 0; qi < bfsOrder.length; qi++) {
        const nodeId = bfsOrder[qi];
        const layer = layerMap.get(nodeId)!;
        for (const tgt of outEdges.get(nodeId) ?? []) {
            if (!layerMap.has(tgt)) {
                layerMap.set(tgt, layer + 1);
                bfsOrder.push(tgt);
            }
        }
    }

    // Group nodes by layer; collect disconnected nodes separately.
    const layerGroups = new Map<number, string[]>();
    const disconnected: string[] = [];
    for (const node of componentNodes) {
        const layer = layerMap.get(node.id);
        if (layer === undefined) {
            disconnected.push(node.id);
        } else {
            if (!layerGroups.has(layer)) layerGroups.set(layer, []);
            layerGroups.get(layer)!.push(node.id);
        }
    }

    const sortedLayers = [...layerGroups.keys()].sort((a, b) => a - b);

    // ── Build ownership children map ────────────────────────────────────────
    // A forward edge (srcLayer < tgtLayer) adds the target to allParents[target].
    // Only the FIRST such connection makes a node the "primary parent" — that
    // parent owns the child for lane-size computation and Y distribution.
    // Connection array order ≈ port order (how they were wired), so children are
    // ordered top-to-bottom in the same sequence as the source ports.
    const ownedChildren = new Map<string, string[]>(); // primary parent → children in port order
    const primaryParent = new Map<string, string>(); // child → owning parent id
    const allParents = new Map<string, string[]>(); // child → all parents (for merge centering)
    // Port role of the source connection for each child — used for crossing-free ordering
    const childSourcePortRole = new Map<string, string>();

    for (const id of layerMap.keys()) {
        ownedChildren.set(id, []);
        allParents.set(id, []);
    }

    for (const conn of connections) {
        if (!componentSet.has(conn.sourceNodeId) || !componentSet.has(conn.targetNodeId)) continue;
        const srcL = layerMap.get(conn.sourceNodeId);
        const tgtL = layerMap.get(conn.targetNodeId);
        if (srcL === undefined || tgtL === undefined || srcL >= tgtL) continue;

        allParents.get(conn.targetNodeId)?.push(conn.sourceNodeId);

        if (!primaryParent.has(conn.targetNodeId)) {
            primaryParent.set(conn.targetNodeId, conn.sourceNodeId);
            ownedChildren.get(conn.sourceNodeId)!.push(conn.targetNodeId);
            // Record the source port role so we can sort children in port order
            const sep = conn.sourcePortId.indexOf('_');
            if (sep !== -1) childSourcePortRole.set(conn.targetNodeId, conn.sourcePortId.slice(sep + 1));
        }
    }

    // Sort each parent's children by port order to prevent edge crossings.
    // For Decision-Table nodes this maps condition index → vertical position.
    for (const [, children] of ownedChildren) {
        if (children.length < 2) continue;
        children.sort(
            (a, b) =>
                getPortSortKey(childSourcePortRole.get(a) ?? '') - getPortSortKey(childSourcePortRole.get(b) ?? '')
        );
    }

    // ── Pass 2: bottom-up subtree span ─────────────────────────────────────
    // subtreeSpan[id] = the minimum vertical space (px) required to render the
    // node together with its entire owned subtree without overlapping.
    const subtreeSpan = new Map<string, number>();
    for (const nodeId of [...bfsOrder].reverse()) {
        const h = nHeight(nodeMap.get(nodeId));
        const children = ownedChildren.get(nodeId) ?? [];
        if (children.length === 0) {
            subtreeSpan.set(nodeId, h);
        } else {
            const childrenTotal =
                children.reduce((sum, cid) => sum + (subtreeSpan.get(cid) ?? 60), 0) +
                Math.max(0, children.length - 1) * (SIBLING_GAP + BRANCH_GAP);
            subtreeSpan.set(nodeId, Math.max(h, childrenTotal));
        }
    }

    // ── Pass 3: top-down Y assignment ──────────────────────────────────────
    // centerYMap stores the vertical centre of each node.
    const centerYMap = new Map<string, number>();

    // Layer-0 roots: stacked top-to-bottom, each allocated its full subtree span.
    {
        let topY = startY;
        for (const id of layerGroups.get(sortedLayers[0] ?? 0) ?? []) {
            const span = subtreeSpan.get(id) ?? nHeight(nodeMap.get(id));
            centerYMap.set(id, topY + span / 2);
            topY += span + SIBLING_GAP + BRANCH_GAP;
        }
    }

    // Subsequent layers: determine Y from parent(s).
    for (const layer of sortedLayers.slice(1)) {
        for (const nodeId of layerGroups.get(layer) ?? []) {
            const parents = allParents.get(nodeId) ?? [];
            const primary = primaryParent.get(nodeId);

            // Merge node: all parents already placed (guaranteed — parents are in earlier layers).
            if (parents.length > 1 && parents.every((p) => centerYMap.has(p))) {
                const avg = parents.reduce((sum, p) => sum + (centerYMap.get(p) ?? startY), 0) / parents.length;
                centerYMap.set(nodeId, avg);
                continue;
            }

            if (primary === undefined || !centerYMap.has(primary)) {
                // No primary parent placed yet — fallback, should not happen in acyclic graphs.
                centerYMap.set(nodeId, startY + nHeight(nodeMap.get(nodeId)) / 2);
                continue;
            }

            const parentCY = centerYMap.get(primary)!;
            const siblings = ownedChildren.get(primary) ?? [];

            if (siblings.length === 1) {
                // Only child: centre on parent.
                centerYMap.set(nodeId, parentCY);
            } else {
                // Multiple siblings: distribute using uniform gaps (same SIBLING_GAP + BRANCH_GAP
                // between every pair). This matches the subtreeSpan calculation in Pass 2 exactly,
                // ensuring equal vertical spacing everywhere.
                let effectiveTotalSpan = 0;
                for (let i = 0; i < siblings.length; i++) {
                    const span = subtreeSpan.get(siblings[i]) ?? nHeight(nodeMap.get(siblings[i]));
                    const gap = i < siblings.length - 1 ? SIBLING_GAP + BRANCH_GAP : 0;
                    effectiveTotalSpan += span + gap;
                }

                let topY = parentCY - effectiveTotalSpan / 2;
                let placed = false;
                for (let i = 0; i < siblings.length; i++) {
                    const sibId = siblings[i];
                    const span = subtreeSpan.get(sibId) ?? nHeight(nodeMap.get(sibId));
                    if (sibId === nodeId) {
                        centerYMap.set(nodeId, topY + span / 2);
                        placed = true;
                        break;
                    }
                    topY += span + SIBLING_GAP + BRANCH_GAP;
                }
                if (!placed) {
                    centerYMap.set(nodeId, parentCY);
                }
            }
        }
    }

    // ── Safety: shift all Y up so the topmost node starts at startY ──
    // The compact top-pair placement can push subtree children above 0 in deep graphs.
    {
        let minTopY = Infinity;
        for (const [nodeId, cy] of centerYMap) {
            minTopY = Math.min(minTopY, cy - nHeight(nodeMap.get(nodeId)) / 2);
        }
        if (minTopY < startY) {
            const shift = startY - minTopY;
            for (const [id, cy] of centerYMap) {
                centerYMap.set(id, cy + shift);
            }
        }
    }

    // ── X positions per layer ───────────────────────────────────────────────
    const layerX = new Map<number, number>();
    let currentX = CANVAS_START_X;
    for (const layer of sortedLayers) {
        layerX.set(layer, currentX);
        const ids = layerGroups.get(layer) ?? [];
        const maxW = ids.length > 0 ? Math.max(...ids.map((id) => nWidth(nodeMap.get(id)))) : 330;
        const hasDT = ids.some((id) => nodeMap.get(id)?.type === NodeType.TABLE);
        currentX += maxW + HORIZONTAL_GAP + (hasDT ? DT_EXTRA_HORIZONTAL_GAP : 0);
    }

    // ── Convert to top-left positions ───────────────────────────────────────
    // Snap the PORT Y (not the top-left) to the 20 px grid so that:
    //  • same-cy nodes share the same snapped port → straight horizontal arrows
    //  • different-cy nodes have port differences that are multiples of 20 px → clean grid-aligned steps
    const positions = new Map<string, IPoint>();
    for (const [nodeId, cy] of centerYMap) {
        const h = nHeight(nodeMap.get(nodeId));
        const layer = layerMap.get(nodeId) ?? 0;
        const x = layerX.get(layer) ?? CANVAS_START_X;
        const portY = snapToGrid(cy); // port snapped to grid
        positions.set(nodeId, { x: snapToGrid(x), y: portY - Math.round(h / 2) });
    }

    // ── Disconnected nodes within the component (BFS stragglers, e.g. from cycles) ──
    let maxOccupiedY = startY;
    for (const [nodeId, pos] of positions) {
        maxOccupiedY = Math.max(maxOccupiedY, pos.y + nHeight(nodeMap.get(nodeId)));
    }

    const disconnectedY = maxOccupiedY + DISCONNECTED_MARGIN;
    let disconnectedX = CANVAS_START_X;
    for (const nodeId of disconnected) {
        positions.set(nodeId, { x: snapToGrid(disconnectedX), y: disconnectedY });
        disconnectedX += nWidth(nodeMap.get(nodeId)) + HORIZONTAL_GAP;
    }

    // Compute final bottomY across all placed positions in this component
    let bottomY = startY;
    for (const [nodeId, pos] of positions) {
        bottomY = Math.max(bottomY, pos.y + nHeight(nodeMap.get(nodeId)));
    }

    return { positions, bottomY };
}

/**
 * Produces a left-to-right layered layout with branch-aware vertical spacing.
 *
 * Three passes:
 *   1. BFS — assign horizontal layers (columns), cycle-safe.
 *   2. Bottom-up — compute the minimum vertical span each node's owned subtree needs.
 *   3. Top-down — distribute children proportionally to their subtree spans;
 *      merge nodes (multiple parents) are centred on the average of parent positions.
 */
export function computeAutoArrangePositions(nodes: NodeModel[], connections: ConnectionModel[]): Map<string, IPoint> {
    const nodeMap = new Map<string, NodeModel>(nodes.map((n) => [n.id, n]));
    const nonNoteNodes = nodes.filter((n) => n.type !== NodeType.NOTE);

    // ── Build connected components (Union-Find, undirected) ────────────────
    const components = buildUndirectedComponents(nonNoteNodes, connections);

    // Separate multi-node components from truly isolated nodes (component size == 1)
    const multiNodeComponents = components.filter((c) => c.length >= 2);
    const isolatedNodes = components.filter((c) => c.length === 1).map((c) => c[0]);

    // ── Sort multi-node components ──────────────────────────────────────────
    // Trigger-containing components first, then by size descending, then by min node ID for stability.
    const triggerTypes = new Set<string>([NodeType.START, NodeType.WEBHOOK_TRIGGER, NodeType.TELEGRAM_TRIGGER]);
    multiNodeComponents.sort((a, b) => {
        const aHasTrigger = a.some((id) => triggerTypes.has(nodeMap.get(id)?.type ?? '')) ? 1 : 0;
        const bHasTrigger = b.some((id) => triggerTypes.has(nodeMap.get(id)?.type ?? '')) ? 1 : 0;
        if (bHasTrigger !== aHasTrigger) return bHasTrigger - aHasTrigger;
        if (b.length !== a.length) return b.length - a.length;
        const minA = [...a].sort()[0] ?? '';
        const minB = [...b].sort()[0] ?? '';
        return minA < minB ? -1 : minA > minB ? 1 : 0;
    });

    // ── Layout each multi-node component, stacking vertically ──────────────
    const positions = new Map<string, IPoint>();
    let currentY = CANVAS_START_Y;

    for (const componentNodeIds of multiNodeComponents) {
        const result = layoutSingleComponent(componentNodeIds, nodeMap, connections, currentY);
        for (const [id, pos] of result.positions) {
            positions.set(id, pos);
        }
        currentY = result.bottomY + COMPONENT_VERTICAL_GAP;
    }

    // ── Place isolated nodes horizontally at currentY ───────────────────────
    if (isolatedNodes.length > 0) {
        let isolatedX = CANVAS_START_X;
        for (const nodeId of isolatedNodes) {
            positions.set(nodeId, { x: snapToGrid(isolatedX), y: currentY });
            isolatedX += nWidth(nodeMap.get(nodeId)) + HORIZONTAL_GAP;
        }
    }

    return positions;
}
