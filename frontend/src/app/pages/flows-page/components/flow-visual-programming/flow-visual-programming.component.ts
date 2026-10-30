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
    OnDestroy,
    OnInit,
    signal,
    untracked,
    ViewChild,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ActivatedRoute, Router } from '@angular/router';
import {
    AppSvgIconComponent,
    ConfirmationDialogService,
    SpinnerComponent,
    UnsavedChangesDialogService,
} from '@shared/components';
import {
    ActionCode,
    GetLlmConfigRequest,
    GraphSessionStatus,
    isTerminalSessionStatus,
    NodeType,
    ResourceCode,
} from '@shared/models';
import { ExecutionTimeoutLimitsStorageService, LABELS_STORE, LlmConfigStorageService } from '@shared/services';
import { escapeHtml, extractHttpErrorMessage, formatNodeLabel, generateUuid } from '@shared/utils';
import {
    catchError,
    debounceTime,
    defaultIfEmpty,
    defer,
    EMPTY,
    filter,
    finalize,
    forkJoin,
    groupBy,
    map,
    mergeMap,
    Observable,
    of,
    Subject,
    switchMap,
    tap,
} from 'rxjs';
import { GraphCollaborationWsService } from 'src/app/features/flows/services/graph-collaboration.ws.service';

import { CanComponentDeactivate } from '../../../../core/guards/unsaved-changes.guard';
import { UnsavedChangesRegistry } from '../../../../core/services/unsaved-changes-registry.service';
import { AgentDefinitionsApiService } from '../../../../features/agent-definitions/services/agent-definitions-api.service';
import { FlowAssistantPanelComponent } from '../../../../features/flow-assistant/components/flow-assistant-panel/flow-assistant-panel.component';
import { FlowAssistantService } from '../../../../features/flow-assistant/flow-assistant.service';
import { CreateFlowDialogComponent } from '../../../../features/flows/components/create-flow-dialog/create-flow-dialog.component';
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
    GraphVersionDto,
    RestoreWarning,
} from '../../../../features/flows/models/graph.model';
import { RunGraphResponse } from '../../../../features/flows/models/run-session.model';
import { CreateGraphWarningsService } from '../../../../features/flows/services/create-graph-warnings.service';
import {
    FlowUsePermissionRefusalService,
    UsePermissionAction,
} from '../../../../features/flows/services/flow-use-permission-refusal.service';
import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import { FlowsStorageService } from '../../../../features/flows/services/flows-storage.service';
import { LabelsStorageService } from '../../../../features/flows/services/labels-storage.service';
import { RunGraphService } from '../../../../features/flows/services/run-graph-session.service';
import { FlowMessagesPanelComponent } from '../../../../pages/running-graph/components/flow-messages-panel/flow-messages-panel.component';
import { RunSessionSSEService } from '../../../../pages/running-graph/services/graph-session-sse.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ConfigService } from '../../../../services/config';
import { EasterEggTriggerService } from '../../../../services/easter-egg-trigger.service';
import { ToastService } from '../../../../services/notifications';
import { invalidKeyValueNodeMessages } from '../../../../visual-programming/core/helpers/key-value-node.helpers';
import { renumberUnsavedNodesHolding } from '../../../../visual-programming/core/helpers/node-number.util';
import { isTriggerNodeType } from '../../../../visual-programming/core/helpers/trigger-node-type.util';
import { EditorActionId } from '../../../../visual-programming/core/keymap/editor-actions';
import {
    CdtExplanations,
    PromptConfig,
} from '../../../../visual-programming/core/models/classification-decision-table.model';
import { FlowModel } from '../../../../visual-programming/core/models/flow.model';
import { FlowViewport } from '../../../../visual-programming/core/models/flow-viewport.model';
import {
    AgentNodeModel,
    ClassificationDecisionTableNodeModel,
    NodeModel,
    ScheduleTriggerNodeModel,
    SubGraphNodeModel,
    TaskNodeModel,
} from '../../../../visual-programming/core/models/node.model';
import { SnakeGameOverlayComponent } from '../../../../visual-programming/easter-egg/snake-game/snake-game-overlay.component';
import { FlowGraphComponent } from '../../../../visual-programming/flow-graph/flow-graph.component';
import { FlowVersionPreviewComponent } from '../../../../visual-programming/flow-version-preview/flow-version-preview.component';
import { CdtExplanationsApiService } from '../../../../visual-programming/services/cdt-explanations-api.service';
import { FlowService } from '../../../../visual-programming/services/flow.service';
import { FlowReadOnlyService } from '../../../../visual-programming/services/flow-readonly.service';
import { FlowTestRunRequest, FlowTestRunService } from '../../../../visual-programming/services/flow-test-run.service';
import { KeymapService } from '../../../../visual-programming/services/keymap.service';
import { NodeAuthorshipStore } from '../../../../visual-programming/services/node-authorship.store';
import { SavedFlowStateService } from '../../../../visual-programming/services/saved-flow-state.service';
import { ScheduleTriggerRuntimeService } from '../../../../visual-programming/services/schedule-trigger-runtime.service';
import { SidePanelService } from '../../../../visual-programming/services/side-panel.service';
import { UndoRedoService } from '../../../../visual-programming/services/undo-redo.service';
import { toStoredCdtExplanations } from '../../../../visual-programming/utils/cdt-explanations';
import { extractToSubflow } from '../../../../visual-programming/utils/extract/extract-to-subflow';
import {
    buildFlowModelFromGraphDto,
    mapGraphDtoToFlowModel,
    mapSnapshotToGraphDto,
    normalizeFlowPorts,
} from '../../../../visual-programming/utils/load';
import { rewriteLegacyOnceScheduleName } from '../../../../visual-programming/utils/load/nodes/schedule-trigger-node.mapper';
import {
    buildBulkSavePayload,
    buildCdtSavedBaseline,
    buildUuidToBackendIdMap,
    clearStaleIds,
    cloneFlowState,
    getConnectionDiff,
    getNodeDiff,
    hasTriggerNodeWrites,
    NodeDiffByType,
    patchCdtPromptBackendIds,
    patchFlowStateWithBackendIds,
    patchLiveFlowWithBackendIds,
} from '../../../../visual-programming/utils/save';
import { withGraphScheduleTriggerRuntimeState } from '../../../../visual-programming/utils/save/schedule-trigger-runtime-state';
import { unpackSubflow } from '../../../../visual-programming/utils/unpack/unpack-subflow';
import { invalidExecutionTimeoutMessages } from '../../../../visual-programming/utils/validation/execution-timeout.validator';
import { isValidOutputSchema } from '../../../../visual-programming/utils/validation/output-schema.validator';
import { FlowHeaderComponent } from './components/header/flow-header.component';
import { PREVIEW_BLOCKED_MESSAGES } from './components/header/flow-header.constants';
import { FlowSaveStatus } from './components/header/flow-save-status.model';
import {
    SHORTCUTS_MODAL_HEIGHT_PX,
    ShortcutsModalComponent,
} from './components/shortcuts-modal/shortcuts-modal.component';
import { SerialSaveQueue } from './serial-save-queue';

/**
 * The shortcut of a header or sessions panel button: the handler its output is bound to, behind the checks that hide
 * or disable it.
 */
interface ButtonShortcut {
    readonly action: EditorActionId;
    /** Which "needs the Use permission" text to show when the keymap says the user may not use this action. */
    readonly usePermissionAction?: UsePermissionAction;
    /** Set when the button is disabled in a version preview; its tooltip there. */
    readonly previewBlockedMessage?: string;
    /**
     * Set when the button exists only in some states, whatever the user's permissions: while it is false the key
     * does nothing and says nothing, as there is no button to press.
     */
    readonly isButtonPresent?: () => boolean;
    readonly handle: () => void;
}

/**
 * How long a node's burst of explanation-save requests has to go quiet before one
 * save is sent. Long enough to collapse a table-wide explain pass into a few saves,
 * short enough to catch a dialog closed right after a single one.
 */
const CDT_EXPLANATIONS_SAVE_DEBOUNCE_MS = 1500;
/** localStorage prefix of a decision table's grid layout, keyed `<graphId>_<node number, else backend id>`. */
const CDT_GRID_STATE_PREFIX = 'cdt-grid-state-';

/** The id each decision table's grid layout is stored under (its number, else its backend id), by node id. */
function cdtGridStorageIds(flow: FlowModel): Map<string, number> {
    const storageIds = new Map<string, number>();
    for (const node of flow.nodes) {
        const storageId = node.type === NodeType.CLASSIFICATION_TABLE ? (node.nodeNumber ?? node.backendId) : null;
        if (storageId != null) storageIds.set(node.id, storageId);
    }
    return storageIds;
}

/** The numbers `nodes` show. */
function numbersOf(nodes: NodeModel[]): Set<number> {
    return new Set(nodes.map((node) => node.nodeNumber).filter((nodeNumber) => nodeNumber != null));
}

/** `flow` with the nodes listed in `numbersByNodeId` showing those numbers. */
function withNodeNumbers(flow: FlowModel, numbersByNodeId: ReadonlyMap<string, number>): FlowModel {
    if (numbersByNodeId.size === 0) return flow;
    return {
        ...flow,
        nodes: flow.nodes.map((node) => {
            const nodeNumber = numbersByNodeId.get(node.id);
            return nodeNumber != null ? { ...node, nodeNumber } : node;
        }),
    };
}

export const TEST_RUN_NODE_GONE_MESSAGE = 'This node no longer exists — reload the flow';
export const TEST_RUN_NODE_NOT_SAVED_MESSAGE = 'Click Save in the top panel to save the graph before running a test';
export const RUN_WHILE_SAVING_MESSAGE = 'The flow is being saved. Run again when it is saved.';
export const TEST_RUN_PAYLOAD_REJECTED_MESSAGE = 'Test payload rejected — open the node to see why';
export const extractParentNotUpdatedMessage = (subflowName: string): string =>
    `Subflow "${subflowName}" was created, but another flow was opened before the original flow was updated — the extracted nodes are still in it`;
export const REMOTE_SAVE_RELOAD_FAILED_MESSAGE = 'Failed to load the latest version of this flow — refresh it';
export const TRIGGER_NODE_CHANGES_NEED_USE_MESSAGE =
    'This change includes trigger nodes, which need the Use permission on flows. Remove or revert the trigger node changes to save.';

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
        SnakeGameOverlayComponent,
    ],
    templateUrl: './flow-visual-programming.component.html',
    styleUrl: './flow-visual-programming.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
    // The page's own store (not root), replaced on every graph load, including when the route switches flows.
    providers: [NodeAuthorshipStore],
})
export class FlowVisualProgrammingComponent implements OnInit, OnDestroy, CanComponentDeactivate {
    private readonly destroyRef = inject(DestroyRef);
    private readonly wsService = inject(GraphCollaborationWsService);
    private readonly profileService = inject(ProfileService);
    private readonly cdtExplanationsApiService = inject(CdtExplanationsApiService);
    private readonly easterEggTrigger = inject(EasterEggTriggerService);
    private readonly flowGraphHost = viewChild(FlowGraphComponent, { read: ElementRef<HTMLElement> });
    /** The sessions panel; there only while it is open. */
    private readonly messagesPanel = viewChild(FlowMessagesPanelComponent);
    private readonly isSnakeGameActive = signal(false);
    /** Board element the snake-game overlay covers; null while no game is running. */
    protected readonly snakeGameBoard = computed<HTMLElement | null>(() =>
        this.isSnakeGameActive() ? (this.flowGraphHost()?.nativeElement ?? null) : null
    );
    /** Read-only node id to node-type colour lookup for the snake-game intro; only evaluated while a game runs. */
    protected readonly snakeGameNodeColors = computed<ReadonlyMap<string, string>>(
        () => new Map(this.flowService.nodes().map((node) => [node.id, node.color]))
    );
    private readonly flowReadOnly = inject(FlowReadOnlyService);
    private readonly keymap = inject(KeymapService);
    private readonly nodeAuthorshipStore = inject(NodeAuthorshipStore);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly flowTestRunService = inject(FlowTestRunService);
    private readonly executionTimeoutLimits = inject(ExecutionTimeoutLimitsStorageService);
    /** The root instance, as for the live canvas and its panels; the version preview has its own. */
    private readonly scheduleTriggerRuntime = inject(ScheduleTriggerRuntimeService);
    private readonly usePermissionRefusal = inject(FlowUsePermissionRefusalService);

    public readonly flowAssistantService = inject(FlowAssistantService);
    public initialNodeId: string | null = null;
    public isLoaded = signal(false);
    private readonly graphState = signal<GraphDto | null>(null);
    /** The latest save another user announced; `graphState` is outdated while its save_version is lower. */
    private readonly remoteSave = signal<{ graphId: number; saveVersion: number } | null>(null);
    private readonly isGraphOutdated = computed(() => {
        const graph = this.graphState();
        const remoteSave = this.remoteSave();
        return (
            !!graph && !!remoteSave && graph.id === remoteSave.graphId && graph.save_version < remoteSave.saveVersion
        );
    });
    private readonly remoteSaveReloads = new Subject<{ graphId: number; saveVersion: number }>();
    /** What the editor compares against as stored on the backend (e.g. the webhook panel's code-only run). */
    private readonly storedGraph = computed<GraphDto | null>(() => (this.isGraphOutdated() ? null : this.graphState()));
    protected readonly availableFlowLights = signal<GetGraphLightRequest[]>([]);
    protected readonly currentFlowId = computed(() => this.graphState()?.id ?? null);
    /** The as-persisted snapshot used for dirty tracking; shared so panels can compare against it. */
    private readonly savedFlowStateService = inject(SavedFlowStateService);
    protected readonly collaborationEditors = this.wsService.editors;
    public readonly loadedFlowState = computed<FlowModel>(() => {
        const graph = this.graphState();
        if (!graph) return { nodes: [], connections: [] };
        return buildFlowModelFromGraphDto(graph);
    });
    public readonly currentFlowState = computed<FlowModel>(() => this.flowService.getFlowState());
    public readonly hasUnsavedChangesSignal = this.savedFlowStateService.hasUnsavedChanges;

    /**
     * Every request that writes the graph with its `save_version` goes through this,
     * one at a time — full saves, single-node saves, explanation saves, the
     * extract/unpack saves and a version restore alike. See
     * `SerialSaveQueue` for why.
     */
    private readonly saveQueue = new SerialSaveQueue();
    /** Full saves (and extract/unpack saves) queued or in flight; what the header's Save spinner shows. */
    private readonly pendingFullSaves = signal(0);
    public readonly isSaving = computed(() => this.pendingFullSaves() > 0);
    /** A regular or test run is being started; shared so it locks the header Run and the panels' test Run. */
    public readonly isRunning = this.flowTestRunService.isRunStarting;
    /** The status of the run streaming into the run panel (regular or test), until it ends. */
    protected readonly activeRunStatus = computed<GraphSessionStatus | null>(() => {
        if (!this.runSessionSSEService.isStreaming()) return null;
        const status = this.runSessionSSEService.status();
        return isTerminalSessionStatus(status) ? null : status;
    });
    /** No unsaved flow edits, no open node panel (its edits reach the flow only on commit) and no version preview. */
    private readonly canReplaceLiveFlow = computed(
        () => !this.hasUnsavedChangesSignal() && !this.isPreviewing() && !this.sidePanelService.selectedNodeId()
    );
    public restoreWarnings = signal<RestoreWarning[]>([]);
    /** Restore warnings still worth showing: one tied to a node goes away once that node is deleted. */
    public readonly activeRestoreWarnings = computed(() => {
        const backendNodeIds = new Set(this.flowService.nodes().map((node) => node.backendId));
        return this.restoreWarnings().filter(
            (warning) => warning.node_id == null || backendNodeIds.has(warning.node_id)
        );
    });

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
    /** The header's save status chip; none while previewing a version. */
    protected readonly saveStatus = computed<FlowSaveStatus | null>(() => {
        if (this.isPreviewing()) return null;
        if (this.isSaving() || this.sidePanelService.savingNodeId() !== null) return 'saving';
        const connection = this.wsService.connectionStatus();
        if (connection === 'lost') return 'connection-lost';
        if (connection === 'reconnecting') return 'reconnecting';
        return this.hasUnsavedChangesSignal() ? 'unsaved' : 'saved';
    });
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
    private liveCdtStorageIds = new Set<string>();
    // The nodeId query opens its panel once; re-mounting the live canvas must not re-open it.
    private lastQueriedNodeId: string | null = null;
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
        this.routeParamMap = toSignal(this.route.paramMap, { initialValue: this.route.snapshot.paramMap });
        this.routeQueryParamMap = toSignal(this.route.queryParamMap, {
            initialValue: this.route.snapshot.queryParamMap,
        });

        this.flowService.bindSavedGraph(this.storedGraph);
        this.destroyRef.onDestroy(() => this.flowService.bindSavedGraph(null));
        this.keymap.register('editing.save', () => this.saveFromShortcut(), {
            allowInEditable: true,
            destroyRef: this.destroyRef,
        });
        this.registerButtonShortcuts();

        effect(() => {
            const params = this.routeQueryParamMap();
            const nodeId = params.get('nodeId');
            if (nodeId !== this.lastQueriedNodeId) {
                this.lastQueriedNodeId = nodeId;
                this.isNodeQueryConsumed = false;
            }
            if (this.isNodeQueryConsumed || !nodeId) {
                this.initialNodeId = null;
                return;
            }
            const match = this.currentFlowState().nodes.find(
                (node) => node.id === nodeId || String(node.backendId) === nodeId
            );
            this.initialNodeId = match?.id ?? nodeId;
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
            this.isSnakeGameActive.set(false);
            this.undoRedoService.setUndoStack([]);
            this.undoRedoService.setRedoStack([]);
            const warnings = this.createGraphWarningService.readPending();
            // Always replace: warnings from a previous flow must not follow the user to this one.
            this.restoreWarnings.set(warnings);
            // Test payload errors are keyed by canvas node id and belong to the previous flow.
            this.flowTestRunService.clearAllServerErrors();
            this.fetchGraph(graphId);
        });

        effect(() => {
            const flowState = this.currentFlowState();
            const cdtStorageIds = new Set(
                flowState.nodes
                    .filter((node) => node.type === NodeType.CLASSIFICATION_TABLE)
                    .map((node) => String(node.nodeNumber ?? node.backendId))
            );
            const cdtRemoved = [...this.liveCdtStorageIds].some((id) => !cdtStorageIds.has(id));
            this.liveCdtStorageIds = cdtStorageIds;
            if (cdtRemoved) this.cleanupCdtGridState(flowState);
        });
        this.easterEggTrigger.activated$
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.startSnakeGame());

        this.sidePanelService.saveNodeRequest$
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((node) => this.handleNodeSaveRequest(node));

        // Subscribed here, not by whatever asked for the save: a dialog that requests
        // one is usually closed moments later, and its request would be aborted
        // mid-flight, leaving `save_version` behind the server's and 409ing after.
        //
        // Debounced per node, so a burst on one table collapses while a request for
        // another is never swallowed by it; then queued behind every other save, so
        // the request is built — node re-read, `save_version` taken — only once the
        // one before it has answered. The graph is the one shown when it was asked for.
        this.sidePanelService.cdtExplanationsSaveRequest$
            .pipe(
                map((nodeId) => ({ nodeId, graphId: this.graphState()?.id ?? null })),
                groupBy(({ nodeId }) => nodeId),
                mergeMap((requestsForNode) => requestsForNode.pipe(debounceTime(CDT_EXPLANATIONS_SAVE_DEBOUNCE_MS))),
                mergeMap(({ nodeId, graphId }) => this.saveQueue.run(() => this.saveCdtExplanations(nodeId, graphId))),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();

        this.sidePanelService.reloadRequested$
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.refreshCurrentFlow());

        this.flowTestRunService.requests$
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((request) => this.handleTestRun(request));

        // The service already updated the canvas and the dirty baseline; the saved graph the save diff
        // starts from must follow, or the next save would send the schedule as changed.
        this.scheduleTriggerRuntime.updates$
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(({ backendId, state }) =>
                this.graphState.update(
                    (graph) => graph && withGraphScheduleTriggerRuntimeState(graph, backendId, state)
                )
            );
        this.wsService.graphSaved$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event) => {
            const currentId = this.profileService.currentUserSignal()?.id;
            if (event.saved_by.user_id === currentId) return;

            const savedBy = event.saved_by.display_name ?? `User ${event.saved_by.user_id}`;
            this.toastService.info(`Graph was saved by ${savedBy}`, 4000, 'bottom-right');

            this.remoteSave.set({ graphId: event.graph_id, saveVersion: event.new_save_version });
        });

        // An outdated graph is reloaded only once nothing local can be lost. Until then `graphState`
        // keeps the old save_version, so a save fails the version check instead of overwriting the
        // other user's save.
        effect(() => {
            if (!this.isGraphOutdated() || !this.canReplaceLiveFlow()) return;
            const remoteSave = this.remoteSave()!;
            untracked(() => this.remoteSaveReloads.next(remoteSave));
        });

        this.remoteSaveReloads
            .pipe(
                switchMap(({ graphId, saveVersion }) =>
                    this.flowApiService.getGraphById(graphId, true).pipe(
                        // A read older than the announced save would leave the canvas just as outdated.
                        map((graph): GraphDto | null => (graph.save_version >= saveVersion ? graph : null)),
                        catchError(() => of(null))
                    )
                ),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((graph) => {
                if (!graph) {
                    this.toastService.warning(REMOTE_SAVE_RELOAD_FAILED_MESSAGE);
                    return;
                }
                // The canvas may have changed while the graph loaded.
                if (graph.id !== this.graphState()?.id || !this.canReplaceLiveFlow()) return;
                // Undo must not bring back the canvas from before the other user's save.
                this.undoRedoService.clear();
                this.applyLoadedGraphState(graph, this.availableFlowLights(), false);
            });
    }

    public ngOnInit(): void {
        this.unsavedChangesRegistry.register(this);
    }

    protected closeSnakeGame(): void {
        this.isSnakeGameActive.set(false);
    }

    public refreshCurrentFlow(): void {
        const graphId = Number(this.route.snapshot.paramMap.get('id'));
        if (!isFinite(graphId)) return;
        this.fetchGraph(graphId, true, true);
    }

    public onExtractToSubflow(selectedNodeIds: Set<string>): void {
        if (!this.graph?.id || this.isSaving()) return;
        if (this.flowReadOnly.isReadOnly()) {
            this.flowReadOnly.notifyBlocked();
            return;
        }

        const graphId = this.graph.id;

        // Step 1: Save current parent graph to establish a clean baseline.
        this.saveFlowState(false)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                // Step 2: Open the Create Flow dialog so the user names the new subflow.
                switchMap(() => {
                    const dialogRef = this.dialog.open<GraphDto | undefined>(CreateFlowDialogComponent, {
                        width: '500px',
                        providers: [{ provide: LABELS_STORE, useExisting: LabelsStorageService }],
                    });
                    return dialogRef.closed;
                }),
                // If the user cancelled the dialog, stop.
                filter((newGraphDto): newGraphDto is GraphDto => newGraphDto != null),
                // Steps 3-6 run as one queued save, so no other save lands between them.
                switchMap((newGraphDto) =>
                    this.queueFullSave(() => this.extractAndSave(graphId, selectedNodeIds, newGraphDto))
                ),
                catchError((err: HttpErrorResponse) => {
                    this.toastService.error(`Extract to subflow failed: ${extractHttpErrorMessage(err)}`);
                    return EMPTY;
                })
            )
            .subscribe((subflowName) => {
                this.toastService.success(`Extracted selection into subflow "${subflowName}"`);
            });
    }

    public onUnpackSubflow(subGraphNodeId: string): void {
        if (!this.graph?.id || this.isSaving()) return;
        if (this.flowReadOnly.isReadOnly()) {
            this.flowReadOnly.notifyBlocked();
            return;
        }

        // Step 1: Find the SubGraphNode.
        const subGraphNode = this.flowService
            .nodes()
            .find((node): node is SubGraphNodeModel => node.id === subGraphNodeId && node.type === NodeType.SUBGRAPH);
        if (!subGraphNode) {
            this.toastService.error('SubGraph node not found');
            return;
        }

        const subgraphId = subGraphNode.data.id;
        if (!subgraphId) {
            this.toastService.error('SubGraph node has no linked flow');
            return;
        }

        const subflowName = subGraphNode.data.name || subGraphNode.node_name || `Subflow #${subgraphId}`;
        const graphId = this.graph.id;

        // Step 2: Fetch the subflow graph first: one this user may not unpack is refused before any question.
        this.flowApiService
            .getGraphById(subgraphId, true)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                map((graphDto) => normalizeFlowPorts(mapGraphDtoToFlowModel(graphDto))),
                filter((subflowFlowModel) => !this.refuseUnpackOfTriggerNodes(subflowFlowModel)),
                // Step 3: Check how many other flows reference this subflow.
                switchMap((subflowFlowModel) =>
                    this.flowApiService.getSubflowUsage(subgraphId).pipe(
                        catchError((err: HttpErrorResponse) => {
                            this.toastService.error(`Could not check subflow usage: ${extractHttpErrorMessage(err)}`);
                            return EMPTY;
                        }),
                        // Step 4: If used elsewhere, show a confirmation dialog; otherwise skip it.
                        switchMap(({ parent_flow_ids }) => {
                            const currentGraphId = this.graph!.id;
                            const otherFlowIds = parent_flow_ids.filter((id) => id !== currentGraphId);
                            if (otherFlowIds.length > 0) {
                                return this.confirmationDialogService
                                    .confirmWithOptions({
                                        title: 'Unpack Subflow',
                                        message:
                                            `This subflow is used in ${otherFlowIds.length} other flow(s). ` +
                                            `Unpack <strong>${escapeHtml(subflowName)}</strong> into the current graph?`,
                                        confirmText: 'Unpack',
                                        cancelText: 'Cancel',
                                        type: 'warning',
                                        checkbox: {
                                            label: 'Also delete the subflow (will break other flows that use it)',
                                        },
                                    })
                                    .pipe(
                                        filter(
                                            (result): result is Exclude<typeof result, 'close'> =>
                                                result !== 'close' && result.confirmed
                                        ),
                                        map((dialogResult) => dialogResult.checked)
                                    );
                            }
                            // Not used elsewhere — skip dialog, auto-delete after unpack.
                            return of(true);
                        }),
                        map((deleteSubflow) => ({ subflowFlowModel, deleteSubflow }))
                    )
                ),
                // Steps 5-7 run as one queued save, so no other save lands between the canvas change and its save.
                switchMap(({ subflowFlowModel, deleteSubflow }) =>
                    this.queueFullSave(() => this.unpackAndSave(graphId, subGraphNodeId, subflowFlowModel)).pipe(
                        map(() => deleteSubflow)
                    )
                ),
                // Step 8: Optionally delete the subflow.
                switchMap((deleteSubflow) => {
                    if (deleteSubflow) {
                        return this.flowStorageService.bulkDelete([subgraphId]).pipe(
                            map((response) => {
                                const gone = [...response.deleted_ids, ...response.not_found_ids].includes(subgraphId);
                                if (!gone) {
                                    const reason = response.skipped.find((entry) => entry.id === subgraphId)?.reason;
                                    this.toastService.warning(
                                        reason === 'in_use_restricted'
                                            ? "Unpacked successfully, but the subflow is used somewhere you don't have access to, so it was kept"
                                            : 'Unpacked successfully, but the subflow could not be deleted, so it was kept'
                                    );
                                }
                                return gone;
                            }),
                            catchError(() => {
                                this.toastService.error('Unpacked successfully, but failed to delete the subflow');
                                return of(false);
                            })
                        );
                    }
                    return of(false);
                }),
                catchError((err: HttpErrorResponse) => {
                    this.toastService.error(`Unpack subflow failed: ${extractHttpErrorMessage(err)}`);
                    return EMPTY;
                })
            )
            .subscribe((deleted) => {
                const suffix = deleted ? ' and deleted the subflow' : '';
                this.toastService.success(`Unpacked "${subflowName}" into the current graph${suffix}`);
            });
    }

    /**
     * Unpacking creates the subflow's nodes in this flow, and creating a trigger node needs Flows:Use, so for a
     * user without it a subflow with trigger nodes is refused as a whole. Returns true when it refused, after
     * telling the user why.
     */
    private refuseUnpackOfTriggerNodes(subflowFlowModel: FlowModel): boolean {
        if (
            this.flowReadOnly.canEditTriggerNodes() ||
            !subflowFlowModel.nodes.some((node) => isTriggerNodeType(node.type))
        ) {
            return false;
        }
        this.usePermissionRefusal.showRefusal('unpack');
        return true;
    }

    /**
     * Steps 3-6 of an extraction: moves the selection into the new subflow, saves the subflow, then
     * the parent. Runs inside `saveQueue` as one task: the canvas is read when its turn comes, and an
     * explanation save waiting behind it runs only once the selection has left the parent, so it
     * finds those nodes gone and sends nothing for them. Emits the subflow's name once both saved.
     * Nothing happens to a parent the page no longer shows (see `isCurrentGraph`).
     */
    private extractAndSave(graphId: number, selectedNodeIds: Set<string>, newGraphDto: GraphDto): Observable<string> {
        if (!this.isCurrentGraph(graphId)) return EMPTY;

        // Step 3: Run the extraction utility.
        const { subflowModel, parentModel } = extractToSubflow(
            this.currentFlowState(),
            selectedNodeIds,
            generateUuid(),
            newGraphDto.id,
            this.flowService.getNextNodeNumber()
        );

        // Step 4: Build the subflow save payload (empty previous = all creates).
        const emptyFlow: FlowModel = { nodes: [], connections: [] };
        const subflowNodeDiff = getNodeDiff(emptyFlow, subflowModel);
        const subflowIdMap = buildUuidToBackendIdMap(subflowModel.nodes);
        const subflowConnectionDiff = getConnectionDiff(emptyFlow, subflowModel, subflowIdMap);
        const subflowPayload = buildBulkSavePayload(
            newGraphDto.id,
            subflowNodeDiff,
            subflowConnectionDiff,
            subflowModel,
            subflowIdMap,
            newGraphDto.save_version
        );

        // Step 5: Bulk-save the subflow nodes to the server.
        return this.flowApiService.bulkSaveGraph(newGraphDto.id, subflowPayload).pipe(
            // Step 6: Update the parent flow with the extraction result and save it.
            switchMap(() => {
                // Another flow opened while the subflow saved: its canvas is not the parent's to
                // replace. The subflow exists now, with copies of the nodes; the parent still has them.
                if (!this.isCurrentGraph(graphId)) {
                    this.toastService.warning(extractParentNotUpdatedMessage(newGraphDto.name));
                    return EMPTY;
                }

                // Update the subgraph node name to match the newly created flow name.
                const namedParentModel: FlowModel = {
                    ...parentModel,
                    nodes: parentModel.nodes.map((node) => {
                        if (node.type !== NodeType.SUBGRAPH) return node;
                        const subgraphNode = node as SubGraphNodeModel;
                        if (subgraphNode.data.id !== newGraphDto.id) return node;
                        return {
                            ...subgraphNode,
                            node_name: newGraphDto.name,
                            data: {
                                ...subgraphNode.data,
                                name: newGraphDto.name,
                                uuid: newGraphDto.uuid ?? '',
                                description: newGraphDto.description ?? '',
                            },
                        };
                    }),
                };

                this.flowService.setFlow(normalizeFlowPorts(namedParentModel));
                return this.sendFlowState(graphId, false).pipe(map(() => newGraphDto.name));
            })
        );
    }

    /**
     * Steps 5-7 of an unpack: puts the subflow's nodes in place of its subgraph node and saves the
     * parent. Runs inside `saveQueue` as one task, for the reasons given at `extractAndSave`.
     */
    private unpackAndSave(graphId: number, subGraphNodeId: string, subflowFlowModel: FlowModel): Observable<void> {
        if (!this.isCurrentGraph(graphId)) return EMPTY;

        // Step 6: Run the unpack utility.
        const unpackedModel = unpackSubflow(this.currentFlowState(), subGraphNodeId, subflowFlowModel, () =>
            this.flowService.getNextNodeNumber()
        );

        // Step 7: Update the parent flow and save.
        this.flowService.setFlow(normalizeFlowPorts(unpackedModel));
        return this.sendFlowState(graphId, false);
    }

    private fetchGraph(graphId: number, forceRefresh = false, showRefreshToast = false): void {
        this.loadGraph(graphId, forceRefresh, showRefreshToast).pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
    }

    /**
     * Loads graph `graphId` onto the page. A failure is reported and leaves for the flows list.
     * Neither happens once the route has moved on to another flow: a slow load (a version
     * restore's reload, say) must not land over the flow the user went to.
     */
    private loadGraph(graphId: number, forceRefresh: boolean, showRefreshToast: boolean): Observable<void> {
        const isStillRouted = (): boolean => Number(this.routeParamMap().get('id')) === graphId;
        return forkJoin({
            graph: this.flowApiService.getGraphById(graphId, forceRefresh),
            flows: this.flowApiService.getGraphsLight().pipe(catchError(() => of([] as GetGraphLightRequest[]))),
        }).pipe(
            filter(isStillRouted),
            tap(({ graph, flows }) => {
                this.applyLoadedGraphState(graph, flows, showRefreshToast);
                this.wsService.connect(graph.id);
            }),
            map(() => void 0),
            catchError((e) => {
                if (!isStillRouted()) return EMPTY;
                this.toastService.error(e.error?.detail || 'Failed to load graph');
                void this.router.navigate(['/flows/my']);
                return EMPTY;
            }),
            finalize(() => this.cdr.markForCheck())
        );
    }

    public onHeaderSave(): void {
        if (this.flowReadOnly.isReadOnly()) {
            this.flowReadOnly.notifyBlocked();
            return;
        }
        this.flowGraphComponent?.emitSave();
    }

    public onGraphSave(flowState: FlowModel): void {
        if (!this.graph?.id || this.isSaving()) return;
        if (this.flowReadOnly.isReadOnly()) {
            this.flowReadOnly.notifyBlocked();
            return;
        }

        this.cleanupCdtGridState(flowState);
        this.saveFlowState(true).pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
    }

    private getBlockingNodeValidationIssues(flowState: FlowModel): string[] {
        let issues: string[] = [];
        try {
            issues = [
                ...this.getInvalidTaskNodeMessages(flowState),
                ...this.getInvalidAgentNodeMessages(flowState),
                ...this.getInvalidClassificationTableMessages(flowState),
                // The key-value panel puts invalid entries into the flow so the canvas follows it; they stop here.
                ...invalidKeyValueNodeMessages(flowState.nodes),
                // As for key-value nodes: a panel commits an invalid timeout to the flow for the save to stop it here.
                ...invalidExecutionTimeoutMessages(flowState.nodes, this.executionTimeoutLimits.limits().minSeconds),
            ];
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

            const label = this.validationMessageLabel(taskNode, 'Untitled task', index);
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

            const label = this.validationMessageLabel(agentNode, 'Untitled agent', index);
            messages.push(`"${label}" is missing ${missingFields.join(', ')}`);
        });

        return messages;
    }

    /** CDT prompt schemas may legitimately be stored as a JSON string (legacy rows,
     *  CSV/JSON import, crew runtime `json.loads`) — parse before applying the object rule. */
    private isValidCdtPromptSchema(schema: PromptConfig['output_schema']): boolean {
        if (schema == null) return true;
        if (typeof schema === 'string') {
            const trimmed = schema.trim();
            if (trimmed === '') return true;
            try {
                return isValidOutputSchema(JSON.parse(trimmed));
            } catch {
                return false;
            }
        }
        return isValidOutputSchema(schema);
    }

    private getInvalidClassificationTableMessages(flowState: FlowModel): string[] {
        const messages: string[] = [];

        flowState.nodes.forEach((node, index) => {
            if (node.type !== NodeType.CLASSIFICATION_TABLE) return;
            const cdtNode = node as ClassificationDecisionTableNodeModel;
            const prompts = cdtNode.data?.table?.prompts ?? {};

            const invalidKeys = Object.entries(prompts)
                .filter(([, cfg]) => cfg.output_schema_invalid || !this.isValidCdtPromptSchema(cfg.output_schema))
                .map(([key]) => key);

            if (invalidKeys.length === 0) return;

            const label = this.validationMessageLabel(cdtNode, 'Untitled decision table', index);
            const detail =
                invalidKeys.length <= 3 ? ` (${invalidKeys.join(', ')})` : ` (${invalidKeys.length} prompts)`;
            messages.push(`"${label}" is missing a valid prompt output schema${detail}`);
        });

        return messages;
    }

    /**
     * The node's trimmed name with its badge number, so same-named nodes are told apart. A node without a name
     * is labelled `fallbackName` with its badge; one with neither gets its list position in parentheses, which
     * cannot be mistaken for a badge.
     */
    private validationMessageLabel(node: NodeModel, fallbackName: string, index: number): string {
        const name = node.node_name?.trim();
        if (name) return formatNodeLabel({ node_name: name, nodeNumber: node.nodeNumber });
        if (node.nodeNumber == null) return `${fallbackName} (${index + 1})`;
        return formatNodeLabel({ node_name: fallbackName, nodeNumber: node.nodeNumber });
    }

    /**
     * Puts the canvas a save patched on screen, then moves every unsaved node off a number the save
     * gave a saved node: the server numbered this save's new nodes from its counter, so an unsaved
     * node may now show the number another node took. The canvas is set first so `getNextNodeNumber`
     * counts from the numbers the server gave, not from the guesses they replaced. Decision tables
     * that changed number take their grid layout along. Returns the moved numbers by node id, for
     * the saved baseline to match.
     */
    private showSavedFlow(graphId: number, liveFlow: FlowModel): Map<string, number> {
        const before = this.currentFlowState();
        this.flowService.setFlow(liveFlow);

        const savedNumbers = numbersOf(liveFlow.nodes.filter((node) => node.backendId != null));
        const nodes = renumberUnsavedNodesHolding(liveFlow.nodes, savedNumbers, () =>
            this.flowService.getNextNodeNumber()
        );
        const shownFlow = { ...liveFlow, nodes };
        this.carryCdtGridStateToNewNumbers(graphId, before, shownFlow);

        const movedNumbers = new Map<string, number>();
        nodes.forEach((node, index) => {
            if (node !== liveFlow.nodes[index] && node.nodeNumber != null) movedNumbers.set(node.id, node.nodeNumber);
        });
        if (movedNumbers.size > 0) this.flowService.setFlow(shownFlow);
        return movedNumbers;
    }

    /**
     * A decision table's grid layout is stored under its number (see the panel's `gridStorageId`).
     * When a table's number changes (a save numbered it, or it was moved off a number another node
     * took), the layout moves to the new key before the canvas takes the number. A key another
     * table shows is never written: that layout is its own. The old key is removed unless a table
     * that kept its number still shows it; a table that has just taken that number (an imported
     * one) must not open with the layout of the table that left it.
     */
    private carryCdtGridStateToNewNumbers(graphId: number, before: FlowModel, after: FlowModel): void {
        const storageIdBefore = cdtGridStorageIds(before);
        const storageIdAfter = cdtGridStorageIds(after);
        const keyOf = (storageId: number) => `${CDT_GRID_STATE_PREFIX}${graphId}_${storageId}`;
        const keptStorageIds = new Set(
            [...storageIdAfter]
                .filter(([nodeId, storageId]) => storageIdBefore.get(nodeId) === storageId)
                .map(([, storageId]) => storageId)
        );

        const carried: [string, string][] = [];
        const vacated = new Set<number>();
        for (const [nodeId, newStorageId] of storageIdAfter) {
            const oldStorageId = storageIdBefore.get(nodeId);
            if (oldStorageId == null || oldStorageId === newStorageId) continue;
            // Another table shows this number too: its layout stays, and this one is not carried over it.
            const heldByAnother = [...storageIdAfter].some(
                ([otherId, storageId]) => otherId !== nodeId && storageId === newStorageId
            );
            if (heldByAnother) continue;
            const layout = localStorage.getItem(keyOf(oldStorageId));
            if (layout == null) continue;
            carried.push([keyOf(newStorageId), layout]);
            if (!keptStorageIds.has(oldStorageId)) vacated.add(oldStorageId);
        }
        // Every read comes before any removal or write, and removals before writes, so two tables
        // trading numbers each end up with the other's old key holding their own layout.
        for (const storageId of vacated) {
            localStorage.removeItem(keyOf(storageId));
        }
        for (const [key, layout] of carried) {
            localStorage.setItem(key, layout);
        }
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

        const toRemove: string[] = [];
        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            if (!key || !key.startsWith(CDT_GRID_STATE_PREFIX)) continue;
            const suffix = key.slice(CDT_GRID_STATE_PREFIX.length);
            if (!suffix.startsWith(`${graphId}_`)) continue;
            if (!liveSuffixes.has(suffix)) toRemove.push(key);
        }
        for (const key of toRemove) {
            localStorage.removeItem(key);
        }
    }

    /**
     * Saves the whole canvas once every save queued before it has answered. The
     * canvas is read then, not when this is called: a save that ran in between may
     * have created a node and handed it its `backendId`, and an earlier snapshot
     * would create it a second time.
     */
    private saveFlowState(showSuccessToast: boolean): Observable<void> {
        return defer(() => {
            if (!this.graph?.id) return EMPTY;
            if (this.flowReadOnly.isReadOnly()) {
                this.flowReadOnly.notifyBlocked();
                return EMPTY;
            }
            const graphId = this.graph.id;
            return this.queueFullSave(() => this.sendFlowState(graphId, showSuccessToast));
        });
    }

    /** Queues `task` in `saveQueue` and counts it in `isSaving` from now until it settles. */
    private queueFullSave<T>(task: () => Observable<T>): Observable<T> {
        return defer(() => {
            this.pendingFullSaves.update((count) => count + 1);
            return this.saveQueue.run(task).pipe(finalize(() => this.pendingFullSaves.update((count) => count - 1)));
        });
    }

    /**
     * Whether the page still shows graph `graphId`. `flows/:id` reuses this component, so
     * between queueing a write and its turn — or its response — another flow may have
     * loaded: the canvas then holds that flow, which must never be sent as this one, nor
     * be overwritten by this one's response. Every queued write checks this when its turn
     * comes and again before it applies what came back.
     */
    private isCurrentGraph(graphId: number | null): graphId is number {
        return graphId != null && this.graphState()?.id === graphId;
    }

    private sendFlowState(graphId: number, showSuccessToast: boolean): Observable<void> {
        if (!this.isCurrentGraph(graphId)) return EMPTY;

        const flowState = this.currentFlowState();
        if (this.getBlockingNodeValidationIssues(flowState).length > 0) {
            return EMPTY;
        }

        const previous = this.loadedFlowState();
        const flowToSave = clearStaleIds(previous, flowState);
        const nodeDiff = getNodeDiff(previous, flowToSave);
        if (this.refuseTriggerNodeWrites(nodeDiff)) {
            return EMPTY;
        }

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
            // Answered after another flow loaded: applying it would replace that flow. Nothing is
            // emitted either, so what was chained on the save (a run, an extraction) does not go on.
            switchMap(({ graph, flows }) => {
                if (!this.isCurrentGraph(graphId)) return EMPTY;
                this.onFlowSaved(graph, flows, flowToSave, previous, nodeDiff, showSuccessToast);
                return of(void 0);
            }),
            catchError((err: HttpErrorResponse) => {
                if (err.status === 409) {
                    this.toastService.warning(
                        'This graph was modified by another user. Please refresh to see the latest changes.'
                    );
                } else {
                    this.toastService.error(`Failed to save graph: ${extractHttpErrorMessage(err)}`);
                }
                return EMPTY;
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
        this.setGraphState(graph);
        this.availableFlowLights.set(flows);
        this.flowService.setNodeNumberFloor(graph.node_number_seq);

        // What was sent becomes the saved baseline; the canvas keeps what it holds now.
        // Patching the snapshot onto the canvas would revert anything that changed
        // while the request was in flight — an explanation that arrived, an edit —
        // and those are still unsaved, so they must stay and read as such. The canvas
        // takes the ids the sent snapshot was given by `tempId`, never by position.
        const patchedFlow = patchCdtPromptBackendIds(
            patchFlowStateWithBackendIds(flowState, previous, nodeDiff, graph),
            graph
        );
        const liveFlow = patchCdtPromptBackendIds(
            patchLiveFlowWithBackendIds(
                clearStaleIds(previous, this.currentFlowState()),
                patchedFlow,
                previous,
                nodeDiff,
                graph
            ),
            graph
        );

        const movedNumbers = this.showSavedFlow(graph.id, liveFlow);
        // Sync isActive from the save response: patchFlowStateWithBackendIds only assigns
        // backend IDs and does not propagate other backend-authoritative fields like is_active.
        for (const dto of graph.schedule_trigger_node_list ?? []) {
            const node = liveFlow.nodes.find(
                (n): n is ScheduleTriggerNodeModel =>
                    n.type === NodeType.SCHEDULE_TRIGGER && (n as ScheduleTriggerNodeModel).backendId === dto.id
            );
            if (node && node.data.isActive !== dto.is_active) {
                this.flowService.updateNode({ ...node, data: { ...node.data, isActive: dto.is_active } });
            }
        }
        this.savedFlowStateService.setSavedFlow(
            cloneFlowState(buildCdtSavedBaseline(withNodeNumbers(patchedFlow, movedNumbers), graph))
        );
        this.sidePanelService.notifyGraphSaved();
        if (showSuccessToast) {
            this.toastService.success('Graph saved successfully');
            this.warnIfCdtMissingLlmConfig(patchedFlow);
        }
    }

    /**
     * Last line of defence: the editor already keeps a user without Flows:Use from creating or changing a
     * trigger node, but a diff can still carry one (undo bringing back a deleted trigger node, say). The backend
     * would refuse the whole save, so it is not sent; the unsaved changes stay for the user to revert.
     * Returns true when it refused the save, after telling the user why.
     */
    private refuseTriggerNodeWrites(nodeDiff: NodeDiffByType): boolean {
        if (this.flowReadOnly.canEditTriggerNodes() || !hasTriggerNodeWrites(nodeDiff)) {
            return false;
        }
        this.toastService.warning(TRIGGER_NODE_CHANGES_NEED_USE_MESSAGE, 6000, 'bottom-right');
        return true;
    }

    /**
     * The panel's node goes onto the canvas now, as asked; the save itself waits its turn
     * in `saveQueue` and then sends the node as the canvas holds it (see `saveNodeToBackend`).
     */
    private handleNodeSaveRequest(node: NodeModel): void {
        if (!this.graph?.id) return;
        if (this.sidePanelService.savingNodeId() === node.id) return;
        if (this.flowReadOnly.isReadOnly()) {
            this.flowReadOnly.notifyBlocked();
            return;
        }
        const graphId = this.graph.id;

        this.flowService.updateNode(node);
        this.sidePanelService.markNodeSaving(node.id);
        this.saveQueue
            .run(() => this.saveNodeToBackend(node.id, graphId))
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.sidePanelService.clearNodeSaving())
            )
            .subscribe();
    }

    /**
     * Runs inside `saveQueue`, so the payload carries the `save_version` the previous save returned.
     *
     * Sends the node as the canvas holds it when the turn comes, not as it was when the save was
     * asked for: it may have been edited since, or been created on the server by a save that ran
     * in between (taking a `backendId` the requested copy lacks). Deleted meanwhile, it is not sent.
     */
    private saveNodeToBackend(nodeId: string, graphId: number): Observable<void> {
        if (!this.isCurrentGraph(graphId)) return EMPTY;
        if (this.flowReadOnly.isReadOnly()) {
            this.flowReadOnly.notifyBlocked();
            return EMPTY;
        }

        const previous = this.loadedFlowState();
        const wholeFlow = clearStaleIds(previous, this.currentFlowState());
        const node = wholeFlow.nodes.find((candidate) => candidate.id === nodeId);
        if (!node) return EMPTY;

        const previousForDiff: FlowModel = {
            nodes: node.backendId != null ? previous.nodes.filter((n) => n.backendId === node.backendId) : [],
            connections: [],
        };
        const singleNodeFlow: FlowModel = { nodes: [node], connections: [] };
        const nodeDiff = getNodeDiff(previousForDiff, singleNodeFlow);
        if (this.refuseTriggerNodeWrites(nodeDiff)) {
            return EMPTY;
        }
        const connectionDiff = { toCreate: [], toUpdate: [], toDelete: [] };

        // The diff stays single-node — only this node is sent — but the payload needs
        // the whole canvas to resolve the node's references to its neighbours. Given
        // just this node, `resolveNodeRef` finds none of them and emits `*_temp_id`
        // for nodes that already exist on the server, which the backend rejects.
        const idMap = buildUuidToBackendIdMap(wholeFlow.nodes);
        const payload = buildBulkSavePayload(
            graphId,
            nodeDiff,
            connectionDiff,
            wholeFlow,
            idMap,
            this.graphState()!.save_version
        );

        return this.flowApiService.bulkSaveGraph(graphId, payload).pipe(
            tap((responseGraph) => {
                if (!this.isCurrentGraph(graphId)) return;
                this.setGraphState(responseGraph);
                this.flowService.setNodeNumberFloor(responseGraph.node_number_seq);

                // The baseline records what was *sent*, patched with what the server
                // assigned it. Reading the node back off the canvas would bake in
                // whatever arrived mid-flight and mark as saved what was never sent;
                // patching only `backendId` would drop the agent task ids and the
                // schedule-trigger fields, leaving those nodes dirty forever after a
                // successful save.
                const sentFlow = patchFlowStateWithBackendIds(
                    { nodes: [node], connections: [] },
                    previous,
                    nodeDiff,
                    responseGraph
                );
                const liveFlow = patchLiveFlowWithBackendIds(
                    clearStaleIds(previous, this.currentFlowState()),
                    sentFlow,
                    previous,
                    nodeDiff,
                    responseGraph
                );
                const movedNumbers = this.showSavedFlow(graphId, liveFlow);

                const savedNode = sentFlow.nodes[0];
                if (savedNode) {
                    const prev = this.savedFlowStateService.savedFlow();
                    const exists = prev.nodes.some((n) => n.id === node.id);
                    const nextNodes = exists
                        ? prev.nodes.map((n) => (n.id === node.id ? savedNode : n))
                        : [...prev.nodes, savedNode];
                    this.savedFlowStateService.setSavedFlow(
                        cloneFlowState(
                            withNodeNumbers({ nodes: nextNodes, connections: prev.connections }, movedNumbers)
                        )
                    );
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

    /**
     * Persists a decision table's explanations — only them. Runs inside `saveQueue`.
     *
     * The node is read off the canvas when its turn comes, never kept from when the
     * save was asked for: by then it may have been deleted or moved into a subflow
     * (its canvas id is gone either way), and a kept copy would send its old
     * `backendId` — a node this graph no longer has.
     *
     * Skipped then, when the saved copy already has them (a full save that ran in
     * between carried them), for a node the server has not got yet (it cannot be
     * explained either), in a read-only editor, and once another flow has loaded.
     * Silent either way: it fires once per explanation, and a failure leaves the
     * canvas dirty for the next full save.
     */
    private saveCdtExplanations(nodeId: string, graphId: number | null): Observable<void> {
        if (!this.isCurrentGraph(graphId) || this.flowReadOnly.isReadOnly()) return EMPTY;

        const node = this.flowService.nodes().find((candidate) => candidate.id === nodeId);
        if (node?.type !== NodeType.CLASSIFICATION_TABLE || node.backendId == null) return EMPTY;
        const backendId = node.backendId;

        const explanations = toStoredCdtExplanations(node.explanations);
        const savedNode = this.savedFlowStateService.savedNode(nodeId);
        if (
            savedNode?.type === NodeType.CLASSIFICATION_TABLE &&
            JSON.stringify(toStoredCdtExplanations(savedNode.explanations)) === JSON.stringify(explanations)
        ) {
            return EMPTY;
        }

        return this.cdtExplanationsApiService
            .saveExplanations(backendId, { save_version: this.graphState()!.save_version, explanations })
            .pipe(
                tap((response) =>
                    this.onCdtExplanationsSaved(graphId, nodeId, backendId, explanations, response.save_version)
                ),
                map(() => void 0),
                catchError(() => EMPTY)
            );
    }

    /**
     * Records what was sent as saved: in the loaded graph, so the next full save's
     * diff starts from it, and in the dirty-check baseline — the explanations only,
     * so an unsaved table edit on the same node still reads as unsaved. Ignored once
     * another flow has loaded: neither belongs to it.
     */
    private onCdtExplanationsSaved(
        graphId: number,
        nodeId: string,
        backendId: number,
        explanations: CdtExplanations,
        saveVersion: number
    ): void {
        if (!this.isCurrentGraph(graphId)) return;
        this.applyOwnWriteToGraphState(graphId, (graph) => ({
            ...graph,
            save_version: saveVersion,
            classification_decision_table_node_list: (graph.classification_decision_table_node_list ?? []).map((dto) =>
                dto.id === backendId
                    ? { ...dto, metadata: { ...(dto.metadata as object | undefined), explanations } }
                    : dto
            ),
        }));
        const saved = this.savedFlowStateService.savedFlow();
        this.savedFlowStateService.setSavedFlow({
            ...saved,
            nodes: saved.nodes.map((candidate) =>
                candidate.id === nodeId && candidate.type === NodeType.CLASSIFICATION_TABLE
                    ? { ...candidate, explanations }
                    : candidate
            ),
        });
    }

    /**
     * Takes a write's own result into `graphState` when the response is not the whole graph. It
     * does not bring in another user's save: whether the graph is outdated is still `remoteSave`
     * against the new `save_version`, and a save announced after this write stays ahead of it. A
     * result for a graph the page no longer shows is dropped.
     */
    private applyOwnWriteToGraphState(graphId: number, update: (graph: GraphDto) => GraphDto): void {
        const graph = this.graphState();
        if (!graph || graph.id !== graphId) return;
        this.setGraphState(update(graph));
    }

    private saveGraphForRun(): Observable<void> {
        if (!this.hasUnsavedChanges()) return of(void 0);
        if (this.isSaving()) return EMPTY;

        return this.saveFlowState(false);
    }

    /** Queued like every save, so it waits out one already in flight. */
    public saveCurrentState(): Observable<void> {
        if (!this.hasUnsavedChanges()) return of(void 0);
        return this.saveFlowState(false);
    }

    public handleRunFlow(): void {
        this.runAfterSave(
            () => this.runGraphService.runGraph(this.graph.id, this.graph.start_node_list[0].variables),
            (error) => this.toastService.error(`Failed to run graph: ${extractHttpErrorMessage(error)}`)
        );
    }

    /** "Run with test payload" from a trigger node panel: save the flow, then start the run at that node. */
    private handleTestRun(request: FlowTestRunRequest): void {
        this.runAfterSave(
            () => this.startTestRun(request),
            (error) => this.reportTestRunError(request.nodeId, error),
            request.nodeId
        );
    }

    /** Runs after the save, when a node added since the last save has its backend id. */
    private startTestRun(request: FlowTestRunRequest): Observable<RunGraphResponse> {
        const node = this.flowService.nodes().find((candidate) => candidate.id === request.nodeId);
        if (!node) {
            this.toastService.error(TEST_RUN_NODE_GONE_MESSAGE);
            return EMPTY;
        }
        if (node.backendId == null) {
            this.toastService.error(TEST_RUN_NODE_NOT_SAVED_MESSAGE);
            return EMPTY;
        }
        return this.runGraphService
            .runTestSession({
                graph_id: this.graph.id,
                node_type: request.nodeType,
                node_id: node.backendId,
                payload: request.payload,
            })
            .pipe(tap(() => this.toastService.success('Test run started')));
    }

    private reportTestRunError(nodeId: string, error: HttpErrorResponse): void {
        if (error.status === 400) {
            const payloadErrors: unknown = error.error?.errors;
            const isMessageList =
                Array.isArray(payloadErrors) && payloadErrors.every((message) => typeof message === 'string');
            this.flowTestRunService.setServerErrors(
                nodeId,
                isMessageList ? payloadErrors : [extractHttpErrorMessage(error)]
            );
            // The errors show under that node's test payload editor; say so when it is not on screen.
            if (this.sidePanelService.selectedNodeId() !== nodeId) {
                this.toastService.error(TEST_RUN_PAYLOAD_REJECTED_MESSAGE);
            }
            return;
        }
        if (error.status === 404) {
            this.toastService.error(TEST_RUN_NODE_GONE_MESSAGE);
            return;
        }
        if (error.status === 403) {
            this.toastService.error("You don't have permission to run tests on this flow.");
            return;
        }
        this.toastService.error(`Failed to start test run: ${extractHttpErrorMessage(error)}`);
    }

    /**
     * Saves unsaved changes, then starts a run with `start` and opens the run panel on its session.
     * Starts nothing while another run starts or the flow is being saved (the save would be skipped),
     * or when the open panel cannot be committed; a failed save has already been reported and starts
     * nothing either. `testRunNodeId` is the trigger node of a test run, so its panel can show that the
     * run is starting.
     */
    private runAfterSave(
        start: () => Observable<RunGraphResponse>,
        onStartError: (error: HttpErrorResponse) => void,
        testRunNodeId: string | null = null
    ): void {
        if (this.isRunning() || !this.graph?.id) return;
        if (this.isSaving()) {
            this.toastService.info(RUN_WHILE_SAVING_MESSAGE);
            return;
        }
        if (this.flowGraphComponent && !this.flowGraphComponent.commitSidePanelToFlow()) return;

        this.flowTestRunService.markRunStarting(testRunNodeId);

        this.saveGraphForRun()
            .pipe(
                switchMap(() => start()),
                takeUntilDestroyed(this.destroyRef),
                tap((response: RunGraphResponse) => {
                    this.currentSessionId = response.session_id?.toString() ?? null;
                    if (this.currentSessionId) {
                        this.runSessionSSEService.startStream(this.currentSessionId);
                    }
                    this.isPanelOpen.set(true);
                    this.isPanelCollapsed.set(false);
                    this.cdr.markForCheck();
                }),
                catchError((error: HttpErrorResponse) => {
                    onStartError(error);
                    return EMPTY;
                }),
                finalize(() => {
                    this.flowTestRunService.clearRunStarting();
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
                this.saveFlowState(false).pipe(
                    map(() => true),
                    defaultIfEmpty(false),
                    catchError(() => of(false))
                )
            )
            .pipe(
                tap((result) => {
                    this.isDeactivating = false;
                    if (result === 'dont-save') {
                        this.savedFlowStateService.setSavedFlow(cloneFlowState(this.currentFlowState()));
                    }
                }),
                map((result) => result === 'save' || result === 'dont-save')
            );
    }

    public onToggleAssistant(): void {
        if (!this.graph?.id) return;
        this.flowAssistantService.toggle(this.graph.id);
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
        this.savedFlowStateService.reset();
    }

    /** Starts the purely visual snake easter egg over the open flow; ignored while loading or already playing. */
    private startSnakeGame(): void {
        if (!this.isLoaded() || this.isSnakeGameActive() || !this.flowGraphHost()) return;
        this.isSnakeGameActive.set(true);
    }

    /**
     * The only way to load a graph into `graphState`: every graph the API returns here is the full graph,
     * and the node authorship store takes it in the same step, so it always mirrors `graphState`. (Runtime
     * schedule trigger state is applied to `graphState` in place: it carries no authorship.)
     */
    private setGraphState(graph: GraphDto): void {
        this.graphState.set(graph);
        this.nodeAuthorshipStore.replaceFromGraph(graph);
    }

    private applyLoadedGraphState(graph: GraphDto, flows: GetGraphLightRequest[], showRefreshToast: boolean): void {
        this.setGraphState(graph);
        this.availableFlowLights.set(flows);
        this.flowService.setNodeNumberFloor(graph.node_number_seq);
        const normalizedFlow = this.loadedFlowState();
        this.flowService.setFlow(normalizedFlow);
        // The saved baseline captures the as-persisted snapshot used for dirty-tracking.
        // It is set BEFORE the legacy-name rewrite so that flows with legacy names are
        // immediately marked dirty — the user accepted this behaviour.
        this.savedFlowStateService.setSavedFlow(cloneFlowState(normalizedFlow));

        // Eagerly rewrite legacy "at HH:MM" once-schedule names to "at HH-MM" in the
        // live canvas state. Because the saved baseline already holds the old names, the
        // flow will be marked dirty until the user saves, which is the intended UX.
        // Renaming changes the schedule node, which needs Flows:Use: without it the old name stays,
        // or every save of the flow would be refused.
        const rewrittenFlow: FlowModel = this.flowReadOnly.canEditTriggerNodes()
            ? {
                  ...normalizedFlow,
                  nodes: normalizedFlow.nodes.map((node) => {
                      if (node.type !== NodeType.SCHEDULE_TRIGGER) return node;
                      const rewrittenName = rewriteLegacyOnceScheduleName(node.node_name);
                      return rewrittenName !== node.node_name ? { ...node, node_name: rewrittenName } : node;
                  }),
              }
            : normalizedFlow;
        this.flowService.setFlow(rewrittenFlow);
        this.cleanupCdtGridState(rewrittenFlow);

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

    public openShortcutsModal(rect: DOMRect): void {
        if (this.isShortcutsOpen()) {
            this.closeShortcutsModal();
            return;
        }

        const screenMargin = 16;
        const lowestTop = window.innerHeight - screenMargin - SHORTCUTS_MODAL_HEIGHT_PX;
        const top = Math.max(screenMargin, Math.min(rect.top, lowestTop));
        const left = rect.right + 8;

        this.shortcutsPos.set({ top, left });
        this.isShortcutsOpen.set(true);
    }

    public closeShortcutsModal(): void {
        this.isShortcutsOpen.set(false);
        this.shortcutsPos.set(null);
    }

    public onFlowEdited(updatedFlow: GraphDto): void {
        this.setGraphState(updatedFlow);
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

    /** A renamed or re-described version keeps the preview bar in step; same id, so nothing reloads. */
    public onVersionUpdated(version: GraphVersionDto): void {
        if (this.previewedVersion()?.id === version.id) {
            this.previewedVersion.set(version);
        }
    }

    public onVersionRestoreRequested(version: GraphVersionDto): void {
        // The dirty check and the optional backup read the live flow (root state, which the preview
        // never touches), so the preview stays open behind the dialog. It closes only once the user
        // picks a restore option; Cancel leaves them in the preview.
        const hasUnsaved = this.hasUnsavedChanges();
        const message = hasUnsaved
            ? `You have unsaved changes. Restoring <strong>${escapeHtml(version.name)}</strong> will replace the current flow state. Save a backup of the current state first?`
            : `Restoring <strong>${escapeHtml(version.name)}</strong> will replace the current flow state. Save a backup of the current state first?`;

        // A restore this user may not do is refused first: before the backup question, the preview exit or a save.
        this.refuseRestoreOfTriggerNodes(version)
            .pipe(
                filter((refused) => !refused),
                switchMap(() =>
                    this.unsavedChangesDialog.confirm({
                        title: 'Restore Version',
                        message,
                        saveText: 'Save & Restore',
                        dontSaveText: 'Just restore',
                        cancelText: 'Cancel',
                        type: 'warning',
                        showDontSave: true,
                        appearance: 'neutral',
                    })
                ),
                switchMap((result) => {
                    if (result === 'save' || result === 'dont-save') {
                        this.onPreviewExit();
                    }
                    if (result === 'save') {
                        return this.saveCurrentState().pipe(switchMap(() => this.restoreVersion(version, true)));
                    }
                    if (result === 'dont-save') {
                        return this.restoreVersion(version, false);
                    }
                    return EMPTY;
                }),
                // The backend's refusal (e.g. permissions changed since they were loaded) is explained there and
                // emits nothing: no toast, nothing reloaded.
                this.usePermissionRefusal.catchRefusal('restore'),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({ error: () => this.toastService.error('Failed to restore version') });
    }

    /**
     * Restoring creates the version's nodes again, and creating a trigger node needs Flows:Use, so for a user
     * without it a version with trigger nodes is refused as a whole; emits true when it refused, after telling
     * the user why. Users with Flows:Use get `false` at once, without fetching the version.
     */
    private refuseRestoreOfTriggerNodes(version: GraphVersionDto): Observable<boolean> {
        if (this.flowReadOnly.canEditTriggerNodes()) {
            return of(false);
        }
        return this.flowApiService.previewGraphVersion(version.id).pipe(
            map(({ snapshot }) =>
                mapGraphDtoToFlowModel(mapSnapshotToGraphDto(snapshot, new Map())).nodes.some((node) =>
                    isTriggerNodeType(node.type)
                )
            ),
            // Unknown (the version could not be read): the restore request decides, through catchRefusal.
            catchError(() => of(false)),
            tap((refused) => {
                if (refused) this.usePermissionRefusal.showRefusal('restore');
            })
        );
    }

    public onShowRestoreWarnings(): void {
        const dialogRef = this.dialog.open<number | undefined>(RestoreWarningsDialogComponent, {
            width: '560px',
            data: { warnings: this.activeRestoreWarnings() },
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
                        return this.saveFlowState(false);
                    }
                    if (result === 'dont-save') {
                        return of(void 0);
                    }
                    return EMPTY;
                })
            )
            .subscribe(() => openVersionDialog());
    }

    /**
     * The header's Run, Sessions, Open / close chat and Get cURL keys, and the sessions panel's Stop session key. The
     * page owns them, not the header or the panel: it handles what those buttons emit, or holds the panel, and knows
     * the state they depend on. Each key calls the same handler its button's output is bound to, after the checks
     * made by hiding or disabling that button: without Flows:Use it says the action needs it, and in a version
     * preview it says what the button's tooltip says.
     */
    private registerButtonShortcuts(): void {
        const shortcuts: readonly ButtonShortcut[] = [
            {
                action: 'flow.run',
                usePermissionAction: 'run',
                previewBlockedMessage: PREVIEW_BLOCKED_MESSAGES.run,
                handle: () => this.handleRunFlow(),
            },
            {
                action: 'flow.stop-session',
                usePermissionAction: 'stopSession',
                // The panel decides whether its selected session can be stopped; closed, it has no Stop button.
                isButtonPresent: () => this.messagesPanel()?.canStopSelectedSession ?? false,
                handle: () => this.messagesPanel()?.onStopSession(),
            },
            {
                action: 'flow.sessions',
                previewBlockedMessage: PREVIEW_BLOCKED_MESSAGES.sessions,
                handle: () => this.handleViewSessions(),
            },
            { action: 'flow.chat', handle: () => this.onToggleAssistant() },
            {
                action: 'flow.curl',
                usePermissionAction: 'getCurl',
                previewBlockedMessage: PREVIEW_BLOCKED_MESSAGES.getCurl,
                handle: () => this.handleGetCurl(),
            },
        ];
        for (const shortcut of shortcuts) {
            this.keymap.register(shortcut.action, () => this.onButtonShortcut(shortcut), {
                // The header, and with it the buttons, only exists once the flow has loaded; the node menu's backdrop
                // covers the buttons while it is open.
                when: () =>
                    this.isLoaded() &&
                    !this.flowGraphComponent?.isNodeMenuOpen() &&
                    (shortcut.isButtonPresent?.() ?? true),
                destroyRef: this.destroyRef,
            });
        }
    }

    private onButtonShortcut(shortcut: ButtonShortcut): void {
        if (this.keymap.unavailableActionIds().has(shortcut.action)) {
            if (shortcut.usePermissionAction) {
                this.usePermissionRefusal.showActionRefusal(shortcut.usePermissionAction);
            }
            return;
        }
        if (shortcut.previewBlockedMessage && this.isPreviewing()) {
            this.toastService.info(shortcut.previewBlockedMessage);
            return;
        }
        shortcut.handle();
    }

    private saveFromShortcut(): void {
        if (this.previewedVersion()) {
            this.toastService.info(PREVIEW_BLOCKED_MESSAGES.save);
            return;
        }
        if (this.flowReadOnly.isReadOnly()) {
            this.flowReadOnly.notifyBlocked();
            return;
        }
        this.onHeaderSave();
    }

    /**
     * Restores `version` and loads the result as one queued full save: the restore is checked
     * against the `save_version` the save before it returned, and Save and Run stay locked until
     * the restored graph — with its new `save_version` — is on the page. Nothing is restored for,
     * or reloaded over, a flow the page no longer shows.
     */
    private restoreVersion(version: GraphVersionDto, backup: boolean): Observable<void> {
        const graphId = this.graph.id;
        return this.queueFullSave(() => {
            if (!this.isCurrentGraph(graphId)) return EMPTY;
            return this.flowApiService
                .restoreGraphVersion(version.id, backup, this.versionHistoryGraphSaveVersion())
                .pipe(
                    switchMap((response) =>
                        this.isCurrentGraph(graphId) ? this.onVersionRestored(graphId, response) : EMPTY
                    )
                );
        });
    }

    private onVersionRestored(graphId: number, response: GraphRestoreResponse): Observable<void> {
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
        return this.reloadRestoredGraph(graphId);
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
    private reloadRestoredGraph(graphId: number): Observable<void> {
        this.savedViewport.set(null);
        this.consumeNodeQuery();
        this.isCanvasReloading.set(true);
        return this.loadGraph(graphId, true, true).pipe(finalize(() => this.isCanvasReloading.set(false)));
    }
}
