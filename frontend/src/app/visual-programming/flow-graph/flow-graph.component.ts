import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    output,
    computed,
    EventEmitter,
    Input,
    OnInit,
    Output,
    signal,
    ViewChild,
    OnDestroy,
    ElementRef, 
    HostListener,
    Type,
} from '@angular/core';
import {
    FCreateNodeEvent,
    EFMarkerType,
    FCanvasComponent,
    FFlowModule,
    FZoomDirective,
    FReassignConnectionEvent,
    FCreateConnectionEvent,
    FFlowComponent,
    FSelectionChangeEvent,
    EFResizeHandleType,
    ICurrentSelection,
    IFFlowState,
    FDragStartedEvent,
    EFZoomDirection,
} from '@foblex/flow';

import { IPoint, IRect, PointExtensions } from '@foblex/2d';
import { FlowService } from '../services/flow.service';
import { SidePanelService } from '../services/side-panel.service';

import { ShortcutListenerDirective } from '../core/directives/shortcut-listener.directive';
import { UndoRedoService } from '../services/undo-redo.service';
import { ClipboardService } from '../services/clipboard.service';
import { MouseTrackerDirective } from '../core/directives/mouse-tracker.directive';
import { Subject, Observable } from 'rxjs';
import {
    DecisionTableNodeModel,
    NodeModel,
    ProjectNodeModel,
    StartNodeModel,
    NoteNodeModel,
} from '../core/models/node.model';
import { ConnectionModel } from '../core/models/connection.model';

import { CustomPortId, ViewPort } from '../core/models/port.model';
import {
    isConnectionValid,
    defineSourceTargetPair,
    generatePortsForNode,
    generatePortsForDecisionTableNode,
} from '../core/helpers/helpers';

import { NgClass, NgIf } from '@angular/common';
import { NodeType } from '../core/enums/node-type';
import { v4 as uuidv4 } from 'uuid';
import { FlowGraphContextMenuComponent } from '../components/flow-graph-context-menu/flow-graph-context-menu.component';

import { ClickOutsideDirective } from '../../shared/directives/click-outside.directive';
import { FlowBaseNodeComponent } from '../components/flow-base-node/flow-base-node.component';
import { NODE_COLORS, NODE_ICONS } from '../core/enums/node-config';

import { FormsModule } from '@angular/forms';
import { NODE_TYPE_PREFIXES } from '../core/enums/node-type-prefixes';
import { FlowModel } from '../core/models/flow.model';

import { FlowStateData } from '../core/models/flow-state-data.model';
import { FlowActionPanelComponent } from '../components/flow-action-panel/flow-action-panel.component';
import { FlowNodePanelComponent } from '../components/flow-nodes-panel/flow-nodes-panel.component';
import { NodesSearchComponent } from '../components/nodes-search/nodes-search.component';
import { generateNodeDisplayName } from '../core/helpers/generate-node-display-name.util';
import { Dialog } from '@angular/cdk/dialog';
import { ProjectDialogComponent } from '../components/project-dialog/project-dialog.component';
import { NoteNodeComponent } from '../components/nodes-components/note-node/note-node.component';
import { NoteEditDialogComponent } from '../components/note-edit-dialog/note-edit-dialog.component';
import { getMinimapClassForNode } from '../core/helpers/get-minimap-class.util'; // Adjust path
import { ToastService } from '../../services/notifications/toast.service';
import { DomainDialogComponent } from '../components/domain-dialog/domain-dialog.component';
import { NodePanelShellComponent } from '../components/node-panels/node-panel-shell/node-panel-shell.component';
import { FlowShortcutsButtonComponent } from '../components/flow-shortcuts-button/flow-shortcuts-button.component';

@Component({
    selector: 'app-flow-graph',
    templateUrl: './flow-graph.component.html',
    styleUrls: ['../styles/_variables.scss', './flow-graph.component.scss'],
    standalone: true,
    changeDetection: ChangeDetectionStrategy.OnPush,
    //   providers: [FlowService],
    imports: [
        FFlowModule,
        FZoomDirective,
        FormsModule,
        FlowBaseNodeComponent,
        ShortcutListenerDirective,
        MouseTrackerDirective,
        FlowGraphContextMenuComponent,
        ClickOutsideDirective,

        FlowActionPanelComponent,
        FlowNodePanelComponent,
        NodesSearchComponent,
        NodePanelShellComponent,
        FlowShortcutsButtonComponent
    ],
})
export class FlowGraphComponent implements OnInit, OnDestroy {
    @Input() flowState!: FlowModel;
    @Input() nodesMode!: 'project-graph' | 'flow-graph';
    @Input() currentFlowId: number | null = null;

    @Output() save = new EventEmitter<void>();

    @ViewChild(FFlowComponent, { static: false })
    public fFlowComponent!: FFlowComponent;

    @ViewChild(FCanvasComponent, { static: true })
    public fCanvasComponent!: FCanvasComponent;

    @ViewChild(FZoomDirective, { static: true })
    public fZoomDirective!: FZoomDirective;

    @ViewChild('nodePanelShell', { static: false })
    public nodePanelShell?: NodePanelShellComponent;

    public getMinimapClassForNode = getMinimapClassForNode;

    public readonly eMarkerType = EFMarkerType;
    public readonly eResizeHandleType = EFResizeHandleType;

    public mouseCursorPosition: { x: number; y: number } = { x: 0, y: 0 };
    public contextMenuPostion: { x: number; y: number } = {
        x: 0,
        y: 0,
    };

    public isLoaded = signal<boolean>(false);
    public showContextMenu = signal(false);

    private readonly destroy$ = new Subject<void>();
    public showVariables = signal<boolean>(false);

    public NodeType = NodeType;

    constructor(
        public readonly flowService: FlowService,
        private readonly undoRedoService: UndoRedoService,
        private readonly clipboardService: ClipboardService,
        public readonly sidePanelService: SidePanelService,
        private readonly cd: ChangeDetectorRef,
        private readonly dialog: Dialog,
        private readonly toastService: ToastService
    ) { }

    public ngOnInit(): void {
        this.initializeFlowStateIfEmpty();
        this.addStartNodeIfNeeded();
        this.generatePortsForNodesIfNeeded();
        this.sanitizeConnections();
        this.flowService.setFlow(this.flowState);
    }

    /**
     * Strips connections that reference ports not actually present on the rendered nodes.
     * Prevents f-flow errors like "fOutput with id ...table-out not found".
     */
    private sanitizeConnections(): void {
        const portIds = new Set<string>();
        for (const node of this.flowState.nodes) {
            if (node.ports) {
                for (const port of node.ports) {
                    portIds.add(port.id);
                }
            }
        }

        const before = this.flowState.connections.length;
        this.flowState.connections = this.flowState.connections.filter(conn => {
            const srcOk = portIds.has(conn.sourcePortId);
            const tgtOk = portIds.has(conn.targetPortId);
            if (!srcOk || !tgtOk) {
                console.warn(
                    `[flow-graph] Removing invalid connection ${conn.id}: ` +
                    `sourcePort "${conn.sourcePortId}" ${srcOk ? 'OK' : 'MISSING'}, ` +
                    `targetPort "${conn.targetPortId}" ${tgtOk ? 'OK' : 'MISSING'}`
                );
            }
            return srcOk && tgtOk;
        });

        if (this.flowState.connections.length < before) {
            console.warn(`[flow-graph] Removed ${before - this.flowState.connections.length} invalid connections`);
        }
    }

    private initializeFlowStateIfEmpty(): void {
        if (!this.flowState || !Array.isArray(this.flowState.nodes)) {
            this.flowState = {
                nodes: [],
                connections: [],
            };
        }
    }

    private addStartNodeIfNeeded(): void {
        // Check if a Start node already exists
        const alreadyHasStart: boolean = this.flowState.nodes.some(
            (node) => node.type === NodeType.START
        );

        if (!alreadyHasStart) {
            // Generate unique ID
            const newStartNodeId: string = uuidv4();

            // Create a new Start node
            const startNode: StartNodeModel = {
                id: newStartNodeId,
                backendId: null,
                category: 'web',
                type: NodeType.START,
                node_name: '__start__',
                data: {
                    initialState: {},
                },
                position: { x: 0, y: 0 },
                ports: generatePortsForNode(newStartNodeId, NodeType.START),
                parentId: null,
                color: NODE_COLORS[NodeType.START],
                icon: NODE_ICONS[NodeType.START],
                input_map: {},
                output_variable_path: null,
                size: { width: 125, height: 60 },
            };

            // Add Start node to the flow
            this.flowState.nodes.push(startNode);
        }
    }

    private generatePortsForNodesIfNeeded(): void {
        this.flowState.nodes = this.flowState.nodes.map((node) => {
            if (node.ports === null) {
                node.ports = generatePortsForNode(node.id, node.type, node.data);
            } else if (node.type === NodeType.TABLE) {
                const tableData = (node as any)?.data?.table ?? {};
                const conditionGroups = tableData?.condition_groups ?? [];
                const validGroups = conditionGroups.filter(
                    (group: any) => group?.valid === true
                );
                const expectedPortCount =
                    1 + validGroups.length + 2;

                if (node.ports.length !== expectedPortCount) {
                    node.ports = generatePortsForDecisionTableNode(
                        node.id,
                        conditionGroups,
                        true,
                        true
                    );
                }
            }
            return node;
        });
    }

    public onSave(): void { }

    ngDoCheck() {
    }
    public onInitialized(): void {
        // this.fCanvasComponent.fitToScreen(new Point(140, 140), false);
        this.isLoaded.set(true);
        setTimeout(() => {
            this.fFlowComponent?.redraw();
            this.cd.detectChanges();
        });
    }
    public updateMouseTrackerPosition(event: { x: number; y: number }) {
        this.mouseCursorPosition = event;
    }
    public onReassignConnection(event: FReassignConnectionEvent): void {
        console.log('Reassigning connection:', event);

        // Validate that we have the necessary information
        if (!event.newTargetId && !event.newSourceId) {
            console.warn('No new target or source provided for reassignment');
            return;
        }

        this.undoRedoService.stateChanged();

        // Find the existing connection to reassign
        const existingConnection = this.flowService
            .connections()
            .find((conn) => conn.id === event.connectionId);

        if (!existingConnection) {
            console.warn(
                'Connection not found for reassignment:',
                event.connectionId
            );
            return;
        }

        // Determine the new source and target ports
        const newSourcePortId =
            event.newSourceId || existingConnection.sourcePortId;
        const newTargetPortId =
            event.newTargetId || existingConnection.targetPortId;

        // Validate the new connection using the existing validation rules
        if (
            !isConnectionValid(
                newSourcePortId as CustomPortId,
                newTargetPortId as CustomPortId
            )
        ) {
            console.warn('New connection is invalid. Reassignment aborted.');
            this.toastService.warning(
                'Cannot reassign connection: Invalid port combination',
                5000,
                'bottom-right'
            );
            return;
        }

        // Extract node IDs from the new port IDs
        const newSourceNodeId = newSourcePortId.split('_')[0];
        const newTargetNodeId = newTargetPortId.split('_')[0];

        // Create the updated connection
        const updatedConnection: ConnectionModel = {
            id: `${newSourcePortId}+${newTargetPortId}`,
            category: 'default',
            sourceNodeId: newSourceNodeId,
            targetNodeId: newTargetNodeId,
            sourcePortId: newSourcePortId as CustomPortId,
            targetPortId: newTargetPortId as CustomPortId,
            behavior: 'fixed',
            type: 'segment',
        };

        // Remove the old connection and add the new one
        this.flowService.removeConnection(event.connectionId);
        this.flowService.addConnection(updatedConnection);

        console.log('Connection reassigned successfully:', {
            oldConnectionId: event.connectionId,
            newConnectionId: updatedConnection.id,
            oldSource: existingConnection.sourcePortId,
            newSource: newSourcePortId,
            oldTarget: existingConnection.targetPortId,
            newTarget: newTargetPortId,
        });

        this.toastService.success(
            'Connection reassigned successfully',
            3000,
            'bottom-right'
        );
    }

    public onConnectionAdded(event: FCreateConnectionEvent): void {
        // Save the state for undo before adding the connection
        this.undoRedoService.stateChanged();

        const { fOutputId, fInputId } = event;

        if (!fInputId) {
            console.warn(
                'Connection event received without an input ID:',
                event
            );
            return;
        }

        if (
            !isConnectionValid(
                fOutputId as CustomPortId,
                fInputId as CustomPortId
            )
        ) {
            console.warn(
                'Connection is invalid and will not be added:',
                fOutputId,
                fInputId
            );
            return;
        }

        const pair = defineSourceTargetPair(
            fOutputId as CustomPortId,
            fInputId as CustomPortId
        );
        if (!pair) {
            console.warn(
                'Failed to define source-target pair for ports:',
                fOutputId,
                fInputId
            );
            return;
        }

        // Generate a new connection ID
        const newConnectionId: CustomPortId =
            `${pair.sourcePortId}+${pair.targetPortId}` as CustomPortId;

        // Get the current list of connections from the flow service
        const currentConnections = this.flowService.connections();

        // If the connection already exists, don't add it
        const isDuplicate = currentConnections.some(
            (conn) => conn.id === newConnectionId
        );
        if (isDuplicate) {
            console.warn(
                'Duplicate connection detected, ignoring:',
                newConnectionId
            );
            return;
        }

        // Extract the source and target node IDs from the port IDs
        const sourceNodeId = pair.sourcePortId.split('_')[0];
        const targetNodeId = pair.targetPortId.split('_')[0];

        // Create the new connection object based on your models
        const newConnection: ConnectionModel = {
            id: newConnectionId,
            category: 'default',
            sourceNodeId: sourceNodeId,
            targetNodeId: targetNodeId,
            sourcePortId: pair.sourcePortId as CustomPortId,
            targetPortId: pair.targetPortId as CustomPortId,
            behavior: 'fixed',
            type: 'segment',
        };
        // Add the new connection to the flow service
        this.flowService.addConnection(newConnection);
    }

    public onCopy(): void {
        if (this.isDialogOpen()) {
            return;
        }

        // Assume fFlowComponent.getSelection() returns a FSelectionChangeEvent

        const selections: FSelectionChangeEvent =
            this.fFlowComponent.getSelection();
        console.log('copying', selections);
        this.clipboardService.copy(selections);
    }
    // Triggered on paste
    public onPaste(): void {
        if (this.isDialogOpen()) {
            return;
        }

        let pastePosition: IRect;

        if (this.mouseCursorPosition) {
            pastePosition = this.fFlowComponent.getPositionInFlow(
                PointExtensions.initialize(
                    this.mouseCursorPosition.x,
                    this.mouseCursorPosition.y
                )
            );
        } else {
            console.warn(
                'No current mouse position available, using default paste position.'
            );
            pastePosition = { x: 0, y: 0 } as IRect; // Set default position
        }

        this.undoRedoService.stateChanged();

        const { newNodes, newConnections } =
            this.clipboardService.paste(pastePosition);

        // After pasting, select the new nodes and connections
        const newNodeIds: string[] = newNodes.map((node) => node.id);
        const newConnectionIds: string[] = newConnections.map(
            (conn) => conn.id
        );

        setTimeout(() => {
            this.fFlowComponent.select(newNodeIds, newConnectionIds);
        }, 0);

        console.log('Pasted nodes:', newNodes);
        console.log('Pasted connections:', newConnections);
    }

    public onUndo(): void {
        if (this.isDialogOpen()) {
            return;
        }

        console.log('component triggered undo');
        this.undoRedoService.onUndo();
    }

    public onRedo(): void {
        if (this.isDialogOpen()) {
            return;
        }

        this.undoRedoService.onRedo();
    }
    public onDelete(): void {
        if (this.isDialogOpen()) {
            return;
        }

        const selections: ICurrentSelection =
            this.fFlowComponent.getSelection();

        // Check if there's anything to delete
        if (
            !selections ||
            (selections.fNodeIds.length === 0 &&
                selections.fConnectionIds.length === 0)
        ) {
            console.warn('No items selected to delete.');
            return;
        }

        console.log('Deleting selected items:', selections);

        // Save state for undo
        this.undoRedoService.stateChanged();

        // Filter out START nodes from deletion
        const nodeIdsToDelete = selections.fNodeIds.filter((nodeId) => {
            const node = this.flowService.nodes().find((n) => n.id === nodeId);
            return node && node.type !== NodeType.START;
        });

        // Perform deletion with filtered node IDs
        this.flowService.deleteSelections({
            fNodeIds: nodeIdsToDelete,
            fConnectionIds: selections.fConnectionIds,
        });
    }

    public onCreateNode(event: FCreateNodeEvent) {
        if (event.data && typeof event.data === 'object') {
            const nodeData = event.data as NodeModel;
            // Create a copy of the node with updated position and category
            const updatedNode: NodeModel = {
                ...nodeData,
                position: {
                    x: event.rect.x,
                    y: event.rect.y,
                },
                category: 'web', // Change category from 'vscode' to 'web'
            };

            // Call the flow service to update the node
            this.flowService.updateNode(updatedNode);

            console.log('Node added to canvas:', updatedNode);
        }
    }

    public onContextMenu(event: MouseEvent): void {
        event.preventDefault();

        console.log(this.mouseCursorPosition);

        this.contextMenuPostion = event;

        this.showContextMenu.set(true);
    }
    public onCloseContextMenu(): void {
        console.log('closing');

        this.showContextMenu.set(false);
    }
    public onAddNodeFromContextMenu(event: {
        type: NodeType;
        data?: any;
    }): void {
        this.undoRedoService.stateChanged();
        this.showContextMenu.set(false);

        // Groups are no longer supported
        if (event.type === NodeType.GROUP) {
            return;
        }

        if (event.type === NodeType.END && this.flowService.hasEndNode()) {
            this.toastService.warning(
                'Only one End node is allowed',
                4000,
                'bottom-right'
            );
            return;
        }

        // Generate common values
        const newNodeId = uuidv4();
        const nodeColor = NODE_COLORS[event.type] || '#ddd';
        const nodeIcon = NODE_ICONS[event.type] || 'ti ti-help';
        const position = this.fFlowComponent.getPositionInFlow(
            PointExtensions.initialize(
                this.contextMenuPostion.x,
                this.contextMenuPostion.y
            )
        );

        let nodeSize: { width: number; height: number };
        if (event.type === NodeType.NOTE) {
            nodeSize = {
                width: 200,
                height: 150,
            };
        } else if (event.type === NodeType.TABLE) {
            const tableData = event.data?.table;
            const conditionGroups = tableData?.condition_groups ?? [];
            const headerHeight = 60;
            const rowHeight = 46;
            const validGroupsCount = conditionGroups.filter((g: any) => g.valid).length;
            const hasDefaultRow = 1;
            const hasErrorRow = 1;
            const totalRows = Math.max(
                validGroupsCount + hasDefaultRow + hasErrorRow,
                2
            );
            const calculatedHeight = headerHeight + rowHeight * totalRows;
            nodeSize = {
                width: 330,
                height: Math.max(calculatedHeight, 152),
            };
        } else {
            nodeSize = {
                width: 330,
                height: 60,
            };
        }

        // Generate ports for non-note nodes
        const ports: ViewPort[] =
            event.type === NodeType.NOTE
                ? []
                : generatePortsForNode(newNodeId, event.type, event.data);

        // Build the display name
        const currentNodes = this.flowService.getFlowState().nodes;
        const newNodeName = generateNodeDisplayName(
            event.type,
            event.data,
            currentNodes
        );

        // Create and add a regular node
        let nodeData = event.data;

        // Add default output_map for end nodes
        if (event.type === NodeType.END) {
            nodeData = {
                ...event.data,
                output_map: {
                    context: 'variables',
                },
            };
        }

        const newNode: NodeModel = {
            id: newNodeId,
            backendId: null,
            category: 'web',
            position: { x: position.x, y: position.y },
            ports,
            parentId: null,
            type: event.type as NodeModel['type'],
            node_name: newNodeName,
            data: nodeData,
            color: nodeColor,
            icon: nodeIcon,
            input_map: {},
            output_variable_path: null,
            size: nodeSize,
        };
        this.flowService.addNode(newNode);
    }

    // side panel logic
    public onOpenNodePanel(node: NodeModel): void {
        if (this.sidePanelService.selectedNodeId() === node.id) {
            return;
        }

        if (node.type === NodeType.NOTE) {
            const noteNode = node as NoteNodeModel;

            const dialogRef = this.dialog.open(NoteEditDialogComponent, {
                data: { node: noteNode },
                disableClose: true,
            });

            dialogRef.closed.subscribe((result: any) => {
                if (result && result.content !== undefined) {
                    const updatedNode: NoteNodeModel = {
                        ...noteNode,
                        data: {
                            ...noteNode.data,
                            content: result.content,
                        },
                    };

                    this.flowService.updateNode(updatedNode);

                    this.cd.detectChanges();
                }
            });
        } else if (node.type === NodeType.START) {
            const startNode = node as StartNodeModel;
            const startNodeInitialState = startNode.data?.initialState || {};

            const dialogRef = this.dialog.open(DomainDialogComponent, {
                disableClose: true,
                width: '1000px',
                height: '800px',
                maxWidth: '90vw',
                maxHeight: '90vh',
                panelClass: 'domain-dialog-panel',
                backdropClass: 'domain-dialog-backdrop',
                data: {
                    initialData: startNodeInitialState,
                },
            });

            dialogRef.closed.subscribe((result: unknown) => {
                if (
                    result !== null &&
                    typeof result === 'object' &&
                    result !== undefined
                ) {
                    this.updateStartNodeInitialState(
                        result as Record<string, unknown>
                    );
                }
            });
        } else {
            void this.sidePanelService.trySelectNode(node);
        }
    }

    public onNodePanelSaved(updatedNode: NodeModel): void {
        console.log(
            'Parent received save event. Calling service with:',
            updatedNode
        );
        this.flowService.updateNode(updatedNode);
        this.sidePanelService.clearSelection();
    }

    public onNodePanelAutosaved(updatedNode: NodeModel): void {
        console.log(
            'Parent received autosave event. Calling service with:',
            updatedNode
        );
        this.flowService.updateNode(updatedNode);
    }

    public flushOpenSidePanelState(): void {
        const updatedNode = this.nodePanelShell?.captureCurrentNodeState();
        if (updatedNode) {
            this.flowService.updateNode(updatedNode);
        }
    }

    public onNodePositionChanged(
        event: IPoint,
        node: NodeModel
    ): void {
        const updatedNode = {
            ...node,
            position: { x: event.x, y: event.y },
        };
        this.flowService.updateNode(updatedNode);
    }

    public onNodeSizeChanged(
        event: { width: number; height: number },
        node: NodeModel
    ): void {
        this.undoRedoService.stateChanged();
        console.log('Node size changed:', event, node);

        const updatedNode = {
            ...node,
            size: {
                width: event.width,
                height: event.height,
            },
        };

        this.flowService.updateNode(updatedNode);
    }
    public onZoomInNode(node: NodeModel): void {
        this.fCanvasComponent.centerGroupOrNode(node.id, true);
    }


    // Add this method to handle double-click on nodes from search
    public onNodeDoubleClickAndZoom(data: {
        node: NodeModel;
        event: MouseEvent;
    }): void {
        // Get the position to zoom around (the node position)
        const position = {
            x: data.node.position.x,
            y: data.node.position.y,
        };

        // First center on the node to ensure we're zooming on the right area
        this.fCanvasComponent.centerGroupOrNode(data.node.id, false);

        this.fZoomDirective.setZoom(position, 1, EFZoomDirection.ZOOM_IN, true);
    }

    public toggleShowVariables(): void {
        this.showVariables.set(!this.showVariables());
        console.log('Show Variables:', this.showVariables());
    }

    public onDomainClick(): void {
        const startNodeInitialState = this.flowService.startNodeInitialState();

        const dialogRef = this.dialog.open(DomainDialogComponent, {
            width: '1000px',
            height: '800px',
            maxWidth: '90vw',
            maxHeight: '90vh',
            panelClass: 'domain-dialog-panel',
            backdropClass: 'domain-dialog-backdrop',
            data: {
                initialData: startNodeInitialState,
            },
        });

        dialogRef.closed.subscribe((result: unknown) => {
            if (
                result !== null &&
                typeof result === 'object' &&
                result !== undefined
            ) {
                this.updateStartNodeInitialState(
                    result as Record<string, unknown>
                );
            }
        });
    }

    private updateStartNodeInitialState(
        newState: Record<string, unknown>
    ): void {
        const startNode = this.flowService
            .nodes()
            .find((node) => node.type === NodeType.START) as
            | StartNodeModel
            | undefined;

        if (startNode) {
            const updatedStartNode: StartNodeModel = {
                ...startNode,
                data: {
                    ...startNode.data,
                    initialState: newState,
                },
            };

            this.flowService.updateNode(updatedStartNode);
        } else {
            this.toastService.error('Start node not found');
        }
    }

    public onProjectExpandToggled(project: ProjectNodeModel): void {
        console.log('Project expanded:', project.data.id);

        const dialogRef = this.dialog.open(ProjectDialogComponent, {
            width: '90vw',
            height: '90vh',
            disableClose: true,

            data: {
                projectId: project.data.id,
                projectName: project.data.name,
            },
        });

        dialogRef.closed.subscribe(() => { });
    }

    private isDialogOpen(): boolean {
        return this.dialog.openDialogs.length > 0;
    }

    public ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

    openShortcuts = output<DOMRect>();

    public onOpenShortcuts(anchorEl: HTMLElement): void {
        this.openShortcuts.emit(anchorEl.getBoundingClientRect());
    }
}
