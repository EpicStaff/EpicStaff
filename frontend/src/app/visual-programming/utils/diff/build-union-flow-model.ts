import { NodeType } from '@shared/models';
import { generateUuid } from '@shared/utils';

import { generatePortsForNode, slugifyPortName } from '../../core/helpers/helpers';
import {
    CollisionBounds,
    findNearestFreePosition,
    getCollisionBounds,
    hasCollision,
} from '../../core/helpers/node-placement.utils';
import { CDT_ROW_HEIGHT, DT_ROW_HEIGHT } from '../../core/helpers/node-size.util';
import { ConnectionModel } from '../../core/models/connection.model';
import { ConditionGroup } from '../../core/models/decision-table.model';
import { FlowModel } from '../../core/models/flow.model';
import { NodeModel } from '../../core/models/node.model';
import { CustomPortId, ViewPort } from '../../core/models/port.model';
import { createFlowConnection } from '../connection.factory';
import { getInputPortRole, getOutputPortRole } from '../node-port-roles';
import { EdgeDiffEntry, EdgeDiffStatus, FlowDiff, NodeDiffEntry, NodeDiffStatus } from './types';

/**
 * The diff state of one union node. Missing references are not here: they belong to the version side and are
 * marked on the plain preview too (`buildVersionMissingReferences`, mapped through `unionIdByVersionId`).
 */
export interface UnionNodeDiffState {
    status: NodeDiffStatus;
}

/** The diff status of every node and connection of a union canvas, by its canvas id. */
export interface FlowDiffCanvasState {
    nodes: ReadonlyMap<string, UnionNodeDiffState>;
    connections: ReadonlyMap<string, EdgeDiffStatus>;
    /**
     * The ports that only the version side of a node on both sides has: the routes a restore adds to a
     * decision table. A node only in the version has none here; its own status says it is added.
     */
    versionOnlyPortIds: ReadonlySet<string>;
}

export interface UnionFlowModel {
    /** Both flows on one canvas: every node and edge of the version and of the current canvas, once. */
    flow: FlowModel;
    diffState: FlowDiffCanvasState;
    /** Union canvas id by version canvas id, to follow version-side ids (warnings, authorship) onto this canvas. */
    unionIdByVersionId: ReadonlyMap<string, string>;
}

/**
 * Turns a diff into one canvas that shows what a restore of the version does to the current canvas.
 * Pure: the same diff and id source give the same model.
 *
 * - Every node gets a fresh canvas id, so the canvas never shares ids with either side.
 * - A node in the version (added, changed, unchanged) shows the version data at the version position.
 *   A node only on the current canvas (deleted) shows its current data, moved to the nearest spot where
 *   it covers no node placed before it. Version nodes do not move, except off a table grown by the rows
 *   of removed routes (`clearGrownTables`). When no free spot is within the search radius of
 *   `findNearestFreePosition`, the node keeps its position.
 * - A node on both sides gets the ports of both sides, so a canvas-only edge still has a port to attach
 *   to (e.g. a decision-table route the version no longer has).
 * - Every edge of the diff is drawn once, between the union nodes, with its status.
 */
export function buildUnionFlowModel(diff: FlowDiff, createId: () => string = generateUuid): UnionFlowModel {
    const unionIdByKey = new Map<string, string>();
    const unionIdByVersionId = new Map<string, string>();
    const unionIdByCurrentId = new Map<string, string>();
    for (const entry of diff.nodes) {
        const unionId = createId();
        unionIdByKey.set(entry.key, unionId);
        if (entry.versionNode) unionIdByVersionId.set(entry.versionNode.id, unionId);
        if (entry.currentNode) unionIdByCurrentId.set(entry.currentNode.id, unionId);
    }

    const extraRowsByUnionId = new Map<string, number>();
    const versionOnlyPortIds = new Set<string>();
    const unionNodeOf = (entry: NodeDiffEntry): NodeModel => {
        const unionId = unionIdByKey.get(entry.key)!;
        const base = (entry.versionNode ?? entry.currentNode)!;
        const ownIds = entry.versionNode ? unionIdByVersionId : unionIdByCurrentId;
        const { ports, otherSideOnlyOutputs, shownSideOnlyPortIds } = mergePorts(unionId, entry);
        extraRowsByUnionId.set(unionId, otherSideOnlyOutputs);
        if (entry.versionNode) shownSideOnlyPortIds.forEach((portId) => versionOnlyPortIds.add(portId));
        return {
            ...base,
            id: unionId,
            backendId: null,
            data: withTableReferences(base, ownIds),
            ports,
            size: { ...base.size, height: base.size.height + otherSideOnlyOutputs * tableRowHeight(base.type) },
        } as NodeModel;
    };

    const boundsOf = (node: NodeModel): CollisionBounds => {
        const bounds = getCollisionBounds(node);
        const extraRows = extraRowsByUnionId.get(node.id) ?? 0;
        return { ...bounds, height: bounds.height + extraRows * tableRowHeight(node.type) };
    };

    const placedNodes: NodeModel[] = diff.nodes.filter((entry) => entry.versionNode).map(unionNodeOf);
    for (const entry of diff.nodes.filter((candidate) => !candidate.versionNode)) {
        const node = unionNodeOf(entry);
        const position = findNearestFreePosition(node.position, boundsOf(node), placedNodes, boundsOf);
        placedNodes.push({ ...node, position });
    }
    clearGrownTables(placedNodes, extraRowsByUnionId, boundsOf);

    const nodeStates = new Map<string, UnionNodeDiffState>(
        diff.nodes.map((entry) => [unionIdByKey.get(entry.key)!, { status: entry.status }])
    );

    const entryByKey = new Map(diff.nodes.map((entry) => [entry.key, entry]));
    const nodeByUnionId = new Map(placedNodes.map((node) => [node.id, node]));
    const sidesByConnectionId = new Map<string, { connection: ConnectionModel; sides: Set<EdgeDiffStatus> }>();
    for (const edge of diff.edges) {
        const source = nodeByUnionId.get(unionIdByKey.get(edge.sourceKey) ?? '');
        const target = nodeByUnionId.get(unionIdByKey.get(edge.targetKey) ?? '');
        const sourceEntry = entryByKey.get(edge.sourceKey);
        if (!source || !target || !sourceEntry) continue;
        const sourceRole = sourcePortRole(edge, sourceEntry, source.type);
        if (sourceRole === null) continue;
        const connection = createFlowConnection(
            source.id,
            target.id,
            `${source.id}_${sourceRole}` as CustomPortId,
            `${target.id}_${getInputPortRole(target.type)}` as CustomPortId
        );
        // Two diff edges can share one line: two classification-table groups with the same route code
        // and target leave through one port. The line keeps one status from both.
        const existing = sidesByConnectionId.get(connection.id);
        if (existing) existing.sides.add(edge.status);
        else sidesByConnectionId.set(connection.id, { connection, sides: new Set([edge.status]) });
    }

    const connectionStates = new Map<string, EdgeDiffStatus>();
    for (const [connectionId, { sides }] of sidesByConnectionId) {
        connectionStates.set(connectionId, combinedEdgeStatus(sides));
    }

    return {
        flow: {
            nodes: placedNodes,
            connections: [...sidesByConnectionId.values()].map(({ connection }) => connection),
        },
        diffState: { nodes: nodeStates, connections: connectionStates, versionOnlyPortIds },
        unionIdByVersionId,
    };
}

/**
 * The ports of the shown side first, then the ones only the other side has. Only decision tables can
 * differ (their output ports come from their groups); `otherSideOnlyOutputs` counts the extra rows a
 * table shows for them. `shownSideOnlyPortIds` are the shown side's ports the other side lacks; empty
 * for a node on one side only.
 */
function mergePorts(
    unionId: string,
    entry: NodeDiffEntry
): { ports: ViewPort[]; otherSideOnlyOutputs: number; shownSideOnlyPortIds: string[] } {
    const [shown, other] = entry.versionNode
        ? [entry.versionNode, entry.currentNode]
        : [entry.currentNode!, entry.versionNode];
    const ports = generatePortsForNode(unionId, shown.type, shown.data);
    if (!other) return { ports, otherSideOnlyOutputs: 0, shownSideOnlyPortIds: [] };
    const shownIds = new Set(ports.map((port) => port.id));
    const otherPorts = generatePortsForNode(unionId, other.type, other.data);
    const otherIds = new Set(otherPorts.map((port) => port.id));
    const otherSideOnly = otherPorts.filter((port) => !shownIds.has(port.id));
    return {
        ports: [...ports, ...otherSideOnly],
        otherSideOnlyOutputs: otherSideOnly.filter((port) => port.port_type === 'output').length,
        shownSideOnlyPortIds: ports.filter((port) => !otherIds.has(port.id)).map((port) => port.id),
    };
}

/**
 * The one exception to "version nodes never move": a table on both sides grows by a row per route only
 * the current canvas has, and may then cover the version node below it. A node that collides with a
 * grown table only because of those rows is moved to the nearest free spot, like a deleted node.
 * Updates `nodes` in place.
 */
function clearGrownTables(
    nodes: NodeModel[],
    extraRowsByUnionId: ReadonlyMap<string, number>,
    boundsOf: (node: NodeModel) => CollisionBounds
): void {
    const grownTableIds = new Set([...extraRowsByUnionId].filter(([, rows]) => rows > 0).map(([id]) => id));
    if (grownTableIds.size === 0) return;
    nodes.forEach((node, index) => {
        const coveredOnlyByGrownRows = nodes.some(
            (table) =>
                table.id !== node.id &&
                grownTableIds.has(table.id) &&
                hasCollision(node.position, boundsOf(node), [table], boundsOf) &&
                !hasCollision(node.position, boundsOf(node), [table], getCollisionBounds)
        );
        if (!coveredOnlyByGrownRows) return;
        const others = nodes.filter((other) => other.id !== node.id);
        nodes[index] = { ...node, position: findNearestFreePosition(node.position, boundsOf(node), others, boundsOf) };
    });
}

function tableRowHeight(type: NodeType): number {
    if (type === NodeType.TABLE) return DT_ROW_HEIGHT;
    if (type === NodeType.CLASSIFICATION_TABLE) return CDT_ROW_HEIGHT;
    return 0;
}

/** Decision-table routes point at canvas ids of their own side; on the union canvas they point at union ids. */
function withTableReferences(node: NodeModel, unionIdOf: ReadonlyMap<string, string>): NodeModel['data'] {
    if (node.type !== NodeType.TABLE && node.type !== NodeType.CLASSIFICATION_TABLE) return node.data;
    const toUnionId = (canvasId: string | null | undefined): string | null =>
        canvasId ? (unionIdOf.get(canvasId) ?? null) : null;
    const table = node.data.table;
    return {
        ...node.data,
        table: {
            ...table,
            default_next_node: toUnionId(table.default_next_node),
            next_error_node: toUnionId(table.next_error_node),
            condition_groups: (table.condition_groups ?? []).map((group: ConditionGroup) => ({
                ...group,
                next_node: toUnionId(group.next_node),
            })),
        },
    } as NodeModel['data'];
}

/**
 * The port role the edge leaves from. A plain edge leaves from the type's output port, as the loader
 * draws saved edges. A route leaves from its group's port; the group is read from the side the edge is
 * on (a deleted edge from the current canvas), because a classification-table route code can differ.
 */
function sourcePortRole(edge: EdgeDiffEntry, sourceEntry: NodeDiffEntry, sourceType: NodeType): string | null {
    if (edge.routeKind === 'edge') return getOutputPortRole(sourceType);
    if (edge.route === 'default') return 'decision-default';
    if (edge.route === 'error') return 'decision-error';
    const groupName = edge.route?.startsWith('group:') ? edge.route.slice('group:'.length) : null;
    if (groupName === null) return null;
    if (edge.routeKind === 'dt-route') return `decision-out-${slugifyPortName(groupName)}`;

    const sideNode = edge.status === 'deleted' ? sourceEntry.currentNode : sourceEntry.versionNode;
    if (sideNode?.type !== NodeType.CLASSIFICATION_TABLE) return null;
    const group = (sideNode.data.table.condition_groups ?? []).find(
        (candidate) => candidate.group_name === groupName && !!candidate.route_code
    );
    return group?.route_code ? `decision-route-${slugifyPortName(group.route_code)}` : null;
}

/** A line on both sides is unchanged; otherwise it is on the version only (added) or the canvas only (deleted). */
function combinedEdgeStatus(statuses: ReadonlySet<EdgeDiffStatus>): EdgeDiffStatus {
    const inVersion = statuses.has('added') || statuses.has('unchanged');
    const onCanvas = statuses.has('deleted') || statuses.has('unchanged');
    if (inVersion && onCanvas) return 'unchanged';
    return inVersion ? 'added' : 'deleted';
}
