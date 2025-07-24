import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  computed,
  EventEmitter,
  Input,
  OnInit,
  Output,
  signal,
  ViewChild,
  OnDestroy,
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
  FDropToGroupEvent,
  FCanvasChangeEvent,
  IFFlowState,
  FDragStartedEvent,
  EFZoomDirection,
} from '@foblex/flow';
import { IPoint, IRect, Point, PointExtensions } from '@foblex/2d';

import { FlowService } from '../services/flow.service';

import { ActivatedRoute, Router } from '@angular/router';
import { ShortcutListenerDirective } from '../core/directives/shortcut-listener.directive';
import { UndoRedoService } from '../services/undo-redo.service';
import { ClipboardService } from '../services/clipboard.service';
import { MouseTrackerDirective } from '../core/directives/mouse-tracker.directive';
import { debounceTime, Subject, Observable } from 'rxjs';
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
import { DynamicSidePanelHostComponent } from '../components/side-panel-host/dynamic-side-panel.component';
import { FlowBaseNodeComponent } from '../components/flow-base-node/flow-base-node.component';
import { NODE_COLORS, NODE_ICONS } from '../core/enums/node-config';

import { FormsModule } from '@angular/forms';
import { NODE_TYPE_PREFIXES } from '../core/enums/node-type-prefixes';
import { FlowModel } from '../core/models/flow.model';

import { FlowStateData } from '../core/models/flow-state-data.model';
import { GroupNodeComponent } from '../components/group-node/group-node.component';
import { GroupNodeModel } from '../core/models/group.model';
import { size } from 'lodash';

import { GroupCollapserService } from '../services/group/group-collapse.service';
import { FlowActionPanelComponent } from '../components/flow-action-panel/flow-action-panel.component';
import { FlowZoomControlsComponent } from '../components/flow-zoom-control-panel/flow-zoom-controls.component';
import { calculateGroupCollapsedPosition } from '../core/helpers/calculate-group-collapsed-position.util';
import { calculateGroupExpandedPosition } from '../core/helpers/calculate-group-expanded-position.util';
import { convertJsonToMap } from '../core/helpers/convert-json-to-map.util';
import { FlowNodePanelComponent } from '../components/flow-nodes-panel/flow-nodes-panel.component';
import { NodesSearchComponent } from '../components/nodes-search/nodes-search.component';
import { generateNodeDisplayName } from '../core/helpers/generate-node-display-name.util';
import { SidePanelService } from '../services/side-panel.service';
import { map, takeUntil } from 'rxjs/operators';
import { Dialog } from '@angular/cdk/dialog';
import { ProjectDialogComponent } from '../components/project-dialog/project-dialog.component';
import { NoteNodeComponent } from '../components/nodes-components/note-node/note-node.component';
import { NoteEditDialogComponent } from '../components/note-edit-dialog/note-edit-dialog.component';

@Component({
  selector: 'app-flow-graph',
  templateUrl: './flow-graph.component.html',
  styleUrls: ['../styles/_variables.scss', './flow-graph.component.scss'],
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  //   providers: [FlowService],
  imports: [
    FZoomDirective,
    FFlowModule,
    FormsModule,
    FlowBaseNodeComponent,
    ShortcutListenerDirective,
    MouseTrackerDirective,
    FlowGraphContextMenuComponent,
    NgIf,
    GroupNodeComponent,
    ClickOutsideDirective,
    DynamicSidePanelHostComponent,
    FlowActionPanelComponent,
    FlowNodePanelComponent,
    NodesSearchComponent,
  ],
})
export class FlowGraphComponent implements OnInit, OnDestroy {
  @Input() flowState!: FlowModel;
  @Input() nodesMode!: 'project-graph' | 'flow-graph';

  @Output() save = new EventEmitter<void>();

  @ViewChild(FFlowComponent, { static: false })
  public fFlowComponent!: FFlowComponent;

  @ViewChild(FCanvasComponent, { static: true })
  public fCanvasComponent!: FCanvasComponent;

  @ViewChild(FZoomDirective, { static: true })
  public fZoomDirective!: FZoomDirective;

  public readonly eMarkerType = EFMarkerType;
  public readonly eResizeHandleType = EFResizeHandleType;

  public mouseCursorPosition: { x: number; y: number } = { x: 0, y: 0 };
  public contextMenuPostion: { x: number; y: number } = {
    x: 0,
    y: 0,
  };

  public isLoaded = signal<boolean>(false);
  public showContextMenu = signal(false);

  public selectedNode: NodeModel | null = null;

  private readonly destroy$ = new Subject<void>();
  private selectedNode$!: Observable<NodeModel | null>;

  public showVariables = signal<boolean>(false);

  // Expose NodeType enum to the template
  public NodeType = NodeType;

  constructor(
    public readonly flowService: FlowService,
    private readonly undoRedoService: UndoRedoService,
    private readonly clipboardService: ClipboardService,
    private readonly groupCollapserService: GroupCollapserService,
    private readonly sidePanelService: SidePanelService,
    private readonly cd: ChangeDetectorRef,
    private readonly dialog: Dialog
  ) {}

  public ngOnInit(): void {
    this.selectedNode$ = this.sidePanelService.getState().pipe(
      map((state) => state.selectedNode),
      takeUntil(this.destroy$)
    );

    this.initializeFlowStateIfEmpty();
    this.addStartNodeIfNeeded();
    this.generatePortsForNodesIfNeeded();
    this.flowService.setFlow(this.flowState);
    this.selectedNode$.subscribe((node) => {
      this.selectedNode = node;
      this.cd.detectChanges();
    });
  }

  private initializeFlowStateIfEmpty(): void {
    if (!this.flowState || !Array.isArray(this.flowState.nodes)) {
      this.flowState = {
        nodes: [],
        connections: [],
        groups: [],
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
    // Check each node and generate ports if they are null
    this.flowState.nodes = this.flowState.nodes.map((node) => {
      if (node.ports === null) {
        node.ports = generatePortsForNode(node.id, node.type);
      }
      return node;
    });
  }

  public onSave(): void {
    console.log('saving');
    this.save.emit();
  }
  ngDoCheck() {
    console.log('PERFORMANCE!');
  }
  public onInitialized(): void {
    // this.fCanvasComponent.fitToScreen(new Point(140, 140), false);
    this.isLoaded.set(true);
    console.log('Flow graph initialized.', this.isLoaded());
  }
  public updateMouseTrackerPosition(event: { x: number; y: number }) {
    this.mouseCursorPosition = event;
  }

  public onReassignConnection(event: FReassignConnectionEvent): void {
    // Save the state for undo before making any changes
    this.undoRedoService.stateChanged();
    console.log('reassign conncetion', event);

    // Step 1: find the old connection from the connections list
    const oldConnection: ConnectionModel | undefined = this.flowService
      .connections()
      .find((conn) => conn.id === event.fConnectionId);

    if (!oldConnection) {
      console.warn('Old connection not found:', event.fConnectionId);
      return;
    }

    // Step 2: Construct the new connection from the new input port (if available)
    if (!event.newFInputId) {
      console.warn(
        'No new input ID provided. Connection cannot be reassigned.'
      );
      return;
    }
    const newTargetNodeId: string = event.newFInputId.split('_')[0];

    // Lookup source and target nodes from flow state
    const nodes = this.flowService.nodes();
    const sourceNode = nodes.find(
      (node) => node.id === oldConnection.sourceNodeId
    );
    const targetNode = nodes.find((node) => node.id === newTargetNodeId);

    // Derive colors from source and target node types
    const startColor = sourceNode ? NODE_COLORS[sourceNode.type] : '#ddd';
    const endColor = targetNode ? NODE_COLORS[targetNode.type] : '#ddd';

    const newConnection: ConnectionModel = {
      id: `${event.fOutputId}+${event.newFInputId}`,
      category: 'default',
      sourceNodeId: oldConnection.sourceNodeId,
      targetNodeId: newTargetNodeId,
      sourcePortId: event.fOutputId as CustomPortId,
      targetPortId: event.newFInputId as CustomPortId,
      startColor,
      endColor,
      behavior: 'floating', // Assuming 'floating' is the default type
      type: 'segment', // Assuming 'straight' is the default type
    };

    // Step 3: Validate the new connection
    if (
      !isConnectionValid(newConnection.sourcePortId, newConnection.targetPortId)
    ) {
      console.warn(
        'New connection is invalid. Reassigning aborted.',
        newConnection
      );
      return;
    }

    // Step 4: Remove the old connection and add the new one
    this.flowService.removeConnection(event.fConnectionId);
    this.flowService.addConnection(newConnection);
    console.log(this.flowService.getFlowState());
    console.log('Reassigned connection successfully added:', newConnection);
  }

  public onConnectionAdded(event: FCreateConnectionEvent): void {
    // Save the state for undo before adding the connection
    this.undoRedoService.stateChanged();

    const { fOutputId, fInputId } = event;

    if (!fInputId) {
      console.warn('Connection event received without an input ID:', event);
      return;
    }

    if (
      !isConnectionValid(fOutputId as CustomPortId, fInputId as CustomPortId)
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
      console.warn('Duplicate connection detected, ignoring:', newConnectionId);
      return;
    }

    // Extract the source and target node IDs from the port IDs
    const sourceNodeId = pair.sourcePortId.split('_')[0];
    const targetNodeId = pair.targetPortId.split('_')[0];

    // Find the corresponding nodes in the flow state
    const sourceNode = this.flowService
      .nodes()
      .find((node) => node.id === sourceNodeId);
    const targetNode = this.flowService
      .nodes()
      .find((node) => node.id === targetNodeId);

    // Get the start and end colors based on node type, using the NODE_COLORS mapping
    const startColor = sourceNode ? NODE_COLORS[sourceNode.type] : '#ddd';
    const endColor = targetNode ? NODE_COLORS[targetNode.type] : '#ddd';

    // Create the new connection object based on your models with added color properties
    const newConnection: ConnectionModel = {
      id: newConnectionId,
      category: 'default',
      sourceNodeId: sourceNodeId,
      targetNodeId: targetNodeId,
      sourcePortId: pair.sourcePortId as CustomPortId,
      targetPortId: pair.targetPortId as CustomPortId,
      startColor,
      endColor,
      behavior: 'fixed',
      type: 'segment',
    };
    // Add the new connection to the flow service
    this.flowService.addConnection(newConnection);
  }

  public onCopy(): void {
    // Assume fFlowComponent.getSelection() returns a FSelectionChangeEvent

    const selections: FSelectionChangeEvent =
      this.fFlowComponent.getSelection();
    console.log('copying', selections);
    this.clipboardService.copy(selections);
  }
  // Triggered on paste
  public onPaste(): void {
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
    const newConnectionIds: string[] = newConnections.map((conn) => conn.id);

    setTimeout(() => {
      this.fFlowComponent.select(newNodeIds, newConnectionIds);
    }, 0);

    console.log('Pasted nodes:', newNodes);
    console.log('Pasted connections:', newConnections);
  }

  public onUndo(): void {
    console.log('component triggered undo');
    this.undoRedoService.onUndo();
  }

  public onRedo(): void {
    this.undoRedoService.onRedo();
  }
  public onDelete(): void {
    const selections: ICurrentSelection = this.fFlowComponent.getSelection();

    // Check if there's anything to delete
    if (
      !selections ||
      (selections.fNodeIds.length === 0 &&
        selections.fConnectionIds.length === 0 &&
        selections.fGroupIds.length === 0)
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
      fGroupIds: selections.fGroupIds,
    });

    // After deletion, regenerate all virtual connections to ensure consistency
    this.regenerateAllVirtualConnections();
  }

  /**
   * Regenerates all virtual connections for all collapsed groups
   */
  private regenerateAllVirtualConnections(): void {
    const collapsedGroups = this.flowService
      .groups()
      .filter((g) => g.collapsed);

    // For each collapsed group
    collapsedGroups.forEach((group) => {
      // 1. Remove existing virtual connections
      this.removeGroupVirtualConnections(group.id);

      // 2. Get current connection data
      const { inputs, outputs, internal } =
        this.groupCollapserService.getGroupAllConnections(group.id);

      // 3. Create new virtual connections
      const virtualConnections = [
        ...this.createVirtualInputConnections(group, inputs),
        ...this.createVirtualOutputConnections(group, outputs),
      ];

      // 4. Add the new virtual connections
      if (virtualConnections.length > 0) {
        this.flowService.addConnectionsInBatch(virtualConnections);
      }
    });

    this.fFlowComponent.redraw();
    this.fFlowComponent.reset();
  }

  /**
   * Removes all virtual connections for a specific group
   */
  private removeGroupVirtualConnections(groupId: string): void {
    const allConnections = this.flowService.connections();
    const virtualConnectionIds = allConnections
      .filter(
        (conn) =>
          (conn.sourceNodeId === groupId || conn.targetNodeId === groupId) &&
          (conn.sourcePortId.includes('group-input') ||
            conn.sourcePortId.includes('group-output') ||
            conn.targetPortId.includes('group-input') ||
            conn.targetPortId.includes('group-output'))
      )
      .map((conn) => conn.id);

    if (virtualConnectionIds.length > 0) {
      this.flowService.removeConnectionsInBatch(virtualConnectionIds);
    }
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
  public onAddNodeFromContextMenu(event: { type: NodeType; data?: any }): void {
    this.undoRedoService.stateChanged();
    this.showContextMenu.set(false);

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

    // Set different size for note nodes
    let nodeSize: { width: number; height: number };
    if (event.type === NodeType.NOTE) {
      nodeSize = {
        width: 200,
        height: 150,
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

    if (event.type === NodeType.GROUP) {
      const groupSize = { width: 500, height: 300 };

      // Calculate positions
      const tempGroupForCalc = {
        position: { x: position.x, y: position.y },
        size: groupSize,
      };
      const calculatedCollapsedPosition =
        calculateGroupCollapsedPosition(tempGroupForCalc);

      // Create the new group
      const newGroup: GroupNodeModel = {
        id: newNodeId,
        category: 'web',
        position: { x: position.x, y: position.y },
        collapsedPosition: calculatedCollapsedPosition,
        ports,
        parentId: null,
        type: event.type,
        node_name: newNodeName,
        data: { name: newNodeName, connectionData: null },
        size: groupSize,
        collapsed: false,
        color: NODE_COLORS[NodeType.GROUP],
        backgroundColor: 'rgba(0, 0, 0, 0.08)',
      };
      this.flowService.addGroup(newGroup);

      // Get current selections
      const { fNodeIds, fGroupIds } = this.fFlowComponent.getSelection();

      const dropEvent = new FDropToGroupEvent(
        newNodeId,
        [...fNodeIds, ...fGroupIds],
        {
          x: 0,
          y: 0,
        }
      );
      this.onDropToGroup(dropEvent);
    } else {
      // Create and add a regular node
      const newNode: NodeModel = {
        id: newNodeId,
        category: 'web',
        position: { x: position.x, y: position.y },
        ports,
        parentId: null,
        type: event.type,
        node_name: newNodeName,
        data: event.data,
        color: nodeColor,
        icon: nodeIcon,
        input_map: {},
        output_variable_path: null,
        size: nodeSize,
      };
      this.flowService.addNode(newNode);
    }
  }

  // side panel logic
  public onEditNode(node: NodeModel): void {
    // Special handling for note nodes
    if (node.type === NodeType.NOTE) {
      const noteNode = node as NoteNodeModel;

      // Open the note edit dialog
      const dialogRef = this.dialog.open(NoteEditDialogComponent, {
        data: { node: noteNode },
      });

      // Handle dialog close with save
      dialogRef.closed.subscribe((result: any) => {
        if (result && result.content !== undefined) {
          // Update the note content
          const updatedNode: NoteNodeModel = {
            ...noteNode,
            data: {
              ...noteNode.data,
              content: result.content,
            },
          };

          // Update the node in the flow service
          this.flowService.updateNode(updatedNode);

          // Trigger change detection to refresh the view
          this.cd.detectChanges();
        }
      });
    } else {
      // For all other node types, use the existing side panel method
      this.sidePanelService.trySelectNode(node).then((selected) => {
        if (!selected) {
          console.log('Node selection was cancelled or failed');
        }
      });
    }
  }

  public onCloseSidePanel(): void {
    this.sidePanelService.tryClosePanel();
  }

  public onSidePanelSaved(updatedNode: NodeModel): void {
    console.log('Node updated:', updatedNode);
    this.flowService.updateNode(updatedNode);
    this.sidePanelService.setHasUnsavedChanges(false);
    this.sidePanelService.tryClosePanel();
  }

  public onGroupSizeChanged(event: IRect, group: GroupNodeModel): void {
    this.undoRedoService.stateChanged();
    console.log('Group size changed:', event, group);

    // Create an updated group with the new size
    const updatedGroup = {
      ...group,
      size: {
        width: event.width,
        height: event.height,
      },
    };

    this.flowService.updateGroup(updatedGroup);
  }
  public onNodeSizeChanged(
    event: { width: number; height: number },
    node: NodeModel
  ): void {
    this.undoRedoService.stateChanged();
    console.log('Node size changed:', event, node);

    // Create an updated node with the new size
    const updatedNode = {
      ...node,
      size: {
        width: event.width,
        height: event.height,
      },
    };

    this.flowService.updateNode(updatedNode);
  }
  public onDropToGroup(event: FDropToGroupEvent): void {
    console.log('Dropping elements to group:', event);

    // Get the target group node by its ID using flowService.groups()
    const targetGroupId = event.fTargetNode;
    const targetGroup: GroupNodeModel | undefined = this.flowService
      .groups()
      .find((group) => group.id === targetGroupId);

    // Validate if the target group exists
    if (!targetGroup || targetGroup.collapsed) {
      console.warn('Target group not found OR collapsed', targetGroupId);
      return;
    }

    // Get the elements that need to be added to the group
    const elementsToGroup: string[] = event.fNodes || [];
    if (elementsToGroup.length === 0) {
      console.warn('No elements to add to the group');
      return;
    }

    // Create a Set for faster lookups
    const elementsSet = new Set(elementsToGroup);

    // Track nodes and groups that were updated
    const updatedNodes: NodeModel[] = [];
    const updatedGroups: GroupNodeModel[] = [];

    // Process each element ID (node or group)
    elementsToGroup.forEach((elementId) => {
      // Try to find it as a regular node
      const node: NodeModel | undefined = this.flowService
        .nodes()
        .find((n) => n.id === elementId);

      if (node) {
        // Only update if its parent is not in the elements being moved
        if (!node.parentId || !elementsSet.has(node.parentId)) {
          const updatedNode: NodeModel = {
            ...node,
            parentId: targetGroupId,
          };
          updatedNodes.push(updatedNode);
          console.log(
            `Updating node ${elementId} with parentId ${targetGroupId}`
          );
        } else {
          console.log(
            `Node ${elementId} has parent ${node.parentId} that is already being moved, skipping update`
          );
        }
      } else {
        // If not found as a node, try to find it as a group
        const group: GroupNodeModel | undefined = this.flowService
          .groups()
          .find((g) => g.id === elementId);

        if (group) {
          // Only update if its parent is not in the elements being moved
          if (!group.parentId || !elementsSet.has(group.parentId)) {
            const updatedGroup: GroupNodeModel = {
              ...group,
              parentId: targetGroupId,
            };
            updatedGroups.push(updatedGroup);
            console.log(
              `Updating group ${elementId} with parentId ${targetGroupId}`
            );
          } else {
            console.log(
              `Group ${elementId} has parent ${group.parentId} that is already being moved, skipping update`
            );
          }
        } else {
          console.warn(
            `Element with ID ${elementId} not found in flow state (neither node nor group)`
          );
        }
      }
    });

    // Update all nodes in a batch if any were found
    if (updatedNodes.length > 0) {
      this.flowService.updateNodesInBatch(updatedNodes);
    }

    // Update all groups in a batch if any were found
    if (updatedGroups.length > 0) {
      this.flowService.updateGroupsInBatch(updatedGroups);
    }

    // After adding all elements to the group, resize the group to fit them
    console.log('Starting group resize operation...');
    this.resizeGroupToFitChildren(targetGroupId);
  }

  private resizeGroupToFitChildren(
    groupId: string
  ): GroupNodeModel | undefined {
    // Get the group by its ID from the computed groups signal
    const group = this.flowService.groups().find((g) => g.id === groupId);
    if (!group) {
      console.warn('Target group not found:', groupId);
      return undefined;
    }

    // Get all child nodes of this group
    const childNodes = this.flowService
      .nodes()
      .filter((node) => node.parentId === groupId);

    // Get all child groups of this group
    const childGroups = this.flowService
      .groups()
      .filter((g) => g.parentId === groupId);

    // Combine the arrays to get all children (both nodes and groups)
    const allChildren = [...childNodes, ...childGroups];

    if (allChildren.length === 0) {
      console.warn('No children found for group:', groupId);
      return group; // Return the original group without changes
    }

    console.log(
      `Group ${groupId} has ${childNodes.length} child nodes and ${childGroups.length} child groups`
    );

    // Calculate the bounding box that encompasses all children
    const boundingBox = this.calculateNodesBoundingBox(allChildren);
    if (!boundingBox) {
      console.warn('Could not calculate bounding box for children');
      return group; // Return the original group without changes
    }

    // Based on your CSS values for the nodes
    const NODE_WIDTH = 330; // Width from your CSS
    const NODE_HEIGHT = 60; // Min-height from your CSS

    // Padding for nodes within the group
    const HORIZONTAL_PADDING = 30;
    const VERTICAL_PADDING = 40;

    // Extra space to accommodate multiple new nodes
    const EXTRA_WIDTH_FOR_NEW_NODES = NODE_WIDTH * 1 + 100; // Space for 2 nodes horizontally
    const EXTRA_HEIGHT_FOR_NEW_NODES = NODE_HEIGHT * 2 + 40; // Space for 2 nodes vertically

    // Current group bounds
    const groupLeft = group.position.x;
    const groupRight = group.position.x + group.size.width;
    const groupTop = group.position.y;
    const groupBottom = group.position.y + group.size.height;

    // Required bounds to fit children with padding
    const requiredLeft = boundingBox.x - HORIZONTAL_PADDING;
    const requiredRight =
      boundingBox.x +
      boundingBox.width +
      HORIZONTAL_PADDING +
      EXTRA_WIDTH_FOR_NEW_NODES;
    const requiredTop = boundingBox.y - VERTICAL_PADDING;
    const requiredBottom =
      boundingBox.y +
      boundingBox.height +
      VERTICAL_PADDING +
      EXTRA_HEIGHT_FOR_NEW_NODES;

    // Calculate new position and size that preserves as much of the original as possible
    // For X position: Move left if needed
    const newX = Math.min(groupLeft, requiredLeft);

    // For Y position: Move up if needed
    const newY = Math.min(groupTop, requiredTop);

    // For width: Expand to cover from newX to either the current right edge or required right edge
    const newWidth = Math.max(groupRight, requiredRight) - newX;

    // For height: Expand to cover from newY to either the current bottom edge or required bottom edge
    const newHeight = Math.max(groupBottom, requiredBottom) - newY;

    // Minimum size constraints
    const MIN_GROUP_WIDTH = 300;
    const MIN_GROUP_HEIGHT = 200;

    // Apply minimum constraints
    const finalWidth = Math.max(newWidth, MIN_GROUP_WIDTH);
    const finalHeight = Math.max(newHeight, MIN_GROUP_HEIGHT);

    // Check if we need to update position or size
    const needsRepositioning =
      newX !== group.position.x || newY !== group.position.y;
    const needsResize =
      finalWidth !== group.size.width || finalHeight !== group.size.height;

    if (!needsResize && !needsRepositioning) {
      console.log(
        'Group already contains all children with sufficient padding. No changes needed.'
      );
      return group;
    }

    // Log calculated values
    console.log('Group adjustment calculation:', {
      boundingBox,
      nodeDimensions: { width: NODE_WIDTH, height: NODE_HEIGHT },
      extraSpace: {
        width: EXTRA_WIDTH_FOR_NEW_NODES,
        height: EXTRA_HEIGHT_FOR_NEW_NODES,
      },
      currentBounds: {
        left: groupLeft,
        right: groupRight,
        top: groupTop,
        bottom: groupBottom,
      },
      requiredBounds: {
        left: requiredLeft,
        right: requiredRight,
        top: requiredTop,
        bottom: requiredBottom,
      },
      newPosition: { x: newX, y: newY },
      newSize: { width: finalWidth, height: finalHeight },
      needsRepositioning,
      needsResize,
    });

    // Create updated group model
    const updatedGroup: GroupNodeModel = {
      ...group,
      position: { x: newX, y: newY },
      size: {
        width: finalWidth,
        height: finalHeight,
      },
    };

    // Update the group using the new updateGroup method
    this.flowService.updateGroup(updatedGroup);

    console.log('Group updated:', {
      groupId,
      oldBounds: {
        left: group.position.x,
        right: group.position.x + group.size.width,
        top: group.position.y,
        bottom: group.position.y + group.size.height,
      },
      newBounds: {
        left: newX,
        right: newX + finalWidth,
        top: newY,
        bottom: newY + finalHeight,
      },
    });

    // NEW CODE: Check if this group has a parent and resize parent groups recursively
    if (updatedGroup.parentId) {
      console.log(
        `Group ${groupId} has parent ${updatedGroup.parentId}, resizing parent group...`
      );
      this.resizeParentGroupToFitChildren(updatedGroup.parentId, updatedGroup);
    }

    return updatedGroup;
  }

  private resizeParentGroupToFitChildren(
    parentGroupId: string,
    childGroup: GroupNodeModel
  ): void {
    // Get the parent group by its ID
    const parentGroup = this.flowService
      .groups()
      .find((g) => g.id === parentGroupId);
    if (!parentGroup) {
      console.warn('Parent group not found:', parentGroupId);
      return;
    }

    console.log(
      `Adjusting parent group ${parentGroupId} to fit changed child group ${childGroup.id}`
    );

    // Get all nodes that are direct children of this parent group
    const childNodes = this.flowService
      .nodes()
      .filter((node) => node.parentId === parentGroupId);

    // Get all groups that are direct children of this parent group
    const childGroups = this.flowService
      .groups()
      .filter((g) => g.parentId === parentGroupId);

    // Combine to get all children
    const allChildren = [...childNodes, ...childGroups];

    if (allChildren.length === 0) {
      console.warn('No children found for parent group:', parentGroupId);
      return;
    }

    // Calculate the bounding box for all children
    const boundingBox = this.calculateNodesBoundingBox(allChildren);
    if (!boundingBox) {
      console.warn(
        'Could not calculate bounding box for parent group children'
      );
      return;
    }

    // Basic padding for nodes within the group
    const HORIZONTAL_PADDING = 30;
    const VERTICAL_PADDING = 40;

    // For parent groups, we DON'T add extra space for new nodes
    // Since that space was already added in the child groups

    // Current parent group bounds
    const groupLeft = parentGroup.position.x;
    const groupRight = parentGroup.position.x + parentGroup.size.width;
    const groupTop = parentGroup.position.y;
    const groupBottom = parentGroup.position.y + parentGroup.size.height;

    // Required bounds to fit all children
    const requiredLeft = boundingBox.x - HORIZONTAL_PADDING;
    const requiredRight =
      boundingBox.x + boundingBox.width + HORIZONTAL_PADDING;
    const requiredTop = boundingBox.y - VERTICAL_PADDING;
    const requiredBottom =
      boundingBox.y + boundingBox.height + VERTICAL_PADDING;

    // Calculate new position (may need to move left/up)
    const newX = Math.min(groupLeft, requiredLeft);
    const newY = Math.min(groupTop, requiredTop);

    // Calculate new size to contain all children
    const newWidth = Math.max(groupRight, requiredRight) - newX;
    const newHeight = Math.max(groupBottom, requiredBottom) - newY;

    // Minimum size constraints
    const MIN_GROUP_WIDTH = 300;
    const MIN_GROUP_HEIGHT = 200;

    // Apply minimum constraints
    const finalWidth = Math.max(newWidth, MIN_GROUP_WIDTH);
    const finalHeight = Math.max(newHeight, MIN_GROUP_HEIGHT);

    // Check if resize/reposition is needed
    const needsRepositioning =
      newX !== parentGroup.position.x || newY !== parentGroup.position.y;
    const needsResize =
      finalWidth !== parentGroup.size.width ||
      finalHeight !== parentGroup.size.height;

    if (!needsResize && !needsRepositioning) {
      console.log(
        'Parent group already fits all children with sufficient padding. No changes needed.'
      );
      return;
    }

    // Create updated parent group model
    const updatedParentGroup: GroupNodeModel = {
      ...parentGroup,
      position: { x: newX, y: newY },
      size: {
        width: finalWidth,
        height: finalHeight,
      },
    };

    // Update the parent group
    this.flowService.updateGroup(updatedParentGroup);

    console.log('Parent group updated:', {
      groupId: parentGroupId,
      oldBounds: {
        left: parentGroup.position.x,
        right: parentGroup.position.x + parentGroup.size.width,
        top: parentGroup.position.y,
        bottom: parentGroup.position.y + parentGroup.size.height,
      },
      newBounds: {
        left: newX,
        right: newX + finalWidth,
        top: newY,
        bottom: newY + finalHeight,
      },
    });

    // Recursively check if this parent group has its own parent
    if (updatedParentGroup.parentId) {
      console.log(
        `Parent group ${parentGroupId} has parent ${updatedParentGroup.parentId}, resizing higher parent...`
      );
      this.resizeParentGroupToFitChildren(
        updatedParentGroup.parentId,
        updatedParentGroup
      );
    }
  }

  private calculateNodesBoundingBox(nodes: NodeModel[]): IRect | null {
    if (nodes.length === 0) {
      return null;
    }

    // Default node dimensions in case size property is missing
    const DEFAULT_WIDTH = 330;
    const DEFAULT_HEIGHT = 60;

    // Initialize with the first node's position and size
    const firstNode = nodes[0];
    const firstNodeWidth =
      (firstNode.size && firstNode.size.width) || DEFAULT_WIDTH;
    const firstNodeHeight =
      (firstNode.size && firstNode.size.height) || DEFAULT_HEIGHT;

    let minX = firstNode.position.x;
    let minY = firstNode.position.y;
    let maxX = firstNode.position.x + firstNodeWidth;
    let maxY = firstNode.position.y + firstNodeHeight;

    // Find the minimum and maximum coordinates for all nodes using their actual size
    nodes.forEach((node) => {
      // Use node's actual size if available, otherwise use defaults
      const nodeWidth = (node.size && node.size.width) || DEFAULT_WIDTH;
      const nodeHeight = (node.size && node.size.height) || DEFAULT_HEIGHT;

      minX = Math.min(minX, node.position.x);
      minY = Math.min(minY, node.position.y);
      maxX = Math.max(maxX, node.position.x + nodeWidth);
      maxY = Math.max(maxY, node.position.y + nodeHeight);
    });

    // Calculate width, height, and gravity center
    const width = maxX - minX;
    const height = maxY - minY;
    const gravityCenter: IPoint = {
      x: minX + width / 2,
      y: minY + height / 2,
    };

    console.log('Calculated bounding box using node model sizes:', {
      x: minX,
      y: minY,
      width,
      height,
      nodes: nodes.map((n) => ({
        id: n.id,
        pos: n.position,
        size: n.size,
      })),
    });

    return {
      x: minX,
      y: minY,
      width,
      height,
      gravityCenter,
    };
  }

  public onGroupRename(event: { id: string; newName: string }): void {
    // Save the state for undo before making changes
    this.undoRedoService.stateChanged();

    // Find the group in the flow service
    const group = this.flowService.groups().find((g) => g.id === event.id);

    if (!group) {
      console.warn(`Group with ID ${event.id} not found`);
      return;
    }

    // Create an updated version of the group with the new name
    const updatedGroup: GroupNodeModel = {
      ...group,
      data: {
        ...group.data,
        name: event.newName,
      },
    };

    // Update the group in the flow service
    this.flowService.updateGroup(updatedGroup);
  }
  public onGroupColorChange(event: {
    id: string;
    backgroundColor: string;
  }): void {
    // Save the state for undo before making changes
    this.undoRedoService.stateChanged();

    // Find the group in the flow service
    const group = this.flowService.groups().find((g) => g.id === event.id);

    if (!group) {
      console.warn(`Group with ID ${event.id} not found`);
      return;
    }

    // Create an updated version of the group with the new color
    const updatedGroup: GroupNodeModel = {
      ...group,
      backgroundColor: event.backgroundColor, // Update the color property directly
    };

    // Update the group in the flow service
    this.flowService.updateGroup(updatedGroup);
  }
  // Handle ungroup event

  public onUngroupGroup(groupId: string): void {
    // Save the state for undo before making changes
    this.undoRedoService.stateChanged();

    // Find the group in the flow service
    const group: GroupNodeModel | undefined = this.flowService
      .groups()
      .find((g) => g.id === groupId);

    if (!group) {
      console.warn(`Group with ID ${groupId} not found`);
      return;
    }

    // Simply set the group's parentId to null and update
    const updatedGroup: GroupNodeModel = {
      ...group,
      parentId: null,
    };

    // Update the group in the flow service
    this.flowService.updateGroup(updatedGroup);
  }

  onGroupToggleCollapsed(groupId: string): void {
    // Find the group
    const group = this.flowService.groups().find((g) => g.id === groupId);
    if (!group) return;

    if (!group.collapsed) {
      console.log('Collapsing group:', group.node_name);

      // Get all connections
      const { inputs, outputs, internal } =
        this.groupCollapserService.getGroupAllConnections(groupId);

      // Log connection information
      console.log('Input connections count:', inputs.length);
      console.log('Output connections count:', outputs.length);
      console.log('Internal connections count:', internal.length);

      // Pass connections to the collapseGroup method
      this.collapseGroup(group, inputs, outputs, internal);
    } else {
      console.log('Expanding group:', group.node_name);
      this.expandGroup(group);
    }

    console.log('Group collapsed state toggled:', !group.collapsed);
  }

  /**
   * Collapses a group and saves positions of all descendant elements
   */
  private collapseGroup(
    group: GroupNodeModel,
    inputs: ConnectionModel[],
    outputs: ConnectionModel[],
    internal: ConnectionModel[]
  ): void {
    // Save the state for undo before collapsing
    this.undoRedoService.stateChanged();

    // Save the relative positions of all descendant elements
    const childPositions = this.calculateAllDescendantRelativePositions(group);

    // Store connection data in the group
    const connectionData = {
      inputs: inputs,
      outputs: outputs,
      internal: internal,
    };

    // Calculate the collapsed position
    const collapsedPosition = calculateGroupCollapsedPosition(group);

    const updatedGroup = {
      ...group,
      collapsed: true,
      collasedPosition: collapsedPosition, // Set the collapsed position
      childPositions: childPositions,
      data: {
        ...group.data,
        connectionData: connectionData,
      },
    };

    // Update the group
    this.flowService.updateGroup(updatedGroup);

    // Create virtual connections to represent external connections
    const virtualConnections: ConnectionModel[] = [
      ...this.createVirtualInputConnections(group, inputs),
      ...this.createVirtualOutputConnections(group, outputs),
    ];

    // Add the virtual connections in batch
    if (virtualConnections.length > 0) {
      this.flowService.addConnectionsInBatch(virtualConnections);
    }
  }

  private createVirtualInputConnections(
    group: GroupNodeModel,
    inputConnections: ConnectionModel[]
  ): ConnectionModel[] {
    return inputConnections.map((conn, index) => {
      // Use the fixed group-input port ID
      const virtualTargetPortId = `${group.id}_group-input` as CustomPortId;

      // Generate a unique connection ID with index to ensure uniqueness
      const newConnectionId =
        `${conn.sourcePortId}+${virtualTargetPortId}_${index}` as CustomPortId;

      // Find the source node for coloring
      const sourceNode =
        this.flowService
          .nodes()
          .find((node) => node.id === conn.sourceNodeId) ||
        this.flowService.groups().find((g) => g.id === conn.sourceNodeId);

      // Create the virtual connection
      return {
        id: newConnectionId,
        category: 'virtual',
        sourceNodeId: conn.sourceNodeId,
        targetNodeId: group.id,
        sourcePortId: conn.sourcePortId,
        targetPortId: virtualTargetPortId,
        startColor:
          conn.startColor ||
          (sourceNode ? NODE_COLORS[sourceNode.type] : '#ddd'),
        endColor: NODE_COLORS[NodeType.GROUP] || '#ddd',
        behavior: 'floating',
        type: 'straight',
      };
    });
  }

  /**
   * Creates virtual connections to represent output connections from a collapsed group
   */
  private createVirtualOutputConnections(
    group: GroupNodeModel,
    outputConnections: ConnectionModel[]
  ): ConnectionModel[] {
    return outputConnections.map((conn, index) => {
      // Use the fixed group-output port ID
      const groupPortId = `${group.id}_group-output` as CustomPortId;

      // Generate a unique connection ID with index to ensure uniqueness
      const newConnectionId =
        `${groupPortId}+${conn.targetPortId}_${index}` as CustomPortId;

      // Find the target node for coloring
      const targetNode =
        this.flowService
          .nodes()
          .find((node) => node.id === conn.targetNodeId) ||
        this.flowService.groups().find((g) => g.id === conn.targetNodeId);

      // Create the virtual connection
      return {
        id: newConnectionId,
        category: 'virtual',
        sourceNodeId: group.id,
        targetNodeId: conn.targetNodeId,
        sourcePortId: groupPortId,
        targetPortId: conn.targetPortId,
        startColor: NODE_COLORS[NodeType.GROUP] || '#ddd',
        endColor:
          conn.endColor || (targetNode ? NODE_COLORS[targetNode.type] : '#ddd'),
        behavior: 'floating',
        type: 'straight',
      };
    });
  }

  //   private expandGroup(group: GroupNodeModel): void {
  //     // Save the state for undo before expanding
  //     this.undoRedoService.stateChanged();

  //     // Find virtual connections to remove
  //     const allConnections = this.flowService.connections();
  //     const virtualConnectionIds = allConnections
  //       .filter(
  //         (conn) =>
  //           (conn.sourceNodeId === group.id || conn.targetNodeId === group.id) &&
  //           (conn.sourcePortId.includes('group-input') ||
  //             conn.sourcePortId.includes('group-output') ||
  //             conn.targetPortId.includes('group-input') ||
  //             conn.targetPortId.includes('group-output'))
  //       )
  //       .map((conn) => conn.id);

  //     // Use the utility function to calculate normal position from collapsed position
  //     let updatedPosition = group.position;

  //     // If we have a collapsed position, use utility function to get normal position
  //     if (group.collapsedPosition) {
  //       updatedPosition = calculateGroupExpandedPosition({
  //         collapsedPosition: group.collapsedPosition,
  //         size: group.size,
  //       });
  //     }

  //     // Update group to expanded state
  //     const updatedGroup = {
  //       ...group,
  //       collapsed: false,
  //       position: updatedPosition,
  //       data: {
  //         ...group.data,
  //         connectionData: null, // Clear out the connection data as it's no longer needed
  //       },
  //     };
  //     this.flowService.updateGroup(updatedGroup);
  //     // Remove all virtual connections in batch
  //     if (virtualConnectionIds.length > 0) {
  //       this.flowService.removeConnectionsInBatch(virtualConnectionIds);
  //     }

  //     // Restore child positions if available
  //     this.restoreAllDescendantPositions(group);
  //   }

  private calculateAllDescendantRelativePositions(
    group: GroupNodeModel
  ): Map<string, { x: number; y: number }> {
    const childPositions = new Map<string, { x: number; y: number }>();

    // Helper function to recursively find all descendants of a group
    const addDescendantsOf = (groupId: string) => {
      // Add nodes that are direct children of this group
      this.flowService.nodes().forEach((node) => {
        if (node.parentId === groupId) {
          childPositions.set(node.id, {
            x: node.position.x - group.position.x,
            y: node.position.y - group.position.y,
          });
        }
      });

      // Find and process nested groups
      this.flowService.groups().forEach((childGroup) => {
        if (childGroup.parentId === groupId) {
          // Add the child group itself
          childPositions.set(childGroup.id, {
            x: childGroup.position.x - group.position.x,
            y: childGroup.position.y - group.position.y,
          });

          // Recursively add descendants of this child group
          addDescendantsOf(childGroup.id);
        }
      });
    };

    // Start the recursive process
    addDescendantsOf(group.id);

    return childPositions;
  }
  private restoreAllDescendantPositions(group: GroupNodeModel): void {
    // Check if we have saved child positions
    if (!group.childPositions) return;

    const updatedNodes: NodeModel[] = [];
    const updatedGroups: GroupNodeModel[] = [];

    // Use the utility function to convert childPositions from JSON to a Map
    const positionsMap = convertJsonToMap(group.childPositions);

    // Restore positions for all nodes that have saved positions
    this.flowService.nodes().forEach((node) => {
      if (positionsMap.has(node.id)) {
        const relativePos = positionsMap.get(node.id)!;
        updatedNodes.push({
          ...node,
          position: this.calculateAbsolutePosition(group.position, relativePos),
        });
      }
    });

    // Restore positions for all groups that have saved positions
    this.flowService.groups().forEach((childGroup) => {
      if (positionsMap.has(childGroup.id)) {
        const relativePos = positionsMap.get(childGroup.id)!;
        updatedGroups.push({
          ...childGroup,
          position: this.calculateAbsolutePosition(group.position, relativePos),
        });
      }
    });

    // Update positions in batch
    if (updatedNodes.length > 0) {
      this.flowService.updateNodesInBatch(updatedNodes);
    }

    if (updatedGroups.length > 0) {
      this.flowService.updateGroupsInBatch(updatedGroups);
    }
  }

  private calculateAbsolutePosition(
    parentPos: { x: number; y: number },
    relativePos: { x: number; y: number }
  ): { x: number; y: number } {
    return {
      x: parentPos.x + relativePos.x,
      y: parentPos.y + relativePos.y,
    };
  }

  //GROUP POSITION CHAHNGED LOGIC TOGETHER WITH NODE POSTIONS CHANGED LOGIC
  private draggingElements = new Set<string>();
  private draggingGroupIds = new Set<string>();
  private isDragging = false;

  public onDragStarted(event: FDragStartedEvent): void {
    console.log('Drag started:', event);

    // Set the drag flag
    this.isDragging = true;

    // Clear previous tracking
    this.draggingElements.clear();
    this.draggingGroupIds.clear();

    // Add all dragged elements to our tracking set
    if (event.fData && event.fData.fNodeIds) {
      event.fData.fNodeIds.forEach((id: string) => {
        this.draggingElements.add(id);

        // Check if this ID belongs to a group
        const group = this.flowService.groups().find((g) => g.id === id);
        if (group) {
          this.draggingGroupIds.add(id);

          // Also get all descendants of this group and track them too
          const descendantIds = this.flowService.getAllDescendantIds(id);
          descendantIds.forEach((descendantId) => {
            this.draggingElements.add(descendantId);
          });
        }
      });
    }

    console.log('Dragging elements:', Array.from(this.draggingElements));
    console.log('Dragging groups:', Array.from(this.draggingGroupIds));

    // Save state for undo
    this.undoRedoService.stateChanged();
  }

  /**
   * Handles the end of a drag operation
   */
  public onDragEnded(): void {
    console.log('Drag ended');

    // Reset all tracking
    setTimeout(() => {
      this.isDragging = false;
      this.draggingElements.clear();
      this.draggingGroupIds.clear();
    }, 100);
  }

  /**
   * Handles when a group's position changes
   */
  public onGroupPositionChanged(newPos: IPoint, group: GroupNodeModel): void {
    console.log('Group position changed for group:', group.id);

    // If we're not in a tracked drag operation, or this group isn't being dragged directly
    if (!this.isDragging || !this.draggingElements.has(group.id)) {
      // This could be a programmatic update or a nested group move
      // We should check if this is a nested group being moved by its parent
      const isNestedGroupMove =
        this.isDragging &&
        group.parentId &&
        this.draggingElements.has(group.parentId);

      if (!isNestedGroupMove) {
        // This is an independent group move, save state
        this.undoRedoService.stateChanged();
      }
    }

    // Calculate new positions
    let updatedPosition: IPoint;
    let updatedCollapsedPosition: IPoint;

    if (group.collapsed) {
      updatedCollapsedPosition = newPos;
      updatedPosition = calculateGroupExpandedPosition({
        collapsedPosition: newPos,
        size: group.size,
      });
    } else {
      updatedPosition = newPos;
      updatedCollapsedPosition = calculateGroupCollapsedPosition({
        position: newPos,
        size: group.size,
      });
    }

    // Create updated group
    const updatedGroup: GroupNodeModel = {
      ...group,
      position: updatedPosition,
      collapsedPosition: updatedCollapsedPosition,
    };

    // Only update child positions if this group is being dragged directly (not via a parent)
    if (!group.parentId || !this.draggingElements.has(group.parentId)) {
      // Calculate position delta
      const deltaX = updatedPosition.x - group.position.x;
      const deltaY = updatedPosition.y - group.position.y;

      // Get all descendant IDs
      const descendantIds = this.flowService.getAllDescendantIds(group.id);

      // Get all descendant nodes and update their positions
      const nodesToUpdate: NodeModel[] = [];
      this.flowService.nodes().forEach((node) => {
        if (descendantIds.has(node.id)) {
          nodesToUpdate.push({
            ...node,
            position: {
              x: node.position.x + deltaX,
              y: node.position.y + deltaY,
            },
          });
        }
      });

      // Get all descendant groups and update their positions
      const groupsToUpdate: GroupNodeModel[] = [];
      this.flowService.groups().forEach((childGroup) => {
        if (descendantIds.has(childGroup.id)) {
          groupsToUpdate.push({
            ...childGroup,
            position: {
              x: childGroup.position.x + deltaX,
              y: childGroup.position.y + deltaY,
            },
            collapsedPosition: childGroup.collapsedPosition
              ? {
                  x: childGroup.collapsedPosition.x + deltaX,
                  y: childGroup.collapsedPosition.y + deltaY,
                }
              : childGroup.collapsedPosition,
          });
        }
      });

      // Update the main group
      this.flowService.updateGroup(updatedGroup);

      // Update all descendants
      if (nodesToUpdate.length > 0) {
        this.flowService.updateNodesInBatch(nodesToUpdate);
      }

      if (groupsToUpdate.length > 0) {
        this.flowService.updateGroupsInBatch(groupsToUpdate);
      }
    } else {
      // This is a nested group being moved by its parent, just update this group
      this.flowService.updateGroup(updatedGroup);
    }
  }

  public onNodePositionChanged(newPos: IPoint, node: NodeModel): void {
    console.log('Node position changed for node:', node.id);
    console.log(this.fFlowComponent.getNodesBoundingBox());
    // If we're not in a tracked drag operation, or this node isn't being dragged directly or by a parent
    if (!this.isDragging || !this.draggingElements.has(node.id)) {
      // This could be a programmatic update or a child node move
      // We should check if this is a child node being moved by its parent group
      const isChildNodeMove =
        this.isDragging &&
        node.parentId &&
        this.draggingElements.has(node.parentId);

      if (!isChildNodeMove) {
        // This is an independent node move, save state
        this.undoRedoService.stateChanged();
      } else {
        // This is a child node being moved as part of its parent group
        // Skip individual update as it will be handled by the group update
        console.log('Skipping node update during parent group move');
        return;
      }
    }

    // Create an updated node with the new position
    const updatedNode = {
      ...node,
      position: newPos,
    };

    // Update the node
    this.flowService.updateNode(updatedNode);
  }

  //EXPANG GROUP NEW LOGIC , PREVIOUS IS COMMENTED ABOVE
  private expandGroup(group: GroupNodeModel): void {
    // Save the state for undo before expanding
    this.undoRedoService.stateChanged();

    // Find virtual connections to remove
    const allConnections = this.flowService.connections();
    const virtualConnectionIds = allConnections
      .filter(
        (conn) =>
          (conn.sourceNodeId === group.id || conn.targetNodeId === group.id) &&
          (conn.sourcePortId.includes('group-input') ||
            conn.sourcePortId.includes('group-output') ||
            conn.targetPortId.includes('group-input') ||
            conn.targetPortId.includes('group-output'))
      )
      .map((conn) => conn.id);

    // Calculate normal position from collapsed position
    let updatedPosition = group.position;
    if (group.collapsedPosition) {
      updatedPosition = calculateGroupExpandedPosition({
        collapsedPosition: group.collapsedPosition,
        size: group.size,
      });
    }

    // Important: Create a copy of the group with its original size and updated position
    const updatedGroup = {
      ...group,
      collapsed: false,
      position: updatedPosition,
      data: {
        ...group.data,
        connectionData: null, // Clear connection data
      },
      // DO NOT change the size - keep the original size from before collapse
    };

    // Step 1: Update the group itself first
    this.flowService.updateGroup(updatedGroup);

    // Step 2: Remove virtual connections
    if (virtualConnectionIds.length > 0) {
      this.flowService.removeConnectionsInBatch(virtualConnectionIds);
    }

    // Step 3: Restore child positions if available
    this.restoreAllDescendantPositions(group);

    // Step 4: If the group has a parent, ensure parent is correctly sized
    if (group.parentId) {
      // Collect all parents that need resizing
      this.adjustParentGroupsForExpandedChild(group.parentId, updatedGroup);
    }
  }

  /**
   * Adjusts all parent groups in the hierarchy to fit an expanded child
   */
  private adjustParentGroupsForExpandedChild(
    parentGroupId: string,
    expandedChild: GroupNodeModel
  ): void {
    // Get the parent group
    const parentGroup = this.flowService
      .groups()
      .find((g) => g.id === parentGroupId);
    if (!parentGroup) {
      console.warn('Parent group not found:', parentGroupId);
      return;
    }

    // Check if parent needs resizing
    const needsResize = this.doesParentNeedResizing(parentGroup, expandedChild);
    if (!needsResize) {
      console.log(
        `Parent group ${parentGroupId} already fits expanded child ${expandedChild.id}`
      );
      return;
    }

    // Calculate new parent size based on all its children
    const updatedParent = this.calculateParentSizeToFitChildren(parentGroup);
    if (!updatedParent) {
      console.warn(
        `Failed to calculate new size for parent group ${parentGroupId}`
      );
      return;
    }

    // Update the parent group
    this.flowService.updateGroup(updatedParent);

    // Continue up the hierarchy if this parent has its own parent
    if (updatedParent.parentId) {
      this.adjustParentGroupsForExpandedChild(
        updatedParent.parentId,
        updatedParent
      );
    }
  }

  /**
   * Checks if a parent group needs resizing to fit an expanded child
   */
  private doesParentNeedResizing(
    parentGroup: GroupNodeModel,
    childGroup: GroupNodeModel
  ): boolean {
    const PADDING = 30; // Padding around elements

    // Calculate child bounds
    const childLeft = childGroup.position.x;
    const childRight = childGroup.position.x + childGroup.size.width;
    const childTop = childGroup.position.y;
    const childBottom = childGroup.position.y + childGroup.size.height;

    // Calculate parent bounds
    const parentLeft = parentGroup.position.x;
    const parentRight = parentGroup.position.x + parentGroup.size.width;
    const parentTop = parentGroup.position.y;
    const parentBottom = parentGroup.position.y + parentGroup.size.height;

    // Check if child overflows parent in any direction
    return (
      childLeft - PADDING < parentLeft ||
      childRight + PADDING > parentRight ||
      childTop - PADDING < parentTop ||
      childBottom + PADDING > parentBottom
    );
  }

  /**
   * Calculates new size for a parent group to fit all its children
   */
  private calculateParentSizeToFitChildren(
    parentGroup: GroupNodeModel
  ): GroupNodeModel | null {
    // Get all children of this parent
    const childNodes = this.flowService
      .nodes()
      .filter((node) => node.parentId === parentGroup.id);

    const childGroups = this.flowService
      .groups()
      .filter((group) => group.parentId === parentGroup.id);

    const allChildren = [...childNodes, ...childGroups];
    if (allChildren.length === 0) return null;

    // Calculate the bounding box
    const boundingBox = this.calculateNodesBoundingBox(allChildren);
    if (!boundingBox) return null;

    const PADDING = 30;

    // Current parent bounds
    const parentLeft = parentGroup.position.x;
    const parentRight = parentGroup.position.x + parentGroup.size.width;
    const parentTop = parentGroup.position.y;
    const parentBottom = parentGroup.position.y + parentGroup.size.height;

    // Required bounds
    const requiredLeft = boundingBox.x - PADDING;
    const requiredRight = boundingBox.x + boundingBox.width + PADDING;
    const requiredTop = boundingBox.y - PADDING;
    const requiredBottom = boundingBox.y + boundingBox.height + PADDING;

    // Calculate new position and size
    const newX = Math.min(parentLeft, requiredLeft);
    const newY = Math.min(parentTop, requiredTop);
    const newWidth = Math.max(parentRight, requiredRight) - newX;
    const newHeight = Math.max(parentBottom, requiredBottom) - newY;

    // Minimum size constraints
    const MIN_WIDTH = 300;
    const MIN_HEIGHT = 200;

    // Create updated parent
    return {
      ...parentGroup,
      position: { x: newX, y: newY },
      size: {
        width: Math.max(newWidth, MIN_WIDTH),
        height: Math.max(newHeight, MIN_HEIGHT),
      },
    };
  }
  public onZoomInNode(node: NodeModel): void {
    // If node doesn't have a parent, just center on it
    if (!node.parentId) {
      this.fCanvasComponent.centerGroupOrNode(node.id, true);
      return;
    }

    // Node has a parent - gather the chain of parent groups
    const parentGroups: GroupNodeModel[] = [];
    let currentParentId: string | null = node.parentId;

    // Get all groups from flow service
    const allGroups = this.flowService.groups();

    // Build the chain of parent groups, from direct parent to the topmost ancestor
    while (currentParentId) {
      const parentGroup = allGroups.find(
        (group) => group.id === currentParentId
      );
      if (!parentGroup) break; // Parent not found, exit loop

      // Add this parent to our chain
      parentGroups.unshift(parentGroup); // Add to the beginning, so we expand from topmost parent

      // Move up to the next parent, if any
      currentParentId = parentGroup.parentId;
    }

    // Now expand all groups in the chain, starting from topmost ancestor
    for (const group of parentGroups) {
      if (group.collapsed) {
        this.expandGroup(group);
      }
    }

    // Finally, center on the target node
    setTimeout(() => {
      // Add a small delay to ensure groups have expanded
      this.fCanvasComponent.centerGroupOrNode(node.id, true);
    }, 100);
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

  public onProjectExpandToggled(project: ProjectNodeModel): void {
    console.log('Project expanded:', project.data.id);

    const dialogRef = this.dialog.open(ProjectDialogComponent, {
      width: '90vw',
      height: '90vh',
      maxWidth: '100vw',
      maxHeight: '100vh',
      data: {
        projectId: project.data.id,
        projectName: project.data.name,
      },
    });

    dialogRef.closed.subscribe(() => {});
  }

  public ngOnDestroy(): void {
    // Close any open side panels
    this.sidePanelService.tryClosePanel().then(() => {
      console.log('Side panel closed on flow graph destroy');
    });

    this.destroy$.next();
    this.destroy$.complete();
  }
}
