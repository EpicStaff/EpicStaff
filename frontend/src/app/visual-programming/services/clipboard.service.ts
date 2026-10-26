import { Injectable } from '@angular/core';
import { ICurrentSelection } from '@foblex/flow';
import { NodeType } from '@shared/models';
import { generateUuid } from '@shared/utils';

import { generatePortsForNode, parsePortId } from '../core/helpers/helpers';
import { isNumberedNodeType } from '../core/helpers/node-number.util';
import { AgentNodeTaskUi } from '../core/models/agent-node.model';
import { CdtSection } from '../core/models/cdt-section.model';
import { ConnectionModel } from '../core/models/connection.model';
import {
    AgentNodeModel,
    ClassificationDecisionTableNodeModel,
    DecisionTableNodeModel,
    NodeModel,
} from '../core/models/node.model';
import { CustomPortId, ViewPort } from '../core/models/port.model';
import { FlowService } from './flow.service';

export interface ClipboardData {
    nodes: NodeModel[];
    connections: ConnectionModel[];
    boundingBox: { minX: number; minY: number };
}

export interface PasteResult {
    newNodes: NodeModel[];
    newConnections: ConnectionModel[];
    skippedNodeCount: number;
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

    /**
     * Adds a copy of the clipboard at `mousePosition`, keeping the copied nodes' layout. Nodes `canPaste`
     * rejects (e.g. trigger nodes the user may not add) are left out with their connections, and counted
     * in `skippedNodeCount`.
     */
    public paste(
        mousePosition: { x: number; y: number },
        canPaste: (node: NodeModel) => boolean = () => true
    ): PasteResult {
        if (!this.clipboard) {
            return { newNodes: [], newConnections: [], skippedNodeCount: 0 };
        }
        return this.pasteData(this.clipboard, mousePosition, canPaste);
    }

    /**
     * Adds `data` to the flow as new, unsaved nodes at `position`, keeping their layout: fresh ids,
     * `backendId: null`, new numbers. Shared by paste and partial import.
     */
    public pasteData(
        data: ClipboardData,
        position: { x: number; y: number },
        canPaste: (node: NodeModel) => boolean = () => true
    ): PasteResult {
        const { connections: clipboardConnections, boundingBox } = data;
        const clipboardNodes = data.nodes.filter(canPaste);
        const skippedNodeCount = data.nodes.length - clipboardNodes.length;

        if (clipboardNodes.length === 0) {
            return { newNodes: [], newConnections: [], skippedNodeCount };
        }

        const offsetX = position.x - boundingBox.minX;
        const offsetY = position.y - boundingBox.minY;

        const oldToNewIdMap = new Map<string, string>();
        const newNodeIds: string[] = clipboardNodes.map((oldNode) => {
            const newNodeId = generateUuid();
            oldToNewIdMap.set(oldNode.id, newNodeId);
            return newNodeId;
        });

        const newNumberByOldId = this.assignNewNodeNumbers(clipboardNodes);

        // Create new nodes with backendId: null for diff-save support
        const newNodes: NodeModel[] = clipboardNodes.map((oldNode, index) => {
            const newNodeId = newNodeIds[index];

            // Deep-clone data so per-paste mutations don't leak into the clipboard
            const newData = oldNode.data ? JSON.parse(JSON.stringify(oldNode.data)) : oldNode.data;
            // DT and CDT next-node refs are repopulated below via FlowService.addConnection's hook
            this.clearDecisionTableNextNodeRefs(oldNode.type, newData);
            // CDT sections must get fresh ids on paste so they don't collide with the
            // copied node's sections within the same graph.
            this.regenerateCdtSectionIds(oldNode.type, newData);
            // Task ids belong to the source node's rows: sent with the copy, a task's context would link
            // to the source's tasks, and the save would never give the copy's tasks their own ids.
            this.resetAgentTaskIds(oldNode.type, newData);

            const newPorts: ViewPort[] = generatePortsForNode(newNodeId, oldNode.type, newData);

            // The copy keeps its name (names may repeat); the number, which tells the two apart, is new.
            return {
                ...oldNode,
                id: newNodeId,
                backendId: null,
                nodeNumber: newNumberByOldId.get(oldNode.id),
                position: {
                    x: oldNode.position.x + offsetX,
                    y: oldNode.position.y + offsetY,
                },
                ports: newPorts,
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

        return { newNodes: returnedNodes, newConnections, skippedNodeCount };
    }

    /**
     * Issues new numbers to the numbered nodes in ascending order of their source number, so the copies
     * keep the originals' relative order whatever order the selection came in. Nodes without a source
     * number go last; ties keep clipboard order.
     */
    private assignNewNodeNumbers(clipboardNodes: NodeModel[]): Map<string, number> {
        const sourceNumber = (node: NodeModel): number => node.nodeNumber ?? Number.MAX_SAFE_INTEGER;
        const newNumberByOldId = new Map<string, number>();

        clipboardNodes
            .filter((node) => isNumberedNodeType(node.type))
            .sort((first, second) => sourceNumber(first) - sourceNumber(second))
            .forEach((node) => newNumberByOldId.set(node.id, this.flowService.getNextNodeNumber()));

        return newNumberByOldId;
    }

    private clearDecisionTableNextNodeRefs(type: NodeType, data: NodeModel['data'] | null): void {
        if ((type !== NodeType.TABLE && type !== NodeType.CLASSIFICATION_TABLE) || !data) return;

        const table = (data as DecisionTableNodeModel['data'] | ClassificationDecisionTableNodeModel['data']).table;
        if (!table) return;

        table.default_next_node = null;
        table.next_error_node = null;
        if (Array.isArray(table.condition_groups)) {
            for (const group of table.condition_groups) {
                group.next_node = null;
            }
        }
    }

    private resetAgentTaskIds(type: NodeType, data: NodeModel['data'] | null): void {
        if (type !== NodeType.AGENT || !data) return;

        const agentData = data as AgentNodeModel['data'];
        if (!Array.isArray(agentData.tasks)) return;

        const newTempIdByOldId = new Map<number, string>();
        const newTempIdByOldTempId = new Map<string, string>();
        const tasks: AgentNodeTaskUi[] = agentData.tasks.map((task) => {
            const tempId = generateUuid();
            if (task.id != null) newTempIdByOldId.set(task.id, tempId);
            newTempIdByOldTempId.set(task.tempId, tempId);
            return { ...task, id: undefined, tempId };
        });

        agentData.tasks = tasks.map((task) => ({
            ...task,
            contextRefs: (task.contextRefs ?? [])
                .map((ref) => ({
                    tempId: ref.id != null ? newTempIdByOldId.get(ref.id) : newTempIdByOldTempId.get(ref.tempId ?? ''),
                }))
                .filter((ref) => ref.tempId != null),
        }));
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
