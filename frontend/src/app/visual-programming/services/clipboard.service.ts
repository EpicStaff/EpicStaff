import { Injectable } from '@angular/core';
import { FlowService } from './flow.service';

import { NodeModel } from '../core/models/node.model';
import { ConnectionModel } from '../core/models/connection.model';

import { v4 as uuidv4 } from 'uuid';
import { FSelectionChangeEvent } from '@foblex/flow';
import { CustomPortId, ViewPort } from '../core/models/port.model';
import {
    parsePortId,
    getPortsForType,
    generatePortsForNode,
} from '../core/helpers/helpers';
import { NodeType } from '../core/enums/node-type';

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

    public copy(selection: FSelectionChangeEvent): void {
        if (
            !selection ||
            selection.fNodeIds.length === 0
        ) {
            return;
        }

        const allNodes: NodeModel[] = this.flowService.getFlowState().nodes;

        const selectedNodes: NodeModel[] = allNodes.filter(
            (node) =>
                selection.fNodeIds.includes(node.id) &&
                node.type !== NodeType.START
        );

        if (selectedNodes.length === 0) {
            return;
        }

        const minX: number = Math.min(
            ...selectedNodes.map((el) => el.position.x)
        );
        const minY: number = Math.min(
            ...selectedNodes.map((el) => el.position.y)
        );

        const selectedNodeIdSet = new Set<string>(
            selectedNodes.map((n) => n.id)
        );

        const allConnections: ConnectionModel[] =
            this.flowService.getFlowState().connections;
        const selectedConnections: ConnectionModel[] = allConnections.filter(
            (conn) => {
                const sourceParsed = parsePortId(conn.sourcePortId);
                const targetParsed = parsePortId(conn.targetPortId);
                if (!sourceParsed || !targetParsed) return false;

                const sourceInSelection =
                    selectedNodeIdSet.has(sourceParsed.nodeId);
                const targetInSelection =
                    selectedNodeIdSet.has(targetParsed.nodeId);

                return sourceInSelection && targetInSelection;
            }
        );

        this.clipboard = {
            nodes: selectedNodes.map((node) => ({
                ...node,
                data: node.data
                    ? JSON.parse(JSON.stringify(node.data))
                    : node.data,
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

        const {
            nodes: clipboardNodes,
            connections: clipboardConnections,
            boundingBox,
        } = this.clipboard;

        if (clipboardNodes.length === 0) {
            return { newNodes: [], newConnections: [] };
        }

        const offsetX = mousePosition.x - boundingBox.minX;
        const offsetY = mousePosition.y - boundingBox.minY;

        const oldToNewIdMap = new Map<string, string>();

        const allNodes = [...this.flowService.getFlowState().nodes];

        const newNodes: NodeModel[] = clipboardNodes.map((oldNode) => {
            const newNodeId = uuidv4();
            oldToNewIdMap.set(oldNode.id, newNodeId);

            const newPorts: ViewPort[] = generatePortsForNode(
                newNodeId,
                oldNode.type
            );

            const newName = this.deriveUniqueName(oldNode.node_name, oldNode.type, allNodes);

            const newNode = {
                ...oldNode,
                id: newNodeId,
                backendId: null,
                position: {
                    x: oldNode.position.x + offsetX,
                    y: oldNode.position.y + offsetY,
                },
                ports: newPorts,
                parentId: null,
                node_name: newName,
            };

            allNodes.push(newNode);

            return newNode;
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

        this.flowService.setFlow({
            ...currentFlow,
            nodes: [...currentFlow.nodes, ...newNodes],
            connections: [...currentFlow.connections, ...newConnections],
        });

        return { newNodes, newConnections };
    }

    private deriveUniqueName(
        originalName: string,
        nodeType: NodeType,
        allNodes: NodeModel[]
    ): string {
        const count = allNodes.filter((n) => n.type === nodeType).length + 1;
        return `${originalName} (#${count})`;
    }
}
