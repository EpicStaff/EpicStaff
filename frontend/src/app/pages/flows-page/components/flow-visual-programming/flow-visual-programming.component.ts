import { Dialog as CdkDialog } from '@angular/cdk/dialog';
import { Overlay } from '@angular/cdk/overlay';
import { HttpErrorResponse } from '@angular/common/http';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    HostListener,
    inject,
    Injector,
    OnDestroy,
    OnInit,
    signal,
    ViewChild,
} from '@angular/core';
import { takeUntilDestroyed, toObservable, toSignal } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ActivatedRoute, Router } from '@angular/router';
import { GetLlmConfigRequest } from '@shared/models';
import { LlmConfigStorageService } from '@shared/services';
import { extractHttpErrorMessage } from '@shared/utils';
import { catchError, EMPTY, filter, finalize, forkJoin, map, Observable, of, switchMap, take, tap, timer } from 'rxjs';
import { GraphCollaborationWsService } from 'src/app/features/flows/services/graph-collaboration.ws.service';
import { buildNodeBackendPayload } from 'src/app/features/flows/services/graph-collaboration.ws.service';
import { mergeNodeEntry } from 'src/app/visual-programming/utils/save/partial-node-broadcast';

import { CanComponentDeactivate } from '../../../../core/guards/unsaved-changes.guard';
import { EpicChatService } from '../../../../features/epic-chat/epic-chat.service';
import { FlowAssistantPanelComponent } from '../../../../features/flow-assistant/components/flow-assistant-panel/flow-assistant-panel.component';
import { FlowAssistantService } from '../../../../features/flow-assistant/flow-assistant.service';
import { FlowSessionsListComponent } from '../../../../features/flows/components/flow-sessions-dialog/flow-sessions-list.component';
import { RestoreWarningsDialogComponent } from '../../../../features/flows/components/restore-warnings-dialog/restore-warnings-dialog.component';
import {
    SaveVersionDialogComponent,
    SaveVersionDialogResult,
} from '../../../../features/flows/components/save-version-dialog/save-version-dialog.component';
import { VersionHistoryPanelComponent } from '../../../../features/flows/components/version-history-panel/version-history-panel.component';
import {
    GetGraphLightRequest,
    GraphDto,
    GraphRestoreResponse,
    RestoreWarning,
} from '../../../../features/flows/models/graph.model';
import { CreateGraphWarningsService } from '../../../../features/flows/services/create-graph-warnings.service';
import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import { FlowsStorageService } from '../../../../features/flows/services/flows-storage.service';
import { RunGraphService } from '../../../../features/flows/services/run-graph-session.service';
import { FlowMessagesPanelComponent } from '../../../../pages/running-graph/components/flow-messages-panel/flow-messages-panel.component';
import { RunSessionSSEService } from '../../../../pages/running-graph/services/graph-session-sse.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ConfigService } from '../../../../services/config/config.service';
import { ToastService } from '../../../../services/notifications/toast.service';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { SpinnerComponent } from '../../../../shared/components/spinner/spinner.component';
import { UnsavedChangesDialogService } from '../../../../shared/components/unsaved-changes-dialog/unsaved-changes-dialog.service';
import { NodeType } from '../../../../visual-programming/core/enums/node-type';
import { ConditionGroup } from '../../../../visual-programming/core/models/decision-table.model';
import { FlowModel } from '../../../../visual-programming/core/models/flow.model';
import { ScheduleTriggerNodeModel } from '../../../../visual-programming/core/models/node.model';
import { NodeModel } from '../../../../visual-programming/core/models/node.model';
import { CustomPortId } from '../../../../visual-programming/core/models/port.model';
import { FlowGraphComponent } from '../../../../visual-programming/flow-graph/flow-graph.component';
import { FlowService } from '../../../../visual-programming/services/flow.service';
import { SidePanelService } from '../../../../visual-programming/services/side-panel.service';
import { UndoRedoService } from '../../../../visual-programming/services/undo-redo.service';
import { createFlowConnection } from '../../../../visual-programming/utils/connection.factory';
import {
    createStartNode,
    hasStartNode,
    mapGraphDtoToFlowModel,
    normalizeFlowPorts,
} from '../../../../visual-programming/utils/load';
import { rewriteLegacyOnceScheduleName } from '../../../../visual-programming/utils/load/nodes/schedule-trigger-node.mapper';
import { mapWsNodePayloadToModel } from '../../../../visual-programming/utils/load/ws-node-payload-to-model';
import { getInputPortRole, getOutputPortRole } from '../../../../visual-programming/utils/node-port-roles';
import {
    buildBulkSavePayload,
    buildCdtSavedBaseline,
    buildUuidToBackendIdMap,
    clearStaleIds,
    cloneFlowState,
    getConnectionDiff,
    getNodeDiff,
    patchCdtPromptBackendIds,
    patchFlowStateWithBackendIds,
} from '../../../../visual-programming/utils/save';
import { FlowUnsavedStateService } from '../../services/flow-unsaved-state.service';
import { FlowHeaderComponent } from './components/header/flow-header.component';
import { ShortcutsModalComponent } from './components/shortcuts-modal/shortcuts-modal.component';
import { FLOW_SHORTCUT_SECTIONS } from './flow-shortcuts.config';

//.
@Component({
    selector: 'app-flow-visual-programming',
    standalone: true,
    imports: [
        AppSvgIconComponent,
        FlowHeaderComponent,
        FlowGraphComponent,
        SpinnerComponent,
        ShortcutsModalComponent,
        FlowMessagesPanelComponent,
        MatTooltipModule,
        FlowAssistantPanelComponent,
    ],
    templateUrl: './flow-visual-programming.component.html',
    styleUrl: './flow-visual-programming.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowVisualProgrammingComponent implements OnInit, OnDestroy, CanComponentDeactivate {
    private readonly destroyRef = inject(DestroyRef);
    private readonly wsService = inject(GraphCollaborationWsService);
    private readonly profileService = inject(ProfileService);
    /** @deprecated used only by the deprecated manual-save path (saveCurrentState). */
    private readonly injector = inject(Injector);

    public readonly flowAssistantService = inject(FlowAssistantService);
    public readonly isEpicChatEnabled: boolean;
    public initialNodeId: string | null = null;
    public isLoaded = signal(false);
    private readonly graphState = signal<GraphDto | null>(null);
    private readonly availableFlowLights = signal<GetGraphLightRequest[]>([]);
    private readonly savedFlowState = signal<FlowModel>({ nodes: [], connections: [] });
    protected readonly collaborationEditors = this.wsService.editors;
    public readonly loadedFlowState = computed<FlowModel>(() => {
        const graph = this.graphState();
        if (!graph) return { nodes: [], connections: [] };

        let flowModel = mapGraphDtoToFlowModel(graph);
        flowModel = this.addStartNodeIfNeeded(flowModel, graph.id);
        const validated = this.validateSubgraphNodes(flowModel, this.availableFlowLights());
        return validated.flowModel;
    });
    public readonly currentFlowState = computed<FlowModel>(() => this.flowService.getFlowState());
    public readonly hasUnsavedChangesSignal = computed<boolean>(() => {
        return JSON.stringify(this.currentFlowState()) !== JSON.stringify(this.savedFlowState());
    });
    /** @deprecated the "saved by" banner was removed in EST-3020; nothing sets or renders it. */
    public readonly savedByBanner = signal<string | null>(null);

    /** @deprecated set only by the deprecated manual REST save path (saveFlowState). */
    public isSaving = signal(false);
    public isRunning = signal(false);
    public restoreWarnings = signal<RestoreWarning[]>([]);

    public isPanelOpen = signal(false);
    public isPanelCollapsed = signal(true);
    public currentSessionId: string | null = null;
    public panelWidthPx = 450;
    public isDragging = false;
    private readonly MIN_PANEL_WIDTH = 430;
    private readonly MAX_PANEL_WIDTH_RATIO = 0.7;
    private readonly routeParamMap;
    private readonly routeQueryParamMap;
    private isDeactivating = false;

    @ViewChild(FlowGraphComponent)
    private flowGraphComponent?: FlowGraphComponent;

    public get graph(): GraphDto {
        return this.graphState()!;
    }

    constructor(
        private readonly route: ActivatedRoute,
        private readonly router: Router,
        private readonly flowStorageService: FlowsStorageService,
        private readonly flowService: FlowService,
        private readonly flowApiService: FlowsApiService,
        private readonly cdr: ChangeDetectorRef,
        private readonly toastService: ToastService,
        private readonly runGraphService: RunGraphService,
        private readonly dialog: CdkDialog,
        private readonly overlay: Overlay,
        private readonly configService: ConfigService,
        private readonly elementRef: ElementRef,
        private readonly epicChatService: EpicChatService,
        private readonly flowUnsavedStateService: FlowUnsavedStateService,
        private readonly unsavedChangesDialog: UnsavedChangesDialogService,
        private readonly undoRedoService: UndoRedoService,
        private readonly createGraphWarningService: CreateGraphWarningsService,
        private readonly runSessionSSEService: RunSessionSSEService,
        private readonly sidePanelService: SidePanelService,
        private readonly llmConfigStorageService: LlmConfigStorageService
    ) {
        this.isEpicChatEnabled = this.configService.isEpicChatEnabled;
        this.routeParamMap = toSignal(this.route.paramMap, { initialValue: this.route.snapshot.paramMap });
        this.routeQueryParamMap = toSignal(this.route.queryParamMap, {
            initialValue: this.route.snapshot.queryParamMap,
        });

        effect(() => {
            this.initialNodeId = this.routeQueryParamMap().get('nodeId');
        });

        effect(() => {
            const graphId = Number(this.routeParamMap().get('id'));
            if (!isFinite(graphId)) return;
            this.undoRedoService.setUndoStack([]);
            this.undoRedoService.setRedoStack([]);
            const warnings = this.createGraphWarningService.readPending();
            if (warnings.length) this.restoreWarnings.set(warnings);
            this.fetchGraph(graphId);
        });

        this.sidePanelService.saveNodeRequest$
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((node) => this.handleNodeSaveRequest(node));

        this.sidePanelService.reloadRequested$
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.refreshCurrentFlow());

        this.wsService.graphSaved$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event) => {
            this.graphState.update((state) => (state ? { ...state, save_version: event.new_save_version } : state));

            const tempIdMap = event.temp_id_map;
            if (tempIdMap && Object.keys(tempIdMap).length > 0) {
                const updates = this.flowService
                    .nodes()
                    .filter((n) => tempIdMap[n.id] != null)
                    .map((n) => ({ ...n, backendId: tempIdMap[n.id] }));
                if (updates.length > 0) {
                    this.flowService.updateNodesInBatch(updates as NodeModel[]);
                }

                this.flowService.applyConnectionIdMap(tempIdMap, event.graph_id);
            }
            this.savedFlowState.set(cloneFlowState(this.currentFlowState()));
        });

        this.wsService.saveFailed$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event) => {
            this.toastService.error(`Auto-save failed: ${event.reason}`, 5000, 'bottom-right');
        });

        this.wsService.opRejected$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((msg) => {
            const text =
                msg.reason === 'target_not_found'
                    ? 'This node was deleted by other user. Your changes not applied'
                    : `Changes not applied (${msg.reason})`;
            this.toastService.error(text, 5000, 'bottom-right');
        });

        this.wsService.graphState$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((msg) => {
            const currentUserId = this.profileService.currentUserSignal()?.id;
            if (msg.restored_by && msg.restored_by.user_id === currentUserId) {
                if (msg.new_save_version != null) {
                    const newSaveVersion = msg.new_save_version;
                    this.graphState.update((state) => (state ? { ...state, save_version: newSaveVersion } : state));
                }
                return;
            }

            let flowModel = mapGraphDtoToFlowModel(msg.flow);
            flowModel = this.addStartNodeIfNeeded(flowModel, msg.flow.id);
            const normalizedFlow = normalizeFlowPorts(flowModel);
            this.flowService.setFlow(normalizedFlow);

            const startNode = normalizedFlow.nodes.find((n) => n.type === NodeType.START && n.backendId == null);
            if (startNode) {
                this.wsService.sendNodeCreated(startNode, msg.flow.id, normalizedFlow.nodes);
            }

            if (msg.restored_by) {
                this.undoRedoService.setUndoStack([]);
                this.undoRedoService.setRedoStack([]);
                const restoredBy = msg.restored_by.display_name ?? `User ${msg.restored_by.user_id}`;
                const versionName = msg.version_name ?? 'a previous version';
                this.toastService.info(`Flow restored to ${versionName} by ${restoredBy}`);
            }

            // Replace the full graphState (not just save_version) with the restored
            // flow. The canvas was already rebuilt from msg.flow above via setFlow();
            // if graphState kept the pre-restore GraphDto, loadedFlowState() and the
            // diffing in saveFlowState() would compare the new canvas against the
            // stale, pre-restore flow on the next save, producing spurious
            // creations/deletions in the bulk-save payload.
            this.graphState.set({
                ...msg.flow,
                save_version: msg.new_save_version ?? msg.flow.save_version,
            });
        });

        this.wsService.nodeCreated$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((msg) => {
            const node = mapWsNodePayloadToModel(msg.node as Record<string, unknown>, msg.list_key);
            if (!node) return;

            const exists = this.flowService.nodes().some((n) => n.id === node.id);
            if (exists) {
                this.flowService.updateNode(node);
            } else {
                this.flowService.addNode(node);
            }
            this.applyRemoteTableRouting(node.id, msg.node as Record<string, unknown>, msg.list_key);
        });

        this.wsService.nodeUpdated$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((msg) => {
            const p = msg.node as Record<string, unknown>;
            const existing =
                p['temp_id'] != null
                    ? this.flowService.nodes().find((n) => n.id === p['temp_id'])
                    : typeof p['id'] === 'number'
                      ? this.flowService.nodes().find((n) => n.backendId === p['id'])
                      : undefined;

            if (msg.changed_fields && msg.changed_fields.length > 0) {
                if (!existing) return;
                const existingPayload = buildNodeBackendPayload(
                    existing,
                    0,
                    this.flowService.nodes(),
                    this.flowService.connections()
                );
                if (!existingPayload) return;
                const mergedPayload = mergeNodeEntry(existingPayload, p);
                const merged = mapWsNodePayloadToModel(mergedPayload, msg.list_key);
                if (!merged) return;
                this.flowService.updateNode({ ...merged, id: existing.id });
                this.applyRemoteTableRouting(existing.id, mergedPayload, msg.list_key);
                return;
            }

            const updated = mapWsNodePayloadToModel(p, msg.list_key);
            if (!updated) return;

            if (existing) {
                this.flowService.updateNode({ ...updated, id: existing.id });
                this.applyRemoteTableRouting(existing.id, p, msg.list_key);
            }
        });

        this.wsService.nodesDeleted$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((msg) => {
            const fNodeIds = msg.refs
                .map((ref) => {
                    if (ref.id != null) {
                        return this.flowService.nodes().find((n) => n.backendId === ref.id)?.id ?? null;
                    }
                    return ref.temp_id ?? null;
                })
                .filter((id): id is string => id !== null);
            if (fNodeIds.length > 0) {
                this.flowService.deleteSelections({ fNodeIds, fConnectionIds: [] });
            }
        });

        this.wsService.connectionCreated$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((msg) => {
            const p = msg.connection as Record<string, unknown>;
            const nodes = this.flowService.nodes();
            const sourceNode =
                p['start_node_id'] != null
                    ? nodes.find((n) => n.backendId === p['start_node_id'])
                    : nodes.find((n) => n.id === p['start_temp_id']);
            const targetNode =
                p['end_node_id'] != null
                    ? nodes.find((n) => n.backendId === p['end_node_id'])
                    : nodes.find((n) => n.id === p['end_temp_id']);
            if (!sourceNode || !targetNode) {
                console.warn('[WS] connection_created: cannot resolve nodes', p);
                return;
            }
            const sourcePortId: CustomPortId = `${sourceNode.id}_${getOutputPortRole(sourceNode.type)}`;
            const targetPortId: CustomPortId = `${targetNode.id}_${getInputPortRole(targetNode.type)}`;
            const conn = createFlowConnection(sourceNode.id, targetNode.id, sourcePortId, targetPortId);
            const connId = (p['temp_id'] as string | undefined) ?? String(p['id']);
            const data =
                typeof p['id'] === 'number'
                    ? {
                          id: p['id'] as number,
                          start_node_id: (p['start_node_id'] as number) ?? 0,
                          end_node_id: (p['end_node_id'] as number) ?? 0,
                          graph: 0,
                          metadata: (p['metadata'] as Record<string, unknown>) ?? {},
                      }
                    : null;
            this.flowService.addConnection({
                ...conn,
                id: connId,
                data,
                waypoints: p['waypoints'] as typeof conn.waypoints,
            });
        });

        this.wsService.connectionDeleted$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((msg) => {
            let fId: string | undefined;
            if (msg.connection_id != null) {
                fId = this.flowService.connections().find((c) => c.data?.id === msg.connection_id)?.id;
            } else if (msg.temp_id != null) {
                fId = this.flowService.connections().find((c) => c.id === msg.temp_id)?.id;
            }
            if (fId) this.flowService.removeConnection(fId);
        });

        this.wsService.connectionsDeleted$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((msg) => {
            const fIds = msg.refs
                .map((ref) => {
                    if (ref.id != null) {
                        return this.flowService.connections().find((c) => c.data?.id === ref.id)?.id ?? null;
                    }
                    return ref.temp_id ?? null;
                })
                .filter((id): id is string => id !== null);
            if (fIds.length > 0) this.flowService.removeConnectionsInBatch(fIds);
        });

        this.wsService.connectionWaypointsUpdated$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((msg) => {
            const fId =
                typeof msg.connection_id === 'number'
                    ? this.flowService.connections().find((c) => c.data?.id === msg.connection_id)?.id
                    : this.flowService.connections().find((c) => c.id === msg.connection_id)?.id;
            if (fId) this.flowService.updateConnectionWaypoints(fId, msg.waypoints);
        });
    }

    public ngOnInit(): void {
        this.flowUnsavedStateService.register(this);
    }

    public refreshCurrentFlow(): void {
        const graphId = Number(this.route.snapshot.paramMap.get('id'));
        if (!isFinite(graphId)) return;
        this.fetchGraph(graphId, true, true);
    }

    public handlePartialImportComplete(): void {
        const graphId = Number(this.route.snapshot.paramMap.get('id'));
        if (!isFinite(graphId)) return;

        // Capture the set of backendIds already on canvas before the fetch.
        // These identify "pre-existing" server nodes so we can isolate only
        // the newly-imported ones after the server graph is loaded.
        const preImportBackendIds = new Set<number>(
            this.loadedFlowState()
                .nodes.map((n) => n.backendId)
                .filter((id): id is number => id !== null)
        );

        forkJoin({
            graph: this.flowApiService.getGraphById(graphId, true),
            flows: this.flowApiService.getGraphsLight().pipe(catchError(() => of([] as GetGraphLightRequest[]))),
        })
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                tap(({ graph, flows }) => {
                    // Update graphState and availableFlowLights so loadedFlowState()
                    // recomputes via mapGraphDtoToFlowModel + addStartNodeIfNeeded +
                    // validateSubgraphNodes (the existing computed pipeline).
                    this.graphState.set(graph);
                    this.availableFlowLights.set(flows);

                    const serverFlow = this.loadedFlowState();

                    // Nodes from the server whose backendId was not present before
                    // the import — these are the newly-imported nodes.
                    const newServerNodes = serverFlow.nodes.filter(
                        (n) => n.backendId !== null && !preImportBackendIds.has(n.backendId)
                    );
                    const newServerNodeIds = new Set<string>(newServerNodes.map((n) => n.id));

                    // Connections that are entirely within the newly-imported node set.
                    // Cross-boundary connections (new ↔ pre-existing) are skipped because
                    // the server-generated UUIDs don't match the canvas UUIDs of
                    // pre-existing nodes.
                    const newServerConnections = serverFlow.connections.filter(
                        (c) => newServerNodeIds.has(c.sourceNodeId) && newServerNodeIds.has(c.targetNodeId)
                    );

                    const currentState = this.flowService.getFlowState();

                    // The backend numbers imported nodes against saved DB state only, so it has
                    // no knowledge of unsaved canvas nodes. Re-issue numbers from the frontend
                    // sequence (which sees all live nodes) to prevent collisions with unsaved nodes.
                    // Only auto-numbered names ("... #N") are touched; custom names are left as-is.
                    const renumberedNewNodes = newServerNodes.map((n) => {
                        if (!/#\s*\d+\s*$/.test(n.node_name ?? '')) {
                            return n;
                        }
                        const newNumber = this.flowService.getNextNodeNumber();
                        return {
                            ...n,
                            nodeNumber: newNumber,
                            node_name: (n.node_name ?? '').replace(/#\s*\d+\s*$/, `#${newNumber}`),
                        };
                    });

                    const mergedFlow = normalizeFlowPorts({
                        nodes: [...currentState.nodes, ...renumberedNewNodes],
                        connections: [...currentState.connections, ...newServerConnections],
                    });

                    // setFlow retriggers ngOnChanges in flow-graph, which runs
                    // _shiftImportedNodes (using _preImportBackendIds set by doPartialImport)
                    // and fitAfterNextFlowChange.
                    // savedFlowState is intentionally NOT updated — the flow stays dirty.
                    this.flowService.setFlow(mergedFlow);

                    // Run the same warning toasts as applyLoadedGraphState.
                    const blockedCount = this.countBlockedSubgraphNodes(serverFlow);
                    if (blockedCount > 0) {
                        this.toastService.warning(
                            `${blockedCount} subgraph node(s) reference missing flows and were blocked.`,
                            6000,
                            'bottom-right'
                        );
                    }

                    this.llmConfigStorageService
                        .getAllConfigs()
                        .pipe(takeUntilDestroyed(this.destroyRef))
                        .subscribe((configs) => {
                            const cdtMissingCount = this.countCdtNodesWithMissingLlmConfig(serverFlow, configs);
                            if (cdtMissingCount > 0) {
                                this.toastService.warning(
                                    `${cdtMissingCount} classification decision table node(s) reference a missing LLM config.`,
                                    6000,
                                    'bottom-right'
                                );
                            }
                        });
                }),
                catchError(() => {
                    this.toastService.error('Failed to load imported nodes');
                    return EMPTY;
                }),
                finalize(() => this.cdr.markForCheck())
            )
            .subscribe();
    }

    private fetchGraph(graphId: number, forceRefresh = false, showRefreshToast = false): void {
        forkJoin({
            graph: this.flowApiService.getGraphById(graphId, forceRefresh),
            flows: this.flowApiService.getGraphsLight().pipe(catchError(() => of([] as GetGraphLightRequest[]))),
        })
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                tap(({ graph, flows }) => {
                    this.applyLoadedGraphState(graph, flows, showRefreshToast);
                    this.wsService.connect(graph.id);
                }),
                catchError(() => {
                    this.toastService.error('Failed to load graph');
                    return EMPTY;
                }),
                finalize(() => this.cdr.markForCheck())
            )
            .subscribe();
    }

    /** @deprecated Manual save removed in EST-3020 (WS autosave persists everything). Kept for potential rollback; no call sites. */
    public onHeaderSave(): void {
        this.flowGraphComponent?.emitSave();
    }

    /** @deprecated Manual save removed in EST-3020 (WS autosave persists everything). Kept for potential rollback; no call sites. */
    public onGraphSave(flowState: FlowModel): void {
        if (!this.graph?.id || this.isSaving()) return;

        this.cleanupCdtGridState(flowState);
        this.saveFlowState(flowState, true).pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
    }

    private cleanupCdtGridState(flowState: FlowModel): void {
        const match = window.location.pathname.match(/\/flows\/(\d+)/);
        const graphId = match?.[1];
        if (!graphId) return;

        const liveSuffixes = new Set<string>();
        for (const node of flowState.nodes) {
            if (node.type !== NodeType.CLASSIFICATION_TABLE) continue;
            const nodeNum = node.nodeNumber ?? node.backendId;
            if (nodeNum == null) continue;
            liveSuffixes.add(`${graphId}_${nodeNum}`);
        }

        const prefix = 'cdt-grid-state-';
        const toRemove: string[] = [];
        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            if (!key || !key.startsWith(prefix)) continue;
            const suffix = key.slice(prefix.length);
            if (!suffix.startsWith(`${graphId}_`)) continue;
            if (!liveSuffixes.has(suffix)) toRemove.push(key);
        }
        for (const key of toRemove) {
            localStorage.removeItem(key);
        }
    }

    /** @deprecated Manual REST save removed in EST-3020 (WS autosave persists everything). Kept for potential rollback; no call sites. */
    private saveFlowState(flowState: FlowModel, showSuccessToast: boolean, retried = false): Observable<void> {
        if (!this.graph?.id) return EMPTY;

        const previous = this.loadedFlowState();
        const flowToSave = clearStaleIds(previous, flowState);
        const nodeDiff = getNodeDiff(previous, flowToSave);
        const idMap = buildUuidToBackendIdMap(flowToSave.nodes);
        const connectionDiff = getConnectionDiff(previous, flowToSave, idMap);
        const payload = buildBulkSavePayload(
            this.graph.id,
            nodeDiff,
            connectionDiff,
            flowToSave,
            idMap,
            this.graphState()!.save_version
        );

        this.isSaving.set(true);

        return this.flowApiService.bulkSaveGraph(this.graph.id, payload).pipe(
            switchMap((graph) =>
                this.flowApiService.getGraphsLight().pipe(
                    map((flows) => ({ graph, flows })),
                    catchError(() => of({ graph, flows: [] as GetGraphLightRequest[] }))
                )
            ),
            tap(({ graph, flows }) => {
                this.graphState.set(graph);
                this.availableFlowLights.set(flows);
                let patchedFlow = patchFlowStateWithBackendIds(flowState, previous, nodeDiff, graph);
                patchedFlow = patchCdtPromptBackendIds(patchedFlow, graph);

                this.flowService.setFlow(patchedFlow);
                // Sync isActive from the save response: patchFlowStateWithBackendIds only assigns
                // backend IDs and does not propagate other backend-authoritative fields like is_active.
                for (const dto of graph.schedule_trigger_node_list ?? []) {
                    const node = patchedFlow.nodes.find(
                        (n): n is ScheduleTriggerNodeModel =>
                            n.type === NodeType.SCHEDULE_TRIGGER && (n as ScheduleTriggerNodeModel).backendId === dto.id
                    );
                    if (node && node.data.isActive !== dto.is_active) {
                        this.flowService.updateNode({ ...node, data: { ...node.data, isActive: dto.is_active } });
                    }
                }
                this.savedFlowState.set(cloneFlowState(buildCdtSavedBaseline(patchedFlow, graph)));
                this.sidePanelService.notifyGraphSaved();
                if (showSuccessToast) {
                    this.toastService.success('Graph saved successfully');
                    this.warnIfCdtMissingLlmConfig(patchedFlow);
                }
            }),
            map(() => void 0),
            catchError((err: HttpErrorResponse) => {
                if (err.status === 409 && !retried && err.error?.current_version != null) {
                    this.graphState.update((state) =>
                        state ? { ...state, save_version: err.error.current_version } : state
                    );
                    return this.saveFlowState(flowState, showSuccessToast, true);
                }
                if (err.status === 409) {
                    this.toastService.warning(
                        'This graph was modified by another user. Please refresh to see the latest changes.'
                    );
                } else {
                    this.toastService.error(`Failed to save graph: ${extractHttpErrorMessage(err)}`);
                }
                return EMPTY;
            }),
            finalize(() => {
                this.isSaving.set(false);
                this.cdr.markForCheck();
            })
        );
    }

    private handleNodeSaveRequest(node: NodeModel): void {
        if (!this.graph?.id) return;
        if (this.sidePanelService.savingNodeId() === node.id) return;

        this.sidePanelService.markNodeSaving(node.id);
        this.flowService.updateNode(node);
        this.wsService.sendNodeUpdated(node, this.graph.id, this.flowService.nodes(), this.flowService.connections());
        this.toastService.success('Node saved');
        setTimeout(() => this.sidePanelService.clearNodeSaving());
    }

    /** @deprecated Manual REST save removed in EST-3020 (WS autosave persists everything). Kept for potential rollback; no call sites. */
    private saveNodeToBackend(node: NodeModel, retried = false): Observable<void> {
        if (!this.graph?.id) return EMPTY;

        this.flowService.updateNode(node);

        const previous = this.loadedFlowState();
        const previousForDiff: FlowModel = {
            nodes: node.backendId != null ? previous.nodes.filter((n) => n.backendId === node.backendId) : [],
            connections: [],
        };
        const singleNodeFlow: FlowModel = { nodes: [node], connections: [] };
        const nodeDiff = getNodeDiff(previousForDiff, singleNodeFlow);
        const connectionDiff = { toCreate: [], toUpdate: [], toDelete: [] };
        const idMap = buildUuidToBackendIdMap([node]);
        const payload = buildBulkSavePayload(
            this.graph.id,
            nodeDiff,
            connectionDiff,
            singleNodeFlow,
            idMap,
            this.graphState()!.save_version
        );

        return this.flowApiService.bulkSaveGraph(this.graph.id, payload).pipe(
            tap((responseGraph) => {
                this.graphState.set(responseGraph);
                const patchedFlow = patchFlowStateWithBackendIds(
                    this.currentFlowState(),
                    previous,
                    nodeDiff,
                    responseGraph
                );
                this.flowService.setFlow(patchedFlow);

                const savedNode = patchedFlow.nodes.find((n) => n.id === node.id);
                if (savedNode) {
                    const prev = this.savedFlowState();
                    const exists = prev.nodes.some((n) => n.id === node.id);
                    const nextNodes = exists
                        ? prev.nodes.map((n) => (n.id === node.id ? savedNode : n))
                        : [...prev.nodes, savedNode];
                    this.savedFlowState.set(cloneFlowState({ nodes: nextNodes, connections: prev.connections }));
                }

                this.toastService.success('Node saved');
            }),
            map(() => void 0),
            catchError((err: HttpErrorResponse) => {
                if (err.status === 409 && !retried && err.error?.current_version != null) {
                    this.graphState.update((state) =>
                        state ? { ...state, save_version: err.error.current_version } : state
                    );
                    return this.saveNodeToBackend(node, true);
                }
                if (err.status === 409) {
                    this.toastService.warning(
                        'This graph was modified by another user. Please refresh to see the latest changes.'
                    );
                } else {
                    this.toastService.error(`Failed to save node: ${extractHttpErrorMessage(err)}`);
                }
                return EMPTY;
            })
        );
    }

    /** @deprecated Manual REST save removed in EST-3020 (the run endpoint flushes the live snapshot itself). Kept for potential rollback; no call sites. */
    private saveGraphForRun(): Observable<void> {
        if (!this.hasUnsavedChanges()) return of(void 0);
        if (this.isSaving()) return EMPTY;

        return this.saveFlowState(this.currentFlowState(), false);
    }

    /** @deprecated Manual REST save removed in EST-3020 (WS autosave persists everything). Kept for potential rollback; no call sites. */
    public saveCurrentState(): Observable<void> {
        if (!this.hasUnsavedChanges()) return of(void 0);
        return toObservable(this.isSaving, { injector: this.injector }).pipe(
            filter((saving) => !saving),
            take(1),
            switchMap(() => this.saveFlowState(this.currentFlowState(), false))
        );
    }

    public handleRunFlow(): void {
        if (this.isRunning() || !this.graph?.id) return;

        this.isRunning.set(true);

        const committedOpenPanel = this.flowGraphComponent?.commitOpenPanelToFlow() ?? false;

        const startNode = this.currentFlowState().nodes.find((n) => n.type === NodeType.START);
        const variables =
            (startNode?.data as { initialState?: Record<string, unknown> } | undefined)?.initialState ??
            this.graph.start_node_list[0]?.variables;

        timer(committedOpenPanel ? 300 : 0)
            .pipe(
                switchMap(() => this.runGraphService.runGraph(this.graph.id, variables)),
                takeUntilDestroyed(this.destroyRef),
                tap((response: { session_id?: number }) => {
                    this.currentSessionId = response.session_id?.toString() ?? null;
                    if (this.currentSessionId) {
                        this.runSessionSSEService.startStream(this.currentSessionId);
                    }
                    this.isPanelOpen.set(true);
                    this.isPanelCollapsed.set(false);
                    this.cdr.markForCheck();
                }),
                catchError((error: HttpErrorResponse) => {
                    this.toastService.error(`Failed to run graph: ${extractHttpErrorMessage(error)}`);
                    return EMPTY;
                }),
                finalize(() => {
                    this.isRunning.set(false);
                    this.cdr.markForCheck();
                })
            )
            .subscribe();
    }

    public handleViewSessions(): void {
        if (!this.graph) return;
        this.dialog.open(FlowSessionsListComponent, {
            data: { flow: this.graph },
            panelClass: 'custom-dialog-panel',
        });
    }

    public handleGetCurl(): void {
        const flowUuid = this.graph?.uuid;
        const startNodeInitialState = this.flowService.startNodeInitialState();
        const apiUrl = this.configService.apiUrl;

        if (flowUuid && startNodeInitialState) {
            const curlCommand = this.generateCurlCommand(flowUuid, startNodeInitialState, apiUrl);
            this.copyToClipboard(curlCommand);
            this.toastService.success('CURL command copied to clipboard!');
        } else {
            this.toastService.error('Unable to generate CURL: Missing flow ID or start node data');
        }
    }

    private generateCurlCommand(flowUuid: string, variables: Record<string, unknown>, apiUrl: string): string {
        const payload = JSON.stringify(
            {
                graph_uuid: flowUuid,
                variables: variables,
            },
            null,
            2
        );

        return `curl \\
  -H "Content-Type: application/json" \\
  -H "Accept: application/json" \\
  -X POST \\
  -d '${payload}' \\
  ${apiUrl}run-session/`;
    }

    private async copyToClipboard(text: string): Promise<void> {
        try {
            await navigator.clipboard.writeText(text);
        } catch {
            // Fallback for older browsers
            const textArea = document.createElement('textarea');
            textArea.value = text;
            document.body.appendChild(textArea);
            textArea.select();
            document.execCommand('copy');
            document.body.removeChild(textArea);
        }
    }

    @HostListener('window:beforeunload', ['$event'])
    public handleBeforeUnload(event: BeforeUnloadEvent): string | void {
        if (this.wsService.connectionStatus() !== 'connected' && this.hasUnsavedChanges()) {
            event.preventDefault();
            return (event.returnValue = '');
        }
    }

    @HostListener('document:keydown', ['$event'])
    public handleCtrlS(event: KeyboardEvent): void {
        if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
            event.preventDefault();
        }
    }

    public hasUnsavedChanges(): boolean {
        return this.hasUnsavedChangesSignal();
    }

    public canDeactivate(): boolean | Observable<boolean> {
        if (this.isDeactivating) return true;
        if (this.wsService.connectionStatus() === 'connected') return true;
        if (!this.hasUnsavedChanges()) return true;

        this.isDeactivating = true;
        return this.unsavedChangesDialog
            .confirm({
                title: 'Connection lost',
                message:
                    'Real-time sync is disconnected, so your latest changes could not be saved. ' +
                    'Leaving now will discard them.',
                saveText: 'Leave anyway',
                cancelText: 'Stay',
                type: 'warning',
            })
            .pipe(
                tap(() => {
                    this.isDeactivating = false;
                }),
                map((result) => result === 'save')
            );
    }

    public onToggleAssistant(): void {
        if (!this.graph?.id) return;
        this.flowAssistantService.toggle(this.graph.id);
    }

    public connectToEpicChat(): void {
        if (!this.graph?.id) {
            this.toastService.error('Unable to connect chat: Missing flow ID');
            return;
        }

        const flowUrl = this.normalizeApiUrl(this.configService.apiUrl);
        if (!flowUrl) {
            this.toastService.error('Unable to connect chat: Missing API URL');
            return;
        }

        this.flowApiService
            .patchGraph(this.graph.id, { epicchat_enabled: true, save_version: this.graphState()!.save_version })
            .subscribe({
                next: () => {
                    this.graph.epicchat_enabled = true;
                    this.epicChatService.requestCreateAgent({
                        name: this.graph.name?.trim() || `Flow ${this.graph.id}`,
                        description: this.graph.description?.trim(),
                        flowId: this.graph.id,
                        flowUrl,
                        selectAfterCreate: true,
                    });
                    this.toastService.success('Flow connected to Epic Chat');
                },
                error: () => {
                    this.toastService.error('Failed to save EpicChat connection');
                },
            });
    }

    private normalizeApiUrl(apiUrl: string): string {
        return (apiUrl || '').trim().replace(/\/+$/, '');
    }

    public closeMessagesPanel(): void {
        this.isPanelCollapsed.set(true);
        this.cdr.markForCheck();
        window.dispatchEvent(new Event('resize'));
    }

    public togglePanelCollapsed(): void {
        this.isPanelCollapsed.update((value) => !value);
        this.cdr.markForCheck();
        window.dispatchEvent(new Event('resize'));
    }

    public onSessionSelected(sessionId: string): void {
        this.currentSessionId = sessionId;
        this.cdr.markForCheck();
    }

    public onDragStart(event: MouseEvent): void {
        event.preventDefault();
        this.isDragging = true;
    }

    @HostListener('document:mousemove', ['$event'])
    public onDragMove(event: MouseEvent): void {
        if (!this.isDragging) return;
        const hostRect = this.elementRef.nativeElement.getBoundingClientRect();
        const maxWidth = hostRect.width * this.MAX_PANEL_WIDTH_RATIO;
        const newWidth = hostRect.right - event.clientX;
        this.panelWidthPx = Math.max(this.MIN_PANEL_WIDTH, Math.min(newWidth, maxWidth));
        this.cdr.markForCheck();
    }

    @HostListener('document:mouseup')
    public onDragEnd(): void {
        if (this.isDragging) {
            this.isDragging = false;
            window.dispatchEvent(new Event('resize'));
        }
    }

    public ngOnDestroy(): void {
        this.cleanupCdtGridState(this.currentFlowState());
        this.flowUnsavedStateService.unregister();
        this.runSessionSSEService.stopStream();
        this.wsService.disconnect();
    }

    /**
     * Routing of decision/classification tables lives inside the node entity —
     * remote node_created/node_updated carry the refs as *_node_id (persisted
     * target) or *_temp_id (the target's canvas id). Resolve them onto this
     * canvas and rebuild the table's outgoing connections so co-editors see
     * routing changes live.
     */
    private applyRemoteTableRouting(canvasNodeId: string, payload: Record<string, unknown>, listKey: string): void {
        if (listKey !== 'decision_table_node_list' && listKey !== 'classification_decision_table_node_list') return;
        const nodes = this.flowService.nodes();
        const node = nodes.find((n) => n.id === canvasNodeId);
        const table = (node?.data as { table?: Record<string, unknown> } | undefined)?.table;
        if (!node || !table) return;

        const toCanvasId = (idVal: unknown, tempVal: unknown): string | null => {
            if (typeof tempVal === 'string' && tempVal) return tempVal;
            if (typeof idVal === 'number') return nodes.find((n) => n.backendId === idVal)?.id ?? null;
            return null;
        };

        const rawGroups = (payload['condition_groups'] as Record<string, unknown>[] | undefined) ?? [];
        const existingGroups = (table['condition_groups'] as Record<string, unknown>[] | undefined) ?? [];
        // Groups arrive in the same order they were mapped into the node data.
        const updatedGroups = existingGroups.map((group, index) => {
            const raw = rawGroups[index];
            if (!raw) return group;
            return { ...group, next_node: toCanvasId(raw['next_node_id'], raw['next_node_temp_id']) };
        });
        const defaultNext = toCanvasId(payload['default_next_node_id'], payload['default_next_node_temp_id']);
        const errorNext = toCanvasId(payload['next_error_node_id'], payload['next_error_node_temp_id']);

        this.flowService.updateNode({
            ...node,
            data: {
                ...(node.data as Record<string, unknown>),
                table: {
                    ...table,
                    condition_groups: updatedGroups,
                    default_next_node: defaultNext,
                    next_error_node: errorNext,
                },
            },
        } as NodeModel);
        this.flowService.resetDecisionTableConnections(
            canvasNodeId,
            updatedGroups as unknown as ConditionGroup[],
            defaultNext,
            errorNext
        );
    }

    private addStartNodeIfNeeded(flowModel: FlowModel, graphId?: number): FlowModel {
        if (hasStartNode(flowModel)) return flowModel;
        return { ...flowModel, nodes: [createStartNode(graphId), ...flowModel.nodes] };
    }

    private validateSubgraphNodes(
        flowModel: FlowModel,
        flows: GetGraphLightRequest[]
    ): { flowModel: FlowModel; blockedCount: number } {
        const availableIds = new Set(flows.map((f) => f.id));
        let blockedCount = 0;

        const nextFlowModel: FlowModel = {
            ...flowModel,
            nodes: flowModel.nodes.map((node) => {
                if (node.type !== NodeType.SUBGRAPH) return node;
                const subgraphId = Number((node as { data?: { id?: unknown } })?.data?.id);
                const isMissing = !subgraphId || !availableIds.has(subgraphId);
                if (isMissing) blockedCount++;
                return { ...node, isBlocked: isMissing };
            }),
        };

        return { flowModel: nextFlowModel, blockedCount };
    }

    private applyLoadedGraphState(graph: GraphDto, flows: GetGraphLightRequest[], showRefreshToast: boolean): void {
        this.graphState.set(graph);
        this.availableFlowLights.set(flows);
        const normalizedFlow = normalizeFlowPorts(this.loadedFlowState());
        this.flowService.setFlow(normalizedFlow);
        // savedFlowState captures the as-persisted snapshot used for dirty-tracking.
        // It is set BEFORE the legacy-name rewrite so that flows with legacy names are
        // immediately marked dirty — the user accepted this behaviour (EST-2826).
        this.savedFlowState.set(cloneFlowState(normalizedFlow));

        // Eagerly rewrite legacy "at HH:MM" once-schedule names to "at HH-MM" in the
        // live canvas state. Because savedFlowState already holds the old names, the
        // flow will be marked dirty until the user saves, which is the intended UX.
        const rewrittenFlow: FlowModel = {
            ...normalizedFlow,
            nodes: normalizedFlow.nodes.map((node) => {
                if (node.type !== NodeType.SCHEDULE_TRIGGER) return node;
                const rewrittenName = rewriteLegacyOnceScheduleName(node.node_name);
                return rewrittenName !== node.node_name ? { ...node, node_name: rewrittenName } : node;
            }),
        };
        this.flowService.setFlow(rewrittenFlow);

        this.isLoaded.set(true);

        if (showRefreshToast) {
            this.toastService.success('Flow refreshed');
        }

        const blockedCount = this.countBlockedSubgraphNodes(this.loadedFlowState());
        if (blockedCount > 0) {
            this.toastService.warning(
                `${blockedCount} subgraph node(s) reference missing flows and were blocked.`,
                6000,
                'bottom-right'
            );
        }

        const loadedFlow = this.loadedFlowState();
        this.llmConfigStorageService
            .getAllConfigs()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((configs) => {
                const cdtMissingCount = this.countCdtNodesWithMissingLlmConfig(loadedFlow, configs);
                if (cdtMissingCount > 0) {
                    this.toastService.warning(
                        `${cdtMissingCount} classification decision table node(s) reference a missing LLM config.`,
                        6000,
                        'bottom-right'
                    );
                }
            });
    }

    private countBlockedSubgraphNodes(flowModel: FlowModel): number {
        return flowModel.nodes.filter((node) => node.type === NodeType.SUBGRAPH && node.isBlocked).length;
    }

    private countCdtNodesWithMissingLlmConfig(flowModel: FlowModel, configs: GetLlmConfigRequest[]): number {
        const availableIds = new Set(configs.map((c) => c.id));
        return flowModel.nodes.filter((node) => {
            if (node.type !== NodeType.CLASSIFICATION_TABLE) return false;
            const table = (
                node as {
                    data?: {
                        table?: {
                            default_llm_config?: number | null;
                            prompts?: Record<string, { llm_config: number | null }>;
                        };
                    };
                }
            ).data?.table;
            if (!table) return false;

            // Any prompt with no LLM config selected counts as missing.
            if (table.prompts) {
                for (const prompt of Object.values(table.prompts)) {
                    if (prompt.llm_config == null) return true;
                }
            }
            // Deleted-config references also count as missing.
            if (table.default_llm_config != null && !availableIds.has(table.default_llm_config)) {
                return true;
            }
            if (table.prompts) {
                for (const prompt of Object.values(table.prompts)) {
                    if (prompt.llm_config != null && !availableIds.has(prompt.llm_config)) return true;
                }
            }
            return false;
        }).length;
    }

    private warnIfCdtMissingLlmConfig(flowState: FlowModel): void {
        if (!this.llmConfigStorageService.isConfigsLoaded()) return;
        const count = this.countCdtNodesWithMissingLlmConfig(flowState, this.llmConfigStorageService.configs());
        if (count > 0) {
            this.toastService.warning(
                `${count} decision table node(s) have a prompt with a missing LLM config.`,
                6000,
                'bottom-right'
            );
        }
    }

    public isShortcutsOpen = signal(false);
    public shortcutsPos = signal<{ top: number; left: number } | null>(null);
    public readonly shortcutSections = FLOW_SHORTCUT_SECTIONS;

    public openShortcutsModal(rect: DOMRect): void {
        if (this.isShortcutsOpen()) {
            this.closeShortcutsModal();
            return;
        }

        const top = rect.top;
        const left = rect.right - 30;

        this.shortcutsPos.set({ top, left });
        this.isShortcutsOpen.set(true);
    }

    public closeShortcutsModal(): void {
        this.isShortcutsOpen.set(false);
        this.shortcutsPos.set(null);
    }

    public onFlowEdited(updatedFlow: GraphDto): void {
        this.graphState.set(updatedFlow);
        this.cdr.markForCheck();
    }

    public onViewVersionHistory(): void {
        if (!this.graph?.id) return;

        const positionStrategy = this.overlay.position().global().right('0').top('5rem');

        const dialogRef = this.dialog.open<GraphRestoreResponse | undefined>(VersionHistoryPanelComponent, {
            positionStrategy,
            height: 'calc(100% - 5rem)',
            width: '380px',
            data: {
                graphId: this.graph.id,
                graphSaveVersion: () => this.graphState()?.save_version,
            },
        });

        dialogRef.closed
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                filter((result): result is GraphRestoreResponse => !!result?.restored)
            )
            .subscribe((response) => {
                this.restoreWarnings.set(response.warnings);
                this.undoRedoService.setUndoStack([]);
                this.undoRedoService.setRedoStack([]);
                this.refreshCurrentFlow();
            });
    }

    public onShowRestoreWarnings(): void {
        const dialogRef = this.dialog.open<number | undefined>(RestoreWarningsDialogComponent, {
            width: '560px',
            data: { warnings: this.restoreWarnings() },
        });

        dialogRef.closed
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                filter((nodeId): nodeId is number => nodeId != null)
            )
            .subscribe((backendNodeId) => {
                const node = this.flowService.nodes().find((n) => n.backendId === backendNodeId);
                if (node) {
                    this.flowGraphComponent?.openNodePanel(node.id);
                }
            });
    }

    public onSaveVersion(): void {
        if (!this.graph.id) return;

        const dialogRef = this.dialog.open<SaveVersionDialogResult>(SaveVersionDialogComponent, {
            width: '560px',
            data: {},
        });

        dialogRef.closed
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                filter((result): result is SaveVersionDialogResult => !!result),
                switchMap((result) =>
                    this.flowApiService
                        .saveGraphVersion({
                            graph_id: this.graph.id,
                            name: result.name,
                            description: result.description,
                        })
                        .pipe(
                            tap(() => {
                                this.toastService.success(`Version '${result.name}' saved`);
                                this.warnIfCdtMissingLlmConfig(this.loadedFlowState());
                            }),
                            catchError(() => {
                                this.toastService.error('Failed to save version');
                                return EMPTY;
                            })
                        )
                )
            )
            .subscribe();
    }
}
