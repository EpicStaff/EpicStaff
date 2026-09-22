import { IPoint } from '@foblex/2d';

import { NodeType } from '../enums/node-type';
import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';
import { getRowPortCenterYFromTop, resolveRowIndex, RowBasedTableNodeModel } from './cdt-row-snap.util';
import { snapToGrid } from './node-placement.utils';
import { CDT_INPUT_PORT_CENTER_Y_OFFSET, DT_INPUT_PORT_CENTER_Y_OFFSET } from './node-size.util';

// Horizontal gap between a layer's right edge and the next layer's left edge. Hard floor ~160px:
// getCollisionBounds pads 15px/side (20 for tables) + getNodeRect's ROUTING_PAD=15 more, plus
// isSourceExitSafe's SOURCE_EXIT_CLEARANCE=40 veto near the source's right edge — do not go lower.
const HORIZONTAL_GAP = 180;
// Extra horizontal gap added after a Decision-Table/Classification-Table layer so fan-out arrows
// have room to untangle
const DT_EXTRA_HORIZONTAL_GAP = 100;
// Per-gap allowance for edges that must run vertically through that column gap — see the counting
// loop before the X-position pass. Frozen (userAdjustedWaypoints) edges still occupy the corridor.
const EDGE_VERTICAL_DELTA_THRESHOLD_PX = 40;
const EDGE_GAP_ALLOWANCE_PX = 20;
const MAX_GAP_ALLOWANCE_PX = 80;
// Uniform vertical gap between every pair of sibling nodes. NOTE: this is below what the router
// can actually route through — getCollisionBounds + ROUTING_PAD consume ~30px per side, so no
// lane can be laid between two nodes only 50px apart. Not addressed by Step 4 (horizontal only).
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
 * in the same top-to-bottom order as the parent's output ports. When the parent is a
 * row-based table (plain DT or CDT), delegates to `resolveRowIndex` for the rendered row
 * order (routes/groups, then Default, then Error); falls through to the legacy rules otherwise.
 */
function getPortSortKey(portRole: string, parentNode?: NodeModel): number {
    if (parentNode?.type === NodeType.CLASSIFICATION_TABLE || parentNode?.type === NodeType.TABLE) {
        const rowIndex = resolveRowIndex(parentNode, portRole);
        if (rowIndex !== null) return rowIndex;
    }
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

// The port ID's slug (e.g. `decision-out-condition-1`) is normalized from the role
// (e.g. `decision-out-Condition 1`, see helpers.ts) — they are NOT the same string, so a port's
// real role must come from the source node's ports array, not from slicing the connection's id.
function resolveSourcePortRole(conn: ConnectionModel, nodeMap: Map<string, NodeModel>): string {
    const sourceNode = nodeMap.get(conn.sourceNodeId);
    const portRole = sourceNode?.ports?.find((p) => p.id === conn.sourcePortId)?.role;
    if (portRole !== undefined) return portRole;
    const sep = conn.sourcePortId.indexOf('_');
    return sep !== -1 ? conn.sourcePortId.slice(sep + 1) : '';
}

function nHeight(n: NodeModel | undefined): number {
    return n?.size.height ?? 60;
}

function nWidth(n: NodeModel | undefined): number {
    return n?.size.width ?? 330;
}

function isRowBasedTable(node: NodeModel | undefined): node is RowBasedTableNodeModel {
    return node?.type === NodeType.TABLE || node?.type === NodeType.CLASSIFICATION_TABLE;
}

// The offset getPortPosition actually draws an input port at, measured from the node's top edge.
// A row-based table's sits in its own wrapper near the top, every other node's at the box centre.
function inputPortOffset(node: NodeModel | undefined): number {
    if (!isRowBasedTable(node)) return nHeight(node) / 2;
    return node.type === NodeType.TABLE ? DT_INPUT_PORT_CENTER_Y_OFFSET : CDT_INPUT_PORT_CENTER_Y_OFFSET;
}

// A row-based table's input port sits near its top, not the box's vertical centre, so centring
// the box on the parent's port kinks the wire. Align the port instead.
function alignedChildCenterY(childNode: NodeModel | undefined, parentPortY: number): number {
    if (!isRowBasedTable(childNode)) return parentPortY;
    return parentPortY - inputPortOffset(childNode) + nHeight(childNode) / 2;
}

// The reference Y the alignment above used, re-read from the parent's final snapped position.
function finalParentCenterY(parentId: string, positions: Map<string, IPoint>, nodeMap: Map<string, NodeModel>) {
    const parentPos = positions.get(parentId);
    if (!parentPos || !nodeMap.has(parentId)) return null;
    return parentPos.y + nHeight(nodeMap.get(parentId)) / 2;
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
 * Aligns a row-based table's (DT or CDT) owned children to the rows feeding them (offset from
 * the table's own top). Only direct-child heights bound feasibility — descendants live in later
 * layers and can't collide with these siblings; the de-overlap pass below handles descendant
 * crowding instead.
 *
 * Per-child, not all-or-nothing: a child whose row can't be resolved, or whose row is too close
 * to a taller neighbour's row, is dropped from the returned offsets so the caller can fall back
 * it to normal sibling distribution — the rest of the table's children stay pinned. Returns null
 * only when nothing is left to pin.
 */
function tryAlignRowBasedChildrenToRows(
    tableId: string,
    tableNode: RowBasedTableNodeModel,
    children: string[],
    connections: ConnectionModel[],
    nodeMap: Map<string, NodeModel>
): { offsets: Map<string, number>; span: number } | null {
    const childOffsets = new Map<string, number>();

    for (const childId of children) {
        const rowOffsets: number[] = [];
        for (const conn of connections) {
            if (conn.sourceNodeId !== tableId || conn.targetNodeId !== childId) continue;
            const portRole = resolveSourcePortRole(conn, nodeMap);
            const rowIndex = resolveRowIndex(tableNode, portRole);
            if (rowIndex === null) continue;
            rowOffsets.push(getRowPortCenterYFromTop(0, rowIndex, tableNode.type));
        }
        if (rowOffsets.length === 0) continue;

        const meanCentreOffset = rowOffsets.reduce((sum, o) => sum + o, 0) / rowOffsets.length;
        const childHeight = nHeight(nodeMap.get(childId));
        const quantizedTopOffset = snapToGrid(meanCentreOffset - childHeight / 2);
        childOffsets.set(childId, quantizedTopOffset + childHeight / 2);
    }

    // Drop one member of each infeasible pair (preferring the taller node) until every remaining
    // pair clears the pitch check, instead of bailing out for the whole table.
    let ordered = [...childOffsets.keys()].sort((a, b) => childOffsets.get(a)! - childOffsets.get(b)!);
    let violationFound = true;
    while (violationFound) {
        violationFound = false;
        for (let i = 0; i < ordered.length - 1; i++) {
            const aId = ordered[i];
            const bId = ordered[i + 1];
            const heightA = nHeight(nodeMap.get(aId));
            const heightB = nHeight(nodeMap.get(bId));
            const gap = childOffsets.get(bId)! - childOffsets.get(aId)!;
            if (gap < (heightA + heightB) / 2) {
                const dropId = heightA >= heightB ? aId : bId;
                childOffsets.delete(dropId);
                ordered = ordered.filter((id) => id !== dropId);
                violationFound = true;
                break;
            }
        }
    }

    if (childOffsets.size === 0) return null;

    const tableHeight = nHeight(tableNode);
    let halfExtent = tableHeight / 2;
    for (const [childId, offset] of childOffsets) {
        const height = nHeight(nodeMap.get(childId));
        halfExtent = Math.max(halfExtent, Math.abs(offset - tableHeight / 2) + height / 2);
    }

    return { offsets: childOffsets, span: halfExtent * 2 };
}

// Reported when the de-overlap sweep finds a pinned (row-aligned) node overlapping its previous
// neighbour and cannot resolve it by pushing unpinned predecessors out of the way.
export interface PinnedOverlapDiagnostic {
    nodeId: string;
    layer: number;
    overlapPx: number;
}

// Shifts the contiguous run of unpinned nodes immediately before `beforeIndex` up by `amount`,
// stopping at a pinned boundary (which can't move) or the start of the list. Uniform shift
// preserves the block's internal spacing. Returns false (no mutation) if the shift would cross
// that boundary — i.e. the overlap genuinely can't be resolved by moving unpinned nodes.
function pushUnpinnedPredecessorsUp(
    ids: string[],
    beforeIndex: number,
    amount: number,
    pinnedNodeIds: Set<string>,
    centerYMap: Map<string, number>,
    nodeMap: Map<string, NodeModel>
): boolean {
    let boundary = -Infinity;
    let blockStart = 0;
    for (let i = beforeIndex; i >= 0; i--) {
        if (pinnedNodeIds.has(ids[i])) {
            boundary = centerYMap.get(ids[i])! + nHeight(nodeMap.get(ids[i])) / 2 + SIBLING_GAP;
            blockStart = i + 1;
            break;
        }
    }
    if (blockStart > beforeIndex) return false;

    const topId = ids[blockStart];
    const currentTop = centerYMap.get(topId)! - nHeight(nodeMap.get(topId)) / 2;
    if (currentTop - amount < boundary) return false;

    for (let i = blockStart; i <= beforeIndex; i++) {
        centerYMap.set(ids[i], centerYMap.get(ids[i])! - amount);
    }
    return true;
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
): { positions: Map<string, IPoint>; bottomY: number; diagnostics: PinnedOverlapDiagnostic[] } {
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

    // ── Pass 1b: classify genuine back edges (DFS, cycle detection) ────────
    // Only an edge to a node currently on the DFS stack is a real cycle edge; those stay
    // excluded from the rank repair below. Roots are visited first, matching BFS root choice.
    const backEdgeKeys = new Set<string>();
    {
        const color = new Map<string, 0 | 1 | 2>();
        for (const id of componentNodeIds) color.set(id, 0);
        for (const startId of [...rootIds, ...componentNodeIds]) {
            if (color.get(startId) !== 0) continue;
            const stack: { id: string; iter: number }[] = [{ id: startId, iter: 0 }];
            color.set(startId, 1);
            while (stack.length > 0) {
                const frame = stack[stack.length - 1];
                const children = outEdges.get(frame.id) ?? [];
                if (frame.iter < children.length) {
                    const tgt = children[frame.iter++];
                    if (color.get(tgt) === 1) backEdgeKeys.add(`${frame.id}->${tgt}`);
                    else if (color.get(tgt) === 0) {
                        color.set(tgt, 1);
                        stack.push({ id: tgt, iter: 0 });
                    }
                } else {
                    color.set(frame.id, 2);
                    stack.pop();
                }
            }
        }
    }

    // ── Pass 1c: relax layers to a fixed point ──────────────────────────────
    // For every non-back edge with layer(v) <= layer(u), push v to layer(u)+1. Excluding
    // cycle edges makes the rest a DAG, so this converges within |V| passes.
    {
        let changed = true;
        let guard = 0;
        while (changed && guard <= componentNodeIds.length) {
            changed = false;
            guard++;
            for (const conn of connections) {
                if (!componentSet.has(conn.sourceNodeId) || !componentSet.has(conn.targetNodeId)) continue;
                if (backEdgeKeys.has(`${conn.sourceNodeId}->${conn.targetNodeId}`)) continue;
                const srcL = layerMap.get(conn.sourceNodeId);
                const tgtL = layerMap.get(conn.targetNodeId);
                if (srcL === undefined || tgtL === undefined || tgtL > srcL) continue;
                layerMap.set(conn.targetNodeId, srcL + 1);
                changed = true;
            }
        }
    }

    // ── Pass 1d: tightening ──────────────────────────────────────────────────
    // A node whose every outgoing (non-back) edge has slack (>1 layer) is pulled right to
    // min(successor layer) - 1, collapsing multi-layer spans that would otherwise route an
    // edge over the nodes in between. Descending-rank order finalises successors first.
    {
        const tighteningOrder = [...layerMap.keys()].sort((a, b) => layerMap.get(b)! - layerMap.get(a)!);
        for (const nodeId of tighteningOrder) {
            const successors = (outEdges.get(nodeId) ?? []).filter(
                (tgt) => layerMap.has(tgt) && !backEdgeKeys.has(`${nodeId}->${tgt}`)
            );
            if (successors.length === 0) continue;
            const successorLayers = successors.map((s) => layerMap.get(s)!);
            const nodeLayer = layerMap.get(nodeId)!;
            const minSuccessorLayer = Math.min(...successorLayers);
            if (successorLayers.every((l) => l - nodeLayer > 1) && minSuccessorLayer - 1 > nodeLayer) {
                layerMap.set(nodeId, minSuccessorLayer - 1);
            }
        }
    }

    // Bottom-up passes below must see children before parents. Post-repair, ranks no longer
    // follow BFS visitation order (a's rank can now exceed a node BFS reached before it), so
    // this is a fresh descending-rank sort, not `[...bfsOrder].reverse()`.
    const subtreeOrder = [...layerMap.keys()].sort((a, b) => layerMap.get(b)! - layerMap.get(a)!);

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

        // A node wired twice from the SAME parent (e.g. CDT Default + Error both → End) must not
        // be misclassified as a genuine merge node — only distinct source ids count as parents.
        const parentsOfTarget = allParents.get(conn.targetNodeId);
        if (parentsOfTarget && !parentsOfTarget.includes(conn.sourceNodeId)) {
            parentsOfTarget.push(conn.sourceNodeId);
        }

        if (!primaryParent.has(conn.targetNodeId)) {
            primaryParent.set(conn.targetNodeId, conn.sourceNodeId);
            ownedChildren.get(conn.sourceNodeId)!.push(conn.targetNodeId);
            // Record the source port role so we can sort children in port order
            childSourcePortRole.set(conn.targetNodeId, resolveSourcePortRole(conn, nodeMap));
        }
    }

    // Sort each parent's children by port order to prevent edge crossings.
    // For Decision-Table nodes this maps condition index → vertical position.
    for (const [parentId, children] of ownedChildren) {
        if (children.length < 2) continue;
        const parentNode = nodeMap.get(parentId);
        children.sort(
            (a, b) =>
                getPortSortKey(childSourcePortRole.get(a) ?? '', parentNode) -
                getPortSortKey(childSourcePortRole.get(b) ?? '', parentNode)
        );
    }

    // ── Pass 2: bottom-up subtree span ─────────────────────────────────────
    // subtreeSpan[id] = the minimum vertical space (px) required to render the
    // node together with its entire owned subtree without overlapping.
    const subtreeSpan = new Map<string, number>();
    const rowAlignedChildOffsets = new Map<string, Map<string, number>>();
    // Children excluded from row-pinning (wrong layer/multi-parent, or dropped by the feasibility
    // check above) — they still belong to this table and need generic sibling spacing in Pass 3.
    const fallbackChildrenMap = new Map<string, string[]>();
    for (const nodeId of subtreeOrder) {
        const h = nHeight(nodeMap.get(nodeId));
        const children = ownedChildren.get(nodeId) ?? [];
        if (children.length === 0) {
            subtreeSpan.set(nodeId, h);
            continue;
        }

        const node = nodeMap.get(nodeId);
        let alignment: { offsets: Map<string, number>; span: number } | null = null;
        if (node?.type === NodeType.CLASSIFICATION_TABLE || node?.type === NodeType.TABLE) {
            // Pin only children exactly one layer right of the table with no other parent —
            // otherwise a node further downstream gets its Y frozen onto a row it isn't next to.
            const tableLayer = layerMap.get(nodeId)!;
            const eligibleChildren = children.filter(
                (cid) => layerMap.get(cid) === tableLayer + 1 && (allParents.get(cid)?.length ?? 0) === 1
            );
            if (eligibleChildren.length > 0) {
                alignment = tryAlignRowBasedChildrenToRows(nodeId, node, eligibleChildren, connections, nodeMap);
            }
        }

        if (alignment) {
            rowAlignedChildOffsets.set(nodeId, alignment.offsets);
            const fallback = children.filter((cid) => !alignment!.offsets.has(cid));
            if (fallback.length > 0) {
                fallbackChildrenMap.set(nodeId, fallback);
                const fallbackTotal =
                    fallback.reduce((sum, cid) => sum + (subtreeSpan.get(cid) ?? 60), 0) +
                    Math.max(0, fallback.length - 1) * (SIBLING_GAP + BRANCH_GAP);
                subtreeSpan.set(nodeId, Math.max(h, alignment.span, fallbackTotal));
            } else {
                subtreeSpan.set(nodeId, Math.max(h, alignment.span));
            }
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
    // Nodes pinned to a row-based table's row — the de-overlap pass below must never move these.
    const pinnedNodeIds = new Set<string>();
    // Nodes whose Y was aligned on a parent's output port, with the parents it was aligned to and
    // the centre that produced — the post-snap pass re-derives these from the parents' final Y.
    const portAlignedParents = new Map<string, string[]>();
    const portAlignedCenterY = new Map<string, number>();

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
                centerYMap.set(nodeId, alignedChildCenterY(nodeMap.get(nodeId), avg));
                portAlignedParents.set(nodeId, parents);
                portAlignedCenterY.set(nodeId, centerYMap.get(nodeId)!);
                continue;
            }

            if (primary === undefined || !centerYMap.has(primary)) {
                // No primary parent placed yet — fallback, should not happen in acyclic graphs.
                centerYMap.set(nodeId, startY + nHeight(nodeMap.get(nodeId)) / 2);
                continue;
            }

            const parentCY = centerYMap.get(primary)!;

            // Row-aligned table child: place it directly at its recorded row offset from the
            // table's top instead of the uniform sibling distribution below.
            const rowOffset = rowAlignedChildOffsets.get(primary)?.get(nodeId);
            if (rowOffset !== undefined) {
                const tableHeight = nHeight(nodeMap.get(primary));
                centerYMap.set(nodeId, parentCY - tableHeight / 2 + rowOffset);
                pinnedNodeIds.add(nodeId);
                continue;
            }

            // If `primary` row-pinned only some of its children, distribute just the
            // fallback subset here — the pinned siblings already have a fixed Y above.
            const siblings = fallbackChildrenMap.get(primary) ?? ownedChildren.get(primary) ?? [];

            if (siblings.length === 1) {
                // Only child: align on parent (a table child aligns its input port, not its box).
                centerYMap.set(nodeId, alignedChildCenterY(nodeMap.get(nodeId), parentCY));
                portAlignedParents.set(nodeId, [primary]);
                portAlignedCenterY.set(nodeId, centerYMap.get(nodeId)!);
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

    // ── Per-layer de-overlap ─────────────────────────────────────────────────
    // A node keeps its computed Y unless its box genuinely overlaps the previous one; only
    // then is it pushed to previousBottom + SIBLING_GAP. Merely touching is not a collision.
    const diagnostics: PinnedOverlapDiagnostic[] = [];
    for (const layer of sortedLayers) {
        const ids = [...(layerGroups.get(layer) ?? [])].sort(
            (a, b) => (centerYMap.get(a) ?? 0) - (centerYMap.get(b) ?? 0)
        );
        let previousBottom = -Infinity;
        for (let i = 0; i < ids.length; i++) {
            const id = ids[i];
            const h = nHeight(nodeMap.get(id));
            const top = centerYMap.get(id)! - h / 2;
            if (pinnedNodeIds.has(id)) {
                // A pin can't move; only act when its box genuinely overlaps the previous
                // node's bottom. Try to push unpinned predecessors out of the way; if that's
                // not possible, report it.
                if (top < previousBottom) {
                    const overlap = previousBottom + SIBLING_GAP - top;
                    const resolved = pushUnpinnedPredecessorsUp(
                        ids,
                        i - 1,
                        overlap,
                        pinnedNodeIds,
                        centerYMap,
                        nodeMap
                    );
                    if (!resolved) diagnostics.push({ nodeId: id, layer, overlapPx: overlap });
                }
                previousBottom = centerYMap.get(id)! + h / 2;
                continue;
            }
            if (top < previousBottom) {
                centerYMap.set(id, previousBottom + SIBLING_GAP + h / 2);
            }
            previousBottom = centerYMap.get(id)! + h / 2;
        }
    }

    // The sweep outranks port alignment: if it moved a node to clear an overlap, that node is no
    // longer aligned on its parent and must not be pulled back by the re-derivation pass below.
    for (const [nodeId, alignedCY] of portAlignedCenterY) {
        if (centerYMap.get(nodeId) !== alignedCY) portAlignedParents.delete(nodeId);
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

    // ── Per-gap edge crossing counts ────────────────────────────────────────
    // For each gap between two adjacent rendered columns, count forward edges (plus any frozen
    // back edge) that span it with a materially different source/target Y — those need a wider
    // corridor than a same-row edge does.
    const layerIndex = new Map<number, number>();
    sortedLayers.forEach((layer, i) => layerIndex.set(layer, i));
    const gapEdgeCount = new Array<number>(Math.max(0, sortedLayers.length - 1)).fill(0);
    for (const conn of connections) {
        if (!componentSet.has(conn.sourceNodeId) || !componentSet.has(conn.targetNodeId)) continue;
        const srcLayer = layerMap.get(conn.sourceNodeId);
        const tgtLayer = layerMap.get(conn.targetNodeId);
        if (srcLayer === undefined || tgtLayer === undefined || srcLayer === tgtLayer) continue;
        const isBack = backEdgeKeys.has(`${conn.sourceNodeId}->${conn.targetNodeId}`);
        if (isBack && !conn.userAdjustedWaypoints) continue;
        const srcCY = centerYMap.get(conn.sourceNodeId);
        const tgtCY = centerYMap.get(conn.targetNodeId);
        if (srcCY === undefined || tgtCY === undefined) continue;
        if (Math.abs(srcCY - tgtCY) <= EDGE_VERTICAL_DELTA_THRESHOLD_PX) continue;
        const loIdx = layerIndex.get(Math.min(srcLayer, tgtLayer))!;
        const hiIdx = layerIndex.get(Math.max(srcLayer, tgtLayer))!;
        for (let k = loIdx; k < hiIdx; k++) gapEdgeCount[k] += 1;
    }

    // ── X positions per layer ───────────────────────────────────────────────
    // layerRight is the layer's shared right edge; nodes are placed against it (see the position
    // loop below) so every output port in a layer lands on the same X regardless of node width.
    const layerRight = new Map<number, number>();
    let currentX = CANVAS_START_X;
    for (let i = 0; i < sortedLayers.length; i++) {
        const layer = sortedLayers[i];
        const ids = layerGroups.get(layer) ?? [];
        const maxW = ids.length > 0 ? Math.max(...ids.map((id) => nWidth(nodeMap.get(id)))) : 330;
        layerRight.set(layer, currentX + maxW);
        const hasDT = ids.some((id) => {
            const t = nodeMap.get(id)?.type;
            return t === NodeType.TABLE || t === NodeType.CLASSIFICATION_TABLE;
        });
        const gapAllowance = Math.min(MAX_GAP_ALLOWANCE_PX, (gapEdgeCount[i] ?? 0) * EDGE_GAP_ALLOWANCE_PX);
        currentX += maxW + HORIZONTAL_GAP + gapAllowance + (hasDT ? DT_EXTRA_HORIZONTAL_GAP : 0);
    }

    // ── Convert to top-left positions ───────────────────────────────────────
    // Snap the PORT Y (not the top-left) to the 20 px grid so that:
    //  • same-cy nodes share the same snapped port → straight horizontal arrows
    //  • different-cy nodes have port differences that are multiples of 20 px → clean grid-aligned steps
    // A row-based table's port isn't at its centre but at its first row — snap THAT instead, or
    // every row (a multiple of its row height away) lands 10px off the grid every ordinary node uses.
    const positions = new Map<string, IPoint>();
    for (const [nodeId, cy] of centerYMap) {
        const h = nHeight(nodeMap.get(nodeId));
        const layer = layerMap.get(nodeId) ?? 0;
        const nodeW = nWidth(nodeMap.get(nodeId));
        const x = layerRight.has(layer) ? layerRight.get(layer)! - nodeW : CANVAS_START_X;
        const nodeType = nodeMap.get(nodeId)?.type;
        let y: number;
        if (nodeType === NodeType.CLASSIFICATION_TABLE || nodeType === NodeType.TABLE) {
            const firstRowPortOffset = getRowPortCenterYFromTop(0, 0, nodeType);
            y = snapToGrid(cy - h / 2 + firstRowPortOffset) - firstRowPortOffset;
        } else {
            y = snapToGrid(cy) - Math.round(h / 2);
        }
        positions.set(nodeId, { x: snapToGrid(x), y });
    }

    // Snapping two related nodes independently lets them disagree by up to 10px, so both kinds of
    // dependent Y are re-derived from the already-final reference instead. Ascending layer order
    // settles a reference before anything anchored to it (a table before its own pinned children).
    const rowPinReference = new Map<string, { tableId: string; centreOffset: number }>();
    for (const [tableId, offsets] of rowAlignedChildOffsets) {
        for (const [childId, centreOffset] of offsets) {
            rowPinReference.set(childId, { tableId, centreOffset });
        }
    }
    const idsPerLayer = new Map<number, string[]>();
    for (const nodeId of positions.keys()) {
        const layer = layerMap.get(nodeId) ?? 0;
        if (!idsPerLayer.has(layer)) idsPerLayer.set(layer, []);
        idsPerLayer.get(layer)!.push(nodeId);
    }

    // Nodes in a layer share a right edge, so a vertical range test is the whole collision test.
    const overlapsLayerSibling = (nodeId: string, layerIds: string[], top: number): boolean => {
        const bottom = top + nHeight(nodeMap.get(nodeId));
        return layerIds.some((otherId) => {
            const other = positions.get(otherId);
            if (otherId === nodeId || !other) return false;
            return top < other.y + nHeight(nodeMap.get(otherId)) && other.y < bottom;
        });
    };

    for (const layer of [...idsPerLayer.keys()].sort((a, b) => a - b)) {
        const layerIds = idsPerLayer.get(layer)!;

        // Both kinds of dependent Y are proposed here and settled by one revert loop, so a row pin
        // and a port alignment contending for the same band resolve against each other.
        const proposedTop = new Map<string, number>();
        for (const nodeId of layerIds) {
            const pin = rowPinReference.get(nodeId);
            if (pin) {
                const tablePos = positions.get(pin.tableId);
                if (tablePos) {
                    proposedTop.set(nodeId, tablePos.y + pin.centreOffset - nHeight(nodeMap.get(nodeId)) / 2);
                }
                continue;
            }
            const parents = portAlignedParents.get(nodeId);
            if (!parents) continue;
            const portYs = parents
                .map((p) => finalParentCenterY(p, positions, nodeMap))
                .filter((y): y is number => y !== null);
            if (portYs.length === 0) continue;
            // A table lands 12px off the 20px grid here and its rows 2px off. That is fine —
            // everything anchored to it is re-derived from this top too, so wires stay straight.
            const portY = portYs.reduce((sum, y) => sum + y, 0) / portYs.length;
            proposedTop.set(nodeId, Math.round(portY - inputPortOffset(nodeMap.get(nodeId))));
        }

        const candidates = [...proposedTop.keys()].sort(
            (a, b) => positions.get(a)!.y - positions.get(b)!.y || (a < b ? -1 : 1)
        );
        const sweptTop = new Map<string, number>();
        for (const nodeId of candidates) {
            sweptTop.set(nodeId, positions.get(nodeId)!.y);
            positions.set(nodeId, { ...positions.get(nodeId)!, y: proposedTop.get(nodeId)! });
        }

        // Non-overlap outranks both: a node put back where the sweep left it keeps one wire kinked
        // — a pin's row wire, an alignment's input wire — which beats drawing it on top of a
        // settled neighbour. Alignments yield before pins; within a kind, topmost offender first.
        const revertOrder = [...candidates].sort(
            (a, b) => Number(rowPinReference.has(a)) - Number(rowPinReference.has(b))
        );
        let reverted = true;
        while (reverted) {
            reverted = false;
            for (const nodeId of revertOrder) {
                const swept = sweptTop.get(nodeId);
                if (swept === undefined || !overlapsLayerSibling(nodeId, layerIds, positions.get(nodeId)!.y)) continue;
                // Nothing to gain when the sweep's own slot is occupied too — keep the straight wire.
                if (overlapsLayerSibling(nodeId, layerIds, swept)) continue;
                positions.set(nodeId, { ...positions.get(nodeId)!, y: swept });
                sweptTop.delete(nodeId);
                reverted = true;
                break;
            }
        }
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

    return { positions, bottomY, diagnostics };
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
    return computeAutoArrangePositionsWithDiagnostics(nodes, connections).positions;
}

// Same layout as computeAutoArrangePositions, but also surfaces per-component de-overlap
// diagnostics (see PinnedOverlapDiagnostic) instead of silently accepting an unresolved overlap.
export function computeAutoArrangePositionsWithDiagnostics(
    nodes: NodeModel[],
    connections: ConnectionModel[]
): { positions: Map<string, IPoint>; diagnostics: PinnedOverlapDiagnostic[] } {
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
    const diagnostics: PinnedOverlapDiagnostic[] = [];
    let currentY = CANVAS_START_Y;

    for (const componentNodeIds of multiNodeComponents) {
        const result = layoutSingleComponent(componentNodeIds, nodeMap, connections, currentY);
        for (const [id, pos] of result.positions) {
            positions.set(id, pos);
        }
        diagnostics.push(...result.diagnostics);
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

    return { positions, diagnostics };
}
