import { computed, Injectable, signal } from '@angular/core';
import { IPoint } from '@foblex/2d';
import { Subject } from 'rxjs';

import { NodeType } from '../core/enums/node-type';
import {
    generatePortsForClassificationDecisionTableNode,
    generatePortsForDecisionTableNode,
    isDecisionPortRole,
    parsePortId,
} from '../core/helpers/helpers';
import { ConnectionModel } from '../core/models/connection.model';
import { ConditionGroup, DecisionTableNode } from '../core/models/decision-table.model';
import { FlowModel } from '../core/models/flow.model';
import {
    ClassificationDecisionTableNodeModel,
    DecisionTableNodeModel,
    NodeModel,
    StartNodeModel,
} from '../core/models/node.model';
import { CustomPortId, ViewPort } from '../core/models/port.model';

export interface FlattenedPort {
    nodeId: string;
    port: ViewPort;
}

@Injectable({
    providedIn: 'root',
})
export class FlowService {
    private flowSignal = signal<FlowModel>({
        nodes: [],
        connections: [],
    });

    private _nextNodeNumber = 1;

    // Subject to request canvas redraw (e.g., after port reordering)
    private canvasRedrawRequest$ = new Subject<void>();
    public readonly canvasRedrawRequested = this.canvasRedrawRequest$.asObservable();

    public readonly nodes = computed(() => this.flowSignal().nodes);
    public readonly connections = computed(() => this.flowSignal().connections);

    public readonly noteNodes = computed(() => this.nodes().filter((node) => node.type === NodeType.NOTE));

    public readonly startNodeInitialState = computed(() => {
        const startNode: StartNodeModel | undefined = this.nodes().find((node) => node.type === NodeType.START);
        return startNode?.data?.initialState || {};
    });

    // Whether there is at least one End node in the flow
    public readonly hasEndNode = computed(() => this.nodes().some((node) => node.type === NodeType.END));

    // Generic helper to check if any node of a type exists
    public hasNodeType(type: NodeType): boolean {
        return this.nodes().some((node) => node.type === type);
    }

    public visibleConnections = computed(() => {
        return this.connections();
    });

    // Selector to get connections for a given port.
    public getConnectionsForPort(portId: CustomPortId): CustomPortId[] {
        return this.portConnectionsMap()[portId] || [];
    }

    constructor() {}

    public getFlowState(): FlowModel {
        return this.flowSignal();
    }

    public requestCanvasRedraw(): void {
        this.canvasRedrawRequest$.next();
    }

    public setFlow(flow: FlowModel) {
        this.flowSignal.set(flow);
        // Re-seed the counter above the highest existing nodeNumber
        let max = 0;
        for (const n of flow.nodes) {
            if (n.nodeNumber != null && n.nodeNumber > max) {
                max = n.nodeNumber;
            }
        }
        this._nextNodeNumber = max + 1;
    }

    /** Returns the next node number and increments the counter. */
    public getNextNodeNumber(): number {
        return this._nextNodeNumber++;
    }

    public addNode(node: NodeModel) {
        this.flowSignal.update((flow: FlowModel) => ({
            ...flow,
            nodes: [...flow.nodes, node],
        }));
    }
    public addConnection(conn: ConnectionModel) {
        // Update the flow state by adding the new connection
        this.flowSignal.update((flow: FlowModel) => ({
            ...flow,
            connections: [...flow.connections, conn],
        }));

        this.updateDecisionTableNextNodeFromConnection(conn);
    }
    public addConnectionsInBatch(connections: ConnectionModel[]): void {
        if (!connections || connections.length === 0) {
            return;
        }

        this.flowSignal.update((flow: FlowModel) => ({
            ...flow,
            connections: [...flow.connections, ...connections],
        }));
    }
    public removeConnectionsInBatch(connectionIds: string[]): void {
        if (!connectionIds || connectionIds.length === 0) {
            return;
        }

        this.flowSignal.update((flow: FlowModel) => ({
            ...flow,
            connections: flow.connections.filter((conn) => !connectionIds.includes(conn.id)),
        }));

        const remainingConnections = this.connections();
        connectionIds.forEach((connectionId) => {
            this.clearDecisionTableNextNodeForConnection(connectionId, remainingConnections);
        });
    }

    public removeConnection(connId: string) {
        let removedConnection: ConnectionModel | undefined;
        this.flowSignal.update((flow: FlowModel) => ({
            ...flow,
            connections: flow.connections.filter((c) => {
                if (c.id === connId) {
                    removedConnection = c;
                    return false;
                }
                return true;
            }),
        }));

        if (removedConnection) {
            this.clearDecisionTableNextNodeForConnection(removedConnection.id, this.connections());
        }
    }

    public updateConnectionWaypoints(id: string, waypoints: IPoint[], isUserAdjusted?: boolean): void {
        this.flowSignal.update((flow) => ({
            ...flow,
            connections: flow.connections.map((c) =>
                c.id === id
                    ? {
                          ...c,
                          waypoints,
                          ...(isUserAdjusted !== undefined ? { userAdjustedWaypoints: isUserAdjusted } : {}),
                      }
                    : c
            ),
        }));
    }

    public resetDecisionTableConnections(
        tableNodeId: string,
        groups: ConditionGroup[],
        defaultNextNode: string | null,
        nextErrorNode: string | null
    ): void {
        const allNodes = this.nodes();
        const existingConnections = this.connections();

        const connectionsToRemove = existingConnections
            .filter(
                (connection) =>
                    connection.sourceNodeId === tableNodeId &&
                    this.isDecisionTableSourcePort(connection.sourcePortId, tableNodeId)
            )
            .map((connection) => connection.id);

        if (connectionsToRemove.length) {
            this.removeConnectionsInBatch(connectionsToRemove);
        }

        let connectionSnapshot = this.connections();

        const nodeType = allNodes.find((n) => n.id === tableNodeId)?.type;
        const isClassificationTable = nodeType === NodeType.CLASSIFICATION_TABLE;

        const validGroupsWithNextNode = groups.filter(
            (group) =>
                group.valid !== false &&
                group.dock_visible !== false &&
                !!group.next_node &&
                // Classification tables route by route_code; a group with no
                // route code has no output port, so don't recreate a connection.
                (!isClassificationTable || !!group.route_code)
        );

        validGroupsWithNextNode.forEach((group) => {
            const portRole = isClassificationTable
                ? `decision-route-${group.route_code ?? group.group_name}`
                : `decision-out-${group.group_name}`;
            connectionSnapshot = this.ensureDecisionTableConnection(
                tableNodeId,
                group.next_node!,
                portRole,
                allNodes,
                connectionSnapshot
            );
        });

        if (defaultNextNode) {
            connectionSnapshot = this.ensureDecisionTableConnection(
                tableNodeId,
                defaultNextNode,
                'decision-default',
                allNodes,
                connectionSnapshot
            );
        }

        if (nextErrorNode) {
            connectionSnapshot = this.ensureDecisionTableConnection(
                tableNodeId,
                nextErrorNode,
                'decision-error',
                allNodes,
                connectionSnapshot
            );
        }
    }

    public updateNodesInBatch(nodes: NodeModel[]): void {
        if (!nodes || nodes.length === 0) {
            return;
        }

        this.flowSignal.update((flow: FlowModel) => {
            // Create a map of node ids to their updated versions for quick lookup
            const nodeUpdatesMap = new Map<string, NodeModel>();
            nodes.forEach((node) => nodeUpdatesMap.set(node.id, node));

            // Create a new nodes array with updates applied
            const updatedNodes = flow.nodes.map((existingNode) => {
                // If this node is in our update list, return the updated version
                if (nodeUpdatesMap.has(existingNode.id)) {
                    return nodeUpdatesMap.get(existingNode.id)!;
                }
                // Otherwise return the existing node unchanged
                return existingNode;
            });

            // Return updated flow state
            return {
                ...flow,
                nodes: updatedNodes,
            };
        });
    }
    public updateNode(updatedNode: NodeModel, options?: { skipDecisionTableReset?: boolean }) {
        const { skipDecisionTableReset = false } = options || {};
        const currentFlow = this.flowSignal();
        const existingNodeIndex = currentFlow.nodes.findIndex((n) => n.id === updatedNode.id);

        const existingNode = existingNodeIndex >= 0 ? currentFlow.nodes[existingNodeIndex] : null;

        const shouldResetDecisionTableConnections =
            (updatedNode.type === NodeType.TABLE || updatedNode.type === NodeType.CLASSIFICATION_TABLE) &&
            this.haveDecisionTableTargetsChanged(
                existingNode as DecisionTableNodeModel | null,
                updatedNode as DecisionTableNodeModel
            );

        this.flowSignal.update((flow: FlowModel) => {
            // Find the index of the node to update
            const index: number = flow.nodes.findIndex((n) => n.id === updatedNode.id);
            if (index < 0) {
                console.warn('Node not found in flow:', updatedNode.id);
                return flow; // Return unchanged flow if node isn't found
            }

            // Create a new array, replacing just the updated node
            const updatedNodes: NodeModel[] = [...flow.nodes];
            updatedNodes[index] = updatedNode;

            // Return a new FlowModel object (signals need new references)
            return {
                ...flow,
                nodes: updatedNodes,
            };
        });

        if (
            shouldResetDecisionTableConnections &&
            !skipDecisionTableReset &&
            (updatedNode.type === NodeType.TABLE || updatedNode.type === NodeType.CLASSIFICATION_TABLE)
        ) {
            const tableData = updatedNode.data.table;
            const conditionGroups = tableData.condition_groups || [];

            this.resetDecisionTableConnections(
                updatedNode.id,
                conditionGroups,
                tableData.default_next_node || null,
                tableData.next_error_node || null
            );
        }

        // Remove any decision-table source connection whose port no longer
        // exists on the node (e.g. its route code was cleared/deleted).
        if (
            !skipDecisionTableReset &&
            (updatedNode.type === NodeType.TABLE || updatedNode.type === NodeType.CLASSIFICATION_TABLE)
        ) {
            this.pruneOrphanDecisionTableConnections(updatedNode);
        }
    }

    private pruneOrphanDecisionTableConnections(tableNode: NodeModel): void {
        const validPortIds = new Set((tableNode.ports ?? []).map((port) => `${port.id}`));

        const orphanConnectionIds = this.connections()
            .filter(
                (connection) =>
                    connection.sourceNodeId === tableNode.id &&
                    this.isDecisionTableSourcePort(connection.sourcePortId, tableNode.id) &&
                    !validPortIds.has(`${connection.sourcePortId}`)
            )
            .map((connection) => connection.id);

        if (orphanConnectionIds.length) {
            this.removeConnectionsInBatch(orphanConnectionIds);
        }
    }

    private haveDecisionTableTargetsChanged(
        previousNode: DecisionTableNodeModel | null,
        updatedNode: DecisionTableNodeModel
    ): boolean {
        if (!updatedNode) {
            return false;
        }

        const previousKey = this.getDecisionTableConnectionsKey(previousNode?.data?.table ?? null);
        const updatedKey = this.getDecisionTableConnectionsKey(updatedNode.data?.table ?? null);

        return previousKey !== updatedKey;
    }

    private getDecisionTableConnectionsKey(table: DecisionTableNode | null): string {
        if (!table) {
            return '';
        }

        const groupsKey = (table.condition_groups ?? [])
            .filter((group) => group.valid !== false && group.dock_visible !== false && !!group.next_node)
            .map(
                (group) =>
                    `${group.route_code ?? ''}::${group.group_name ?? ''}::${group.next_node ?? ''}::${String(group.dock_visible !== false)}`
            )
            .sort()
            .join('|');

        const defaultKey = table.default_next_node ?? '';
        const errorKey = table.next_error_node ?? '';

        return `${groupsKey}__default:${defaultKey}__error:${errorKey}`;
    }

    public updateConnectionsInBatch(connections: ConnectionModel[]): void {
        if (!connections || connections.length === 0) {
            return;
        }

        this.flowSignal.update((flow: FlowModel) => {
            // Create a map of connection ids to their updated versions for quick lookup
            const connUpdatesMap = new Map<string, ConnectionModel>();
            connections.forEach((conn) => connUpdatesMap.set(conn.id, conn));

            // Create a new connections array with updates applied
            const updatedConnections: ConnectionModel[] = flow.connections.map((existingConn) => {
                if (connUpdatesMap.has(existingConn.id)) {
                    return connUpdatesMap.get(existingConn.id)!;
                }
                return existingConn;
            });

            // Return updated flow state
            return {
                ...flow,
                connections: updatedConnections,
            };
        });
    }

    private ensureDecisionTableConnection(
        tableNodeId: string,
        targetNodeName: string,
        sourcePortRole: string,
        allNodes: NodeModel[],
        existingConnections: ConnectionModel[]
    ): ConnectionModel[] {
        const targetNode = allNodes.find((n) => n.node_name === targetNodeName || n.id === targetNodeName);

        if (!targetNode) {
            console.warn(`Target node not found: ${targetNodeName}`);
            return existingConnections;
        }

        const targetInputPort = targetNode.ports?.find((p: ViewPort) => p.port_type === 'input');

        if (!targetInputPort) {
            console.warn(`No input port found on target node: ${targetNode.node_name}`);
            return existingConnections;
        }

        const normalizedRole = this.normalizeDecisionPortRole(sourcePortRole);
        const sourcePortId = `${tableNodeId}_${normalizedRole}` as CustomPortId;
        const targetPortId = targetInputPort.id;

        const connectionId = `${sourcePortId}+${targetPortId}`;
        const connectionExists = existingConnections.some((connection) => connection.id === connectionId);

        if (!connectionExists) {
            const newConnection: ConnectionModel = {
                id: connectionId,
                category: 'default',
                sourceNodeId: tableNodeId,
                targetNodeId: targetNode.id,
                sourcePortId,
                targetPortId,
                behavior: 'fixed',
                type: 'segment',
                data: null,
            };

            this.addConnection(newConnection);

            return [...existingConnections, newConnection];
        }

        return existingConnections;
    }

    private updateDecisionTableNextNodeFromConnection(connection: ConnectionModel): void {
        const sourceNode = this.nodes().find((node) => node.id === connection.sourceNodeId);

        if (!sourceNode || (sourceNode.type !== NodeType.TABLE && sourceNode.type !== NodeType.CLASSIFICATION_TABLE)) {
            return;
        }

        const tableData = (sourceNode as DecisionTableNodeModel | ClassificationDecisionTableNodeModel).data?.table;
        if (!tableData) {
            return;
        }

        const targetNode = this.nodes().find((node) => node.id === connection.targetNodeId);
        if (!targetNode) {
            return;
        }

        const sourcePortRole = this.extractPortRole(connection.sourcePortId);
        if (!sourcePortRole) {
            return;
        }

        const normalizedSourceRole = this.normalizeDecisionPortRole(sourcePortRole);

        const isCdt = sourceNode.type === NodeType.CLASSIFICATION_TABLE;

        const updatedTable = {
            ...tableData,
            condition_groups: (tableData.condition_groups || []).map((group: ConditionGroup) => {
                const key = isCdt ? (group.route_code ?? group.group_name) : group.group_name;
                const prefix = isCdt ? 'decision-route-' : 'decision-out-';
                const normalizedGroupRole = key ? this.normalizeDecisionPortRole(`${prefix}${key}`) : null;

                if (normalizedGroupRole === normalizedSourceRole) {
                    return {
                        ...group,
                        next_node: targetNode.id,
                    };
                }

                return group;
            }),
        };

        let defaultNextNode = tableData.default_next_node;
        let nextErrorNode = tableData.next_error_node;

        if (normalizedSourceRole === 'decision-default') {
            defaultNextNode = targetNode.id;
        } else if (normalizedSourceRole === 'decision-error') {
            nextErrorNode = targetNode.id;
        }

        const updatedNode = {
            ...sourceNode,
            data: {
                ...(sourceNode as DecisionTableNodeModel | ClassificationDecisionTableNodeModel).data,
                table: {
                    ...updatedTable,
                    default_next_node: defaultNextNode,
                    next_error_node: nextErrorNode,
                },
            },
        } as NodeModel;

        this.updateNode(updatedNode, { skipDecisionTableReset: true });
    }

    private clearDecisionTableNextNodeForConnection(
        connectionId: string,
        remainingConnections: ConnectionModel[]
    ): void {
        const [sourcePortId] = connectionId.split('+');
        if (!sourcePortId) {
            return;
        }

        const sourceInfo = parsePortId(sourcePortId);
        if (!sourceInfo) {
            return;
        }
        const sourceNodeId = sourceInfo.nodeId;
        const sourceNode = this.nodes().find((node) => node.id === sourceNodeId);

        if (!sourceNode || (sourceNode.type !== NodeType.TABLE && sourceNode.type !== NodeType.CLASSIFICATION_TABLE)) {
            return;
        }

        const tableData = (sourceNode as DecisionTableNodeModel | ClassificationDecisionTableNodeModel).data?.table;
        if (!tableData) {
            return;
        }

        const sourceRole = this.extractPortRole(sourcePortId);
        if (!sourceRole) {
            return;
        }

        const normalizedSourceRole = this.normalizeDecisionPortRole(sourceRole);

        const stillConnected = remainingConnections.some((conn) => {
            if (conn.sourceNodeId !== sourceNodeId) {
                return false;
            }
            const connRole = this.extractPortRole(conn.sourcePortId);
            if (!connRole) {
                return false;
            }
            return this.normalizeDecisionPortRole(connRole) === normalizedSourceRole;
        });

        if (stillConnected) {
            return;
        }

        const isCdt = sourceNode.type === NodeType.CLASSIFICATION_TABLE;

        const updatedTable = {
            ...tableData,
            condition_groups: (tableData.condition_groups || []).map((group: ConditionGroup) => {
                const key = isCdt ? (group.route_code ?? group.group_name) : group.group_name;
                const prefix = isCdt ? 'decision-route-' : 'decision-out-';
                const normalizedGroupRole = key ? this.normalizeDecisionPortRole(`${prefix}${key}`) : null;
                if (normalizedGroupRole === normalizedSourceRole) {
                    return {
                        ...group,
                        next_node: null,
                    };
                }
                return group;
            }),
        };

        let defaultNextNode = tableData.default_next_node;
        let nextErrorNode = tableData.next_error_node;

        if (normalizedSourceRole === 'decision-default') {
            defaultNextNode = null;
        } else if (normalizedSourceRole === 'decision-error') {
            nextErrorNode = null;
        }

        const updatedNode = {
            ...sourceNode,
            data: {
                ...(sourceNode as DecisionTableNodeModel | ClassificationDecisionTableNodeModel).data,
                table: {
                    ...updatedTable,
                    default_next_node: defaultNextNode,
                    next_error_node: nextErrorNode,
                },
            },
        } as NodeModel;

        this.updateNode(updatedNode, { skipDecisionTableReset: true });
    }

    private normalizeDecisionPortRole(role: string): string {
        if (role.startsWith('decision-out-')) {
            const suffix = role.substring('decision-out-'.length);
            return `decision-out-${suffix.toLowerCase().replace(/\s+/g, '-')}`;
        }
        if (role.startsWith('decision-route-')) {
            const suffix = role.substring('decision-route-'.length);
            return `decision-route-${suffix.toLowerCase().replace(/\s+/g, '-')}`;
        }
        return role;
    }

    private normalizeDecisionPortId(portId: string): string {
        const underscoreIndex = portId.indexOf('_');
        if (underscoreIndex === -1) {
            return portId;
        }

        const nodeId = portId.substring(0, underscoreIndex);
        const role = portId.substring(underscoreIndex + 1);

        if (!role.startsWith('decision-out-')) {
            return portId;
        }

        const normalizedRole = this.normalizeDecisionPortRole(role);
        return `${nodeId}_${normalizedRole}`;
    }

    private normalizeConnectionId(connId: string): string {
        if (!connId.includes('+')) {
            return connId;
        }

        const [sourcePortId, ...rest] = connId.split('+');
        if (!sourcePortId || rest.length === 0) {
            return connId;
        }

        const targetPortId = rest.join('+');
        const normalizedSourcePortId = this.normalizeDecisionPortId(sourcePortId);

        return `${normalizedSourcePortId}+${targetPortId}`;
    }

    private extractPortRole(portId: string): string | null {
        const underscoreIndex = portId.indexOf('_');
        if (underscoreIndex === -1) {
            return null;
        }

        return portId.substring(underscoreIndex + 1);
    }

    private isDecisionTableSourcePort(portId: CustomPortId, tableNodeId: string): boolean {
        const portIdValue = `${portId}`;
        return portIdValue.startsWith(`${tableNodeId}_decision-`);
    }

    private canPortsConnect(portA: FlattenedPort, portB: FlattenedPort): boolean {
        // Prevent connecting ports on the same node.
        if (portA.nodeId === portB.nodeId) {
            return false;
        }

        const a = portA.port;
        const b = portB.port;
        if (a.port_type === 'input' && b.port_type === 'output') {
            return this.isAllowedRole(a.allowedConnections, b.role);
        }
        if (a.port_type === 'output' && b.port_type === 'input') {
            return this.isAllowedRole(b.allowedConnections, a.role);
        }
        if (a.port_type === 'input-output' && b.port_type === 'input-output') {
            return this.isAllowedRole(a.allowedConnections, b.role) || this.isAllowedRole(b.allowedConnections, a.role);
        }
        return false;
    }

    private isAllowedRole(allowedRoles: string[], targetRole: string): boolean {
        return allowedRoles.some((allowedRole) => {
            if (allowedRole === targetRole) {
                return true;
            }
            if (allowedRole === 'table-out' && isDecisionPortRole(targetRole)) {
                return true;
            }
            return false;
        });
    }
    public deleteSelections(selections: { fNodeIds: string[]; fConnectionIds: string[] }): void {
        this.flowSignal.update((flow: FlowModel) => {
            const nodeIdsToRemove = new Set(selections.fNodeIds);
            const connectionIdsToRemove = new Set<string>();

            const connectionsById = new Map(flow.connections.map((conn) => [conn.id, conn] as const));

            selections.fConnectionIds.forEach((originalId) => {
                const normalizedId = this.normalizeConnectionId(originalId);
                const connection = connectionsById.get(normalizedId) ?? connectionsById.get(originalId);

                if (!connection) {
                    console.warn('Connection not found when attempting to delete:', originalId);
                    return;
                }

                connectionIdsToRemove.add(connection.id);
            });
            // Auto-delete conditional edge nodes that lose their source connection
            for (const conn of flow.connections) {
                if (!connectionIdsToRemove.has(conn.id)) continue;
                const targetNode = flow.nodes.find((n) => n.id === conn.targetNodeId);
                if (targetNode?.type === NodeType.EDGE) {
                    nodeIdsToRemove.add(targetNode.id);
                }
            }

            // Track removed connections for decision table cleanup
            const removedConnections: ConnectionModel[] = [];

            const updatedConnections = flow.connections.filter((conn) => {
                const isSelected = connectionIdsToRemove.has(conn.id);

                // Check if connection involves any node being removed
                const isOrphaned = nodeIdsToRemove.has(conn.sourceNodeId) || nodeIdsToRemove.has(conn.targetNodeId);

                if (isSelected || isOrphaned) {
                    removedConnections.push(conn);
                    return false; // remove connection
                }

                return true; // keep connection
            });

            const decisionTableUpdates = new Map<string, { table: DecisionTableNode; ports: ViewPort[] }>();

            const normalizeDecisionGroupName = (name: string): string =>
                (name || '').toLowerCase().replace(/\s+/g, '-');

            removedConnections.forEach((conn) => {
                const sourceNode = flow.nodes.find((node) => node.id === conn.sourceNodeId);

                if (
                    !sourceNode ||
                    (sourceNode.type !== NodeType.TABLE && sourceNode.type !== NodeType.CLASSIFICATION_TABLE)
                ) {
                    return;
                }

                const tableData = sourceNode.data.table;

                if (!tableData) {
                    return;
                }

                const existingUpdate = decisionTableUpdates.get(sourceNode.id);
                const updatedTable: DecisionTableNode = existingUpdate?.table ?? {
                    ...tableData,
                    condition_groups: (tableData.condition_groups || []).map((group: ConditionGroup) => ({ ...group })),
                };

                const portId = String(conn.sourcePortId);

                if (portId === `${sourceNode.id}_decision-default`) {
                    updatedTable.default_next_node = null;
                } else if (portId === `${sourceNode.id}_decision-error`) {
                    updatedTable.next_error_node = null;
                } else {
                    const prefix = `${sourceNode.id}_decision-out-`;
                    const routePrefix = `${sourceNode.id}_decision-route-`;
                    if (portId.startsWith(prefix)) {
                        const normalizedGroupKey = portId.slice(prefix.length);
                        updatedTable.condition_groups = updatedTable.condition_groups.map((group) => {
                            const groupKey = normalizeDecisionGroupName(group.group_name);
                            if (groupKey === normalizedGroupKey) {
                                return {
                                    ...group,
                                    next_node: null,
                                } as ConditionGroup;
                            }
                            return group;
                        });
                    } else if (portId.startsWith(routePrefix)) {
                        const normalizedRouteKey = portId.slice(routePrefix.length);
                        updatedTable.condition_groups = updatedTable.condition_groups.map((group) => {
                            const routeKey = (group.route_code || '').toLowerCase().replace(/\s+/g, '-');
                            if (routeKey === normalizedRouteKey) {
                                return {
                                    ...group,
                                    next_node: null,
                                } as ConditionGroup;
                            }
                            return group;
                        });
                    }
                }

                const updatedPorts =
                    sourceNode.type === NodeType.CLASSIFICATION_TABLE
                        ? generatePortsForClassificationDecisionTableNode(sourceNode.id, updatedTable.condition_groups)
                        : generatePortsForDecisionTableNode(
                              sourceNode.id,
                              updatedTable.condition_groups
                              // !!updatedTable.default_next_node,
                              // !!updatedTable.next_error_node
                          );

                decisionTableUpdates.set(sourceNode.id, {
                    table: updatedTable,
                    ports: updatedPorts,
                });
            });

            // Filter out nodes marked for removal
            const updatedNodes = flow.nodes
                .filter((node) => !nodeIdsToRemove.has(node.id))
                .map((node) => {
                    const decisionUpdate = decisionTableUpdates.get(node.id);
                    if (!decisionUpdate) {
                        return node;
                    }

                    if (node.type !== NodeType.TABLE && node.type !== NodeType.CLASSIFICATION_TABLE) return node;

                    return {
                        ...node,
                        data: {
                            ...node.data,
                            table: decisionUpdate.table,
                        },
                        ports: decisionUpdate.ports,
                    } as NodeModel;
                });

            // Create an updated flow state
            return {
                ...flow,
                nodes: updatedNodes,
                connections: updatedConnections,
            };
        });
    }

    /**
     * Replaces oldNodeId with newNode in the flow, remapping edges:
     * - Outgoing decision-default / decision-error edges keep their suffix on newNode.
     * - If options.portIdMap is provided, per-rule outgoing edges whose old port id
     *   exists as a key in portIdMap are remapped to the corresponding new port id.
     * - All other outgoing edges (per-rule ports) are redirected to newNode's
     *   decision-default port when options.mapPerRuleEdgesToDefault is true.
     * - Incoming edges are rebuilt pointing to newNode (same target port role).
     *
     * Uses batched add/remove APIs to produce a single flow-state update per step.
     */
    public replaceNodePreservingEdges(
        oldNodeId: string,
        newNode: NodeModel,
        options: { portIdMap?: Record<string, string>; mapPerRuleEdgesToDefault?: boolean }
    ): void {
        const currentConnections = this.connections();

        // Snapshot edges that touch the old node
        const outgoing = currentConnections.filter((c) => c.sourceNodeId === oldNodeId);
        const incoming = currentConnections.filter((c) => c.targetNodeId === oldNodeId);

        // 1. Add the new node
        this.addNode(newNode);

        // 2. Build replacement edges
        const newEdges: ConnectionModel[] = [];

        outgoing.forEach((edge) => {
            const oldPortId = `${edge.sourcePortId}`;
            let newSourcePortId: CustomPortId;

            if (oldPortId.endsWith('_decision-default')) {
                newSourcePortId = `${newNode.id}_decision-default` as CustomPortId;
            } else if (oldPortId.endsWith('_decision-error')) {
                newSourcePortId = `${newNode.id}_decision-error` as CustomPortId;
            } else if (options.portIdMap?.[oldPortId]) {
                newSourcePortId = options.portIdMap[oldPortId] as CustomPortId;
            } else if (options.mapPerRuleEdgesToDefault) {
                newSourcePortId = `${newNode.id}_decision-default` as CustomPortId;
            } else {
                // Keep the role suffix, replace the node-id prefix
                const role = this.extractPortRole(oldPortId);
                newSourcePortId = role
                    ? (`${newNode.id}_${role}` as CustomPortId)
                    : (`${newNode.id}_decision-default` as CustomPortId);
            }

            const newEdgeId = `${newSourcePortId}+${edge.targetPortId}`;
            // Deduplicate: skip if we already built an edge with this id
            if (newEdges.some((e) => e.id === newEdgeId)) {
                return;
            }

            newEdges.push({
                id: newEdgeId,
                category: edge.category,
                sourceNodeId: newNode.id,
                targetNodeId: edge.targetNodeId,
                sourcePortId: newSourcePortId,
                targetPortId: edge.targetPortId,
                behavior: edge.behavior,
                type: edge.type,
                startColor: edge.startColor,
                endColor: edge.endColor,
                data: null,
            });
        });

        incoming.forEach((edge) => {
            const role = this.extractPortRole(`${edge.targetPortId}`);
            const newTargetPortId = role ? (`${newNode.id}_${role}` as CustomPortId) : edge.targetPortId;

            const newEdgeId = `${edge.sourcePortId}+${newTargetPortId}`;
            if (newEdges.some((e) => e.id === newEdgeId)) {
                return;
            }

            newEdges.push({
                id: newEdgeId,
                category: edge.category,
                sourceNodeId: edge.sourceNodeId,
                targetNodeId: newNode.id,
                sourcePortId: edge.sourcePortId,
                targetPortId: newTargetPortId,
                behavior: edge.behavior,
                type: edge.type,
                startColor: edge.startColor,
                endColor: edge.endColor,
                data: null,
            });
        });

        // 3. Remove old edges (all that touched the old node)
        const oldEdgeIds = [...outgoing, ...incoming].map((e) => e.id);
        if (oldEdgeIds.length > 0) {
            this.removeConnectionsInBatch(oldEdgeIds);
        }

        // 4. Remove old node
        this.flowSignal.update((flow: FlowModel) => ({
            ...flow,
            nodes: flow.nodes.filter((n) => n.id !== oldNodeId),
        }));

        // 5. Add new edges in batch
        if (newEdges.length > 0) {
            this.addConnectionsInBatch(newEdges);
        }
    }

    // Compute a mapping from each port id to an array of eligible connection port ids.
    // This is automatically recomputed when nodes or connections change.
    public portConnectionsMap = computed((): Record<CustomPortId, CustomPortId[]> => {
        const nodes = this.flowSignal().nodes;
        const connections = this.flowSignal().connections;

        const allPorts: FlattenedPort[] = [];
        nodes.forEach((node) => {
            // Add null check before calling forEach
            if (node.ports) {
                node.ports.forEach((port: ViewPort) => {
                    allPorts.push({ nodeId: node.id, port });
                });
            }
        });

        const connectionCount: Record<CustomPortId, number> = {};
        connections.forEach((conn) => {
            connectionCount[conn.sourcePortId] = (connectionCount[conn.sourcePortId] || 0) + 1;
            connectionCount[conn.targetPortId] = (connectionCount[conn.targetPortId] || 0) + 1;
        });

        const map: Record<CustomPortId, CustomPortId[]> = {};
        allPorts.forEach((current) => {
            // Start with an empty set so we don't include the port itself
            const eligible = new Set<CustomPortId>();

            const currentConnCount = connectionCount[current.port.id] || 0;
            if (!current.port.multiple && currentConnCount > 0) {
                // If already connected and single-use, no allowed connections.
                map[current.port.id] = ['__none__'];
                return;
            }

            allPorts.forEach((other) => {
                // Skip self
                if (current.port.id === other.port.id) return;

                // Pass the full connections array to our updated canPortsConnect check.
                if (this.canPortsConnect(current, other)) {
                    const otherConnCount = connectionCount[other.port.id] || 0;
                    if (!other.port.multiple && otherConnCount > 0) {
                        return;
                    }
                    eligible.add(other.port.id);
                }
            });

            const result = Array.from(eligible);
            // If no eligible ports found, add a dummy value that will never match.
            if (result.length === 0) {
                result.push('__none__');
            }
            map[current.port.id] = result;
        });
        return map;
    });
}
