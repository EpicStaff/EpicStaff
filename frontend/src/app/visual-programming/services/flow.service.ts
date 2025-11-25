import { Injectable, signal, computed } from '@angular/core';
import { Observable, of } from 'rxjs';
import { delay, map } from 'rxjs/operators';
import { FlowModel } from '../core/models/flow.model';
import {
    DecisionTableNodeModel,
    NodeModel,
    StartNodeModel,
} from '../core/models/node.model';
import { ConnectionModel } from '../core/models/connection.model';

import { IPoint, IRect } from '@foblex/2d';
import { CustomPortId, ViewPort } from '../core/models/port.model';
import {
    DecisionTableNode,
    ConditionGroup,
} from '../core/models/decision-table.model';
import { generatePortsForDecisionTableNode } from '../core/helpers/helpers';

import { NodeType } from '../core/enums/node-type';
import { FDropToGroupEvent } from '@foblex/flow';
import { GroupNodeModel } from '../core/models/group.model';

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
        groups: [],
    });

    public readonly nodes = computed(() => this.flowSignal().nodes);
    public readonly connections = computed(() => this.flowSignal().connections);
    public readonly groups = computed(() => this.flowSignal().groups);

    public readonly noteNodes = computed(() =>
        this.nodes().filter((node) => node.type === NodeType.NOTE)
    );

    public readonly startNodeInitialState = computed(() => {
        const startNode: StartNodeModel | undefined = this.nodes().find(
            (node) => node.type === NodeType.START
        );
        return startNode?.data?.initialState || {};
    });

    // Whether there is at least one End node in the flow
    public readonly hasEndNode = computed(() =>
        this.nodes().some((node) => node.type === NodeType.END)
    );

    // Generic helper to check if any node of a type exists
    public hasNodeType(type: NodeType): boolean {
        return this.nodes().some((node) => node.type === type);
    }

    public visibleConnections = computed(() => {
        const connections = this.connections();
        const groups = this.groups();

        // Get all collapsed groups
        const collapsedGroups = groups.filter((g) => g.collapsed);

        if (collapsedGroups.length === 0) {
            return connections;
        }

        // Find connections that should be hidden
        const hiddenConnectionIds = new Set<string>();

        // Step 1: Hide all original connections stored in collapsed groups
        // (but only if they still exist in the connections array)
        collapsedGroups.forEach((group) => {
            const connectionData = group.data?.connectionData;
            if (connectionData) {
                connectionData.inputs?.forEach((conn) => {
                    if (connections.some((c) => c.id === conn.id)) {
                        hiddenConnectionIds.add(conn.id);
                    }
                });

                connectionData.outputs?.forEach((conn) => {
                    if (connections.some((c) => c.id === conn.id)) {
                        hiddenConnectionIds.add(conn.id);
                    }
                });

                connectionData.internal?.forEach((conn) => {
                    if (connections.some((c) => c.id === conn.id)) {
                        hiddenConnectionIds.add(conn.id);
                    }
                });
            }
        });

        // Step 2: Hide virtual connections for descendants of collapsed groups
        const descendantsOfCollapsedGroups = new Set<string>();

        // Build set of all groups that are inside any collapsed group
        collapsedGroups.forEach((group) => {
            const descendants = this.getAllDescendantIds(group.id);
            descendants.forEach((id) => descendantsOfCollapsedGroups.add(id));
        });

        // Hide virtual connections for any group that's a descendant of a collapsed group
        connections.forEach((conn) => {
            // Check if this is a virtual connection
            if (
                conn.sourcePortId.includes('group-') ||
                conn.targetPortId.includes('group-')
            ) {
                // Get the group IDs from the connection
                const sourceGroupId = conn.sourceNodeId;
                const targetGroupId = conn.targetNodeId;

                // If either end is a descendant of a collapsed group, hide it
                if (
                    descendantsOfCollapsedGroups.has(sourceGroupId) ||
                    descendantsOfCollapsedGroups.has(targetGroupId)
                ) {
                    hiddenConnectionIds.add(conn.id);
                }
            }
        });

        // Return filtered connections
        return connections.filter((conn) => !hiddenConnectionIds.has(conn.id));
    });
    // Add this computed property to your FlowService class
    public visibleGroups = computed(() => {
        const groups = this.groups();

        // Create a map of collapsed group IDs for quick lookup
        const collapsedGroups = new Map<string, GroupNodeModel>();
        groups.forEach((group) => {
            if (group.collapsed) {
                collapsedGroups.set(group.id, group);
            }
        });

        // Skip filtering if no collapsed groups
        if (collapsedGroups.size === 0) {
            return groups;
        }

        // Helper function to check if a group is inside a collapsed group
        const isInsideCollapsedGroup = (
            groupParentId: string | null
        ): boolean => {
            if (!groupParentId) return false;

            // Check if direct parent is collapsed
            if (collapsedGroups.has(groupParentId)) {
                return true;
            }

            // If parent group exists, check its parent recursively
            const parentGroup = groups.find((g) => g.id === groupParentId);
            if (parentGroup && parentGroup.parentId) {
                return isInsideCollapsedGroup(parentGroup.parentId);
            }

            return false;
        };

        // Filter groups
        return groups.filter(
            (group) => !isInsideCollapsedGroup(group.parentId)
        );
    });
    public visibleNodes = computed(() => {
        const nodes = this.nodes();
        const groups = this.groups();

        // Create a map of collapsed group IDs for quick lookup
        const collapsedGroups = new Map<string, GroupNodeModel>();
        groups.forEach((group) => {
            if (group.collapsed) {
                collapsedGroups.set(group.id, group);
            }
        });

        // Skip filtering if no collapsed groups
        const filteredByGroups =
            collapsedGroups.size === 0
                ? nodes
                : nodes.filter(
                      (node) =>
                          !this.isInsideCollapsedGroup(
                              node.parentId,
                              groups,
                              collapsedGroups
                          )
                  );

        // Additionally filter out nodes with category 'vscode'
        return filteredByGroups.filter((node) => node.category !== 'vscode');
    });

    // Helper method for the recursion (extract from the visibleNodes computed)
    private isInsideCollapsedGroup(
        nodeParentId: string | null,
        groups: GroupNodeModel[],
        collapsedGroups: Map<string, GroupNodeModel>
    ): boolean {
        if (!nodeParentId) return false;

        // Check if direct parent is collapsed
        if (collapsedGroups.has(nodeParentId)) {
            return true;
        }

        // If parent group exists, check its parent recursively
        const parentGroup = groups.find((g) => g.id === nodeParentId);
        if (parentGroup && parentGroup.parentId) {
            return this.isInsideCollapsedGroup(
                parentGroup.parentId,
                groups,
                collapsedGroups
            );
        }

        return false;
    }

    // Add a new computed property for vscode nodes
    public vscodeNodes = computed(() => {
        return this.nodes().filter((node) => node.category === 'vscode');
    });
    // Selector to get connections for a given port.
    public getConnectionsForPort(portId: CustomPortId): CustomPortId[] {
        return this.portConnectionsMap()[portId] || [];
    }

    constructor() {}

    public getFlowState(): FlowModel {
        return this.flowSignal();
    }

    public setFlow(flow: FlowModel) {
        this.flowSignal.set(flow);
    }

    public addGroup(group: GroupNodeModel) {
        this.flowSignal.update((flow: FlowModel) => ({
            ...flow,
            groups: [...flow.groups, group],
        }));
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

        console.log('New connection added to the flow state:', conn);

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

        console.log(`Batch added ${connections.length} connections`);
    }
    public removeConnectionsInBatch(connectionIds: string[]): void {
        if (!connectionIds || connectionIds.length === 0) {
            return;
        }

        this.flowSignal.update((flow: FlowModel) => ({
            ...flow,
            connections: flow.connections.filter(
                (conn) => !connectionIds.includes(conn.id)
            ),
        }));

        console.log(`Batch removed ${connectionIds.length} connections`);

        const remainingConnections = this.connections();
        connectionIds.forEach((connectionId) => {
            this.clearDecisionTableNextNodeForConnection(
                connectionId,
                remainingConnections
            );
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
            this.clearDecisionTableNextNodeForConnection(
                removedConnection.id,
                this.connections()
            );
        }
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

        const validGroupsWithNextNode = groups.filter(
            (group) => group.valid && group.next_node
        );

        validGroupsWithNextNode.forEach((group) => {
            connectionSnapshot = this.ensureDecisionTableConnection(
                tableNodeId,
                group.next_node!,
                `decision-out-${group.group_name}`,
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

            // Log the batch update
            console.log(`Batch updated ${nodes.length} nodes`);

            // Return updated flow state
            return {
                ...flow,
                nodes: updatedNodes,
            };
        });
    }
    public updateNode(
        updatedNode: NodeModel,
        options?: { skipDecisionTableReset?: boolean }
    ) {
        const { skipDecisionTableReset = false } = options || {};
        const currentFlow = this.flowSignal();
        const existingNodeIndex = currentFlow.nodes.findIndex(
            (n) => n.id === updatedNode.id
        );

        const existingNode =
            existingNodeIndex >= 0 ? currentFlow.nodes[existingNodeIndex] : null;

        const shouldResetDecisionTableConnections =
            updatedNode.type === NodeType.TABLE &&
            this.haveDecisionTableTargetsChanged(
                existingNode as DecisionTableNodeModel | null,
                updatedNode as DecisionTableNodeModel
            );

        this.flowSignal.update((flow: FlowModel) => {
            // Find the index of the node to update
            const index: number = flow.nodes.findIndex(
                (n) => n.id === updatedNode.id
            );
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

        if (shouldResetDecisionTableConnections && !skipDecisionTableReset) {
            const tableData = (updatedNode as any)?.data?.table;
            if (tableData) {
                const conditionGroups = tableData.condition_groups || [];
                this.resetDecisionTableConnections(
                    updatedNode.id,
                    conditionGroups,
                    tableData.default_next_node || null,
                    tableData.next_error_node || null
                );
            }
        }
    }

    private haveDecisionTableTargetsChanged(
        previousNode: DecisionTableNodeModel | null,
        updatedNode: DecisionTableNodeModel
    ): boolean {
        if (!updatedNode) {
            return false;
        }

        const previousKey = this.getDecisionTableConnectionsKey(
            previousNode?.data?.table ?? null
        );
        const updatedKey = this.getDecisionTableConnectionsKey(
            updatedNode.data?.table ?? null
        );

        return previousKey !== updatedKey;
    }

    private getDecisionTableConnectionsKey(
        table: DecisionTableNode | null
    ): string {
        if (!table) {
            return '';
        }

        const groupsKey = (table.condition_groups ?? [])
            .filter((group) => group.valid === true && !!group.next_node)
            .map((group) => `${group.group_name ?? ''}::${group.next_node ?? ''}`)
            .sort()
            .join('|');

        const defaultKey = table.default_next_node ?? '';
        const errorKey = table.next_error_node ?? '';

        return `${groupsKey}__default:${defaultKey}__error:${errorKey}`;
    }
    public updateGroupsInBatch(groups: GroupNodeModel[]): void {
        if (!groups || groups.length === 0) {
            return;
        }

        this.flowSignal.update((flow: FlowModel) => {
            // Create a map of group ids to their updated versions for quick lookup
            const groupUpdatesMap = new Map<string, GroupNodeModel>();
            groups.forEach((group) => groupUpdatesMap.set(group.id, group));

            // Create a new groups array with updates applied
            const updatedGroups = flow.groups.map((existingGroup) => {
                // If this group is in our update list, return the updated version
                if (groupUpdatesMap.has(existingGroup.id)) {
                    return groupUpdatesMap.get(existingGroup.id)!;
                }
                // Otherwise return the existing group unchanged
                return existingGroup;
            });

            // Log the batch update
            console.log(`Batch updated ${groups.length} groups`);

            // Return updated flow state
            return {
                ...flow,
                groups: updatedGroups,
            };
        });
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
            const updatedConnections: ConnectionModel[] = flow.connections.map(
                (existingConn) => {
                    if (connUpdatesMap.has(existingConn.id)) {
                        return connUpdatesMap.get(existingConn.id)!;
                    }
                    return existingConn;
                }
            );

            // Log the batch update
            console.log(`Batch updated ${connections.length} connections`);

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
        const targetNode = allNodes.find(
            (n) => n.node_name === targetNodeName || n.id === targetNodeName
        );

        if (!targetNode) {
            console.warn(`Target node not found: ${targetNodeName}`);
            return existingConnections;
        }

        const targetInputPort = targetNode.ports?.find(
            (p: ViewPort) => p.port_type === 'input'
        );

        if (!targetInputPort) {
            console.warn(
                `No input port found on target node: ${targetNode.node_name}`
            );
            return existingConnections;
        }

        const normalizedRole = this.normalizeDecisionPortRole(sourcePortRole);
        const sourcePortId = `${tableNodeId}_${normalizedRole}` as CustomPortId;
        const targetPortId = targetInputPort.id;

        const connectionId = `${sourcePortId}+${targetPortId}`;
        const connectionExists = existingConnections.some(
            (connection) => connection.id === connectionId
        );

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
            };

            this.addConnection(newConnection);

            return [...existingConnections, newConnection];
        }

        return existingConnections;
    }

    private updateDecisionTableNextNodeFromConnection(
        connection: ConnectionModel
    ): void {
        const sourceNode = this.nodes().find(
            (node) => node.id === connection.sourceNodeId
        );

        if (!sourceNode || sourceNode.type !== NodeType.TABLE) {
            return;
        }

        const tableData = (sourceNode as DecisionTableNodeModel).data?.table;
        if (!tableData) {
            return;
        }

        const targetNode = this.nodes().find(
            (node) => node.id === connection.targetNodeId
        );
        if (!targetNode) {
            return;
        }

        const sourcePortRole = this.extractPortRole(connection.sourcePortId);
        if (!sourcePortRole) {
            return;
        }

        const normalizedSourceRole =
            this.normalizeDecisionPortRole(sourcePortRole);

        const updatedTable: DecisionTableNode = {
            ...tableData,
            condition_groups: (tableData.condition_groups || []).map((group) => {
                const normalizedGroupRole = group.group_name
                    ? this.normalizeDecisionPortRole(
                          `decision-out-${group.group_name}`
                      )
                    : null;

                if (normalizedGroupRole === normalizedSourceRole) {
                    return {
                        ...group,
                        next_node:
                            targetNode.node_name || targetNode.id || null,
                    };
                }

                return group;
            }),
        };

        let defaultNextNode = tableData.default_next_node;
        let nextErrorNode = tableData.next_error_node;

        if (normalizedSourceRole === 'decision-default') {
            defaultNextNode = targetNode.node_name || targetNode.id || null;
        } else if (normalizedSourceRole === 'decision-error') {
            nextErrorNode = targetNode.node_name || targetNode.id || null;
        }

        const updatedNode: DecisionTableNodeModel = {
            ...(sourceNode as DecisionTableNodeModel),
            data: {
                ...(sourceNode as DecisionTableNodeModel).data,
                table: {
                    ...updatedTable,
                    default_next_node: defaultNextNode,
                    next_error_node: nextErrorNode,
                },
            },
        };

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

        const sourceNodeId = sourcePortId.split('_')[0];
        const sourceNode = this.nodes().find((node) => node.id === sourceNodeId);

        if (!sourceNode || sourceNode.type !== NodeType.TABLE) {
            return;
        }

        const tableData = (sourceNode as DecisionTableNodeModel).data?.table;
        if (!tableData) {
            return;
        }

        const sourceRole = this.extractPortRole(sourcePortId);
        if (!sourceRole) {
            return;
        }

        const normalizedSourceRole =
            this.normalizeDecisionPortRole(sourceRole);

        const stillConnected = remainingConnections.some((conn) => {
            if (conn.sourceNodeId !== sourceNodeId) {
                return false;
            }
            const connRole = this.extractPortRole(conn.sourcePortId);
            if (!connRole) {
                return false;
            }
            return (
                this.normalizeDecisionPortRole(connRole) === normalizedSourceRole
            );
        });

        if (stillConnected) {
            return;
        }

        const updatedTable: DecisionTableNode = {
            ...tableData,
            condition_groups: (tableData.condition_groups || []).map((group) => {
                const normalizedGroupRole = group.group_name
                    ? this.normalizeDecisionPortRole(
                          `decision-out-${group.group_name}`
                      )
                    : null;
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

        const updatedNode: DecisionTableNodeModel = {
            ...(sourceNode as DecisionTableNodeModel),
            data: {
                ...(sourceNode as DecisionTableNodeModel).data,
                table: {
                    ...updatedTable,
                    default_next_node: defaultNextNode,
                    next_error_node: nextErrorNode,
                },
            },
        };

        this.updateNode(updatedNode, { skipDecisionTableReset: true });
    }

    private normalizeDecisionPortRole(role: string): string {
        if (!role.startsWith('decision-out-')) {
            return role;
        }

        const suffix = role.substring('decision-out-'.length);
        return `decision-out-${suffix.toLowerCase().replace(/\s+/g, '-')}`;
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
        const normalizedSourcePortId =
            this.normalizeDecisionPortId(sourcePortId);

        return `${normalizedSourcePortId}+${targetPortId}`;
    }

    private isGroupPortId(portId: string): boolean {
        const role = this.extractPortRole(portId);
        return role?.startsWith('group-') ?? false;
    }

    private extractPortRole(portId: string): string | null {
        const underscoreIndex = portId.indexOf('_');
        if (underscoreIndex === -1) {
            return null;
        }

        return portId.substring(underscoreIndex + 1);
    }

    private isDecisionTableSourcePort(
        portId: CustomPortId,
        tableNodeId: string
    ): boolean {
        const portIdValue = `${portId}`;
        return portIdValue.startsWith(`${tableNodeId}_decision-`);
    }

    public updateGroup(updatedGroup: GroupNodeModel): void {
        this.flowSignal.update((flow: FlowModel) => {
            // Find the index of the group to update
            const index: number = flow.groups.findIndex(
                (g) => g.id === updatedGroup.id
            );
            if (index < 0) {
                console.warn('Group not found in flow:', updatedGroup.id);
                return flow; // Return unchanged flow if group isn't found
            }

            // Create a new array, replacing just the updated group
            const updatedGroups: GroupNodeModel[] = [...flow.groups];
            updatedGroups[index] = updatedGroup;

            // Return a new FlowModel object (signals need new references)
            return {
                ...flow,
                groups: updatedGroups,
            };
        });
    }

    private canPortsConnect(
        portA: FlattenedPort,
        portB: FlattenedPort,
        connections: ConnectionModel[]
    ): boolean {
        // Prevent connecting ports on the same node.
        if (portA.nodeId === portB.nodeId) {
            return false;
        }

        // If any connection already exists between the two nodes, do not allow any further connections.
        const alreadyConnected = connections.some(
            (conn) =>
                (conn.sourceNodeId === portA.nodeId &&
                    conn.targetNodeId === portB.nodeId) ||
                (conn.sourceNodeId === portB.nodeId &&
                    conn.targetNodeId === portA.nodeId)
        );
        if (alreadyConnected) {
            return false;
        }

        const a = portA.port;
        const b = portB.port;
        if (a.port_type === 'input' && b.port_type === 'output') {
            return a.allowedConnections.includes(b.role);
        }
        if (a.port_type === 'output' && b.port_type === 'input') {
            return b.allowedConnections.includes(a.role);
        }
        if (a.port_type === 'input-output' && b.port_type === 'input-output') {
            return (
                a.allowedConnections.includes(b.role) ||
                b.allowedConnections.includes(a.role)
            );
        }
        return false;
    }
    public deleteSelections(selections: {
        fNodeIds: string[];
        fConnectionIds: string[];
        fGroupIds: string[];
    }): void {
        // Filter out any virtual connections from deletion requests
        this.flowSignal.update((flow: FlowModel) => {
            const nodeIdsToRemove = new Set(selections.fNodeIds);
            const groupIdsToRemove = new Set(selections.fGroupIds);
            const connectionIdsToRemove = new Set<string>();

            const connectionsById = new Map(
                flow.connections.map((conn) => [conn.id, conn] as const)
            );

            selections.fConnectionIds.forEach((originalId) => {
                const normalizedId = this.normalizeConnectionId(originalId);
                const connection =
                    connectionsById.get(normalizedId) ??
                    connectionsById.get(originalId);

                if (!connection) {
                    console.warn(
                        'Connection not found when attempting to delete:',
                        originalId
                    );
                    return;
                }

                const isVirtual =
                    this.isGroupPortId(connection.sourcePortId) ||
                    this.isGroupPortId(connection.targetPortId);

                if (isVirtual) {
                    return;
                }

                connectionIdsToRemove.add(connection.id);
            });

            // Track nodes and groups that need parentId update
            const nodesToUpdate: NodeModel[] = [];
            const groupsToUpdate: GroupNodeModel[] = [];

            // Recursively find all descendants of collapsed groups
            const addAllDescendants = (
                groupId: string,
                isCollapsed: boolean
            ) => {
                flow.nodes.forEach((node) => {
                    if (node.parentId === groupId) {
                        if (isCollapsed) {
                            // If parent group is collapsed, mark node for removal
                            nodeIdsToRemove.add(node.id);
                        } else {
                            // If parent group is expanded, update the parentId to null
                            nodesToUpdate.push({ ...node, parentId: null });
                        }
                    }
                });

                flow.groups.forEach((childGroup) => {
                    if (childGroup.parentId === groupId) {
                        if (isCollapsed) {
                            // If parent group is collapsed, mark group for removal
                            groupIdsToRemove.add(childGroup.id);
                            // Process its descendants
                            addAllDescendants(childGroup.id, true);
                        } else {
                            // If parent group is expanded, update the parentId to null
                            groupsToUpdate.push({
                                ...childGroup,
                                parentId: null,
                            });
                        }
                    }
                });
            };

            // Process all groups that are being deleted
            flow.groups.forEach((group) => {
                if (groupIdsToRemove.has(group.id)) {
                    addAllDescendants(group.id, group.collapsed);
                }
            });

            console.log('Group IDs to remove:', Array.from(groupIdsToRemove));
            console.log('Node IDs to remove:', Array.from(nodeIdsToRemove));
            console.log('Nodes to update:', nodesToUpdate.length);
            console.log('Groups to update:', groupsToUpdate.length);

            // Track removed connection IDs for logging
            const removedConnectionIds: string[] = [];
            const removedConnections: ConnectionModel[] = [];

            const updatedConnections = flow.connections.filter((conn) => {
                const isSelected = connectionIdsToRemove.has(conn.id);

                // Check if connection involves any node or group being removed
                const isOrphaned =
                    nodeIdsToRemove.has(conn.sourceNodeId) ||
                    nodeIdsToRemove.has(conn.targetNodeId) ||
                    groupIdsToRemove.has(conn.sourceNodeId) ||
                    groupIdsToRemove.has(conn.targetNodeId);

                if (isSelected || isOrphaned) {
                    removedConnectionIds.push(conn.id);
                    removedConnections.push(conn);
                    return false; // remove connection
                }

                return true; // keep connection
            });

            console.log('Connection IDs to remove:', removedConnectionIds);

            const decisionTableUpdates = new Map<
                string,
                { table: DecisionTableNode; ports: ViewPort[] }
            >();

            const normalizeDecisionGroupName = (name: string): string =>
                (name || '').toLowerCase().replace(/\s+/g, '-');

            removedConnections.forEach((conn) => {
                const sourceNode = flow.nodes.find(
                    (node) => node.id === conn.sourceNodeId
                );

                if (!sourceNode || sourceNode.type !== NodeType.TABLE) {
                    return;
                }

                const tableData = (sourceNode as any).data
                    ?.table as DecisionTableNode | undefined;
                if (!tableData) {
                    return;
                }

                const existingUpdate = decisionTableUpdates.get(sourceNode.id);
                const updatedTable: DecisionTableNode =
                    existingUpdate?.table ?? {
                        ...tableData,
                        condition_groups: (tableData.condition_groups || []).map(
                            (group) => ({ ...group })
                        ),
                    };

                const portId = String(conn.sourcePortId);

                if (portId === `${sourceNode.id}_decision-default`) {
                    updatedTable.default_next_node = null;
                } else if (portId === `${sourceNode.id}_decision-error`) {
                    updatedTable.next_error_node = null;
                } else {
                    const prefix = `${sourceNode.id}_decision-out-`;
                    if (portId.startsWith(prefix)) {
                        const normalizedGroupKey = portId.slice(prefix.length);
                        updatedTable.condition_groups =
                            updatedTable.condition_groups.map((group) => {
                                const groupKey = normalizeDecisionGroupName(
                                    group.group_name
                                );
                                if (groupKey === normalizedGroupKey) {
                                    return {
                                        ...group,
                                        next_node: null,
                                    } as ConditionGroup;
                                }
                                return group;
                            });
                    }
                }

                const updatedPorts = generatePortsForDecisionTableNode(
                    sourceNode.id,
                    updatedTable.condition_groups,
                    !!updatedTable.default_next_node,
                    !!updatedTable.next_error_node
                );

                decisionTableUpdates.set(sourceNode.id, {
                    table: updatedTable,
                    ports: updatedPorts,
                });
            });

            // Filter out nodes and groups marked for removal
            const updatedNodes = flow.nodes
                .filter((node) => !nodeIdsToRemove.has(node.id))
                .map((node) => {
                     const decisionUpdate = decisionTableUpdates.get(node.id);
                     if (!decisionUpdate) {
                         return node;
                     }

                    const baseNode = node as Record<string, any>;

                    return {
                        ...baseNode,
                        data: {
                            ...(baseNode['data'] || {}),
                            table: decisionUpdate.table,
                        },
                        ports: decisionUpdate.ports,
                    } as NodeModel;
                });

            const updatedGroups = flow.groups.filter(
                (group) => !groupIdsToRemove.has(group.id)
            );

            // Create an updated flow state
            const newFlowState = {
                ...flow,
                nodes: updatedNodes,
                connections: updatedConnections,
                groups: updatedGroups,
            };

            // Schedule batch updates for nodes and groups that need parentId updates
            setTimeout(() => {
                if (nodesToUpdate.length > 0) {
                    this.updateNodesInBatch(nodesToUpdate);
                }

                if (groupsToUpdate.length > 0) {
                    this.updateGroupsInBatch(groupsToUpdate);
                }
            }, 0);

            return newFlowState;
        });
    }

    // Helper method in FlowService
    public getAllDescendantIds(groupId: string): Set<string> {
        const descendantIds = new Set<string>();
        const allNodes = this.nodes();
        const allGroups = this.groups();

        // Recursive function to add descendants
        const addDescendants = (parentId: string) => {
            // Add direct child nodes
            allNodes.forEach((node) => {
                if (node.parentId === parentId) {
                    descendantIds.add(node.id);
                }
            });

            // Add and process child groups
            allGroups.forEach((group) => {
                if (group.parentId === parentId) {
                    descendantIds.add(group.id);
                    // Recursively process this group's children
                    addDescendants(group.id);
                }
            });
        };

        // Start recursion
        addDescendants(groupId);

        return descendantIds;
    }

    // Compute a mapping from each port id to an array of eligible connection port ids.
    // This is automatically recomputed when nodes or connections change.
    public portConnectionsMap = computed(
        (): Record<CustomPortId, CustomPortId[]> => {
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
                connectionCount[conn.sourcePortId] =
                    (connectionCount[conn.sourcePortId] || 0) + 1;
                connectionCount[conn.targetPortId] =
                    (connectionCount[conn.targetPortId] || 0) + 1;
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
                    if (this.canPortsConnect(current, other, connections)) {
                        const otherConnCount =
                            connectionCount[other.port.id] || 0;
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
        }
    );
}
