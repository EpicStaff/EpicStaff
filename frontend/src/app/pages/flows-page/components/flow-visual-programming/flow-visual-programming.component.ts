import { Dialog as CdkDialog } from '@angular/cdk/dialog';
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
    ViewChild,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { catchError, defaultIfEmpty, EMPTY, finalize, forkJoin, map, Observable, of, switchMap, tap } from 'rxjs';

import { CanComponentDeactivate } from '../../../../core/guards/unsaved-changes.guard';
import { EpicChatService } from '../../../../features/epic-chat/epic-chat.service';
import { FlowSessionsListComponent } from '../../../../features/flows/components/flow-sessions-dialog/flow-sessions-list.component';
import { GetGraphLightRequest, GraphDto } from '../../../../features/flows/models/graph.model';
import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import { FlowsStorageService } from '../../../../features/flows/services/flows-storage.service';
import { RunGraphService } from '../../../../features/flows/services/run-graph-session.service';
import { FlowMessagesPanelComponent } from '../../../../pages/running-graph/components/flow-messages-panel/flow-messages-panel.component';
import { ConfigService } from '../../../../services/config/config.service';
import { ToastService } from '../../../../services/notifications/toast.service';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { SpinnerComponent } from '../../../../shared/components/spinner/spinner.component';
import { UnsavedChangesDialogService } from '../../../../shared/components/unsaved-changes-dialog/unsaved-changes-dialog.service';
import { NodeType } from '../../../../visual-programming/core/enums/node-type';
import { FlowModel } from '../../../../visual-programming/core/models/flow.model';
import { FlowGraphComponent } from '../../../../visual-programming/flow-graph/flow-graph.component';
import { FlowService } from '../../../../visual-programming/services/flow.service';
import {
    createStartNode,
    hasStartNode,
    mapGraphDtoToFlowModel,
    normalizeFlowPorts,
} from '../../../../visual-programming/utils/load';
import {
    buildBulkSavePayload,
    buildUuidToBackendIdMap,
    cloneFlowState,
    getConnectionDiff,
    getNodeDiff,
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
    ],
    templateUrl: './flow-visual-programming.component.html',
    styleUrl: './flow-visual-programming.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowVisualProgrammingComponent implements OnInit, OnDestroy, CanComponentDeactivate {
    private readonly destroyRef = inject(DestroyRef);

    public readonly isEpicChatEnabled: boolean;
    public initialNodeId: string | null = null;
    public isLoaded = signal(false);
    private readonly graphState = signal<GraphDto | null>(null);
    private readonly availableFlowLights = signal<GetGraphLightRequest[]>([]);
    private readonly savedFlowState = signal<FlowModel>({ nodes: [], connections: [] });
    public readonly loadedFlowState = computed<FlowModel>(() => {
        const graph = this.graphState();
        if (!graph) return { nodes: [], connections: [] };

        let flowModel = mapGraphDtoToFlowModel(graph);
        flowModel = this.addStartNodeIfNeeded(flowModel);
        const validated = this.validateSubgraphNodes(flowModel, this.availableFlowLights());
        return validated.flowModel;
    });
    public readonly currentFlowState = computed<FlowModel>(() => this.flowService.getFlowState());
    private readonly hasUnsavedChangesSignal = computed<boolean>(() => {
        return JSON.stringify(this.currentFlowState()) !== JSON.stringify(this.savedFlowState());
    });

    public isSaving = signal(false);
    public isRunning = signal(false);

    public isPanelOpen = signal(false);
    public isPanelCollapsed = signal(true);
    public currentSessionId: string | null = null;
    public panelWidthPx = 450;
    public isDragging = false;
    private readonly MIN_PANEL_WIDTH = 430;
    private readonly MAX_PANEL_WIDTH_RATIO = 0.7;
    private readonly routeParamMap;
    private readonly routeQueryParamMap;

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
        private readonly configService: ConfigService,
        private readonly elementRef: ElementRef,
        private readonly epicChatService: EpicChatService,
        private readonly flowUnsavedStateService: FlowUnsavedStateService,
        private readonly unsavedChangesDialog: UnsavedChangesDialogService
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
            this.fetchGraph(graphId);
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

    private fetchGraph(graphId: number, forceRefresh = false, showRefreshToast = false): void {
        forkJoin({
            graph: this.flowApiService.getGraphById(graphId, forceRefresh),
            flows: this.flowApiService.getGraphsLight().pipe(catchError(() => of([] as GetGraphLightRequest[]))),
        })
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                tap(({ graph, flows }) => {
                    console.log(
                        `[load][fetchGraph] graphId=${graphId} loaded edge_list=${graph.edge_list?.length ?? 0} ` +
                            `decision_tables=${graph.decision_table_node_list?.length ?? 0} flowsLight=${flows.length}`
                    );
                    this.applyLoadedGraphState(graph, flows, showRefreshToast);
                }),
                catchError(() => {
                    this.toastService.error('Failed to load graph');
                    return EMPTY;
                }),
                finalize(() => this.cdr.markForCheck())
            )
            .subscribe();
    }

    public onHeaderSave(): void {
        this.flowGraphComponent?.emitSave();
    }

    public onGraphSave(flowState: FlowModel): void {
        if (!this.graph?.id || this.isSaving()) return;

        this.saveFlowState(flowState, true).pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
    }

    private saveFlowState(flowState: FlowModel, showSuccessToast: boolean): Observable<void> {
        if (!this.graph?.id) return EMPTY;

        const previous = this.loadedFlowState();
        const nodeDiff = getNodeDiff(previous, flowState);
        const idMap = buildUuidToBackendIdMap(flowState.nodes);
        const connectionDiff = getConnectionDiff(previous, flowState, idMap);
        const payload = buildBulkSavePayload(this.graph.id, nodeDiff, connectionDiff, flowState, idMap);

        console.log(
            `[save][connections][current] graphId=${this.graph.id} ` +
                `connections=${flowState.connections.length} ` +
                `items=${JSON.stringify(
                    flowState.connections.map((c) => ({
                        id: c.id,
                        sourceNodeId: c.sourceNodeId,
                        targetNodeId: c.targetNodeId,
                        sourcePortId: c.sourcePortId,
                        targetPortId: c.targetPortId,
                        backendEdgeId: c.data?.id ?? null,
                    }))
                )}`
        );
        console.log(
            `[save][connections][diff] graphId=${this.graph.id} ` +
                `toCreate=${connectionDiff.toCreate.length} toDelete=${connectionDiff.toDelete.length} ` +
                `toCreateItems=${JSON.stringify(
                    connectionDiff.toCreate.map((c) => ({
                        id: c.id,
                        sourceNodeId: c.sourceNodeId,
                        targetNodeId: c.targetNodeId,
                        sourcePortId: c.sourcePortId,
                        targetPortId: c.targetPortId,
                    }))
                )} ` +
                `toDeleteItems=${JSON.stringify(
                    connectionDiff.toDelete.map((c) => ({
                        id: c.id,
                        sourceNodeId: c.sourceNodeId,
                        targetNodeId: c.targetNodeId,
                        sourcePortId: c.sourcePortId,
                        targetPortId: c.targetPortId,
                        backendEdgeId: c.data?.id ?? null,
                    }))
                )}`
        );
        console.log(
            `[save][payload][backend] graphId=${this.graph.id} ` +
                `edge_list_count=${((payload['edge_list'] as unknown[]) ?? []).length} ` +
                `deleted_edge_ids_count=${(((payload['deleted'] as { edge_ids?: unknown[] })?.edge_ids as unknown[]) ?? []).length} ` +
                `edge_list=${JSON.stringify(payload['edge_list'] ?? [])} ` +
                `deleted_edge_ids=${JSON.stringify((payload['deleted'] as { edge_ids?: unknown[] })?.edge_ids ?? [])}`
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
                console.log(
                    `[save][response][backend] graphId=${graph.id} edge_list=${graph.edge_list?.length ?? 0} ` +
                        `edges=${JSON.stringify(
                            (graph.edge_list ?? []).map((e) => ({
                                id: e.id,
                                start_node_id: e.start_node_id,
                                end_node_id: e.end_node_id,
                            }))
                        )}`
                );
                this.graphState.set(graph);
                this.availableFlowLights.set(flows);
                const patchedFlow = patchFlowStateWithBackendIds(flowState, previous, nodeDiff, graph);
                console.log(
                    `[save][connections][patched-flow] graphId=${graph.id} ` +
                        `connections=${patchedFlow.connections.length} ` +
                        `items=${JSON.stringify(
                            patchedFlow.connections.map((c) => ({
                                id: c.id,
                                sourceNodeId: c.sourceNodeId,
                                targetNodeId: c.targetNodeId,
                                sourcePortId: c.sourcePortId,
                                targetPortId: c.targetPortId,
                                backendEdgeId: c.data?.id ?? null,
                            }))
                        )}`
                );
                this.flowService.setFlow(patchedFlow);
                this.savedFlowState.set(cloneFlowState(patchedFlow));
                if (showSuccessToast) {
                    this.toastService.success('Graph saved successfully');
                }
            }),
            map(() => void 0),
            catchError((err) => {
                this.toastService.error(`Failed to save graph: ${err?.error?.error || 'Unknown error'}`);
                return EMPTY;
            }),
            finalize(() => {
                this.isSaving.set(false);
                this.cdr.markForCheck();
            })
        );
    }

    private saveGraphForRun(): Observable<void> {
        if (!this.hasUnsavedChanges()) return of(void 0);
        if (this.isSaving()) return EMPTY;

        return this.saveFlowState(this.currentFlowState(), false);
    }

    public handleRunFlow(): void {
        if (this.isRunning() || !this.graph?.id) return;

        this.isRunning.set(true);

        const saveFirst$: Observable<void> = this.saveGraphForRun();

        saveFirst$
            .pipe(
                switchMap(() => this.runGraphService.runGraph(this.graph.id, this.graph.start_node_list[0].variables)),
                takeUntilDestroyed(this.destroyRef),
                tap((response: { session_id?: number }) => {
                    this.currentSessionId = response.session_id?.toString() ?? null;
                    this.isPanelOpen.set(true);
                    this.isPanelCollapsed.set(false);
                    this.cdr.markForCheck();
                }),
                catchError((error: { error?: { error?: string } }) => {
                    this.toastService.error(`Failed to run graph: ${error?.error?.error || 'Unknown error'}`);
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
        if (this.hasUnsavedChanges()) {
            event.preventDefault();
            return (event.returnValue = '');
        }
    }

    @HostListener('document:keydown', ['$event'])
    public handleCtrlS(event: KeyboardEvent): void {
        if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
            event.preventDefault();
            this.onHeaderSave();
        }
    }

    public hasUnsavedChanges(): boolean {
        return this.hasUnsavedChangesSignal();
    }

    public canDeactivate(): boolean | Observable<boolean> {
        if (!this.hasUnsavedChanges()) return true;

        return this.unsavedChangesDialog
            .confirmUnsavedChanges(() =>
                this.saveFlowState(this.currentFlowState(), false).pipe(
                    map(() => true),
                    defaultIfEmpty(false),
                    catchError(() => of(false))
                )
            )
            .pipe(map((result) => result === 'save' || result === 'dont-save'));
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
        this.flowUnsavedStateService.unregister();
    }

    private addStartNodeIfNeeded(flowModel: FlowModel): FlowModel {
        if (hasStartNode(flowModel)) return flowModel;
        return { ...flowModel, nodes: [createStartNode(), ...flowModel.nodes] };
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
        this.savedFlowState.set(cloneFlowState(normalizedFlow));

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
    }

    private countBlockedSubgraphNodes(flowModel: FlowModel): number {
        return flowModel.nodes.filter((node) => node.type === NodeType.SUBGRAPH && node.isBlocked).length;
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
}
