import { Injectable } from '@angular/core';
import { ICurrentSelection } from '@foblex/flow';
import { generateUuid } from '@shared/utils';

import { NodeType } from '../core/enums/node-type';
import { generateMultipleNodeDisplayNames } from '../core/helpers/generate-node-display-name.util';
import { generatePortsForNode, parsePortId } from '../core/helpers/helpers';
import { CdtSection } from '../core/models/cdt-section.model';
import { ConnectionModel } from '../core/models/connection.model';
import { ClassificationDecisionTableNodeModel, DecisionTableNodeModel, NodeModel } from '../core/models/node.model';
import { CustomPortId, ViewPort } from '../core/models/port.model';
import { FlowService } from './flow.service';

interface ClipboardData {
    nodes: NodeModel[];
    connections: ConnectionModel[];
    boundingBox: { minX: number; minY: number };
}

@Injectable({
    providedIn: 'root',
})
export class ClipboardService {
    private clipboard: ClipboardData | null = null;

    constructor(private flowService: FlowService) {}

    public setClipboardData(data: ClipboardData): void {
        this.clipboard = data;
    }

    public getClipboardData(): ClipboardData | null {
        return this.clipboard;
    }

    public copy(selection: ICurrentSelection): void {
        if (!selection || selection.fNodeIds.length === 0) {
            return;
        }

        const allNodes: NodeModel[] = this.flowService.getFlowState().nodes;

        const selectedNodes: NodeModel[] = allNodes.filter(
            (node) => selection.fNodeIds.includes(node.id) && node.type !== NodeType.START && node.type !== NodeType.END
        );

        if (selectedNodes.length === 0) {
            return;
        }

        const minX: number = Math.min(...selectedNodes.map((el) => el.position.x));
        const minY: number = Math.min(...selectedNodes.map((el) => el.position.y));

        const selectedNodeIdSet = new Set<string>(selectedNodes.map((n) => n.id));

        const allConnections: ConnectionModel[] = this.flowService.getFlowState().connections;
        const selectedConnections: ConnectionModel[] = allConnections.filter((conn) => {
            const sourceParsed = parsePortId(conn.sourcePortId);
            const targetParsed = parsePortId(conn.targetPortId);
            if (!sourceParsed || !targetParsed) return false;

            const sourceInSelection = selectedNodeIdSet.has(sourceParsed.nodeId);
            const targetInSelection = selectedNodeIdSet.has(targetParsed.nodeId);

            return sourceInSelection && targetInSelection;
        });

        this.clipboard = {
            nodes: selectedNodes.map((node) => ({
                ...node,
                data: node.data ? JSON.parse(JSON.stringify(node.data)) : node.data,
                ports: node.ports ? [...node.ports] : node.ports,
                position: { ...node.position },
            })),
            connections: selectedConnections.map((conn) => ({ ...conn })),
            boundingBox: { minX, minY },
        };
    }

    public paste(mousePosition: { x: number; y: number }): {
        newNodes: NodeModel[];
        newConnections: ConnectionModel[];
    } {
        if (!this.clipboard) {
            return { newNodes: [], newConnections: [] };
        }

        const { nodes: clipboardNodes, connections: clipboardConnections, boundingBox } = this.clipboard;

        if (clipboardNodes.length === 0) {
            return { newNodes: [], newConnections: [] };
        }

        const offsetX = mousePosition.x - boundingBox.minX;
        const offsetY = mousePosition.y - boundingBox.minY;

        const oldToNewIdMap = new Map<string, string>();
        const newNodeIds: string[] = clipboardNodes.map((oldNode) => {
            const newNodeId = generateUuid();
            oldToNewIdMap.set(oldNode.id, newNodeId);
            return newNodeId;
        });

        // Assign sequential badge numbers and generate names in one pass
        const nodesToCreate = clipboardNodes.map((oldNode) => ({
            type: oldNode.type,
            data: oldNode.data,
        }));
        const nodeNumbers = nodesToCreate.map(() => this.flowService.getNextNodeNumber());
        const displayNames = generateMultipleNodeDisplayNames(nodesToCreate, nodeNumbers);

        // Create new nodes with backendId: null for diff-save support
        const newNodes: NodeModel[] = clipboardNodes.map((oldNode, index) => {
            const newNodeId = newNodeIds[index];

            // Deep-clone data so per-paste mutations don't leak into the clipboard
            const newData = oldNode.data ? JSON.parse(JSON.stringify(oldNode.data)) : oldNode.data;
            // DT next-node refs are repopulated below via FlowService.addConnection's hook
            this.clearDecisionTableNextNodeRefs(oldNode.type, newData);
            // CDT sections must get fresh ids on paste so they don't collide with the
            // copied node's sections within the same graph.
            this.regenerateCdtSectionIds(oldNode.type, newData);

            const newPorts: ViewPort[] = generatePortsForNode(newNodeId, oldNode.type, newData);

            return {
                ...oldNode,
                id: newNodeId,
                backendId: null,
                nodeNumber: nodeNumbers[index],
                position: {
                    x: oldNode.position.x + offsetX,
                    y: oldNode.position.y + offsetY,
                },
                ports: newPorts,
                node_name: displayNames[index],
                data: newData,
            };
        });

        const newConnections = clipboardConnections
            .map((oldConn) => {
                const newSourceNodeId = oldToNewIdMap.get(oldConn.sourceNodeId);
                const newTargetNodeId = oldToNewIdMap.get(oldConn.targetNodeId);

                if (!newSourceNodeId || !newTargetNodeId) {
                    return null;
                }

                const sourcePortParts = oldConn.sourcePortId.split('_');
                const targetPortParts = oldConn.targetPortId.split('_');

                if (sourcePortParts.length < 2 || targetPortParts.length < 2) {
                    return null;
                }

                const newSourcePortId = `${newSourceNodeId}_${sourcePortParts[1]}`;
                const newTargetPortId = `${newTargetNodeId}_${targetPortParts[1]}`;
                const newConnectionId = `${newSourcePortId}+${newTargetPortId}`;

                return {
                    id: newConnectionId,
                    sourceNodeId: newSourceNodeId,
                    targetNodeId: newTargetNodeId,
                    sourcePortId: newSourcePortId as CustomPortId,
                    targetPortId: newTargetPortId as CustomPortId,
                };
            })
            .filter((conn) => conn !== null) as ConnectionModel[];

        const currentFlow = this.flowService.getFlowState();

        // Add nodes first so addConnection's DT-sync hook can resolve source/target by id
        this.flowService.setFlow({
            ...currentFlow,
            nodes: [...currentFlow.nodes, ...newNodes],
        });

        // Route each new connection through addConnection so updateDecisionTableNextNodeFromConnection
        // repopulates the copied DT's data.table.*_node refs from the (already-remapped) target ids
        for (const conn of newConnections) {
            this.flowService.addConnection(conn);
        }

        // Return hook-updated nodes from flow state — otherwise the caller's downstream updateNode
        // (positioning) would overwrite the freshly-synced data.table.* refs with the pre-hook nulls
        const finalNodeById = new Map(this.flowService.nodes().map((n) => [n.id, n]));
        const returnedNodes = newNodes.map((n) => finalNodeById.get(n.id) ?? n);

        return { newNodes: returnedNodes, newConnections };
    }

    private clearDecisionTableNextNodeRefs(type: NodeType, data: NodeModel['data'] | null): void {
        if (type !== NodeType.TABLE || !data) return;

        const table = (data as DecisionTableNodeModel['data']).table;
        if (!table) return;

        table.default_next_node = null;
        table.next_error_node = null;
        if (Array.isArray(table.condition_groups)) {
            for (const group of table.condition_groups) {
                group.next_node = null;
            }
        }
    }

    private regenerateCdtSectionIds(type: NodeType, data: NodeModel['data'] | null): void {
        if (type !== NodeType.CLASSIFICATION_TABLE || !data) return;

        const table = (data as ClassificationDecisionTableNodeModel['data']).table;
        if (!table) return;

        const sections: CdtSection[] = Array.isArray(table.sections) ? table.sections : [];
        if (sections.length === 0) return;

        const idMap = new Map<string, string>();
        table.sections = sections.map((section: CdtSection) => {
            const newId = generateUuid();
            idMap.set(section.id, newId);
            return { ...section, id: newId };
        });

        if (Array.isArray(table.condition_groups)) {
            for (const group of table.condition_groups) {
                group.section = group.section ? (idMap.get(group.section) ?? null) : null;
            }
        }
    }
}
