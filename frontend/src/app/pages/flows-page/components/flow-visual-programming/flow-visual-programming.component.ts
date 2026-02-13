import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    signal,
    OnInit,
    OnDestroy,
    HostListener,
    AfterViewInit,
    ViewChild,
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { FlowService } from '../../../../visual-programming/services/flow.service';
import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import {
    CreateGraphDtoRequest,
    GraphDto,
    UpdateGraphDtoRequest,
} from '../../../../features/flows/models/graph.model';
import { FlowHeaderComponent } from './components/header/flow-header.component';
import { FlowGraphComponent } from '../../../../visual-programming/flow-graph/flow-graph.component';
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

import { ConditionalEdgeService } from './services/conditional-edge.service';
import { CrewNodeService } from './services/crew-node.service';
import { EdgeService } from './services/edge.service';
import { PythonNodeService } from './services/python-node.service';
import { RunGraphService } from '../../../../services/run-graph-session.service';
import { StartNodeService } from './services/start-node.service';
import { StartNode, CreateStartNodeRequest } from './models/start-node.model';

import {
    ConditionalEdge,
    CreateConditionalEdgeRequest,
    CustomConditionalEdgeModelForNode,
    GetConditionalEdgeRequest,
} from './models/conditional-edge.model';
import { CreateEdgeRequest, Edge } from './models/edge.model';
import { GetProjectRequest } from '../../../../features/projects/models/project.model';

import { CreateCrewNodeRequest, CrewNode } from './models/crew-node.model';
import {
    CreatePythonNodeRequest,
    PythonNode,
} from './models/python-node.model';

import { v4 as uuidv4 } from 'uuid';
import { ToastService } from '../../../../services/notifications/toast.service';
import { ConnectionModel } from '../../../../visual-programming/core/models/connection.model';
import { FlowModel } from '../../../../visual-programming/core/models/flow.model';
import { GroupNodeModel } from '../../../../visual-programming/core/models/group.model';
import {
    NodeModel,
    StartNodeModel,
} from '../../../../visual-programming/core/models/node.model';
import { NodeType } from '../../../../visual-programming/core/enums/node-type';
import { GraphUpdateService } from '../../../../visual-programming/services/graph/save-graph.service';
import { Dialog as CdkDialog } from '@angular/cdk/dialog';
import { FlowsStorageService } from '../../../../features/flows/services/flows-storage.service';
import { SpinnerComponent } from '../../../../shared/components/spinner/spinner.component';
import { FlowSessionsListComponent } from '../../../../features/flows/components/flow-sessions-dialog/flow-sessions-list.component';
import { UnsavedChangesDialogService } from '../../../../shared/components/unsaved-changes-dialog';

import { isEqual } from 'lodash';
import { CanComponentDeactivate } from '../../../../core/guards/unsaved-changes.guard';
import { ConfigService } from '../../../../services/config/config.service';
import { SidePanelService } from '../../../../visual-programming/services/side-panel.service';
import { ShortcutsModalComponent } from './components/shortcuts-modal/shortcuts-modal.component';
import { ShortcutSection } from './components/shortcuts-modal/shortcuts-modal.component';
@Component({
    selector: 'app-flow-visual-programming',
    standalone: true,
    imports: [FlowHeaderComponent, FlowGraphComponent, SpinnerComponent, ShortcutsModalComponent],
    templateUrl: './flow-visual-programming.component.html',
    styleUrl: './flow-visual-programming.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowVisualProgrammingComponent
    implements OnInit, OnDestroy, CanComponentDeactivate
{
    public isLoaded = false;
    public graph!: GraphDto;

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
        private readonly sidePanelService: SidePanelService
    ) {}

    public ngOnInit(): void {
        const id = Number(this.route.snapshot.paramMap.get('id'));
        if (!id) {
            console.warn('Invalid graph ID.');
            return;
        }

        this.fetchGraph(id);
    }

    private fetchGraph(graphId: number): void {
        this.flowApiService
            .getGraphById(graphId)
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => this.cdr.markForCheck())
            )
            .subscribe({
                next: (graph: GraphDto) => {
                    console.log('view flow page fetched graph:', graph);

                    this.graph = graph;

                    this.isLoaded = true;
                    this.initialState = graph.metadata;
                },
                error: (err) => {
                    console.error('Error fetching graph:', err);
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
                console.log(
                    'flow state that i got from service on saveflow',
                    flowState
                );

                const startNodeInFlow = flowState.nodes.find(
                    (node) => node.type === NodeType.START
                ) as StartNodeModel | undefined;

                if (!startNodeInFlow) {
                    console.log('no start node in flow');
                    return this.saveGraphDirectly(flowState, showNotif);
                }
                console.log('save graph with start node');
                return this.saveGraphWithStartNode(
                    flowState,
                    startNodeInFlow,
                    showNotif
                );
            })
        );
    }

    private saveGraphWithStartNode(
        flowState: FlowModel,
        startNode: StartNodeModel,
        showNotif: boolean
    ): Observable<boolean> {
        const initialStateData = startNode.data.initialState;

        return this.startNodeService.getStartNodes().pipe(
            takeUntil(this.destroy$),
            switchMap((startNodes) => {
                const matchingStartNode = startNodes.find(
                    (sn) => sn.graph === this.graph.id
                );

                if (matchingStartNode) {
                    return this.startNodeService.updateStartNode(
                        matchingStartNode.id,
                        {
                            graph: this.graph.id,
                            variables: initialStateData,
                        }
                    );
                }

                return this.startNodeService.createStartNode({
                    graph: this.graph.id,
                    variables: initialStateData,
                });
            }),
            switchMap(() =>
                this.graphUpdateService.saveGraph(flowState, this.graph)
            ),
            map((result) => {
                this.graph = result.graph;
                this.initialState = flowState;
                if (showNotif) {
                    this.toastService.success('Graph saved successfully');
                }
                return true;
            }),
            catchError((err) => {
                this.toastService.error(
                    `Failed to save graph: ${
                        err?.error?.error || 'Unknown error'
                    }`
                );
                console.error('Error saving graph:', err);
                return of(false);
            }),
            finalize(() => {
                this.isSaving = false;
                this.cdr.markForCheck();
            })
        );
    }

    private saveGraphDirectly(
        flowState: FlowModel,
        showNotif: boolean
    ): Observable<boolean> {
        return this.graphUpdateService.saveGraph(flowState, this.graph).pipe(
            takeUntil(this.destroy$),
            map((result) => {
                this.graph = result.graph;
                this.initialState = flowState;
                if (showNotif) {
                    this.toastService.success('Graph saved successfully');
                }
                return true;
            }),
            catchError((err) => {
                this.toastService.error(
                    `Failed to save graph: ${
                        err?.error?.error || 'Unknown error'
                    }`
                );
                console.error('Error saving graph:', err);
                return of(false);
            }),
            finalize(() => {
                this.isSaving = false;
                this.cdr.markForCheck();
            })
        );
    }

    private saveGraphForRun(): Observable<any> {
        // Trigger autosave before getting flow state
        this.flushActiveSidePanelState();
        this.sidePanelService.triggerAutosave();

        // Wait for autosave to complete before getting flow state
        return of(null).pipe(
            switchMap(() => new Promise((resolve) => setTimeout(resolve, 200))),
            switchMap(() => {
                const flowState: FlowModel = this.flowService.getFlowState();

                const startNodeInFlow = flowState.nodes.find(
                    (node) => node.type === NodeType.START
                ) as StartNodeModel | undefined;

                if (!startNodeInFlow) {
                    return this.graphUpdateService
                        .saveGraph(flowState, this.graph)
                        .pipe(
                            tap((result) => {
                                this.graph = result.graph;
                                this.initialState = flowState;
                            })
                        );
                }

                const initialStateData = startNodeInFlow.data.initialState;

                return this.startNodeService.getStartNodes().pipe(
                    switchMap((startNodes) => {
                        const matchingStartNode = startNodes.find(
                            (sn) => sn.graph === this.graph.id
                        );

                        if (matchingStartNode) {
                            return this.startNodeService.updateStartNode(
                                matchingStartNode.id,
                                {
                                    graph: this.graph.id,
                                    variables: initialStateData,
                                }
                            );
                        }

                        return this.startNodeService.createStartNode({
                            graph: this.graph.id,
                            variables: initialStateData,
                        });
                    }),
                    switchMap(() =>
                        this.graphUpdateService.saveGraph(flowState, this.graph)
                    ),
                    tap((result) => {
                        this.graph = result.graph;
                        this.initialState = flowState;
                    })
                );
            })
        );
    }

    public handleRunFlow(): void {
        if (this.isRunning || !this.graph?.id) return;

        this.isRunning = true;

        // Check if we have unsaved changes and save first if needed
        const saveFirst$ = this.hasUnsavedChanges()
            ? this.saveGraphForRun()
            : of(null);

        saveFirst$
            .pipe(
                switchMap(() =>
                    this.runGraphService.runGraph(
                        this.graph.id,
                        this.graph.start_node_list[0].variables
                    )
                ),
                takeUntil(this.destroy$),
                finalize(() => {
                    this.isRunning = false;
                    this.cdr.markForCheck();
                })
            )
            .subscribe({
                next: (response: any) => {
                    this.isNavigatingToRun = true;
                    this.router.navigate([
                        'graph',
                        this.graph.id,
                        'session',
                        response.session_id,
                    ]);
                },
                error: (error: any) => {
                    this.toastService.error(
                        `Failed to run graph: ${
                            error?.error?.error || 'Unknown error'
                        }`
                    );
                    console.error('Failed to run graph:', error);
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
        const flowId = this.graph?.id;
        const startNodeInitialState = this.flowService.startNodeInitialState();
        const apiUrl = this.configService.apiUrl;

        if (flowId && startNodeInitialState) {
            const curlCommand = this.generateCurlCommand(
                flowId,
                startNodeInitialState,
                apiUrl
            );
            this.copyToClipboard(curlCommand);
            this.toastService.success('CURL command copied to clipboard!');
        } else {
            this.toastService.error(
                'Unable to generate CURL: Missing flow ID or start node data'
            );
        }
    }

    private generateCurlCommand(
        flowId: number,
        variables: Record<string, unknown>,
        apiUrl: string
    ): string {
        const variablesJson = JSON.stringify(variables, null, 2);
        const payload = JSON.stringify(
            {
                graph_id: flowId.toString(),
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
            console.error('Failed to copy to clipboard:', err);
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
                            console.log('save flow');
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

    public ngOnDestroy(): void {
        // this.destroy$.next();
        // this.destroy$.complete();
    }

    private flushActiveSidePanelState(): void {
        this.flowGraphComponent?.flushOpenSidePanelState();
    }

    public isShortcutsOpen = signal(false);
    public shortcutsPos = signal<{ top: number; left: number } | null>(null);

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
    
    public readonly shortcutSections: ShortcutSection[] = [
    // {
    //     id: 'alignment',
    //     title: 'Alignment',
    //     rows: [
    //         { id: 'align-left', label: 'Align left', keys: ['Alt', 'A'] },
    //         { id: 'align-right', label: 'Align right', keys: ['Alt', 'D'] },
    //         { id: 'align-top', label: 'Align top', keys: ['Alt', 'W'] },
    //         { id: 'align-bottom', label: 'Align bottom', keys: ['Alt', 'S'] },
    //         { id: 'align-center-h', label: 'Align center (horizontally)', keys: ['Alt', 'H'] },
    //         { id: 'align-center-v', label: 'Align center (vertically)', keys: ['Alt', 'V'] },
    //     ],
    // },
    {
        id: 'navigating',
        title: 'Navigating',
        rows: [
            { id: 'next-item', label: 'Go to the next item', keys: ['Tab'] },
            { id: 'prev-item', label: 'Go to the previous item', keys: ['Shift', 'Tab'] }, // PS: i think, we should not override the default navigation behavior ?
            // { id: 'first-item', label: 'First item', keys: ['Home'] },
            // { id: 'last-item', label: 'Last item', keys: ['End'] },
            // { id: 'add-element', label: 'Add element', keys: ['N'] },
        ],
    },
    // {
    //     id: 'basic-actions',
    //     title: 'Basic Actions',
    //     rows: [
    //         { id: 'move-items', label: 'Move items', keys: ['arrows'] },
    //         { id: 'fast-move', label: 'Fast move', keys: ['Shift', 'arrows'] },
    //         { id: 'select-all', label: 'Select All', keys: ['Ctrl', 'A'] },
    //         { id: 'duplicate', label: 'Duplicate', keys: ['Ctrl', 'D'] },
    //         { id: 'search', label: 'Search', keys: ['/'] },
    //     ],
    // },
    {
        id: 'selection',
        title: 'Selection',
        rows: [
            // { id: 'select-item', label: 'Select an item', keys: ['Space'] },
            // { id: 'select-several', label: 'Select several items', keys: ['Shift', '←', '→', '↑', '↓'] },
            { id: 'add-remove-selection', label: 'Add/remove selection', keys: ['Ctrl', 'click'] },
            // { id: 'remove-selection', label: 'Remove all selection', keys: ['Esc'] },
        ],
    },
    // {
    //     id: 'connections',
    //     title: 'Connections',
    //     rows: [
    //         { id: 'connection-mode', label: 'Connection Mode', keys: ['C'] },
    //         { id: 'switch-between-items', label: 'Switch between items', keys: ['Tab'] },
    //         { id: 'switch-between-connections', label: 'Switch between connections', keys: ['Ctrl', 'arrows'] },
    //         { id: 'confirm-connection', label: 'Confirm', keys: ['Enter'] },
    //     ],
    // },
    {
        id: 'opening-editing',
        title: 'Opening/editing items',
        rows: [
            // { id: 'open-item', label: 'Open/activate item', keys: ['Enter'] },
            // { id: 'start-edit', label: 'Start editing the text', keys: ['Enter'] },
            { id: 'exit-edit', label: 'Exit edit mode', keys: ['Esc'] },
        ],
    },
    {
        id: 'zoom',
        title: 'Zoom',
        rows: [
            { id: 'zoom-in', label: 'Zoom in', keys: ['Ctrl', '+'] },
            { id: 'zoom-out', label: 'Zoom out', keys: ['Ctrl', '-'] },
            // { id: 'fit', label: 'Fit', keys: ['Ctrl', '0'] },
        ],
    },
    {
        id: 'delete',
        title: 'Delete',
        rows: [
            { id: 'delete-item', label: 'Delete', keys: ['Delete'] },
            { id: 'undo', label: 'Undo', keys: ['Ctrl', 'Z'] },
            { id: 'redo', label: 'Redo', keys: ['Ctrl', 'Shift', 'Z'] },
        ],
    },
    {
        id: 'filling-data',
        title: 'Filling in data',
        rows: [
            { id: 'confirm', label: 'Confirm', keys: ['Enter'] },
            // { id: 'new-line', label: 'New line', keys: ['Shift', 'arrows'] },
        ],
    }];

    public closeShortcutsModal(): void {
        this.isShortcutsOpen.set(false);
        this.shortcutsPos.set(null);
    }
}
