import { Dialog as CdkDialog } from '@angular/cdk/dialog';
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
import { AppSvgIconComponent, SpinnerComponent, UnsavedChangesDialogService } from '@shared/components';
import { ActionCode, GetLlmConfigRequest, NodeType, ResourceCode } from '@shared/models';
import { LlmConfigStorageService } from '@shared/services';
import { extractHttpErrorMessage } from '@shared/utils';
import {
    catchError,
    defaultIfEmpty,
    EMPTY,
    filter,
    finalize,
    forkJoin,
    map,
    Observable,
    of,
    switchMap,
    take,
    tap,
} from 'rxjs';
import { GraphCollaborationWsService } from 'src/app/features/flows/services/graph-collaboration.ws.service';

import { CanComponentDeactivate } from '../../../../core/guards/unsaved-changes.guard';
import { UnsavedChangesRegistry } from '../../../../core/services/unsaved-changes-registry.service';
import { AgentDefinitionsApiService } from '../../../../features/agent-definitions/services/agent-definitions-api.service';
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
    GraphVersionDto,
    RestoreWarning,
} from '../../../../features/flows/models/graph.model';
import { CreateGraphWarningsService } from '../../../../features/flows/services/create-graph-warnings.service';
import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import { FlowsStorageService } from '../../../../features/flows/services/flows-storage.service';
import { RunGraphService } from '../../../../features/flows/services/run-graph-session.service';
import { FlowMessagesPanelComponent } from '../../../../pages/running-graph/components/flow-messages-panel/flow-messages-panel.component';
import { RunSessionSSEService } from '../../../../pages/running-graph/services/graph-session-sse.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import { FlowModel } from '../../../../visual-programming/core/models/flow.model';
import { FlowViewport } from '../../../../visual-programming/core/models/flow-viewport.model';
import {
    AgentNodeModel,
    NodeModel,
    ScheduleTriggerNodeModel,
    TaskNodeModel,
} from '../../../../visual-programming/core/models/node.model';
import { FlowGraphComponent } from '../../../../visual-programming/flow-graph/flow-graph.component';
import { FlowVersionPreviewComponent } from '../../../../visual-programming/flow-version-preview/flow-version-preview.component';
import { FlowService } from '../../../../visual-programming/services/flow.service';
import { SidePanelService } from '../../../../visual-programming/services/side-panel.service';
import { UndoRedoService } from '../../../../visual-programming/services/undo-redo.service';
import { buildFlowModelFromGraphDto, normalizeFlowPorts } from '../../../../visual-programming/utils/load';
import { rewriteLegacyOnceScheduleName } from '../../../../visual-programming/utils/load/nodes/schedule-trigger-node.mapper';
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
import { isValidOutputSchema } from '../../../../visual-programming/utils/validation/output-schema.validator';
import { FlowHeaderComponent } from './components/header/flow-header.component';
import { ShortcutsModalComponent } from './components/shortcuts-modal/shortcuts-modal.component';
import { FLOW_SHORTCUT_SECTIONS } from './flow-shortcuts.config';

@Component({
    selector: 'app-flow-visual-programming',
    imports: [
        AppSvgIconComponent,
        FlowHeaderComponent,
        FlowGraphComponent,
        SpinnerComponent,
        ShortcutsModalComponent,
        FlowMessagesPanelComponent,
        MatTooltipModule,
        FlowAssistantPanelComponent,
        VersionHistoryPanelComponent,
        FlowVersionPreviewComponent,
    ],
    templateUrl: './flow-visual-programming.component.html',
    styleUrl: './flow-visual-programming.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowVisualProgrammingComponent implements OnInit, OnDestroy, CanComponentDeactivate {
    private readonly destroyRef = inject(DestroyRef);
    private readonly wsService = inject(GraphCollaborationWsService);
    private readonly profileService = inject(ProfileService);
    private readonly injector = inject(Injector);

    public readonly flowAssistantService = inject(FlowAssistantService);
    public readonly isEpicChatEnabled: boolean;
    public initialNodeId: string | null = null;
    public initialNodeExpand = true;
    public isLoaded = signal(false);
    private readonly graphState = signal<GraphDto | null>(null);
    protected readonly availableFlowLights = signal<GetGraphLightRequest[]>([]);
    private readonly savedFlowState = signal<FlowModel>({ nodes: [], connections: [] });
    protected readonly collaborationEditors = this.wsService.editors;
    public readonly loadedFlowState = computed<FlowModel>(() => {
        const graph = this.graphState();
        if (!graph) return { nodes: [], connections: [] };
        return buildFlowModelFromGraphDto(graph, this.availableFlowLights());
    });
    public readonly currentFlowState = computed<FlowModel>(() => this.flowService.getFlowState());
    public readonly hasUnsavedChangesSignal = computed<boolean>(() => {
        return JSON.stringify(this.currentFlowState()) !== JSON.stringify(this.savedFlowState());
    });

    public isSaving = signal(false);
    public isRunning = signal(false);
    public restoreWarnings = signal<RestoreWarning[]>([]);

    public isPanelOpen = signal(false);
    public isPanelCollapsed = signal(true);
    public currentSessionId: string | null = null;
    public panelWidthPx = 450;
    public isDragging = false;

    public isVersionHistoryOpen = signal(false);
    public readonly versionHistoryGraphSaveVersion = computed<number | undefined>(
        () => this.graphState()?.save_version
    );

    /** The version shown instead of the live canvas; null while editing the live flow. */
    public readonly previewedVersion = signal<GraphVersionDto | null>(null);
    public readonly isPreviewing = computed(() => this.previewedVersion() !== null);
    /** Live canvas pan/zoom captured on entering a preview, handed back when the live canvas re-mounts. */
    public readonly savedViewport = signal<FlowViewport | null>(null);
    public readonly selectedVersionId = signal<number | null>(null);
    /** True while a restored version loads; the live canvas then re-mounts and fits it. */
    public readonly isCanvasReloading = signal(false);
    private readonly MIN_PANEL_WIDTH = 430;
    private readonly MAX_PANEL_WIDTH_RATIO = 0.7;
    private readonly MIN_CANVAS_WIDTH = 560;
    private readonly routeParamMap;
    private readonly routeQueryParamMap;
    private isDeactivating = false;
    private lastFetchedGraphId: number | null = null;
    // The nodeId/nodeName query opens its panel once; re-mounting the live canvas must not re-open it.
    private lastNodeQueryKey: string | null = null;
    private isNodeQueryConsumed = false;

    @ViewChild(FlowGraphComponent)
    private flowGraphComponent?: FlowGraphComponent;

    @ViewChild(VersionHistoryPanelComponent)
    private versionHistoryPanel?: VersionHistoryPanelComponent;

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
        private readonly configService: ConfigService,
        private readonly elementRef: ElementRef,
        private readonly epicChatService: EpicChatService,
        private readonly unsavedChangesDialog: UnsavedChangesDialogService,
        private readonly undoRedoService: UndoRedoService,
        private readonly createGraphWarningService: CreateGraphWarningsService,
        private readonly runSessionSSEService: RunSessionSSEService,
        private readonly permissionsService: PermissionsService,
        private readonly sidePanelService: SidePanelService,
        private readonly llmConfigStorageService: LlmConfigStorageService,
        private readonly agentDefinitionsApiService: AgentDefinitionsApiService,
        private readonly unsavedChangesRegistry: UnsavedChangesRegistry
    ) {
        this.isEpicChatEnabled = this.configService.isEpicChatEnabled;
        this.routeParamMap = toSignal(this.route.paramMap, { initialValue: this.route.snapshot.paramMap });
        this.routeQueryParamMap = toSignal(this.route.queryParamMap, {
            initialValue: this.route.snapshot.queryParamMap,
        });

        effect(() => {
            const params = this.routeQueryParamMap();
            const nodeQueryKey = [params.get('nodeId'), params.get('nodeName'), params.get('nodeType')].join('|');
            if (nodeQueryKey !== this.lastNodeQueryKey) {
                this.lastNodeQueryKey = nodeQueryKey;
                this.isNodeQueryConsumed = false;
            }
            if (this.isNodeQueryConsumed) {
                this.initialNodeId = null;
                return;
            }
            const nodeId = params.get('nodeId');
            if (nodeId) {
                const match = this.currentFlowState().nodes.find(
                    (n) => n.id === nodeId || String(n.backendId) === nodeId
                );
                this.initialNodeId = match?.id ?? nodeId;
                this.initialNodeExpand = true;
                return;
            }

            // Callers that only know a node by name (e.g. the Secret Usage dialog, whose backend
            // response has no node id) use nodeName/nodeType instead — resolve it against the
            // loaded graph once available. nodeType disambiguates same-named nodes of different types.
            // This path only selects the node (small panel) rather than expanding it.
            const nodeName = params.get('nodeName');
            if (!nodeName) {
                this.initialNodeId = null;
                return;
            }
            const nodeType = params.get('nodeType');
            const match = this.currentFlowState().nodes.find(
                (n) => n.node_name === nodeName && (!nodeType || n.type === nodeType)
            );
            this.initialNodeId = match?.id ?? null;
            this.initialNodeExpand = false;
        });

        effect(() => {
            const graphId = Number(this.routeParamMap().get('id'));
            if (!isFinite(graphId)) return;
            if (graphId === this.lastFetchedGraphId) return;
            this.lastFetchedGraphId = graphId;
            this.previewedVersion.set(null);
            this.savedViewport.set(null);
            this.selectedVersionId.set(null);
            this.isVersionHistoryOpen.set(false);
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
            const currentId = this.profileService.currentUserSignal()?.id;
            if (event.saved_by.user_id === currentId) return;

            const savedBy = event.saved_by.display_name ?? `User ${event.saved_by.user_id}`;
            this.toastService.info(`Graph was saved by ${savedBy}`, 4000, 'bottom-right');

            if (!this.hasUnsavedChangesSignal()) {
                this.graphState.update((state) => (state ? { ...state, save_version: event.new_save_version } : state));
            }
        });
    }

    public ngOnInit(): void {
        this.unsavedChangesRegistry.register(this, {
            onRefresh: this.refreshCurrentFlow.bind(this),
        });
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
                    // recomputes via buildFlowModelFromGraphDto (the shared post-load pipeline).
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

    private fetchGraph(graphId: number, forceRefresh = false, showRefreshToast = false, onSettled?: () => void): void {
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
                catchError((e) => {
                    this.toastService.error(e.error?.detail || 'Failed to load graph');
                    void this.router.navigate(['/flows/my']);
                    return EMPTY;
                }),
                finalize(() => {
                    onSettled?.();
                    this.cdr.markForCheck();
                })
            )
            .subscribe();
    }

    public onHeaderSave(): void {
        this.flowGraphComponent?.emitSave();
    }

    public onGraphSave(flowState: FlowModel): void {
        if (!this.graph?.id || this.isSaving()) return;

        this.cleanupCdtGridState(flowState);
        this.saveFlowState(flowState, true).pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
    }

    private getBlockingNodeValidationIssues(flowState: FlowModel): string[] {
        let issues: string[] = [];
        try {
            issues = [...this.getInvalidTaskNodeMessages(flowState), ...this.getInvalidAgentNodeMessages(flowState)];
        } catch (error) {
            console.error('Node validation crashed before save — blocking the save defensively', error);
            return ['a node failed validation — check the console and try again'];
        }

        if (issues.length > 0) {
            this.toastService.error(`Cannot save flow — fix the following node(s) first: ${issues.join('; ')}.`);
        }
        return issues;
    }

    private getInvalidTaskNodeMessages(flowState: FlowModel): string[] {
        const messages: string[] = [];

        flowState.nodes.forEach((node, index) => {
            if (node.type !== NodeType.TASK) return;
            const taskNode = node as TaskNodeModel;

            const missingFields: string[] = [];
            if (!taskNode.node_name?.trim()) missingFields.push('node name');
            if (taskNode.data?.agent_definition == null) missingFields.push('agent');
            if (!taskNode.data?.instructions?.trim()) missingFields.push('instructions');
            if (taskNode.data?.output_schema_invalid || !isValidOutputSchema(taskNode.data?.output_schema)) {
                missingFields.push('a valid output schema');
            }

            if (missingFields.length === 0) return;

            const label = taskNode.node_name?.trim() || `Untitled task #${index + 1}`;
            messages.push(`"${label}" is missing ${missingFields.join(', ')}`);
        });

        return messages;
    }

    private getInvalidAgentNodeMessages(flowState: FlowModel): string[] {
        const messages: string[] = [];

        flowState.nodes.forEach((node, index) => {
            if (node.type !== NodeType.AGENT) return;
            const agentNode = node as AgentNodeModel;

            const missingFields: string[] = [];
            if (!agentNode.node_name?.trim()) missingFields.push('node name');
            if (agentNode.data?.agent_definition == null) missingFields.push('agent');

            const tasks = agentNode.data?.tasks ?? [];
            if (tasks.length === 0) {
                missingFields.push('at least one task');
            } else {
                const seenNames = new Set<string>();
                let hasBlankName = false;
                let hasDuplicateName = false;
                let hasBlankInstructions = false;
                let hasInvalidSchema = false;

                for (const task of tasks) {
                    const trimmedName = (task.name ?? '').trim();
                    if (!trimmedName) {
                        hasBlankName = true;
                    } else if (seenNames.has(trimmedName)) {
                        hasDuplicateName = true;
                    } else {
                        seenNames.add(trimmedName);
                    }

                    if (!(task.instructions ?? '').trim()) {
                        hasBlankInstructions = true;
                    }

                    if (task.output_schema_invalid || !isValidOutputSchema(task.output_schema)) {
                        hasInvalidSchema = true;
                    }
                }

                if (hasBlankName) missingFields.push('a task name');
                if (hasDuplicateName) missingFields.push('unique task names');
                if (hasBlankInstructions) missingFields.push('a task description');
                if (hasInvalidSchema) missingFields.push('a valid task output schema');
            }

            if (missingFields.length === 0) return;

            const label = agentNode.node_name?.trim() || `Untitled agent #${index + 1}`;
            messages.push(`"${label}" is missing ${missingFields.join(', ')}`);
        });

        return messages;
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

    private saveFlowState(flowState: FlowModel, showSuccessToast: boolean): Observable<void> {
        if (!this.graph?.id) return EMPTY;
        if (this.getBlockingNodeValidationIssues(flowState).length > 0) {
            return EMPTY;
        }
        const graphId = this.graph.id;

        this.isSaving.set(true);

        const previous = this.loadedFlowState();
        const flowToSave = clearStaleIds(previous, flowState);
        const nodeDiff = getNodeDiff(previous, flowToSave);
        const idMap = buildUuidToBackendIdMap(flowToSave.nodes);
        const connectionDiff = getConnectionDiff(previous, flowToSave, idMap);
        const payload = buildBulkSavePayload(
            graphId,
            nodeDiff,
            connectionDiff,
            flowToSave,
            idMap,
            this.graphState()!.save_version
        );

        return this.flowApiService.bulkSaveGraph(graphId, payload).pipe(
            switchMap((graph) =>
                this.flowApiService.getGraphsLight().pipe(
                    map((flows) => ({ graph, flows })),
                    catchError(() => of({ graph, flows: [] as GetGraphLightRequest[] }))
                )
            ),
            tap(({ graph, flows }) => this.onFlowSaved(graph, flows, flowState, previous, nodeDiff, showSuccessToast)),
            map(() => void 0),
            catchError((err: HttpErrorResponse) => {
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

    private onFlowSaved(
        graph: GraphDto,
        flows: GetGraphLightRequest[],
        flowState: FlowModel,
        previous: FlowModel,
        nodeDiff: ReturnType<typeof getNodeDiff>,
        showSuccessToast: boolean
    ): void {
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
    }

    private handleNodeSaveRequest(node: NodeModel): void {
        if (!this.graph?.id) return;
        if (this.sidePanelService.savingNodeId() === node.id) return;

        this.sidePanelService.markNodeSaving(node.id);
        this.saveNodeToBackend(node)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.sidePanelService.clearNodeSaving())
            )
            .subscribe();
    }

    private saveNodeToBackend(node: NodeModel): Observable<void> {
        if (!this.graph?.id) return EMPTY;
        const graphId = this.graph.id;

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
            graphId,
            nodeDiff,
            connectionDiff,
            singleNodeFlow,
            idMap,
            this.graphState()!.save_version
        );

        return this.flowApiService.bulkSaveGraph(graphId, payload).pipe(
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

    private saveGraphForRun(): Observable<void> {
        if (!this.hasUnsavedChanges()) return of(void 0);
        if (this.isSaving()) return EMPTY;

        return this.saveFlowState(this.currentFlowState(), false);
    }

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
        if (this.flowGraphComponent && !this.flowGraphComponent.commitSidePanelToFlow()) return;

        this.isRunning.set(true);

        const saveFirst$: Observable<void> = this.saveGraphForRun();

        saveFirst$
            .pipe(
                switchMap(() => this.runGraphService.runGraph(this.graph.id, this.graph.start_node_list[0].variables)),
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
            this.toastService.success('cURL command copied to clipboard!');
        } else {
            this.toastService.error('Unable to generate cURL: Missing flow ID or start node data');
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
        if (this.hasUnsavedChanges()) {
            event.preventDefault();
            return (event.returnValue = '');
        }
    }

    @HostListener('document:keydown', ['$event'])
    public handleCtrlS(event: KeyboardEvent): void {
        if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
            event.preventDefault();
            if (this.previewedVersion()) {
                this.toastService.info('Exit preview mode to save');
                return;
            }
            this.onHeaderSave();
        }
    }

    public hasUnsavedChanges(): boolean {
        return this.hasUnsavedChangesSignal();
    }

    public canDeactivate(): boolean | Observable<boolean> {
        if (this.isDeactivating) return true;
        if (!this.permissionsService.can(ResourceCode.Flows, ActionCode.Update)) return true;
        if (!this.hasUnsavedChanges()) return true;

        this.isDeactivating = true;
        return this.unsavedChangesDialog
            .confirmUnsavedChanges(() =>
                this.saveFlowState(this.currentFlowState(), false).pipe(
                    map(() => true),
                    defaultIfEmpty(false),
                    catchError(() => of(false))
                )
            )
            .pipe(
                tap((result) => {
                    this.isDeactivating = false;
                    if (result === 'dont-save') {
                        this.savedFlowState.set(cloneFlowState(this.currentFlowState()));
                    }
                }),
                map((result) => result === 'save' || result === 'dont-save')
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
        this.flowGraphComponent?.closeNodesSearch();
    }

    @HostListener('document:mousemove', ['$event'])
    public onDragMove(event: MouseEvent): void {
        if (!this.isDragging) return;
        const hostRect = this.elementRef.nativeElement.getBoundingClientRect();
        const versionHistoryWidth = this.getVersionHistoryWidth();
        const maxWidth = this.getMaxPanelWidth(hostRect.width, versionHistoryWidth);
        const newWidth = hostRect.right - versionHistoryWidth - event.clientX;
        this.panelWidthPx = this.clampPanelWidth(newWidth, maxWidth);
        this.cdr.markForCheck();
    }

    @HostListener('document:mouseup')
    public onDragEnd(): void {
        if (this.isDragging) {
            this.isDragging = false;
            window.dispatchEvent(new Event('resize'));
        }
    }

    private getVersionHistoryWidth(): number {
        const versionHistoryEl = this.elementRef.nativeElement.querySelector('app-version-history-panel');
        return versionHistoryEl?.getBoundingClientRect().width ?? 0;
    }

    private getMaxPanelWidth(hostWidth: number, versionHistoryWidth: number): number {
        const remaining = hostWidth - versionHistoryWidth;
        return Math.min(remaining * this.MAX_PANEL_WIDTH_RATIO, remaining - this.MIN_CANVAS_WIDTH);
    }

    private clampPanelWidth(value: number, maxWidth: number): number {
        const upperBound = Math.max(maxWidth, 0);
        const lowerBound = Math.min(this.MIN_PANEL_WIDTH, upperBound);
        return Math.max(lowerBound, Math.min(value, upperBound));
    }

    private clampPanelWidthToViewport(): void {
        const hostRect = this.elementRef.nativeElement.getBoundingClientRect();
        const versionHistoryWidth = this.getVersionHistoryWidth();
        const maxWidth = this.getMaxPanelWidth(hostRect.width, versionHistoryWidth);
        this.panelWidthPx = this.clampPanelWidth(this.panelWidthPx, maxWidth);
    }

    public ngOnDestroy(): void {
        this.unsavedChangesRegistry.unregister(this);
        this.runSessionSSEService.stopStream();
        this.wsService.disconnect();
    }

    private applyLoadedGraphState(graph: GraphDto, flows: GetGraphLightRequest[], showRefreshToast: boolean): void {
        this.graphState.set(graph);
        this.availableFlowLights.set(flows);
        const normalizedFlow = this.loadedFlowState();
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

        // Fetch agent definitions fresh on every flow-page load so agent/task node
        // "missing LLM" warnings reflect edits made on other pages (e.g. the agents page).
        this.agentDefinitionsApiService.refreshDefinitions().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
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
        const left = rect.right + 8;

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
        this.flowGraphComponent?.closeNodesSearch();
        this.isVersionHistoryOpen.set(true);
        requestAnimationFrame(() => {
            this.clampPanelWidthToViewport();
            this.cdr.markForCheck();
        });
    }

    public onVersionHistoryClosed(): void {
        this.isVersionHistoryOpen.set(false);
        this.selectedVersionId.set(null);
        this.onPreviewExit();
    }

    public onVersionPreviewRequested(version: GraphVersionDto): void {
        if (!this.previewedVersion()) {
            // Edits pending in an open node panel belong to the live flow; keep them before its canvas goes away.
            if (!this.commitLiveSidePanel()) {
                this.toastService.warning('Fix the errors in the open node panel before previewing a version');
                return;
            }
            this.savedViewport.set(this.flowGraphComponent?.captureViewport() ?? null);
            this.consumeNodeQuery();
        }
        // Switching between versions keeps the viewport captured on the first entry.
        this.previewedVersion.set(version);
        this.selectedVersionId.set(version.id);
    }

    /** Plain exit: the live canvas re-mounts with its root state and the viewport saved on entry. */
    public onPreviewExit(): void {
        this.previewedVersion.set(null);
    }

    public onVersionDeleted(version: GraphVersionDto): void {
        if (this.selectedVersionId() === version.id) {
            this.selectedVersionId.set(null);
        }
        if (this.previewedVersion()?.id === version.id) {
            this.onPreviewExit();
        }
    }

    public onVersionRestoreRequested(version: GraphVersionDto): void {
        // The dirty check and the optional backup read the live flow (root state, which the preview
        // never touches), so the preview stays open behind the dialog. It closes only once the user
        // picks a restore option; Cancel leaves them in the preview.
        const hasUnsaved = this.hasUnsavedChanges();
        const message = hasUnsaved
            ? `You have unsaved changes. Restoring <strong>${version.name}</strong> will replace the current flow state. Save a backup of the current state first?`
            : `Restoring <strong>${version.name}</strong> will replace the current flow state. Save a backup of the current state first?`;

        this.unsavedChangesDialog
            .confirm({
                title: 'Restore version',
                message,
                saveText: 'Save & Restore',
                dontSaveText: 'Discard & Restore',
                cancelText: 'Cancel',
                type: 'warning',
                showDontSave: true,
            })
            .pipe(
                switchMap((result) => {
                    if (result === 'save' || result === 'dont-save') {
                        this.onPreviewExit();
                    }
                    if (result === 'save') {
                        return this.saveCurrentState().pipe(
                            switchMap(() =>
                                this.flowApiService.restoreGraphVersion(
                                    version.id,
                                    true,
                                    this.versionHistoryGraphSaveVersion()
                                )
                            )
                        );
                    }
                    if (result === 'dont-save') {
                        return this.flowApiService.restoreGraphVersion(
                            version.id,
                            false,
                            this.versionHistoryGraphSaveVersion()
                        );
                    }
                    return EMPTY;
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (response) => {
                    if (response.warnings.length > 0) {
                        this.toastService.warning(
                            `Version restored with ${response.warnings.length} warning(s): some dependencies have since been deleted`
                        );
                    } else {
                        this.toastService.success('Version restored successfully');
                    }
                    this.onVersionHistoryClosed();
                    this.restoreWarnings.set(response.warnings);
                    this.undoRedoService.setUndoStack([]);
                    this.undoRedoService.setRedoStack([]);
                    this.reloadRestoredGraph();
                },
                error: () => this.toastService.error('Failed to restore version'),
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

        const openVersionDialog = () => {
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
                                    if (this.isVersionHistoryOpen()) {
                                        this.versionHistoryPanel?.loadVersions();
                                    }
                                }),
                                catchError(() => {
                                    this.toastService.error('Failed to save version');
                                    return EMPTY;
                                })
                            )
                    )
                )
                .subscribe();
        };

        if (!this.hasUnsavedChanges()) {
            openVersionDialog();
            return;
        }

        this.unsavedChangesDialog
            .confirm({
                title: 'Your flow has unsaved changes',
                message:
                    'Your flow has unsaved changes. <strong>Save</strong> the flow first to include them in the version, or <strong>continue</strong> to version the last saved state.',
                saveText: 'Save',
                dontSaveText: 'Continue',
                cancelText: 'Cancel',
                type: 'warning',
                showDontSave: true,
            })
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                switchMap((result) => {
                    if (result === 'save') {
                        return this.saveFlowState(this.currentFlowState(), false).pipe(map(() => void 0));
                    }
                    if (result === 'dont-save') {
                        return of(void 0);
                    }
                    return EMPTY;
                })
            )
            .subscribe(() => openVersionDialog());
    }

    /** Commits the live node panel into the root flow; false (or a throw) means it holds invalid edits. */
    private commitLiveSidePanel(): boolean {
        try {
            return this.flowGraphComponent?.commitSidePanelToFlow() ?? true;
        } catch (error) {
            console.error('Committing the open node panel failed', error);
            return false;
        }
    }

    private consumeNodeQuery(): void {
        this.isNodeQueryConsumed = true;
        this.initialNodeId = null;
    }

    /**
     * Loads the restored graph while the live canvas is unmounted, so it re-mounts and fits the
     * restored version instead of keeping the pre-restore (or pre-preview) viewport.
     */
    private reloadRestoredGraph(): void {
        const graphId = Number(this.route.snapshot.paramMap.get('id'));
        if (!isFinite(graphId)) return;
        this.savedViewport.set(null);
        this.consumeNodeQuery();
        this.isCanvasReloading.set(true);
        this.fetchGraph(graphId, true, true, () => this.isCanvasReloading.set(false));
    }
}
