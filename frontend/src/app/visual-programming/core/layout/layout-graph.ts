import { NodeType } from '@shared/models';

import { portOffsetFromTop } from '../geometry/port-position';
import { resolveRowIndex, RowBasedTableNodeModel } from '../helpers/cdt-row-snap.util';
import { getClassificationTableVisualHeight, getDecisionTableVisualHeight } from '../helpers/node-size.util';
import { ConnectionModel } from '../models/connection.model';
import { ClassificationDecisionTableNodeModel, DecisionTableNodeModel, NodeModel } from '../models/node.model';
import { resolveWireEnds } from '../routing/route-all';

/**
 * The graph auto-arrange works on: every non-NOTE node as a box, every drawable
 * connection as an edge carrying its two port offsets from the node tops. Port offsets come from
 * portOffsetFromTop, the geometry the router draws with, so layout and routing never disagree.
 */

export interface LayoutNode {
    id: string;
    width: number;
    height: number;
    inputOffsetY: number; // the first left port's offset from the top; height / 2 without one
    isTrigger: boolean;
    isTable: boolean;
    isDummy: boolean;
    hasSelfLoop: boolean; // left out of the edges, but a wire into the node all the same (it blocks the off-grid feeding-median exemption)
}

export interface LayoutEdge {
    id: string;
    source: string;
    target: string;
    sourceOffsetY: number;
    targetOffsetY: number;
    fromTableRow: boolean; // the source port is a row of a DT/CDT (Default and Error included)
    sourceRow: number | null; // that row's index, else null
}

export interface LayoutGraph {
    nodes: Map<string, LayoutNode>;
    edges: LayoutEdge[]; // sorted by id
}

const TRIGGER_TYPES = new Set<string>([NodeType.START, NodeType.WEBHOOK_TRIGGER, NodeType.TELEGRAM_TRIGGER]);

export function byId(first: string, second: string): number {
    return first < second ? -1 : first > second ? 1 : 0;
}

function isRowBasedTable(node: NodeModel): node is RowBasedTableNodeModel {
    return node.type === NodeType.TABLE || node.type === NodeType.CLASSIFICATION_TABLE;
}

// A table's rendered height follows its current rows; it wins over size.height.
function visualHeight(node: NodeModel): number {
    if (node.type === NodeType.TABLE) {
        return getDecisionTableVisualHeight((node as DecisionTableNodeModel).data.table?.condition_groups ?? []);
    }
    if (node.type === NodeType.CLASSIFICATION_TABLE) {
        const conditionGroups = (node as ClassificationDecisionTableNodeModel).data.table?.condition_groups ?? [];
        return getClassificationTableVisualHeight(conditionGroups);
    }
    return node.size.height;
}

function layoutNode(node: NodeModel, hasSelfLoop: boolean): LayoutNode {
    const inputPort = node.ports?.find((candidate) => candidate.position === 'left');
    return {
        id: node.id,
        width: node.size.width,
        height: visualHeight(node),
        inputOffsetY: portOffsetFromTop(node, inputPort),
        isTrigger: TRIGGER_TYPES.has(node.type),
        isTable: isRowBasedTable(node),
        isDummy: false,
        hasSelfLoop,
    };
}

/**
 * Builds the layout graph and its undirected components. Left out: NOTE nodes (they keep their
 * position), stale connections (a node or port missing), top/bottom-port connections (the router
 * leaves those alone too) and self-loops (the router draws them; they don't shape the layout).
 * Components come trigger-first, then largest, then by smallest id; each lists its ids sorted.
 * Single-node components are returned as `isolated`, sorted by id.
 */
export function buildLayoutGraph(
    nodes: NodeModel[],
    connections: ConnectionModel[]
): { graph: LayoutGraph; components: string[][]; isolated: string[] } {
    const layoutNodes = nodes.filter((node) => node.type !== NodeType.NOTE).sort((a, b) => byId(a.id, b.id));
    const nodesById = new Map(layoutNodes.map((node) => [node.id, node]));
    const selfLooped = new Set<string>();
    const drawable = connections.flatMap((connection) => {
        const ends = resolveWireEnds(connection, nodesById);
        if (!ends) return [];
        if (ends.sourceNode === ends.targetNode) {
            selfLooped.add(ends.sourceNode.id);
            return [];
        }
        return [{ connection, ends }];
    });
    const graph: LayoutGraph = {
        nodes: new Map(layoutNodes.map((node) => [node.id, layoutNode(node, selfLooped.has(node.id))])),
        edges: [],
    };

    for (const { connection, ends } of drawable) {
        const { sourceNode, targetNode, sourcePort, targetPort } = ends;
        const sourceRow = isRowBasedTable(sourceNode) ? resolveRowIndex(sourceNode, sourcePort.role) : null;
        graph.edges.push({
            id: connection.id,
            source: sourceNode.id,
            target: targetNode.id,
            sourceOffsetY: portOffsetFromTop(sourceNode, sourcePort),
            targetOffsetY: portOffsetFromTop(targetNode, targetPort),
            fromTableRow: sourceRow !== null,
            sourceRow,
        });
    }
    graph.edges.sort((a, b) => byId(a.id, b.id));

    const allComponents = undirectedComponents([...graph.nodes.keys()], graph.edges);
    const isolated = allComponents.filter((component) => component.length === 1).map(([id]) => id);
    const hasTrigger = (component: string[]): number =>
        component.some((id) => graph.nodes.get(id)!.isTrigger) ? 1 : 0;
    const components = allComponents
        .filter((component) => component.length > 1)
        .sort((a, b) => hasTrigger(b) - hasTrigger(a) || b.length - a.length || byId(a[0], b[0]));
    return { graph, components, isolated: isolated.sort(byId) };
}

// Union-find over the edges, treated as undirected. Every component lists its ids sorted.
function undirectedComponents(ids: string[], edges: LayoutEdge[]): string[][] {
    const parent = new Map(ids.map((id) => [id, id]));
    const find = (id: string): string => {
        let root = id;
        while (parent.get(root) !== root) root = parent.get(root)!;
        parent.set(id, root);
        return root;
    };
    for (const edge of edges) {
        const sourceRoot = find(edge.source);
        const targetRoot = find(edge.target);
        if (sourceRoot === targetRoot) continue;
        const [kept, merged] = byId(sourceRoot, targetRoot) < 0 ? [sourceRoot, targetRoot] : [targetRoot, sourceRoot];
        parent.set(merged, kept);
    }
    const groups = new Map<string, string[]>();
    for (const id of [...ids].sort(byId)) {
        const root = find(id);
        if (!groups.has(root)) groups.set(root, []);
        groups.get(root)!.push(id);
    }
    return [...groups.values()];
}
