import { inject, Injectable, signal } from '@angular/core';
import { FFlowComponent, FReassignConnectionEvent } from '@foblex/flow';
import { NodeType } from '@shared/models';

import { ToastService } from '../../services/notifications';
import { CDT_ROUTE_CONTINUE_COPY } from '../components/node-panels/classification-decision-table-node-panel/cdt.constants';
import { isRoutePortBlockedByContinue } from '../components/node-panels/classification-decision-table-node-panel/cdt-route-continue.util';
import { isConnectionValid } from '../core/helpers/helpers';
import { ConnectionModel } from '../core/models/connection.model';
import { CustomPortId } from '../core/models/port.model';
import { FlowService } from '../services/flow.service';
import { UndoRedoService } from '../services/undo-redo.service';
import { createFlowConnection } from '../utils/connection.factory';
import { FlowRoutingOrchestratorService } from './flow-routing-orchestrator.service';

interface ConnectionEndGrab {
    connection: ConnectionModel;
    group: ConnectionModel[];
    endpoint: 'source' | 'target';
    fromPort: boolean;
}

/**
 * Callbacks the component provides so the handler can interact with
 * the host view without holding component-level references directly.
 */
export interface ReassignHandlerCallbacks {
    detectChanges(): void;
    queryConnectionElement(connectionId: string): Element | null;
}

/**
 * Handles connection reassignment logic for the flow editor.
 *
 * Manages the grab → suppress → reassign lifecycle when a user drags
 * a connection endpoint to a different port.
 *
 * Provided at the FlowGraphComponent level — one instance per editor.
 */
@Injectable()
export class FlowReassignHandlerService {
    private readonly flowService = inject(FlowService);
    private readonly undoRedoService = inject(UndoRedoService);
    private readonly toastService = inject(ToastService);
    private readonly routingOrchestrator = inject(FlowRoutingOrchestratorService);

    // ── State ────────────────────────────────────────────────────────
    readonly suppressedConnectionIds = signal<ReadonlySet<string>>(new Set<string>());
    readonly followerIds = signal<ReadonlySet<string>>(new Set<string>());
    private groupIds: string[] = [];

    // ── Public API ───────────────────────────────────────────────────

    /**
     * Called from the component's `(mousedown)` handler.
     * Resolves the grab, records the group, suppresses neighbours,
     * and redirects the mouse event onto the drag handle when the
     * grab originates from a port.
     */
    handleMouseDown(
        event: MouseEvent,
        isEditingLocked: boolean,
        fFlowComponent: FFlowComponent,
        callbacks: ReassignHandlerCallbacks
    ): void {
        const isPlainPress = event.button === 0 && !event.shiftKey && !event.ctrlKey && !event.metaKey;
        const grab = isPlainPress && !isEditingLocked ? this.resolveConnectionEndGrab(event, fFlowComponent) : null;

        this.groupIds = grab?.group.map((conn) => conn.id) ?? [];
        this.suppressNeighbours(grab, callbacks);

        if (!grab?.fromPort) {
            return;
        }

        const connectionElement = callbacks.queryConnectionElement(grab.connection.id);
        const handle = connectionElement && this.getDragHandle(connectionElement, grab.endpoint);
        if (!handle) {
            return;
        }

        const { left, top, width, height } = handle.getBoundingClientRect();
        // Foblex starts a reassign only when mousedown lands on a connection drag handle,
        // so the grab point is moved onto it.
        Object.defineProperties(event, {
            clientX: { value: left + width / 2 },
            clientY: { value: top + height / 2 },
        });
    }

    /**
     * Handles `FReassignConnectionEvent` from Foblex.
     * Validates and applies the reassignment for one or more grouped connections.
     * Returns `true` when at least one connection was reassigned.
     */
    onReassignConnection(event: FReassignConnectionEvent): boolean {
        const existingConnection = this.flowService.connections().find((conn) => conn.id === event.connectionId);

        if (!existingConnection) {
            console.warn('Connection not found for reassignment:', event.connectionId);
            return false;
        }

        const groupIdSet = new Set(
            this.groupIds.includes(existingConnection.id) ? this.groupIds : [existingConnection.id]
        );
        this.groupIds = [];

        const isSourceMoved = event.endpoint === 'source';
        const nextPortId = (isSourceMoved ? event.nextSourceId : event.nextTargetId) as CustomPortId | undefined;
        const currentPortId = isSourceMoved ? existingConnection.sourcePortId : existingConnection.targetPortId;
        if (!nextPortId || nextPortId === currentPortId) {
            return false;
        }

        const connections = this.flowService.connections();
        const moved = connections.filter((conn) => groupIdSet.has(conn.id));
        const updated: ConnectionModel[] = [];
        const occupied = connections.filter((conn) => !groupIdSet.has(conn.id));

        for (const conn of moved) {
            const sourcePortId = isSourceMoved ? nextPortId : conn.sourcePortId;
            const targetPortId = isSourceMoved ? conn.targetPortId : nextPortId;
            const error = this.getReassignError(sourcePortId, targetPortId, [...occupied, ...updated]);
            if (error) {
                this.toastService.warning(error, 5000, 'bottom-right');
                return false;
            }
            updated.push(
                createFlowConnection(sourcePortId.split('_')[0], targetPortId.split('_')[0], sourcePortId, targetPortId)
            );
        }

        this.undoRedoService.stateChanged();

        moved.forEach((conn) => this.flowService.removeConnection(conn.id));
        updated.forEach((conn) => this.flowService.addConnection(conn));
        this.routingOrchestrator.rerouteSegmentConnections();

        this.toastService.success(
            updated.length > 1 ? `${updated.length} connections reassigned` : 'Connection reassigned successfully',
            3000,
            'bottom-right'
        );

        return true;
    }

    /**
     * Called on drag start to record follower connections for group reassignment.
     * Returns `true` if the drag is a reassign drag that set followers.
     */
    recordDragStart(dragConnectionId: string | undefined): boolean {
        if (dragConnectionId && dragConnectionId === this.groupIds[0]) {
            this.followerIds.set(new Set(this.groupIds.slice(1)));
            return true;
        }
        return false;
    }

    /** Clears suppressed and follower highlights on pointer up / cancel. */
    resetHighlight(): void {
        if (this.suppressedConnectionIds().size > 0) {
            this.suppressedConnectionIds.set(new Set<string>());
        }
        if (this.followerIds().size > 0) {
            this.followerIds.set(new Set<string>());
        }
    }

    /**
     * Checks whether a port is occupied (single-connection port already has a connection).
     * Also used by the component's `onConnectionAdded` for new-connection validation.
     */
    hasOccupiedPort(sourcePortId: string, targetPortId: string, connections: ConnectionModel[]): boolean {
        const allPorts = this.flowService.nodes().flatMap((n) => n.ports ?? []);
        const sourcePort = allPorts.find((p) => p.id === sourcePortId);
        const targetPort = allPorts.find((p) => p.id === targetPortId);
        const sourceOccupied =
            !!sourcePort && !sourcePort.multiple && connections.some((conn) => conn.sourcePortId === sourcePortId);
        const targetOccupied =
            !!targetPort && !targetPort.multiple && connections.some((conn) => conn.targetPortId === targetPortId);
        return sourceOccupied || targetOccupied;
    }

    // ── Private helpers ──────────────────────────────────────────────

    private resolveConnectionEndGrab(event: MouseEvent, fFlowComponent: FFlowComponent): ConnectionEndGrab | null {
        const target = event.target as Element | null;

        const connectionElement = target?.closest('f-connection');
        if (connectionElement) {
            return this.resolveHandleGrab(connectionElement, event, fFlowComponent);
        }

        const portElement = target?.closest<HTMLElement>('[data-f-output-id], [data-f-input-id]');
        const portId = portElement?.dataset['fOutputId'] ?? portElement?.dataset['fInputId'];
        return portId ? this.resolvePortGrab(portId, fFlowComponent) : null;
    }

    private resolveHandleGrab(
        connectionElement: Element,
        event: MouseEvent,
        fFlowComponent: FFlowComponent
    ): ConnectionEndGrab | null {
        const connection = this.flowService.connections().find((conn) => conn.id === connectionElement.id);
        if (!connection) {
            return null;
        }

        const endpoint = (['target', 'source'] as const).find((end) => {
            const handle = this.getDragHandle(connectionElement, end);
            if (!handle) {
                return false;
            }
            const { left, top, width, height } = handle.getBoundingClientRect();
            const radius = width / 2;
            return (event.clientX - (left + radius)) ** 2 + (event.clientY - (top + height / 2)) ** 2 <= radius ** 2;
        });
        if (!endpoint) {
            return null;
        }

        const selectedIds = this.getSelectedConnectionIds(fFlowComponent);
        const portId = endpoint === 'source' ? connection.sourcePortId : connection.targetPortId;
        const selectedAtPort = selectedIds.has(connection.id)
            ? this.connectionsAtPort(portId).filter((conn) => conn.id !== connection.id && selectedIds.has(conn.id))
            : [];

        return { connection, group: [connection, ...selectedAtPort], endpoint, fromPort: false };
    }

    private resolvePortGrab(portId: string, fFlowComponent: FFlowComponent): ConnectionEndGrab | null {
        const port = this.flowService
            .nodes()
            .flatMap((node) => node.ports ?? [])
            .find((p) => p.id === portId);
        if (!port) {
            return null;
        }

        const attached = this.connectionsAtPort(portId);
        const selectedIds = this.getSelectedConnectionIds(fFlowComponent);
        const selected = attached.filter((conn) => selectedIds.has(conn.id));
        const canMoveAll = port.port_type === 'input' || !port.multiple;
        const group = selected.length > 0 ? selected : canMoveAll ? attached : [];
        if (group.length === 0) {
            return null;
        }

        const [connection] = group;
        return {
            connection,
            group,
            endpoint: connection.sourcePortId === portId ? 'source' : 'target',
            fromPort: true,
        };
    }

    private getSelectedConnectionIds(fFlowComponent: FFlowComponent): Set<string> {
        return new Set(fFlowComponent.getSelection().fConnectionIds);
    }

    private suppressNeighbours(grab: ConnectionEndGrab | null, callbacks: ReassignHandlerCallbacks): void {
        const suppressed = new Set<string>();
        if (grab) {
            const portId = grab.endpoint === 'source' ? grab.connection.sourcePortId : grab.connection.targetPortId;
            this.connectionsAtPort(portId)
                .filter((conn) => conn.id !== grab.connection.id)
                .forEach((conn) => suppressed.add(conn.id));
        }

        if (suppressed.size === 0 && this.suppressedConnectionIds().size === 0) {
            return;
        }

        this.suppressedConnectionIds.set(suppressed);
        // Foblex picks the connection to reassign later in this same mousedown,
        // so the disabled flags must reach it synchronously.
        callbacks.detectChanges();
    }

    private connectionsAtPort(portId: string): ConnectionModel[] {
        return this.flowService
            .connections()
            .filter((conn) => conn.sourcePortId === portId || conn.targetPortId === portId);
    }

    private getDragHandle(connectionElement: Element, endpoint: 'source' | 'target'): Element | null {
        return connectionElement.querySelector(
            endpoint === 'source' ? 'circle[f-connection-drag-handle-start]' : 'circle[f-connection-drag-handle-end]'
        );
    }

    /** A Classification Decision Table route-code port whose row has Continue on; see `isRoutePortBlockedByContinue`. */
    isRoutePortBlocked(sourcePortId: CustomPortId): boolean {
        const sourceNodeId = sourcePortId.split('_')[0];
        const sourceNode = this.flowService.nodes().find((node) => node.id === sourceNodeId);
        if (sourceNode?.type !== NodeType.CLASSIFICATION_TABLE) {
            return false;
        }
        return isRoutePortBlockedByContinue(sourceNode.data.table?.condition_groups ?? [], sourceNode.id, sourcePortId);
    }

    private getReassignError(
        sourcePortId: CustomPortId,
        targetPortId: CustomPortId,
        connections: ConnectionModel[]
    ): string | null {
        if (!isConnectionValid(sourcePortId, targetPortId)) {
            return 'Cannot reassign connection: Invalid port combination';
        }
        if (connections.some((conn) => conn.sourcePortId === sourcePortId && conn.targetPortId === targetPortId)) {
            return 'These ports are already connected';
        }
        if (this.hasOccupiedPort(sourcePortId, targetPortId, connections)) {
            return 'This port already has a connection';
        }
        if (this.isRoutePortBlocked(sourcePortId)) {
            return CDT_ROUTE_CONTINUE_COPY.routePortBlockedByContinue;
        }
        return null;
    }
}
