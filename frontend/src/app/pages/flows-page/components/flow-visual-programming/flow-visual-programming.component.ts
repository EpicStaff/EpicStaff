import { Dialog as CdkDialog } from '@angular/cdk/dialog';
import {
    AfterViewInit,
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    HostListener,
    OnDestroy,
    OnInit,
    signal,
    ViewChild,
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { isEqual } from 'lodash';
import {
    catchError,
    EMPTY,
    finalize,
    forkJoin,
    map,
    Observable,
    of,
    Subject,
    switchMap,
    takeUntil,
    tap,
    throwError,
} from 'rxjs';
import { v4 as uuidv4 } from 'uuid';

import { CanComponentDeactivate } from '../../../../core/guards/unsaved-changes.guard';
import { EpicChatService } from '../../../../features/epic-chat/epic-chat.service';
import { FlowSessionsListComponent } from '../../../../features/flows/components/flow-sessions-dialog/flow-sessions-list.component';
import { CreateGraphDtoRequest, GraphDto, UpdateGraphDtoRequest } from '../../../../features/flows/models/graph.model';
import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import { FlowsStorageService } from '../../../../features/flows/services/flows-storage.service';
import { RunGraphService } from '../../../../features/flows/services/run-graph-session.service';
import { GetProjectRequest } from '../../../../features/projects/models/project.model';
import { ConfigService } from '../../../../services/config/config.service';
import { ToastService } from '../../../../services/notifications/toast.service';
import { SpinnerComponent } from '../../../../shared/components/spinner/spinner.component';
import { UnsavedChangesDialogService } from '../../../../shared/components/unsaved-changes-dialog';
import { NodeType } from '../../../../visual-programming/core/enums/node-type';
import { ConnectionModel } from '../../../../visual-programming/core/models/connection.model';
import { FlowModel } from '../../../../visual-programming/core/models/flow.model';
import { NodeModel, StartNodeModel } from '../../../../visual-programming/core/models/node.model';
import { FlowGraphComponent } from '../../../../visual-programming/flow-graph/flow-graph.component';
import { FlowService } from '../../../../visual-programming/services/flow.service';
import { buildFlowModelFromGraph } from '../../../../visual-programming/services/graph/load-graph.service';
import { GraphUpdateService } from '../../../../visual-programming/services/graph/save-graph.service';
import {
    CreatedNodeMapping,
    getUIMetadataForComparison,
} from '../../../../visual-programming/services/graph/save-graph.types';
import { SidePanelService } from '../../../../visual-programming/services/side-panel.service';
import { FlowUnsavedStateService } from '../../services/flow-unsaved-state.service';
import { FlowHeaderComponent } from './components/header/flow-header.component';
import { ShortcutsModalComponent } from './components/shortcuts-modal/shortcuts-modal.component';
import { FLOW_SHORTCUT_SECTIONS } from './flow-shortcuts.config';
import {
    ConditionalEdge,
    CreateConditionalEdgeRequest,
    CustomConditionalEdgeModelForNode,
    GetConditionalEdgeRequest,
} from './models/conditional-edge.model';
import { CreateCrewNodeRequest, CrewNode } from './models/crew-node.model';
import { CreateEdgeRequest, Edge } from './models/edge.model';
import { CreatePythonNodeRequest, PythonNode } from './models/python-node.model';
import { CreateStartNodeRequest, StartNode } from './models/start-node.model';
import { ConditionalEdgeService } from './services/conditional-edge.service';
import { CrewNodeService } from './services/crew-node.service';
import { EdgeService } from './services/edge.service';
import { PythonNodeService } from './services/python-node.service';
import { StartNodeService } from './services/start-node.service';

@Component({
    selector: 'app-flow-visual-programming',
    standalone: true,
    imports: [FlowHeaderComponent, FlowGraphComponent, SpinnerComponent, ShortcutsModalComponent],
    templateUrl: './flow-visual-programming.component.html',
    styleUrl: './flow-visual-programming.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowVisualProgrammingComponent implements OnInit, OnDestroy, CanComponentDeactivate {
    public readonly isEpicChatEnabled: boolean;
    public initialNodeId: string | null = null;
    public isLoaded = false;
    public graph!: GraphDto;
    /** The flow model built from backend data — used as [flowState] input for the graph component. */
    public loadedFlowState!: FlowModel;

    public isSaving = false;
    public isRunning = false;

    private initialState: FlowModel | undefined;
    private readonly destroy$ = new Subject<void>();
    private isNavigatingToRun = false;

    @ViewChild(FlowGraphComponent)
    private flowGraphComponent?: FlowGraphComponent;

    constructor(
        private readonly route: ActivatedRoute,
        private readonly router: Router,
        private readonly flowStorageService: FlowsStorageService,
        private readonly flowService: FlowService,
        private readonly flowApiService: FlowsApiService,
        private readonly cdr: ChangeDetectorRef,
        private readonly toastService: ToastService,
        private readonly graphUpdateService: GraphUpdateService,
        private readonly runGraphService: RunGraphService,
        private readonly startNodeService: StartNodeService,
        private readonly dialog: CdkDialog,
        private readonly unsavedChangesDialogService: UnsavedChangesDialogService,
        private readonly configService: ConfigService,
        private readonly sidePanelService: SidePanelService,
        private readonly epicChatService: EpicChatService,
        private readonly flowUnsavedStateService: FlowUnsavedStateService
    ) {
        this.isEpicChatEnabled = this.configService.isEpicChatEnabled;
    }

    public ngOnInit(): void {
        this.flowUnsavedStateService.register(this);

        this.route.queryParamMap.pipe(takeUntil(this.destroy$)).subscribe((queryParams) => {
            this.initialNodeId = queryParams.get('nodeId');
        });

        this.route.paramMap.pipe(takeUntil(this.destroy$)).subscribe((params) => {
            const id = Number(params.get('id'));
            if (!id) {
                return;
            }
            this.fetchGraph(id);
        });
    }

    public refreshCurrentFlow(): void {
        const graphId = Number(this.route.snapshot.paramMap.get('id'));
        if (!graphId) {
            return;
        }
        this.fetchGraph(graphId, true, true);
    }

    private fetchGraph(graphId: number, forceRefresh = false, showRefreshToast = false): void {
        this.flowApiService
            .getGraphById(graphId, forceRefresh)
            .pipe(
                switchMap((graph: GraphDto) =>
                    this.flowApiService.getGraphsLight().pipe(
                        map((flows) => ({ graph, flows })),
                        catchError((err) => {
                            return of({ graph, flows: [] as GraphDto[] });
                        })
                    )
                ),
                takeUntil(this.destroy$),
                finalize(() => this.cdr.markForCheck())
            )
            .subscribe({
                next: ({ graph, flows }) => {
                    this.graph = graph;

                    // Build the FlowModel dynamically from backend node/edge lists
                    const flowModel = buildFlowModelFromGraph(graph);

                    // Validate subgraph nodes against available flows
                    const availableIds = new Set(flows.map((f) => f.id));
                    let blockedCount = 0;
                    flowModel.nodes = flowModel.nodes.map((node) => {
                        if (node.type !== NodeType.SUBGRAPH) return node;
                        const subgraphId = Number((node as { data?: { id?: unknown } })?.data?.id);
                        const isMissing = !subgraphId || !availableIds.has(subgraphId);
                        if (isMissing) blockedCount++;
                        return { ...node, isBlocked: isMissing };
                    });

                    this.loadedFlowState = flowModel;
                    this.initialState = flowModel;
                    this.isLoaded = true;

                    if (showRefreshToast) {
                        this.toastService.success('Flow refreshed');
                    }

                    if (blockedCount > 0) {
                        this.toastService.warning(
                            `${blockedCount} subgraph node(s) reference missing flows and were blocked.`,
                            6000,
                            'bottom-right'
                        );
                    }
                },
                error: () => {
                    this.toastService.error('Failed to load graph');
                },
            });
    }

    public handleSaveFlow(showNotif: boolean): Observable<boolean> {
        if (this.isSaving) {
            return of(false);
        }

        this.isSaving = true;
        this.flushActiveSidePanelState();

        this.sidePanelService.triggerAutosave();

        return of(null).pipe(
            switchMap(() => new Promise((resolve) => setTimeout(resolve, 200))),
            switchMap(() => {
                const flowState: FlowModel = this.flowService.getFlowState();

                const startNodeInFlow = flowState.nodes.find((node) => node.type === NodeType.START) as
                    | StartNodeModel
                    | undefined;

                if (!startNodeInFlow) {
                    return this.saveGraphDirectly(flowState, showNotif);
                }
                return this.saveGraphWithStartNode(flowState, startNodeInFlow, showNotif);
            })
        );
    }

    private saveGraphWithStartNode(
        flowState: FlowModel,
        startNode: StartNodeModel,
        showNotif: boolean
    ): Observable<boolean> {
        const initialStateData = startNode.data.initialState;
        const metadata = getUIMetadataForComparison(startNode);

        return this.startNodeService.getStartNodes().pipe(
            takeUntil(this.destroy$),
            switchMap((startNodes) => {
                const matchingStartNode = startNodes.find((sn) => sn.graph === this.graph.id);

                if (matchingStartNode) {
                    return this.startNodeService.partialUpdateStartNode(matchingStartNode.id, {
                        graph: this.graph.id,
                        variables: initialStateData,
                        metadata,
                    });
                }

                return this.startNodeService.createStartNode({
                    graph: this.graph.id,
                    variables: initialStateData,
                    metadata,
                });
            }),
            switchMap((startNodeResult) => {
                if (startNodeResult?.id != null) {
                    const sn = flowState.nodes.find((n) => n.type === NodeType.START);
                    if (sn) sn.backendId = startNodeResult.id;

                    const snInService = this.flowService.nodes()?.find((n) => n.type === NodeType.START);
                    if (snInService) snInService.backendId = startNodeResult.id;
                }
                return this.graphUpdateService.saveGraph(flowState, this.graph);
            }),
            map((result) => {
                this.graph = result.graph;
                this.patchBackendIds(result.createdMappings);
                this.initialState = this.flowService.getFlowState();
                if (showNotif) {
                    this.toastService.success('Graph saved successfully');
                }
                return true;
            }),
            catchError((err) => {
                this.toastService.error(`Failed to save graph: ${err?.error?.error || 'Unknown error'}`);
                console.error('Error saving graph:', err);
                return of(false);
            }),
            finalize(() => {
                this.isSaving = false;
                this.cdr.markForCheck();
            })
        );
    }

    private saveGraphDirectly(flowState: FlowModel, showNotif: boolean): Observable<boolean> {
        return this.graphUpdateService.saveGraph(flowState, this.graph).pipe(
            takeUntil(this.destroy$),
            map((result) => {
                this.graph = result.graph;
                this.patchBackendIds(result.createdMappings);
                this.initialState = this.flowService.getFlowState();
                if (showNotif) {
                    this.toastService.success('Graph saved successfully');
                }
                return true;
            }),
            catchError((err) => {
                this.toastService.error(`Failed to save graph: ${err?.error?.error || 'Unknown error'}`);
                return of(false);
            }),
            finalize(() => {
                this.isSaving = false;
                this.cdr.markForCheck();
            })
        );
    }

    private saveGraphForRun(): Observable<unknown> {
        // Trigger autosave before getting flow state
        this.flushActiveSidePanelState();
        this.sidePanelService.triggerAutosave();

        // Wait for autosave to complete before getting flow state
        return of(null).pipe(
            switchMap(() => new Promise((resolve) => setTimeout(resolve, 200))),
            switchMap(() => {
                const flowState: FlowModel = this.flowService.getFlowState();

                const startNodeInFlow = flowState.nodes.find((node) => node.type === NodeType.START) as
                    | StartNodeModel
                    | undefined;

                if (!startNodeInFlow) {
                    return this.graphUpdateService.saveGraph(flowState, this.graph).pipe(
                        tap((result) => {
                            this.graph = result.graph;
                            this.patchBackendIds(result.createdMappings);
                            this.initialState = this.flowService.getFlowState();
                        })
                    );
                }

                const initialStateData = startNodeInFlow.data.initialState;
                const metadata = getUIMetadataForComparison(startNodeInFlow);

                return this.startNodeService.getStartNodes().pipe(
                    switchMap((startNodes) => {
                        const matchingStartNode = startNodes.find((sn) => sn.graph === this.graph.id);

                        if (matchingStartNode) {
                            return this.startNodeService.partialUpdateStartNode(matchingStartNode.id, {
                                graph: this.graph.id,
                                variables: initialStateData,
                                metadata,
                            });
                        }

                        return this.startNodeService.createStartNode({
                            graph: this.graph.id,
                            variables: initialStateData,
                            metadata,
                        });
                    }),
                    switchMap(() => this.graphUpdateService.saveGraph(flowState, this.graph)),
                    tap((result) => {
                        this.graph = result.graph;
                        this.patchBackendIds(result.createdMappings);
                        this.initialState = this.flowService.getFlowState();
                    })
                );
            })
        );
    }

    /**
     * After a save, newly created nodes get a backend ID from the POST response.
     * This patches the UI nodes in the flow service so that the next save
     * recognises them as existing (update) rather than new (delete + create).
     */
    private patchBackendIds(mappings: CreatedNodeMapping[]): void {
        if (!mappings || mappings.length === 0) return;

        const mappingMap = new Map(mappings.map((m) => [m.uiNodeId, m.backendId]));

        const updatedNodes = this.flowService
            .nodes()
            .filter((node) => mappingMap.has(node.id))
            .map((node) => ({
                ...node,
                backendId: mappingMap.get(node.id)!,
            }));

        if (updatedNodes.length > 0) {
            this.flowService.updateNodesInBatch(updatedNodes as NodeModel[]);
        }
    }

    public handleRunFlow(): void {
        if (this.isRunning || !this.graph?.id) return;

        this.isRunning = true;

        // Check if we have unsaved changes and save first if needed
        const saveFirst$: Observable<unknown> = this.hasUnsavedChanges() ? this.saveGraphForRun() : of(null);

        saveFirst$
            .pipe(
                switchMap(() => this.runGraphService.runGraph(this.graph.id, this.graph.start_node_list[0].variables)),
                takeUntil(this.destroy$),
                finalize(() => {
                    this.isRunning = false;
                    this.cdr.markForCheck();
                })
            )
            .subscribe({
                next: (response: { session_id?: number }) => {
                    this.isNavigatingToRun = true;
                    this.router.navigate(['graph', this.graph.id, 'session', response.session_id]);
                },
                error: (error: { error?: { error?: string } }) => {
                    this.toastService.error(`Failed to run graph: ${error?.error?.error || 'Unknown error'}`);
                },
            });
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
            const curlCommand = this.generateCurlCommand(
                flowUuid,
                startNodeInitialState,
                apiUrl
            );
            this.copyToClipboard(curlCommand);
            this.toastService.success('CURL command copied to clipboard!');
        } else {
            this.toastService.error('Unable to generate CURL: Missing flow ID or start node data');
        }
    }

    private generateCurlCommand(
        flowUuid: string,
        variables: Record<string, unknown>,
        apiUrl: string
    ): string {
        const variablesJson = JSON.stringify(variables, null, 2);
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
        } catch (err) {
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
        const currentState = this.flowService.getFlowState();

        return !isEqual(currentState, this.initialState);
    }

    public canDeactivate(): boolean | Observable<boolean> {
        // Allow navigation if it's triggered by the run button
        if (this.isNavigatingToRun) {
            return true;
        }

        if (this.hasUnsavedChanges()) {
            return this.unsavedChangesDialogService
                .confirmUnsavedChanges(() => this.handleSaveFlow(false))
                .pipe(
                    switchMap((result) => {
                        if (result === 'close' || result === 'cancel') {
                            return of(false);
                        }
                        if (result === 'save') {
                            return of(true);
                        }
                        if (result === 'dont-save') {
                            return of(true);
                        }
                        return of(false);
                    })
                );
        }
        return true;
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

        this.flowApiService.patchGraph(this.graph.id, { epicchat_enabled: true }).subscribe({
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

    public ngOnDestroy(): void {
        this.flowUnsavedStateService.unregister();
        this.destroy$.next();
        this.destroy$.complete();
    }

    private flushActiveSidePanelState(): void {
        this.flowGraphComponent?.flushOpenSidePanelState();
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
        this.graph = updatedFlow;
        this.cdr.markForCheck();
    }
}
