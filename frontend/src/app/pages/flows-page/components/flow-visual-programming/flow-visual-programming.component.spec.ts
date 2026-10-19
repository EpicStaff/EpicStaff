import { Dialog as CdkDialog, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, forwardRef, inject, input, output, signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltipModule } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { ActivatedRoute, convertToParamMap, Router } from '@angular/router';
import { AppSvgIconComponent, SpinnerComponent, UnsavedChangesDialogService } from '@shared/components';
import { GraphSessionStatus, NodeType } from '@shared/models';
import { LlmConfigStorageService } from '@shared/services';
import { BehaviorSubject, Observable, of, Subject, throwError } from 'rxjs';

import { UnsavedChangesRegistry } from '../../../../core/services/unsaved-changes-registry.service';
import { AgentDefinitionsApiService } from '../../../../features/agent-definitions/services/agent-definitions-api.service';
import { FlowAssistantService } from '../../../../features/flow-assistant/flow-assistant.service';
import { VersionHistoryPanelComponent } from '../../../../features/flows/components/version-history-panel/version-history-panel.component';
import { GetGraphLightRequest, GraphDto, GraphVersionDto } from '../../../../features/flows/models/graph.model';
import { CreateGraphWarningsService } from '../../../../features/flows/services/create-graph-warnings.service';
import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import { FlowsStorageService } from '../../../../features/flows/services/flows-storage.service';
import { GraphCollaborationWsService } from '../../../../features/flows/services/graph-collaboration.ws.service';
import { RunGraphService } from '../../../../features/flows/services/run-graph-session.service';
import { RunSessionSSEService } from '../../../../pages/running-graph/services/graph-session-sse.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import { NodePanelShellComponent } from '../../../../visual-programming/components/node-panels/node-panel-shell/node-panel-shell.component';
import { PythonNodePanelComponent } from '../../../../visual-programming/components/node-panels/python-node-panel/python-node-panel.component';
import { AgentNode, AgentNodeTaskUi } from '../../../../visual-programming/core/models/agent-node.model';
import {
    CdtExplanation,
    CdtExplanations,
} from '../../../../visual-programming/core/models/classification-decision-table.model';
import { GetClassificationDecisionTableNodeRequest } from '../../../../visual-programming/core/models/classification-decision-table-node.model';
import { FlowModel } from '../../../../visual-programming/core/models/flow.model';
import { FlowViewport } from '../../../../visual-programming/core/models/flow-viewport.model';
import {
    AgentNodeModel,
    ClassificationDecisionTableNodeModel,
    GraphNoteModel,
    NodeModel,
    WebhookTriggerNodeModel,
} from '../../../../visual-programming/core/models/node.model';
import { SubGraphNode } from '../../../../visual-programming/core/models/subgraph-node.model';
import { GetWebhookTriggerNodeRequest } from '../../../../visual-programming/core/models/webhook-trigger';
import { FLOW_EDITOR_STATE_PROVIDERS } from '../../../../visual-programming/core/providers/flow-editor-state.providers';
import { FlowGraphComponent } from '../../../../visual-programming/flow-graph/flow-graph.component';
import { CdtExplanationStoreService } from '../../../../visual-programming/services/cdt-explanation-store.service';
import { CdtExplanationsApiService } from '../../../../visual-programming/services/cdt-explanations-api.service';
import { FlowService } from '../../../../visual-programming/services/flow.service';
import { FlowTestRunService } from '../../../../visual-programming/services/flow-test-run.service';
import { NodeAuthorshipStore } from '../../../../visual-programming/services/node-authorship.store';
import { SidePanelService } from '../../../../visual-programming/services/side-panel.service';
import { UndoRedoService } from '../../../../visual-programming/services/undo-redo.service';
import { mapGraphNoteToModel } from '../../../../visual-programming/utils/load/nodes/graph-note.mapper';
import { mapWebhookTriggerNodeToModel } from '../../../../visual-programming/utils/load/nodes/webhook-trigger-node.mapper';
import { livePython, liveTask } from '../../../../visual-programming/utils/testing/live-graph.fixture';
import {
    extractParentNotUpdatedMessage,
    FlowVisualProgrammingComponent,
    REMOTE_SAVE_RELOAD_FAILED_MESSAGE,
    RUN_WHILE_SAVING_MESSAGE,
    TEST_RUN_NODE_GONE_MESSAGE,
    TEST_RUN_PAYLOAD_REJECTED_MESSAGE,
} from './flow-visual-programming.component';

/** Past the page's private 1.5 s explanation-save debounce. */
const NODE_AUTOSAVE_WAIT_MS = 2000;
const CAPTURED_VIEWPORT: FlowViewport = { position: { x: 120, y: -40 }, scale: 0.75 };
const VERSION_A: GraphVersionDto = { id: 11, graph_id: 1, name: 'Version A', description: '', created_at: '' };
const VERSION_B: GraphVersionDto = { id: 12, graph_id: 1, name: 'Version B', description: '', created_at: '' };
/** The authorship the backend renders on a node nobody has edited since it was created. */
const UNEDITED_NODE = {
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
};

function graphDto(overrides: Partial<GraphDto> = {}): GraphDto {
    return { id: 1, uuid: 'graph-uuid', name: 'Flow', description: '', save_version: 1, ...overrides } as GraphDto;
}

const RESTORED_GRAPH = graphDto({
    save_version: 2,
    graph_note_list: [
        {
            id: 99,
            created_at: '2026-01-01T00:00:00Z',
            node_name: 'Restored note',
            graph: 1,
            content: 'restored',
            metadata: {},
            created_by: null,
            last_edited_by: null,
            last_edited_at: null,
        },
    ],
});

@Component({
    selector: 'app-flow-graph',
    template: '',
    providers: [{ provide: FlowGraphComponent, useExisting: forwardRef(() => FlowGraphStubComponent) }],
})
class FlowGraphStubComponent {
    static instances: FlowGraphStubComponent[] = [];

    readonly flowState = input<FlowModel>();
    readonly currentFlowId = input<number>();
    readonly availableFlows = input<GetGraphLightRequest[]>([]);
    readonly flowName = input<string>();
    readonly initialNodeId = input<string | null>(null);
    readonly initialNodeExpand = input(true);
    readonly initialViewport = input<FlowViewport | null>(null);
    readonly isSaving = input(false);
    readonly hasUnsavedChanges = input(false);
    readonly save = output<FlowModel>();
    readonly openShortcuts = output<DOMRect>();
    readonly requestReload = output<void>();
    readonly importComplete = output<void>();

    commitSidePanelToFlow = vi.fn((): boolean => true);
    captureViewport = vi.fn((): FlowViewport | null => CAPTURED_VIEWPORT);
    emitSave = vi.fn();
    closeNodesSearch = vi.fn();
    openNodePanel = vi.fn();

    constructor() {
        FlowGraphStubComponent.instances.push(this);
    }
}

/** Stands in for the real wrapper: its own editor services, filled with a "snapshot" flow. */
@Component({
    selector: 'app-flow-version-preview',
    template: '',
    providers: [...FLOW_EDITOR_STATE_PROVIDERS],
})
class FlowVersionPreviewStubComponent {
    readonly version = input.required<GraphVersionDto>();
    readonly flowsLight = input<unknown[]>([]);
    readonly closed = output<void>();
    readonly openShortcuts = output<DOMRect>();

    constructor() {
        inject(FlowService).setFlow({
            nodes: [{ id: 'snapshot-node', node_name: 'Snapshot node' } as FlowModel['nodes'][number]],
            connections: [],
        });
    }
}

@Component({ selector: 'app-flow-header', template: '' })
class FlowHeaderStubComponent {
    readonly graphName = input<string>();
    readonly graphId = input<number>();
    readonly isAssistantOpen = input(false);
    readonly graph = input<GraphDto>();
    readonly isSaving = input(false);
    readonly isRunning = input(false);
    readonly isPreviewMode = input(false);
    readonly runStatus = input<unknown>(null);
    readonly hasUnsavedChanges = input(false);
    readonly editors = input<unknown[]>([]);
    readonly save = output<void>();
    readonly saveVersion = output<void>();
    readonly viewVersionHistory = output<void>();
    readonly viewSessions = output<void>();
    readonly run = output<void>();
    readonly getCurl = output<void>();
    readonly toggleAssistant = output<void>();
    readonly flowEdited = output<GraphDto>();
}

@Component({ selector: 'app-shortcuts-modal', template: '' })
class ShortcutsModalStubComponent {
    readonly open = input(false);
    readonly pos = input<unknown>(null);
    readonly title = input('');
    readonly icon = input<string | null>(null);
    readonly sections = input<unknown[]>([]);
    readonly flows = input<readonly GetGraphLightRequest[]>([]);
    readonly currentFlowId = input<number | null>(null);
    readonly closed = output<void>();
}

@Component({
    selector: 'app-version-history-panel',
    template: '',
    providers: [{ provide: VersionHistoryPanelComponent, useExisting: forwardRef(() => VersionHistoryStubComponent) }],
})
class VersionHistoryStubComponent {
    readonly graphId = input<number>();
    readonly graphSaveVersion = input<number | undefined>();
    readonly hasUnsavedChanges = input(false);
    readonly selectedVersionId = input<number | null>(null);
    readonly previewedVersionId = input<number | null>(null);
    readonly closed = output<void>();
    readonly restoreRequested = output<GraphVersionDto>();
    readonly previewRequested = output<GraphVersionDto>();
    readonly versionDeleted = output<GraphVersionDto>();
    readonly versionUpdated = output<GraphVersionDto>();
    loadVersions = vi.fn();
}

describe('FlowVisualProgrammingComponent', () => {
    let fixture: ComponentFixture<FlowVisualProgrammingComponent>;
    let component: FlowVisualProgrammingComponent;
    let flowService: FlowService;
    let flowsApi: Record<string, ReturnType<typeof vi.fn>>;
    let unsavedChangesDialog: { confirm: ReturnType<typeof vi.fn>; confirmUnsavedChanges: ReturnType<typeof vi.fn> };
    let toast: Record<string, ReturnType<typeof vi.fn>>;
    let paramMap$: BehaviorSubject<ReturnType<typeof convertToParamMap>>;
    /** A signal, so FlowReadOnlyService's computed re-reads it when a test revokes Flows:Update. */
    let canUpdateFlows: WritableSignal<boolean>;
    let runGraph: Record<string, ReturnType<typeof vi.fn>>;
    let runSessionSse: { stopStream: ReturnType<typeof vi.fn>; startStream: ReturnType<typeof vi.fn> };
    let isStreaming: ReturnType<typeof signal<boolean>>;
    let sessionStatus: ReturnType<typeof signal<GraphSessionStatus>>;
    let explanationsApi: { saveExplanations: ReturnType<typeof vi.fn> };
    let flowsStorage: { deleteFlow: ReturnType<typeof vi.fn> };

    beforeEach(() => {
        explanationsApi = { saveExplanations: vi.fn() };
        FlowGraphStubComponent.instances = [];
        canUpdateFlows = signal(true);
        flowsApi = {
            getGraphById: vi.fn().mockReturnValue(of(graphDto())),
            getGraphsLight: vi.fn().mockReturnValue(of([])),
            bulkSaveGraph: vi.fn().mockReturnValue(of(graphDto({ save_version: 2 }))),
            restoreGraphVersion: vi.fn().mockReturnValue(of({ restored: true, graph_id: 1, warnings: [] })),
            saveGraphVersion: vi.fn(),
            patchGraph: vi.fn(),
            getSubflowUsage: vi.fn(),
        };
        flowsStorage = { deleteFlow: vi.fn().mockReturnValue(of(undefined)) };
        unsavedChangesDialog = { confirm: vi.fn(), confirmUnsavedChanges: vi.fn() };
        toast = { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() };
        runGraph = { runGraph: vi.fn(), runTestSession: vi.fn() };
        runSessionSse = { stopStream: vi.fn(), startStream: vi.fn() };
        isStreaming = signal(false);
        sessionStatus = signal(GraphSessionStatus.RUNNING);
        const paramMap = convertToParamMap({ id: '1' });
        paramMap$ = new BehaviorSubject(paramMap);
        const queryParamMap = convertToParamMap({});

        TestBed.configureTestingModule({
            imports: [FlowVisualProgrammingComponent],
            providers: [
                {
                    provide: ActivatedRoute,
                    useValue: {
                        paramMap: paramMap$,
                        queryParamMap: of(queryParamMap),
                        snapshot: { paramMap, queryParamMap },
                    },
                },
                { provide: Router, useValue: { navigate: vi.fn() } },
                { provide: FlowsApiService, useValue: flowsApi },
                { provide: FlowsStorageService, useValue: flowsStorage },
                { provide: ToastService, useValue: toast },
                { provide: RunGraphService, useValue: runGraph },
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
                { provide: UnsavedChangesDialogService, useValue: unsavedChangesDialog },
                { provide: CreateGraphWarningsService, useValue: { readPending: () => [] } },
                {
                    provide: RunSessionSSEService,
                    useValue: { ...runSessionSse, isStreaming, status: sessionStatus },
                },
                {
                    provide: PermissionsService,
                    useValue: { can: () => canUpdateFlows(), canAny: () => true, canEditSecrets: () => false },
                },
                { provide: LlmConfigStorageService, useValue: { getAllConfigs: () => of([]) } },
                { provide: AgentDefinitionsApiService, useValue: { refreshDefinitions: () => of([]) } },
                { provide: UnsavedChangesRegistry, useValue: { register: vi.fn(), unregister: vi.fn() } },
                {
                    provide: GraphCollaborationWsService,
                    useValue: {
                        editors: signal([]),
                        graphSaved$: new Subject(),
                        connect: vi.fn(),
                        disconnect: vi.fn(),
                    },
                },
                {
                    provide: ProfileService,
                    useValue: {
                        currentUserSignal: signal(null),
                        shortcutSettings: signal({ custom: [] }),
                    },
                },
                { provide: FlowAssistantService, useValue: { isOpen: signal(false), toggle: vi.fn() } },
                { provide: CdtExplanationsApiService, useValue: explanationsApi },
            ],
        });
        TestBed.overrideComponent(PythonNodePanelComponent, { set: { template: '', imports: [] } });
        TestBed.overrideComponent(NodePanelShellComponent, { add: { providers: [NodeAuthorshipStore] } });
        TestBed.overrideComponent(FlowVisualProgrammingComponent, {
            set: {
                imports: [
                    AppSvgIconComponent,
                    SpinnerComponent,
                    MatTooltipModule,
                    FlowHeaderStubComponent,
                    FlowGraphStubComponent,
                    FlowVersionPreviewStubComponent,
                    ShortcutsModalStubComponent,
                    VersionHistoryStubComponent,
                ],
            },
        });

        fixture = TestBed.createComponent(FlowVisualProgrammingComponent);
        component = fixture.componentInstance;
        flowService = TestBed.inject(FlowService);
        fixture.detectChanges();
    });

    function liveCanvas(): FlowGraphStubComponent | undefined {
        const element = fixture.nativeElement.querySelector('app-flow-graph');
        return element ? FlowGraphStubComponent.instances.at(-1) : undefined;
    }

    function pressCtrlS(target: EventTarget = window): KeyboardEvent {
        const event = new KeyboardEvent('keydown', {
            code: 'KeyS',
            key: 's',
            ctrlKey: true,
            bubbles: true,
            cancelable: true,
        });
        target.dispatchEvent(event);
        return event;
    }

    function flowSaveRequestsAcrossAllCanvases(): number {
        return FlowGraphStubComponent.instances.reduce((count, canvas) => count + canvas.emitSave.mock.calls.length, 0);
    }

    function makeLiveFlowDirty(): void {
        const flow = flowService.getFlowState();
        flowService.setFlow({
            ...flow,
            nodes: flow.nodes.map((node) => ({ ...node, position: { x: 4242, y: 0 } })),
        });
    }

    describe('version preview', () => {
        function preview(): HTMLElement | null {
            return fixture.nativeElement.querySelector('app-flow-version-preview');
        }

        function enterPreview(version: GraphVersionDto = VERSION_A): void {
            component.onVersionPreviewRequested(version);
            fixture.detectChanges();
        }

        it('does not make the flow dirty when entering and exiting a preview', () => {
            const dirtyBefore = component.hasUnsavedChangesSignal();
            const flowBefore = structuredClone(flowService.getFlowState());

            enterPreview();
            expect(preview()).not.toBeNull();
            expect(liveCanvas()).toBeUndefined();
            component.onPreviewExit();
            fixture.detectChanges();

            expect(component.hasUnsavedChangesSignal()).toBe(dirtyBefore);
            expect(flowService.getFlowState()).toEqual(flowBefore);
        });

        it('hands the viewport captured on entry back to the live canvas on a plain exit', () => {
            const firstCanvas = liveCanvas()!;

            enterPreview(VERSION_A);
            enterPreview(VERSION_B);
            component.onPreviewExit();
            fixture.detectChanges();

            expect(firstCanvas.captureViewport).toHaveBeenCalledTimes(1);
            expect(liveCanvas()).not.toBe(firstCanvas);
            expect(liveCanvas()!.initialViewport()).toEqual(CAPTURED_VIEWPORT);
        });

        it.each(['save', 'dont-save'] as const)(
            'restoring from the preview via "%s" shows the restored graph with a normal fit',
            (dialogResult) => {
                const restoredGraph$ = new Subject<GraphDto>();
                enterPreview();
                flowsApi['getGraphById'].mockReturnValue(restoredGraph$);
                unsavedChangesDialog.confirm.mockReturnValue(of(dialogResult));

                component.onVersionRestoreRequested(VERSION_A);
                fixture.detectChanges();

                expect(flowsApi['restoreGraphVersion']).toHaveBeenCalledWith(VERSION_A.id, dialogResult === 'save', 1);
                expect(liveCanvas()).toBeUndefined();

                restoredGraph$.next(RESTORED_GRAPH);
                restoredGraph$.complete();
                fixture.detectChanges();

                const canvas = liveCanvas()!;
                expect(component.previewedVersion()).toBeNull();
                expect(component.selectedVersionId()).toBeNull();
                expect(component.isVersionHistoryOpen()).toBe(false);
                expect(canvas.initialViewport()).toBeNull();
                expect(canvas.flowState()!.nodes.some((node) => node.backendId === 99)).toBe(true);
            }
        );

        it('opens the shortcuts modal from the preview canvas', () => {
            enterPreview();
            const previewStub = fixture.debugElement.query(By.directive(FlowVersionPreviewStubComponent))
                .componentInstance as FlowVersionPreviewStubComponent;

            previewStub.openShortcuts.emit(new DOMRect(10, 20, 30, 40));

            expect(component.isShortcutsOpen()).toBe(true);
            expect(component.shortcutsPos()).toEqual({ top: 20, left: 48 });
        });

        it.each([
            ['moves it up so its bottom stays on screen', 900, 218],
            ['pins it to the top margin in a window shorter than the modal', 500, 16],
        ])('when the shortcuts button is low, %s', (_case, windowHeight, expectedTop) => {
            vi.stubGlobal('innerHeight', windowHeight);
            try {
                component.openShortcutsModal(new DOMRect(10, 700, 30, 40));

                expect(component.shortcutsPos()).toEqual({ top: expectedTop, left: 48 });
            } finally {
                vi.unstubAllGlobals();
            }
        });

        it('keeps the preview open while the restore dialog is shown and after Cancel', () => {
            const dialogResult$ = new Subject<string>();
            enterPreview(VERSION_A);
            unsavedChangesDialog.confirm.mockReturnValue(dialogResult$);

            component.onVersionRestoreRequested(VERSION_A);
            fixture.detectChanges();
            expect(component.previewedVersion()).toEqual(VERSION_A);

            dialogResult$.next('cancel');
            dialogResult$.complete();
            fixture.detectChanges();

            expect(component.previewedVersion()).toEqual(VERSION_A);
            expect(preview()).not.toBeNull();
            expect(flowsApi['restoreGraphVersion']).not.toHaveBeenCalled();
        });

        // F-08 (version deleted in another tab), R-08 (stale save_version), R-10 (server error).
        it.each([404, 409, 500])('reports a failed restore (%i) and reloads nothing', (httpStatus) => {
            enterPreview(VERSION_A);
            const graphLoadsBefore = flowsApi['getGraphById'].mock.calls.length;
            flowsApi['restoreGraphVersion'].mockReturnValue(
                throwError(() => new HttpErrorResponse({ status: httpStatus }))
            );
            unsavedChangesDialog.confirm.mockReturnValue(of('dont-save'));

            component.onVersionRestoreRequested(VERSION_A);
            fixture.detectChanges();

            expect(toast['error']).toHaveBeenCalledWith('Failed to restore version');
            expect(toast['success']).not.toHaveBeenCalled();
            expect(flowsApi['getGraphById'].mock.calls.length).toBe(graphLoadsBefore);
            expect(component.isCanvasReloading()).toBe(false);
            expect(liveCanvas()).toBeDefined();
        });

        // F-09 / F-10: someone else saved or restored the flow while this tab was previewing.
        it('warns about a concurrent change when saving the live flow after a preview', () => {
            makeLiveFlowDirty();
            enterPreview();
            component.onPreviewExit();
            fixture.detectChanges();
            flowsApi['bulkSaveGraph'].mockReturnValue(throwError(() => new HttpErrorResponse({ status: 409 })));

            component.onGraphSave(flowService.getFlowState());

            expect(toast['warning']).toHaveBeenCalledWith(expect.stringContaining('modified by another user'));
            const payload = JSON.stringify(flowsApi['bulkSaveGraph'].mock.calls[0][1]);
            expect(payload).not.toContain('snapshot-node');
            expect(component.hasUnsavedChangesSignal()).toBe(true);
        });

        it('drops a restore warning once its node is deleted, and keeps warnings not tied to a node', () => {
            flowService.setFlow({ nodes: [], connections: [] });
            component.onGraphSave(flowService.getFlowState());
            const restoredNote = RESTORED_GRAPH.graph_note_list![0];
            flowsApi['getGraphById'].mockReturnValue(of(RESTORED_GRAPH));
            unsavedChangesDialog.confirm.mockReturnValue(of('dont-save'));
            flowsApi['restoreGraphVersion'].mockReturnValue(
                of({
                    restored: true,
                    graph_id: 1,
                    warnings: [
                        { type: 'fk_nulled', node_id: restoredNote.id, reason: 'Subflow was deleted' },
                        { type: 'edge_dropped', reason: 'Edge to a removed node' },
                    ],
                })
            );
            component.onVersionRestoreRequested(VERSION_A);
            fixture.detectChanges();
            expect(component.activeRestoreWarnings()).toHaveLength(2);

            const restoredFlow = flowService.getFlowState();
            flowService.setFlow({
                ...restoredFlow,
                nodes: restoredFlow.nodes.filter((node) => node.backendId !== restoredNote.id),
            });

            expect(component.activeRestoreWarnings().map((warning) => warning.type)).toEqual(['edge_dropped']);
        });

        it('does not carry restore warnings over to the next flow that is opened', () => {
            component.restoreWarnings.set([{ type: 'edge_dropped', reason: 'Edge to a removed node' }]);

            paramMap$.next(convertToParamMap({ id: '2' }));
            fixture.detectChanges();

            expect(component.restoreWarnings()).toEqual([]);
        });

        it('saves only the live flow when leaving the page while previewing', () => {
            makeLiveFlowDirty();
            enterPreview();
            unsavedChangesDialog.confirmUnsavedChanges.mockImplementation((onSave: () => Observable<boolean>) => {
                onSave().subscribe();
                return of('save');
            });

            const result = component.canDeactivate();
            (result as Observable<boolean>).subscribe();

            expect(flowsApi['bulkSaveGraph']).toHaveBeenCalledTimes(1);
            const payload = JSON.stringify(flowsApi['bulkSaveGraph'].mock.calls[0][1]);
            expect(payload).toContain('"x":4242');
            expect(payload).not.toContain('snapshot-node');
        });

        it('tells the user to exit the preview instead of saving on Ctrl+S', () => {
            makeLiveFlowDirty();
            enterPreview();

            const event = pressCtrlS();

            expect(event.defaultPrevented).toBe(true);
            expect(toast['info']).toHaveBeenCalledWith('Exit preview mode to save');
            expect(flowSaveRequestsAcrossAllCanvases()).toBe(0);
            expect(flowsApi['bulkSaveGraph']).not.toHaveBeenCalled();
        });

        it('does not enter the preview when the open node panel cannot be committed', () => {
            liveCanvas()!.commitSidePanelToFlow.mockReturnValue(false);

            enterPreview();

            expect(component.previewedVersion()).toBeNull();
            expect(component.selectedVersionId()).toBeNull();
            expect(preview()).toBeNull();
            expect(liveCanvas()).toBeDefined();
            expect(toast['warning']).toHaveBeenCalled();
        });

        it('clears the selection and leaves the preview when the previewed version is deleted, but not for another version', () => {
            enterPreview(VERSION_A);

            component.onVersionDeleted(VERSION_B);
            expect(component.previewedVersion()).toEqual(VERSION_A);
            expect(component.selectedVersionId()).toBe(VERSION_A.id);

            component.onVersionDeleted(VERSION_A);
            fixture.detectChanges();
            expect(component.previewedVersion()).toBeNull();
            expect(component.selectedVersionId()).toBeNull();
            expect(liveCanvas()).toBeDefined();
        });

        it('shows the new name of the previewed version after a rename, and ignores other versions', () => {
            enterPreview(VERSION_A);

            component.onVersionUpdated({ ...VERSION_B, name: 'Other renamed' });
            expect(component.previewedVersion()?.name).toBe(VERSION_A.name);

            component.onVersionUpdated({ ...VERSION_A, name: 'Renamed' });
            expect(component.previewedVersion()?.name).toBe('Renamed');
            expect(component.previewedVersion()?.id).toBe(VERSION_A.id);
        });

        it('leaves the preview when the version history panel is closed', () => {
            enterPreview();

            component.onVersionHistoryClosed();
            fixture.detectChanges();

            expect(component.previewedVersion()).toBeNull();
            expect(liveCanvas()).toBeDefined();
        });

        it('offers "Continue" when saving a version of a flow with unsaved changes', () => {
            makeLiveFlowDirty();
            unsavedChangesDialog.confirm.mockReturnValue(of('cancel'));

            component.onSaveVersion();

            expect(unsavedChangesDialog.confirm).toHaveBeenCalledWith(
                expect.objectContaining({ dontSaveText: 'Continue' })
            );
        });
    });

    describe('shortcuts list', () => {
        it('hands the shortcuts list every flow the user can see and which one is being edited', () => {
            flowsApi['getGraphsLight'].mockReturnValue(
                of([
                    { id: 1, uuid: 'graph-uuid', name: 'Flow', description: '' },
                    { id: 12, uuid: 'uuid-12', name: 'Billing', description: '' },
                    { id: 34, uuid: 'uuid-34', name: 'Support', description: '' },
                ])
            );

            component.refreshCurrentFlow();
            fixture.detectChanges();

            const shortcutsModal = fixture.debugElement.query(By.directive(ShortcutsModalStubComponent))
                .componentInstance as ShortcutsModalStubComponent;
            expect(shortcutsModal.flows().map((flow) => flow.name)).toEqual(['Flow', 'Billing', 'Support']);
            expect(shortcutsModal.currentFlowId()).toBe(1);
        });
    });

    describe('Ctrl+S', () => {
        const READ_ONLY_MESSAGE = 'You have read-only access to this flow.';

        const pythonNode = {
            id: 'python-1',
            backendId: livePython.id,
            type: NodeType.PYTHON,
            node_name: 'Python-Node (#1)',
            python_code_id: 12,
            data: { code: 'def main(): pass', entrypoint: 'main', libraries: [], secret_ids: [], secret_names: [] },
            test_input: {},
            position: { x: 0, y: 0 },
            ports: null,
            color: '',
            icon: '',
            size: { width: 200, height: 100 },
            input_map: {},
            output_variable_path: null,
        } as unknown as NodeModel;

        async function openNodePanel(): Promise<NodeModel[]> {
            flowService.setFlow({ nodes: [pythonNode], connections: [] });
            TestBed.inject(SidePanelService).setSelectedNodeId(pythonNode.id);
            const panelFixture = TestBed.createComponent(NodePanelShellComponent);
            panelFixture.componentRef.setInput('node', pythonNode);
            panelFixture.detectChanges();
            await new Promise((resolve) => setTimeout(resolve, 0));
            panelFixture.detectChanges();
            const panelSaves: NodeModel[] = [];
            panelFixture.componentInstance.save.subscribe((node) => panelSaves.push(node));
            return panelSaves;
        }

        it('saves the flow', () => {
            const event = pressCtrlS();

            expect(event.defaultPrevented).toBe(true);
            expect(flowSaveRequestsAcrossAllCanvases()).toBe(1);
        });

        it('saves the flow even while typing in a text field', () => {
            const field = document.body.appendChild(document.createElement('input'));

            pressCtrlS(field);
            field.remove();

            expect(flowSaveRequestsAcrossAllCanvases()).toBe(1);
        });

        it('says why and saves nothing in a read-only flow', () => {
            canUpdateFlows.set(false);

            pressCtrlS();

            expect(toast['info']).toHaveBeenCalledWith(READ_ONLY_MESSAGE);
            expect(flowSaveRequestsAcrossAllCanvases()).toBe(0);
        });

        it('saves both the open node panel and the flow', async () => {
            const panelSaves = await openNodePanel();

            pressCtrlS();

            expect(panelSaves.map((node) => node.id)).toEqual([pythonNode.id]);
            expect(flowSaveRequestsAcrossAllCanvases()).toBe(1);
        });
    });

    describe('test run from a trigger node', () => {
        const savedWebhook: GetWebhookTriggerNodeRequest = {
            id: 21,
            graph: 1,
            node_name: 'Webhook Trigger #1',
            python_code: { id: 5, libraries: [], code: 'def main(trigger_payload): pass', entrypoint: 'main' },
            input_map: {},
            output_variable_path: null,
            webhook_trigger_path: '',
            metadata: {},
            webhook_trigger: null,
            test_payload: {},
            use_storage: false,
            created_at: '2026-01-01T00:00:00Z',
            created_by: null,
            last_edited_by: null,
            last_edited_at: null,
        };
        let testRun: FlowTestRunService;
        let webhookNode: WebhookTriggerNodeModel;

        beforeEach(() => {
            testRun = TestBed.inject(FlowTestRunService);
            // Added since the last save: its backend id only exists once the run has saved the flow.
            webhookNode = { ...mapWebhookTriggerNodeToModel(savedWebhook), backendId: null };
            flowService.setFlow({ ...flowService.getFlowState(), nodes: [webhookNode] });
            flowsApi['bulkSaveGraph'].mockReturnValue(
                of(graphDto({ save_version: 2, webhook_trigger_node_list: [savedWebhook] }))
            );
        });

        function rejectWith(status: number, error: unknown): void {
            runGraph['runTestSession'].mockReturnValue(throwError(() => new HttpErrorResponse({ status, error })));
        }

        it('saves the flow, then starts the run at the saved node with the shown payload', () => {
            runGraph['runTestSession'].mockReturnValue(of({ session_id: 7 }));

            testRun.request('webhook-trigger', webhookNode.id, { id: '104' });

            expect(liveCanvas()!.commitSidePanelToFlow).toHaveBeenCalled();
            expect(flowsApi['bulkSaveGraph']).toHaveBeenCalledTimes(1);
            expect(runGraph['runTestSession']).toHaveBeenCalledWith({
                graph_id: 1,
                node_type: 'webhook-trigger',
                node_id: 21,
                payload: { id: '104' },
            });
            expect(runSessionSse.startStream).toHaveBeenCalledWith('7');
            expect(component.isPanelOpen()).toBe(true);
            expect(toast['success']).toHaveBeenCalledWith('Test run started');
            expect(component.isRunning()).toBe(false);
        });

        it('locks both run buttons while the run starts', () => {
            const response$ = new Subject<{ session_id: number }>();
            runGraph['runTestSession'].mockReturnValue(response$);

            testRun.request('webhook-trigger', webhookNode.id, {});

            expect(component.isRunning()).toBe(true);
            expect(testRun.runningNodeId()).toBe(webhookNode.id);
            component.handleRunFlow();
            expect(runGraph['runGraph']).not.toHaveBeenCalled();

            response$.next({ session_id: 8 });
            response$.complete();
            expect(component.isRunning()).toBe(false);
            expect(testRun.runningNodeId()).toBeNull();
        });

        it('shows the payload errors of a 400 under the editor of the open node instead of a toast', () => {
            TestBed.inject(SidePanelService).setSelectedNodeId(webhookNode.id);
            rejectWith(400, {
                status_code: 400,
                code: 'test_run_payload_invalid',
                message: 'Invalid payload',
                errors: ["'edited_message': not a field parent selected on this node"],
            });

            testRun.request('webhook-trigger', webhookNode.id, { edited_message: {} });

            expect(testRun.serverErrors().get(webhookNode.id)).toEqual([
                "'edited_message': not a field parent selected on this node",
            ]);
            expect(toast['error']).not.toHaveBeenCalled();
        });

        it('also toasts a 400 when the side panel does not show that node', () => {
            TestBed.inject(SidePanelService).setSelectedNodeId('another-node');
            rejectWith(400, { errors: ["'edited_message': not a field parent selected on this node"] });

            testRun.request('webhook-trigger', webhookNode.id, { edited_message: {} });

            expect(toast['error']).toHaveBeenCalledWith(TEST_RUN_PAYLOAD_REJECTED_MESSAGE);
            expect(testRun.serverErrors().get(webhookNode.id)).toEqual([
                "'edited_message': not a field parent selected on this node",
            ]);
        });

        it('drops the errors of the previous run when a new test run starts', () => {
            testRun.setServerErrors(webhookNode.id, ['stale']);
            runGraph['runTestSession'].mockReturnValue(new Subject());

            testRun.request('webhook-trigger', webhookNode.id, {});

            expect(testRun.serverErrors().has(webhookNode.id)).toBe(false);
        });

        it('starts no run when the save fails', () => {
            flowsApi['bulkSaveGraph'].mockReturnValue(
                throwError(() => new HttpErrorResponse({ status: 500, error: { message: 'Boom' } }))
            );

            testRun.request('webhook-trigger', webhookNode.id, {});

            expect(flowsApi['bulkSaveGraph']).toHaveBeenCalledTimes(1);
            expect(runGraph['runTestSession']).not.toHaveBeenCalled();
            expect(component.isRunning()).toBe(false);
        });

        it('starts neither run while the flow is being saved, and says why', () => {
            flowsApi['bulkSaveGraph'].mockReturnValue(new Subject<GraphDto>());
            component.onGraphSave(flowService.getFlowState());
            expect(component.isSaving()).toBe(true);

            testRun.request('webhook-trigger', webhookNode.id, {});
            component.handleRunFlow();

            expect(toast['info']).toHaveBeenCalledTimes(2);
            expect(toast['info']).toHaveBeenCalledWith(RUN_WHILE_SAVING_MESSAGE);
            expect(liveCanvas()!.commitSidePanelToFlow).not.toHaveBeenCalled();
            expect(runGraph['runTestSession']).not.toHaveBeenCalled();
            expect(runGraph['runGraph']).not.toHaveBeenCalled();
            expect(component.isRunning()).toBe(false);
        });

        it('clears the test payload errors when another flow loads', () => {
            testRun.setServerErrors(webhookNode.id, ['from flow 1']);

            paramMap$.next(convertToParamMap({ id: '2' }));
            fixture.detectChanges();

            expect(testRun.serverErrors().size).toBe(0);
        });

        it('shows the message of another 400 under the editor', () => {
            rejectWith(400, {
                status_code: 400,
                code: 'invalid',
                message: 'payload: Test payload must be a JSON object.',
            });

            testRun.request('webhook-trigger', webhookNode.id, {});

            expect(testRun.serverErrors().get(webhookNode.id)).toEqual([
                'payload: Test payload must be a JSON object.',
            ]);
        });

        it.each([
            [404, TEST_RUN_NODE_GONE_MESSAGE],
            [403, "You don't have permission to run tests on this flow."],
            [500, 'Failed to start test run: Boom'],
        ])('reports a %i as a toast', (httpStatus, message) => {
            rejectWith(httpStatus, { message: 'Boom' });

            testRun.request('webhook-trigger', webhookNode.id, {});

            expect(toast['error']).toHaveBeenCalledWith(message);
            expect(testRun.serverErrors().size).toBe(0);
        });

        it('does not start a run for a node removed before the save finished', () => {
            testRun.request('webhook-trigger', 'removed-node', {});

            expect(runGraph['runTestSession']).not.toHaveBeenCalled();
            expect(toast['error']).toHaveBeenCalledWith(TEST_RUN_NODE_GONE_MESSAGE);
        });

        it('shows the status of the streaming run in the header until it ends', () => {
            const header = (): FlowHeaderStubComponent =>
                fixture.debugElement.query(By.directive(FlowHeaderStubComponent)).componentInstance;

            isStreaming.set(true);
            fixture.detectChanges();
            expect(header().runStatus()).toBe(GraphSessionStatus.RUNNING);

            sessionStatus.set(GraphSessionStatus.ENDED);
            fixture.detectChanges();
            expect(header().runStatus()).toBeNull();
        });
    });

    describe('stored graph for the editor', () => {
        const STORED_PYTHON_CODE = { id: 55, code: 'def main(**kwargs): pass', entrypoint: 'main', libraries: [] };

        function loadFlowWithWebhookNode(graphId: number): void {
            flowsApi['getGraphById'].mockReturnValue(
                of(
                    graphDto({
                        id: graphId,
                        webhook_trigger_node_list: [
                            {
                                id: 21,
                                graph: graphId,
                                node_name: 'Webhook Trigger #1',
                                python_code: STORED_PYTHON_CODE,
                                input_map: {},
                                output_variable_path: null,
                                webhook_trigger_path: '',
                                metadata: {},
                                webhook_trigger: null,
                                test_payload: {},
                                use_storage: false,
                                created_at: '2026-01-01T00:00:00Z',
                                created_by: null,
                                last_edited_by: null,
                                last_edited_at: null,
                            },
                        ],
                    })
                )
            );
            paramMap$.next(convertToParamMap({ id: String(graphId) }));
            fixture.detectChanges();
        }

        function remoteSave(): void {
            TestBed.inject(GraphCollaborationWsService).graphSaved$.next({
                type: 'graph_saved',
                graph_id: 2,
                new_save_version: 3,
                saved_by: { user_id: 7, display_name: 'Another user' },
                saved_at: '',
            });
        }

        it('gives the editor the stored webhook code and its id of the loaded flow, until the page goes away', () => {
            loadFlowWithWebhookNode(2);

            expect(flowService.savedWebhookTriggerNode(21)?.python_code).toEqual(STORED_PYTHON_CODE);

            fixture.destroy();

            expect(flowService.hasSavedGraph()).toBe(false);
            expect(flowService.savedWebhookTriggerNode(21)).toBeNull();
        });

        it('drops it when another user saves a flow with unsaved edits, until the graph is loaded again', () => {
            loadFlowWithWebhookNode(2);
            // A clean flow would take the save over right away; unsaved edits keep the outdated graph.
            makeLiveFlowDirty();

            remoteSave();
            fixture.detectChanges();

            expect(flowService.hasSavedGraph()).toBe(false);
            expect(flowService.savedWebhookTriggerNode(21)).toBeNull();

            loadFlowWithWebhookNode(3);

            expect(flowService.savedWebhookTriggerNode(21)?.python_code).toEqual(STORED_PYTHON_CODE);
        });
    });

    describe('when another user saves the flow', () => {
        const REMOTE_GRAPH = graphDto({
            save_version: 2,
            graph_note_list: [
                {
                    id: 77,
                    created_at: '2026-01-01T00:00:00Z',
                    node_name: 'Remote note',
                    graph: 1,
                    content: 'remote',
                    metadata: {},
                    created_by: null,
                    last_edited_by: null,
                    last_edited_at: null,
                },
            ],
        });
        let undoRedo: UndoRedoService;

        beforeEach(() => {
            undoRedo = TestBed.inject(UndoRedoService);
            flowsApi['getGraphById'].mockClear();
            flowsApi['getGraphById'].mockReturnValue(of(REMOTE_GRAPH));
        });

        function remoteSave(): void {
            TestBed.inject(GraphCollaborationWsService).graphSaved$.next({
                type: 'graph_saved',
                graph_id: 1,
                new_save_version: 2,
                saved_by: { user_id: 7, display_name: 'Another user' },
                saved_at: '',
            });
            fixture.detectChanges();
        }

        function showsRemoteSave(): boolean {
            return flowService.getFlowState().nodes.some((node) => node.backendId === 77);
        }

        it('loads the save into a clean editor and drops the undo history from before it', () => {
            undoRedo.setUndoStack([flowService.getFlowState()]);

            remoteSave();

            expect(flowsApi['getGraphById']).toHaveBeenCalledWith(1, true);
            expect(showsRemoteSave()).toBe(true);
            expect(component.versionHistoryGraphSaveVersion()).toBe(2);
            expect(component.hasUnsavedChangesSignal()).toBe(false);
            expect(undoRedo.canUndo()).toBe(false);
        });

        it('keeps the old save_version while the flow has unsaved edits, so the next save is rejected', () => {
            makeLiveFlowDirty();

            remoteSave();

            expect(flowsApi['getGraphById']).not.toHaveBeenCalled();
            expect(flowService.hasSavedGraph()).toBe(false);
            component.onGraphSave(flowService.getFlowState());
            expect(flowsApi['bulkSaveGraph'].mock.calls[0][1].save_version).toBe(1);
        });

        it('waits until the open node panel closes, since its edits are not in the flow yet', () => {
            const sidePanel = TestBed.inject(SidePanelService);
            sidePanel.setSelectedNodeId('open-node');

            remoteSave();
            expect(flowsApi['getGraphById']).not.toHaveBeenCalled();

            sidePanel.clearSelection();
            fixture.detectChanges();
            expect(showsRemoteSave()).toBe(true);
        });

        it('waits until the version preview closes', () => {
            component.onVersionPreviewRequested(VERSION_A);
            fixture.detectChanges();

            remoteSave();
            expect(flowsApi['getGraphById']).not.toHaveBeenCalled();

            component.onPreviewExit();
            fixture.detectChanges();
            expect(showsRemoteSave()).toBe(true);
        });

        it('discards the loaded save when the flow was edited while it loaded', () => {
            const remoteGraph$ = new Subject<GraphDto>();
            flowsApi['getGraphById'].mockReturnValue(remoteGraph$);
            remoteSave();

            makeLiveFlowDirty();
            remoteGraph$.next(REMOTE_GRAPH);
            remoteGraph$.complete();
            fixture.detectChanges();

            expect(showsRemoteSave()).toBe(false);
            expect(component.hasUnsavedChangesSignal()).toBe(true);
            expect(component.versionHistoryGraphSaveVersion()).toBe(1);
        });

        it.each([
            ['the request fails', () => throwError(() => new HttpErrorResponse({ status: 500 }))],
            ['the backend returns a graph older than the save', () => of(graphDto())],
        ])('warns and keeps the old save_version when %s', (_case, response) => {
            flowsApi['getGraphById'].mockReturnValue(response());

            remoteSave();

            expect(toast['warning']).toHaveBeenCalledWith(REMOTE_SAVE_RELOAD_FAILED_MESSAGE);
            expect(component.versionHistoryGraphSaveVersion()).toBe(1);
        });
    });

    describe('node authorship for the details dialog', () => {
        const grace = { id: 9, display_name: 'Grace Hopper', avatar_url: null };
        const pythonGraph = graphDto({ python_node_list: [livePython] });
        let nextRouteId = 100;

        // The page's own store, which the live canvas's side panel reads.
        const pageStore = (): NodeAuthorshipStore => fixture.debugElement.injector.get(NodeAuthorshipStore);
        const livePythonNode = () => flowService.getFlowState().nodes.find((node) => node.type === NodeType.PYTHON)!;

        function openFlow(graph: GraphDto): void {
            flowsApi['getGraphById'].mockReturnValue(of(graph));
            paramMap$.next(convertToParamMap({ id: String(nextRouteId++) }));
            fixture.detectChanges();
        }

        function enterPreview(): void {
            component.onVersionPreviewRequested(VERSION_A);
            fixture.detectChanges();
        }

        it('shows the author of a node as the loaded graph lists it', () => {
            openFlow(pythonGraph);

            expect(pageStore().authorshipOf(livePythonNode())).toEqual({
                created_by: livePython.created_by,
                created_at: livePython.created_at,
                last_edited_by: livePython.last_edited_by,
                last_edited_at: livePython.last_edited_at,
            });
        });

        it('shows the fresh last editor after a flow save, from the save response', () => {
            openFlow(pythonGraph);
            const node = livePythonNode();
            flowService.setFlow({ nodes: [{ ...node, position: { x: 500, y: 0 } }], connections: [] });
            flowsApi['bulkSaveGraph'].mockReturnValue(
                of(
                    graphDto({
                        save_version: 2,
                        python_node_list: [
                            { ...livePython, last_edited_by: grace, last_edited_at: '2026-10-06T10:00:00Z' },
                        ],
                    })
                )
            );

            component.onGraphSave(flowService.getFlowState());

            expect(pageStore().authorshipOf(livePythonNode())).toEqual(
                expect.objectContaining({ last_edited_by: grace, last_edited_at: '2026-10-06T10:00:00Z' })
            );
        });

        it('shows the fresh last editor after a single-node save from the side panel', () => {
            openFlow(pythonGraph);
            flowsApi['bulkSaveGraph'].mockReturnValue(
                of(graphDto({ save_version: 2, python_node_list: [{ ...livePython, last_edited_by: grace }] }))
            );

            TestBed.inject(SidePanelService).requestSaveNode({ ...livePythonNode(), node_name: 'Renamed' });

            expect(pageStore().authorshipOf(livePythonNode()).last_edited_by).toEqual(grace);
        });

        it("gives a node re-created by undo after its deletion was saved the new row's authorship", () => {
            openFlow(pythonGraph);
            const deletedNode = livePythonNode();
            flowsApi['bulkSaveGraph'].mockReturnValue(of(graphDto({ save_version: 2, python_node_list: [] })));
            flowService.setFlow({ nodes: [], connections: [] });
            component.onGraphSave(flowService.getFlowState());

            // Undo brings the node back with the id of the row the save deleted.
            flowService.setFlow({ nodes: [deletedNode], connections: [] });
            const recreatedRow = {
                ...livePython,
                id: 40,
                created_by: grace,
                created_at: '2026-10-06T11:00:00Z',
                last_edited_by: grace,
                last_edited_at: '2026-10-06T11:00:00Z',
            };
            flowsApi['bulkSaveGraph'].mockReturnValue(
                of(graphDto({ save_version: 3, python_node_list: [recreatedRow] }))
            );
            component.onGraphSave(flowService.getFlowState());

            const recreatedNode = livePythonNode();
            expect(recreatedNode.backendId).toBe(40);
            expect(pageStore().authorshipOf(recreatedNode)).toEqual({
                created_by: grace,
                created_at: '2026-10-06T11:00:00Z',
                last_edited_by: grace,
                last_edited_at: '2026-10-06T11:00:00Z',
            });
            expect(pageStore().authorshipOf({ type: NodeType.PYTHON, backendId: livePython.id })).toEqual(
                expect.objectContaining({ created_by: null, last_edited_by: null })
            );
        });

        it('shows the fresh last editor after a partial import, which reloads the whole graph', () => {
            openFlow(pythonGraph);
            flowsApi['getGraphById'].mockReturnValue(
                of(graphDto({ python_node_list: [{ ...livePython, last_edited_by: grace }] }))
            );

            component.handlePartialImportComplete();

            expect(
                pageStore().authorshipOf({ type: NodeType.PYTHON, backendId: livePython.id }).last_edited_by
            ).toEqual(grace);
        });

        it('takes the rename response as the whole graph: fresh rows win, nodes it no longer lists are dropped', () => {
            openFlow(graphDto({ python_node_list: [livePython], task_node_list: [liveTask] }));
            expect(pageStore().authorshipOf({ type: NodeType.TASK, backendId: liveTask.id }).created_by).toEqual(
                liveTask.created_by
            );

            component.onFlowEdited(
                graphDto({
                    name: 'Renamed',
                    python_node_list: [{ ...livePython, last_edited_by: grace }],
                    task_node_list: [],
                })
            );

            expect(
                pageStore().authorshipOf({ type: NodeType.PYTHON, backendId: livePython.id }).last_edited_by
            ).toEqual(grace);
            expect(pageStore().authorshipOf({ type: NodeType.TASK, backendId: liveTask.id })).toEqual({
                created_by: null,
                created_at: null,
                last_edited_by: null,
                last_edited_at: null,
            });
        });

        it('gives the version preview its own store, which the live graph never fills', () => {
            openFlow(pythonGraph);
            enterPreview();

            const previewStore = fixture.debugElement
                .query(By.directive(FlowVersionPreviewStubComponent))
                .injector.get(NodeAuthorshipStore);

            expect(previewStore).not.toBe(pageStore());
            expect(previewStore.authorshipOf({ type: NodeType.PYTHON, backendId: livePython.id })).toEqual({
                created_by: null,
                created_at: null,
                last_edited_by: null,
                last_edited_at: null,
            });
        });
    });

    describe('single-node save', () => {
        const READ_ONLY_MESSAGE = 'You have read-only access to this flow.';
        let sidePanelService: SidePanelService;
        let note: GraphNoteModel;

        beforeEach(() => {
            sidePanelService = TestBed.inject(SidePanelService);
            note = mapGraphNoteToModel(RESTORED_GRAPH.graph_note_list![0]);
            flowService.setFlow({ nodes: [note], connections: [] });
        });

        afterEach(() => vi.useRealTimers());

        it('saves the node when the editor may change the flow', () => {
            sidePanelService.requestSaveNode(note);

            expect(flowsApi['bulkSaveGraph']).toHaveBeenCalledTimes(1);
            expect(sidePanelService.savingNodeId()).toBeNull();
            expect(toast['success']).toHaveBeenCalledWith('Node saved');
        });

        it('sends nothing for a requested save in a read-only editor, says why and clears the saving state', () => {
            canUpdateFlows.set(false);
            const updateNode = vi.spyOn(flowService, 'updateNode');

            sidePanelService.requestSaveNode(note);

            expect(flowsApi['bulkSaveGraph']).not.toHaveBeenCalled();
            expect(updateNode).not.toHaveBeenCalled();
            expect(sidePanelService.savingNodeId()).toBeNull();
            expect(toast['info']).toHaveBeenCalledWith(READ_ONLY_MESSAGE);
        });

        describe('queued behind a full save', () => {
            const SAVED_NOTE = RESTORED_GRAPH.graph_note_list![0];
            let fullSave: Subject<GraphDto>;
            let unsavedNote: GraphNoteModel;

            beforeEach(() => {
                // Added since the last save: the full save below is what creates it on the server.
                unsavedNote = { ...note, backendId: null };
                flowService.setFlow({ nodes: [unsavedNote], connections: [] });
                fullSave = new Subject<GraphDto>();
                flowsApi['bulkSaveGraph']
                    .mockReturnValueOnce(fullSave)
                    .mockReturnValueOnce(of(graphDto({ save_version: 3, graph_note_list: [SAVED_NOTE] })));
                component.onGraphSave(flowService.getFlowState());
            });

            function answerFullSave(): void {
                fullSave.next(graphDto({ save_version: 2, graph_note_list: [SAVED_NOTE] }));
                fullSave.complete();
            }

            it('sends a node the full save created as an update with its new id, never a second create', () => {
                sidePanelService.requestSaveNode({ ...unsavedNote, node_name: 'Renamed note' });
                expect(flowsApi['bulkSaveGraph']).toHaveBeenCalledTimes(1);

                answerFullSave();

                expect(flowsApi['bulkSaveGraph']).toHaveBeenCalledTimes(2);
                const payload = flowsApi['bulkSaveGraph'].mock.calls[1][1] as Record<string, unknown>;
                expect(payload).toEqual(expect.objectContaining({ save_version: 2 }));
                expect(payload['graph_note_list']).toEqual([
                    expect.objectContaining({ id: SAVED_NOTE.id, node_name: 'Renamed note' }),
                ]);
                expect(JSON.stringify(payload)).not.toContain('temp_id');
                expect(flowService.nodes()[0].backendId).toBe(SAVED_NOTE.id);
            });

            it('sends nothing for a node deleted while its save waited, and clears the saving state', () => {
                sidePanelService.requestSaveNode({ ...unsavedNote, node_name: 'Renamed note' });
                flowService.setFlow({ nodes: [], connections: [] });

                answerFullSave();

                expect(flowsApi['bulkSaveGraph']).toHaveBeenCalledTimes(1);
                expect(sidePanelService.savingNodeId()).toBeNull();
                expect(toast['success']).not.toHaveBeenCalledWith('Node saved');
                expect(flowService.nodes()).toEqual([]);
            });

            it('puts the node on the canvas at once, then sends it as the canvas holds it, reverting no later edit', () => {
                sidePanelService.requestSaveNode({ ...unsavedNote, node_name: 'Renamed note' });
                expect(flowService.nodes()[0].node_name).toBe('Renamed note');

                // Edited again while its save waits behind the full save.
                flowService.updateNode({ ...flowService.nodes()[0], node_name: 'Renamed again' });
                answerFullSave();

                const payload = flowsApi['bulkSaveGraph'].mock.calls[1][1] as Record<string, unknown>;
                expect(payload['graph_note_list']).toEqual([
                    expect.objectContaining({ id: SAVED_NOTE.id, node_name: 'Renamed again' }),
                ]);
                expect(flowService.nodes()[0].node_name).toBe('Renamed again');
            });
        });
    });

    describe('full save of an agent node', () => {
        const SAVED_AGENT: AgentNode = {
            ...UNEDITED_NODE,
            id: 50,
            metadata: {},
            node_name: 'Agent #1',
            input_map: {},
            output_variable_path: null,
            agent_definition: 3,
            surface_list: [],
            inline_surface: null,
            tasks: [
                { id: 500, name: 'Existing', order: 0, instructions: 'Do it', output_schema: {}, context_tasks: [] },
            ],
        };

        function agent(): AgentNodeModel {
            return flowService.nodes().find((node): node is AgentNodeModel => node.backendId === SAVED_AGENT.id)!;
        }

        function setTasks(tasks: AgentNodeTaskUi[]): void {
            flowService.updateNode({ ...agent(), data: { ...agent().data, tasks } });
        }

        function newTask(tempId: string): AgentNodeTaskUi {
            return { tempId, name: tempId, instructions: `Run ${tempId}`, output_schema: {}, contextRefs: [] };
        }

        it('hands the ids the save assigned to the right tasks, even after a task was inserted while it was in flight', () => {
            flowsApi['getGraphById'].mockReturnValue(of(graphDto({ agent_node_list: [SAVED_AGENT] })));
            component.refreshCurrentFlow();
            const [existing] = agent().data.tasks;
            setTasks([existing, newTask('added')]);
            const fullSave = new Subject<GraphDto>();
            flowsApi['bulkSaveGraph'].mockReturnValue(fullSave);
            component.onGraphSave(flowService.getFlowState());

            setTasks([newTask('inserted'), ...agent().data.tasks]);
            fullSave.next(
                graphDto({
                    save_version: 2,
                    agent_node_list: [
                        {
                            ...SAVED_AGENT,
                            tasks: [
                                ...SAVED_AGENT.tasks,
                                {
                                    id: 501,
                                    name: 'added',
                                    order: 1,
                                    instructions: 'Run added',
                                    output_schema: {},
                                    context_tasks: [],
                                },
                            ],
                        },
                    ],
                })
            );
            fullSave.complete();

            expect(agent().data.tasks.map(({ tempId, id }) => ({ tempId, id }))).toEqual([
                { tempId: 'inserted', id: undefined },
                { tempId: existing.tempId, id: 500 },
                { tempId: 'added', id: 501 },
            ]);
        });
    });

    // Nested here for the shared TestBed setup; nothing below involves a preview.
    describe('save queue and explanation saves', () => {
        const SPAM = { text: 'Bins spam', fingerprint: 'f-spam', generatedBy: 'gpt-4o-mini' };
        const SPAM_AGAIN = { text: 'Bins spam, take two', fingerprint: 'f-spam', generatedBy: 'gpt-4o-mini' };
        const REFUND = { text: 'Routes refunds', fingerprint: 'f-refund', generatedBy: 'gpt-4o-mini' };

        let sidePanelService: SidePanelService;
        let store: CdtExplanationStoreService;

        function cdtDto(id: number, name: string, routeCode: string): GetClassificationDecisionTableNodeRequest {
            return {
                ...UNEDITED_NODE,
                id,
                graph: 1,
                node_name: name,
                pre_python_code: null,
                pre_input_map: {},
                pre_output_variable_path: null,
                pre_use_storage: false,
                post_python_code: null,
                post_input_map: {},
                post_output_variable_path: null,
                post_use_storage: false,
                prompt_configs: [],
                default_llm_config: null,
                default_next_node_id: null,
                next_error_node_id: null,
                condition_groups: [
                    {
                        id: id * 10,
                        classification_decision_table_node: id,
                        group_name: name,
                        order: 1,
                        expression: 'score > 0.9',
                        prompt: null,
                        manipulation: null,
                        continue_flag: false,
                        route_code: routeCode,
                        dock_visible: true,
                        field_expressions: {},
                        field_manipulations: {},
                    },
                ],
                metadata: { position: { x: 0, y: 0 } },
            };
        }

        const CDT_GRAPH = graphDto({
            save_version: 1,
            classification_decision_table_node_list: [cdtDto(21, 'Triage', 'spam'), cdtDto(22, 'Refunds', 'refund')],
        });

        beforeEach(() => {
            localStorage.clear();
            sidePanelService = TestBed.inject(SidePanelService);
            store = TestBed.inject(CdtExplanationStoreService);
            flowsApi['getGraphById'].mockReturnValue(of(CDT_GRAPH));
            component.refreshCurrentFlow();
            vi.useFakeTimers();
        });

        afterEach(() => {
            vi.useRealTimers();
            localStorage.clear();
        });

        function table(backendId: number): ClassificationDecisionTableNodeModel {
            const node = flowService.nodes().find((candidate) => candidate.backendId === backendId);
            if (node?.type !== NodeType.CLASSIFICATION_TABLE) throw new Error(`no table ${backendId}`);
            return node;
        }

        /** What the decision-tree dialog does when an explanation arrives. */
        function explain(backendId: number, stepKey: string, explanation: CdtExplanation): void {
            const node = table(backendId);
            store
                .forNode({
                    nodeId: node.id,
                    backendId,
                    retainedStepKeys: new Set(['rule:route:spam', 'rule:route:refund']),
                })
                .set(stepKey, explanation);
        }

        /** An unsaved grid edit: the rule's expression changed in the panel. */
        function editExpression(backendId: number, expression: string): void {
            const node = table(backendId);
            const rows = node.data.table.condition_groups.map((row) => ({ ...row, expression }));
            flowService.updateNode({
                ...node,
                data: { ...node.data, table: { ...node.data.table, condition_groups: rows } },
            });
        }

        function waitOutDebounce(): void {
            vi.advanceTimersByTime(NODE_AUTOSAVE_WAIT_MS);
        }

        it('persists only the explanations, never unsaved table edits on the same node', () => {
            explanationsApi.saveExplanations.mockReturnValue(
                of({ explanations: { 'rule:route:spam': SPAM }, save_version: 2 })
            );
            editExpression(21, 'score > 0.5');

            explain(21, 'rule:route:spam', SPAM);
            waitOutDebounce();

            expect(flowsApi['bulkSaveGraph']).not.toHaveBeenCalled();
            expect(explanationsApi.saveExplanations).toHaveBeenCalledExactlyOnceWith(21, {
                save_version: 1,
                explanations: { 'rule:route:spam': SPAM },
            });
            // The edit is still on the canvas, and still unsaved.
            expect(table(21).data.table.condition_groups[0].expression).toBe('score > 0.5');
            expect(component.hasUnsavedChanges()).toBe(true);
        });

        it('leaves the canvas clean when the explanations were the only change', () => {
            explanationsApi.saveExplanations.mockReturnValue(
                of({ explanations: { 'rule:route:spam': SPAM }, save_version: 2 })
            );

            explain(21, 'rule:route:spam', SPAM);
            expect(component.hasUnsavedChanges()).toBe(true);
            waitOutDebounce();

            expect(component.hasUnsavedChanges()).toBe(false);
            expect(component.versionHistoryGraphSaveVersion()).toBe(2);
        });

        it('collapses a burst on one table into one request carrying the latest explanation', () => {
            explanationsApi.saveExplanations.mockReturnValue(of({ explanations: {}, save_version: 2 }));

            explain(21, 'rule:route:spam', SPAM);
            vi.advanceTimersByTime(500);
            explain(21, 'rule:route:spam', SPAM_AGAIN);
            waitOutDebounce();

            expect(explanationsApi.saveExplanations).toHaveBeenCalledExactlyOnceWith(21, {
                save_version: 1,
                explanations: { 'rule:route:spam': SPAM_AGAIN },
            });
        });

        it('does not let one table swallow another table’s request', () => {
            explanationsApi.saveExplanations
                .mockReturnValueOnce(of({ explanations: {}, save_version: 2 }))
                .mockReturnValueOnce(of({ explanations: {}, save_version: 3 }));

            explain(21, 'rule:route:spam', SPAM);
            vi.advanceTimersByTime(500);
            explain(22, 'rule:route:refund', REFUND);
            waitOutDebounce();

            expect(explanationsApi.saveExplanations.mock.calls.map(([nodeId]) => nodeId)).toEqual([21, 22]);
        });

        it('sends the next save only once the previous one answered, with the save_version it returned', () => {
            const first = new Subject<{ explanations: CdtExplanations; save_version: number }>();
            explanationsApi.saveExplanations
                .mockReturnValueOnce(first)
                .mockReturnValueOnce(of({ explanations: {}, save_version: 3 }));

            explain(21, 'rule:route:spam', SPAM);
            explain(22, 'rule:route:refund', REFUND);
            waitOutDebounce();
            expect(explanationsApi.saveExplanations).toHaveBeenCalledTimes(1);

            first.next({ explanations: { 'rule:route:spam': SPAM }, save_version: 2 });
            first.complete();

            expect(explanationsApi.saveExplanations).toHaveBeenCalledTimes(2);
            expect(explanationsApi.saveExplanations.mock.calls[1]).toEqual([
                22,
                { save_version: 2, explanations: { 'rule:route:refund': REFUND } },
            ]);
        });

        it('holds a full save until an in-flight explanation save answers, then sends its save_version', () => {
            const explanationSave = new Subject<{ explanations: CdtExplanations; save_version: number }>();
            explanationsApi.saveExplanations.mockReturnValue(explanationSave);
            explain(21, 'rule:route:spam', SPAM);
            waitOutDebounce();

            component.onGraphSave(flowService.getFlowState());
            expect(flowsApi['bulkSaveGraph']).not.toHaveBeenCalled();
            expect(component.isSaving()).toBe(true);

            explanationSave.next({ explanations: { 'rule:route:spam': SPAM }, save_version: 2 });
            explanationSave.complete();

            expect(flowsApi['bulkSaveGraph']).toHaveBeenCalledTimes(1);
            expect(flowsApi['bulkSaveGraph'].mock.calls[0][1]).toEqual(expect.objectContaining({ save_version: 2 }));
            expect(toast['warning']).not.toHaveBeenCalled();
        });

        it('skips a pending explanation save that a full save already carried', () => {
            flowsApi['bulkSaveGraph'].mockReturnValue(of({ ...CDT_GRAPH, save_version: 2 }));
            explain(21, 'rule:route:spam', SPAM);

            component.onGraphSave(flowService.getFlowState());
            waitOutDebounce();

            expect(flowsApi['bulkSaveGraph']).toHaveBeenCalledTimes(1);
            expect(explanationsApi.saveExplanations).not.toHaveBeenCalled();
            expect(component.hasUnsavedChanges()).toBe(false);
        });

        it('sends an explanation that arrived during a full save after it, with the new save_version', () => {
            const fullSave = new Subject<GraphDto>();
            flowsApi['bulkSaveGraph'].mockReturnValue(fullSave);
            explanationsApi.saveExplanations.mockReturnValue(
                of({ explanations: { 'rule:route:spam': SPAM }, save_version: 3 })
            );

            component.onGraphSave(flowService.getFlowState());
            explain(21, 'rule:route:spam', SPAM);
            waitOutDebounce();
            expect(explanationsApi.saveExplanations).not.toHaveBeenCalled();

            fullSave.next({ ...CDT_GRAPH, save_version: 2 });
            fullSave.complete();

            // The full save did not carry it, and did not wipe it off the canvas either.
            expect(table(21).explanations).toEqual({ 'rule:route:spam': SPAM });
            expect(explanationsApi.saveExplanations).toHaveBeenCalledExactlyOnceWith(21, {
                save_version: 2,
                explanations: { 'rule:route:spam': SPAM },
            });
            expect(component.hasUnsavedChanges()).toBe(false);
        });

        it('fails silently and keeps the canvas dirty for the next full save', () => {
            explanationsApi.saveExplanations.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 409 })));

            explain(21, 'rule:route:spam', SPAM);
            waitOutDebounce();

            expect(explanationsApi.saveExplanations).toHaveBeenCalledTimes(1);
            expect(toast['warning']).not.toHaveBeenCalled();
            expect(toast['error']).not.toHaveBeenCalled();
            expect(component.hasUnsavedChanges()).toBe(true);
            expect(component.versionHistoryGraphSaveVersion()).toBe(1);
        });

        it('sends nothing for a read-only editor', () => {
            canUpdateFlows.set(false);
            const node = table(21);
            flowService.updateNode({ ...node, explanations: { 'rule:route:spam': SPAM } });

            sidePanelService.requestCdtExplanationsSave(node.id);
            waitOutDebounce();

            expect(explanationsApi.saveExplanations).not.toHaveBeenCalled();
        });

        function deleteTable(backendId: number): void {
            const deleted = table(backendId);
            flowService.setFlow({
                ...flowService.getFlowState(),
                nodes: flowService.nodes().filter((node) => node.id !== deleted.id),
            });
        }

        it('skips the save of a table deleted before its turn came', () => {
            explanationsApi.saveExplanations.mockReturnValue(of({ explanations: {}, save_version: 2 }));
            explain(21, 'rule:route:spam', SPAM);

            deleteTable(21);
            waitOutDebounce();

            expect(explanationsApi.saveExplanations).not.toHaveBeenCalled();
        });

        it('skips the save of a table deleted while its save waited in the queue, never sending a copy', () => {
            const fullSave = new Subject<GraphDto>();
            flowsApi['bulkSaveGraph'].mockReturnValue(fullSave);
            explanationsApi.saveExplanations.mockReturnValue(of({ explanations: {}, save_version: 3 }));
            component.onGraphSave(flowService.getFlowState());

            explain(21, 'rule:route:spam', SPAM);
            waitOutDebounce();
            deleteTable(21);
            fullSave.next({ ...CDT_GRAPH, save_version: 2 });
            fullSave.complete();

            expect(explanationsApi.saveExplanations).not.toHaveBeenCalled();
        });

        function announceOtherUsersSave(saveVersion: number): void {
            TestBed.inject(GraphCollaborationWsService).graphSaved$.next({
                type: 'graph_saved',
                graph_id: 1,
                new_save_version: saveVersion,
                saved_by: { user_id: 7, display_name: 'Another user' },
                saved_at: '',
            });
        }

        it('sends the version it loaded once another user has saved, so the server refuses instead of overwriting', () => {
            explanationsApi.saveExplanations.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 409 })));
            announceOtherUsersSave(3);
            expect(flowService.hasSavedGraph()).toBe(false);

            explain(21, 'rule:route:spam', SPAM);
            waitOutDebounce();

            expect(explanationsApi.saveExplanations).toHaveBeenCalledWith(
                21,
                expect.objectContaining({ save_version: 1 })
            );
            expect(component.versionHistoryGraphSaveVersion()).toBe(1);
            expect(component.hasUnsavedChanges()).toBe(true);
        });

        it('keeps the graph outdated when another user saved while its own save was in flight', () => {
            const explanationSave = new Subject<{ explanations: CdtExplanations; save_version: number }>();
            explanationsApi.saveExplanations.mockReturnValue(explanationSave);
            explain(21, 'rule:route:spam', SPAM);
            waitOutDebounce();

            announceOtherUsersSave(3);
            explanationSave.next({ explanations: { 'rule:route:spam': SPAM }, save_version: 2 });
            explanationSave.complete();

            expect(component.versionHistoryGraphSaveVersion()).toBe(2);
            // Its node lists still lack what the other user saved.
            expect(flowService.hasSavedGraph()).toBe(false);
        });

        describe('every other graph write waits its turn too', () => {
            let explanationSave: Subject<{ explanations: CdtExplanations; save_version: number }>;

            /** An explanation save that has been sent and not answered yet. */
            function explanationSaveInFlight(): void {
                explanationSave = new Subject();
                explanationsApi.saveExplanations.mockReturnValueOnce(explanationSave);
                explain(21, 'rule:route:spam', SPAM);
                waitOutDebounce();
                expect(explanationsApi.saveExplanations).toHaveBeenCalledTimes(1);
            }

            function answerExplanationSave(): void {
                explanationSave.next({ explanations: { 'rule:route:spam': SPAM }, save_version: 2 });
                explanationSave.complete();
            }

            it('sends a version restore once the save before it answered, with the version it returned', () => {
                unsavedChangesDialog.confirm.mockReturnValue(of('dont-save'));
                explanationSaveInFlight();

                component.onVersionRestoreRequested(VERSION_A);
                expect(flowsApi['restoreGraphVersion']).not.toHaveBeenCalled();

                answerExplanationSave();

                expect(flowsApi['restoreGraphVersion']).toHaveBeenCalledExactlyOnceWith(VERSION_A.id, false, 2);
            });
        });

        // `flows/:id` reuses the page: a write queued for one flow must neither be sent for, nor
        // land on, the next one.
        describe('another flow loads while a write waits or is in flight', () => {
            const OTHER_GRAPH = graphDto({
                id: 2,
                save_version: 7,
                classification_decision_table_node_list: [cdtDto(31, 'Other', 'other')],
            });
            let explanationSave: Subject<{ explanations: CdtExplanations; save_version: number }>;

            function openOtherFlow(): void {
                flowsApi['getGraphById'].mockReturnValue(of(OTHER_GRAPH));
                paramMap$.next(convertToParamMap({ id: '2' }));
                fixture.detectChanges();
            }

            function otherFlowIsShownUntouched(): void {
                const backendIds = flowService.nodes().map((node) => node.backendId);
                expect(component.versionHistoryGraphSaveVersion()).toBe(OTHER_GRAPH.save_version);
                expect(backendIds).toContain(31);
                expect(backendIds).not.toContain(21);
            }

            function explanationSaveInFlight(): void {
                explanationSave = new Subject();
                explanationsApi.saveExplanations.mockReturnValueOnce(explanationSave);
                explain(21, 'rule:route:spam', SPAM);
                waitOutDebounce();
            }

            function answerExplanationSave(): void {
                explanationSave.next({ explanations: { 'rule:route:spam': SPAM }, save_version: 2 });
                explanationSave.complete();
            }

            it('drops a full save queued for the flow that was shown, and ignores the answer before it', () => {
                explanationSaveInFlight();
                component.onGraphSave(flowService.getFlowState());
                expect(component.isSaving()).toBe(true);

                openOtherFlow();
                answerExplanationSave();

                expect(flowsApi['bulkSaveGraph']).not.toHaveBeenCalled();
                expect(component.isSaving()).toBe(false);
                otherFlowIsShownUntouched();
            });

            it('ignores the answer to a full save sent for the flow that was shown', () => {
                const fullSave = new Subject<GraphDto>();
                flowsApi['bulkSaveGraph'].mockReturnValue(fullSave);
                component.onGraphSave(flowService.getFlowState());

                openOtherFlow();
                fullSave.next({ ...CDT_GRAPH, save_version: 2 });
                fullSave.complete();

                otherFlowIsShownUntouched();
                expect(component.isSaving()).toBe(false);
                expect(toast['success']).not.toHaveBeenCalledWith('Graph saved successfully');
            });

            it('drops an explanation save queued for the flow that was shown', () => {
                const fullSave = new Subject<GraphDto>();
                flowsApi['bulkSaveGraph'].mockReturnValue(fullSave);
                component.onGraphSave(flowService.getFlowState());
                explain(21, 'rule:route:spam', SPAM);
                waitOutDebounce();

                openOtherFlow();
                fullSave.next({ ...CDT_GRAPH, save_version: 2 });
                fullSave.complete();

                expect(explanationsApi.saveExplanations).not.toHaveBeenCalled();
                otherFlowIsShownUntouched();
            });

            it('drops a version restore queued for the flow that was shown', () => {
                unsavedChangesDialog.confirm.mockReturnValue(of('dont-save'));
                explanationSaveInFlight();
                component.onVersionRestoreRequested(VERSION_A);

                openOtherFlow();
                answerExplanationSave();

                expect(flowsApi['restoreGraphVersion']).not.toHaveBeenCalled();
                expect(component.isSaving()).toBe(false);
                otherFlowIsShownUntouched();
            });

            it('does not load a restored version over the flow opened while it reloaded', () => {
                unsavedChangesDialog.confirm.mockReturnValue(of('dont-save'));
                const reload = new Subject<GraphDto>();
                flowsApi['getGraphById'].mockImplementation((graphId: number) =>
                    graphId === 1 ? reload : of(OTHER_GRAPH)
                );
                component.onVersionRestoreRequested(VERSION_A);
                expect(component.isCanvasReloading()).toBe(true);

                paramMap$.next(convertToParamMap({ id: '2' }));
                fixture.detectChanges();
                reload.next(RESTORED_GRAPH);
                reload.complete();

                otherFlowIsShownUntouched();
                expect(component.isCanvasReloading()).toBe(false);
                expect(component.isSaving()).toBe(false);
                expect(toast['error']).not.toHaveBeenCalled();
            });

            it('leaves the other flow’s canvas alone when it loads while an extraction saves the subflow', () => {
                const subflow = graphDto({ id: 5, uuid: 'subflow-uuid', name: 'Spam handling', save_version: 1 });
                vi.spyOn(TestBed.inject(CdkDialog), 'open').mockReturnValue({
                    closed: of(subflow),
                } as unknown as DialogRef<unknown, unknown>);
                const subflowSave = new Subject<GraphDto>();
                flowsApi['bulkSaveGraph'].mockImplementation((graphId: number) =>
                    graphId === subflow.id ? subflowSave : of({ ...CDT_GRAPH, save_version: 2 })
                );
                component.onExtractToSubflow(new Set([table(21).id]));

                openOtherFlow();
                subflowSave.next({ ...subflow, save_version: 2 });
                subflowSave.complete();

                expect(flowsApi['bulkSaveGraph'].mock.calls.map(([graphId]) => graphId)).toEqual([1, subflow.id]);
                expect(component.isSaving()).toBe(false);
                otherFlowIsShownUntouched();
                // The subflow exists now; the user is told the original flow kept its nodes.
                expect(toast['warning']).toHaveBeenCalledExactlyOnceWith(
                    extractParentNotUpdatedMessage('Spam handling')
                );
                expect(toast['success']).not.toHaveBeenCalledWith(expect.stringContaining('Extracted selection'));
            });
        });

        describe('extract to subflow', () => {
            const SUBFLOW = graphDto({ id: 5, uuid: 'subflow-uuid', name: 'Spam handling', save_version: 1 });
            let subflowSave: Subject<GraphDto>;

            beforeEach(() => {
                vi.spyOn(TestBed.inject(CdkDialog), 'open').mockReturnValue({
                    closed: of(SUBFLOW),
                } as unknown as DialogRef<unknown, unknown>);
                subflowSave = new Subject<GraphDto>();
                let parentSaves = 0;
                flowsApi['bulkSaveGraph'].mockImplementation((graphId: number) => {
                    if (graphId === SUBFLOW.id) return subflowSave;
                    parentSaves++;
                    return of(
                        parentSaves === 1
                            ? { ...CDT_GRAPH, save_version: 2 }
                            : graphDto({
                                  save_version: 3,
                                  classification_decision_table_node_list: [cdtDto(22, 'Refunds', 'refund')],
                              })
                    );
                });
            });

            function answerSubflowSave(): void {
                subflowSave.next({ ...SUBFLOW, save_version: 2 });
                subflowSave.complete();
            }

            it('saves the subflow and then the parent as one queued save', () => {
                component.onExtractToSubflow(new Set([table(21).id]));

                expect(flowsApi['bulkSaveGraph'].mock.calls.map(([graphId]) => graphId)).toEqual([1, SUBFLOW.id]);
                expect(component.isSaving()).toBe(true);
                // The parent still shows the table until the subflow has it.
                expect(table(21)).toBeDefined();

                answerSubflowSave();

                expect(flowsApi['bulkSaveGraph'].mock.calls.map(([graphId]) => graphId)).toEqual([1, SUBFLOW.id, 1]);
                expect(flowsApi['bulkSaveGraph'].mock.calls[2][1]).toEqual(
                    expect.objectContaining({ save_version: 2 })
                );
                expect(flowService.nodes().some((node) => node.backendId === 21)).toBe(false);
                expect(component.isSaving()).toBe(false);
                expect(toast['success']).toHaveBeenCalledWith('Extracted selection into subflow "Spam handling"');
            });

            it('holds an explanation save until it is done, and then sends nothing for the extracted table', () => {
                explanationsApi.saveExplanations.mockReturnValue(of({ explanations: {}, save_version: 4 }));
                component.onExtractToSubflow(new Set([table(21).id]));

                // Explained while the subflow is being saved: the table is still on the canvas.
                explain(21, 'rule:route:spam', SPAM);
                waitOutDebounce();
                expect(explanationsApi.saveExplanations).not.toHaveBeenCalled();

                answerSubflowSave();
                waitOutDebounce();

                expect(flowService.nodes().some((node) => node.backendId === 21)).toBe(false);
                expect(explanationsApi.saveExplanations).not.toHaveBeenCalled();
            });
        });

        describe('unpack a subflow', () => {
            const SUBGRAPH_NODE: SubGraphNode = {
                ...UNEDITED_NODE,
                id: 41,
                node_name: 'Inner flow',
                graph: 1,
                subgraph: 9,
                subgraph_detail: { id: 9, uuid: 'inner-uuid', name: 'Inner flow', description: '', tags: [] },
                input_map: {},
                output_variable_path: null,
                metadata: {},
            };
            const INNER_FLOW = graphDto({
                id: 9,
                name: 'Inner flow',
                classification_decision_table_node_list: [cdtDto(31, 'Inner', 'inner')],
            });

            function subgraphNodeOnCanvas(): NodeModel | undefined {
                return flowService.nodes().find((node) => node.backendId === SUBGRAPH_NODE.id);
            }

            beforeEach(() => {
                flowsApi['getGraphById'].mockReturnValue(of({ ...CDT_GRAPH, subgraph_node_list: [SUBGRAPH_NODE] }));
                component.refreshCurrentFlow();
                flowsApi['getGraphById'].mockReturnValue(of(INNER_FLOW));
                flowsApi['getSubflowUsage'].mockReturnValue(of({ parent_flow_ids: [1] }));
            });

            it('changes the canvas only once an explanation save in flight has answered, then saves with its version', () => {
                const explanationSave = new Subject<{ explanations: CdtExplanations; save_version: number }>();
                explanationsApi.saveExplanations.mockReturnValueOnce(explanationSave);
                explain(21, 'rule:route:spam', SPAM);
                waitOutDebounce();

                component.onUnpackSubflow(subgraphNodeOnCanvas()!.id);

                expect(subgraphNodeOnCanvas()).toBeDefined();
                expect(flowsApi['bulkSaveGraph']).not.toHaveBeenCalled();
                expect(component.isSaving()).toBe(true);

                explanationSave.next({ explanations: { 'rule:route:spam': SPAM }, save_version: 2 });
                explanationSave.complete();

                expect(subgraphNodeOnCanvas()).toBeUndefined();
                expect(flowService.nodes().some((node) => node.node_name === 'Inner')).toBe(true);
                expect(flowsApi['bulkSaveGraph']).toHaveBeenCalledTimes(1);
                expect(flowsApi['bulkSaveGraph'].mock.calls[0][1]).toEqual(
                    expect.objectContaining({ save_version: 2 })
                );
                expect(flowsStorage.deleteFlow).toHaveBeenCalledWith(9);
                expect(component.isSaving()).toBe(false);
            });
        });

        it('resolves a single-node save’s references to neighbours by backend id, never a temp id', () => {
            vi.useRealTimers();
            const triage = table(21);
            const refunds = table(22);
            const rows = triage.data.table.condition_groups.map((row) => ({ ...row, next_node: refunds.id }));
            const edited = {
                ...triage,
                data: { ...triage.data, table: { ...triage.data.table, condition_groups: rows } },
            };

            sidePanelService.requestSaveNode(edited);

            const payload = flowsApi['bulkSaveGraph'].mock.calls[0][1] as Record<string, Record<string, unknown>[]>;
            const [sent] = payload['classification_decision_table_node_list'];
            const [group] = sent['condition_groups'] as Record<string, unknown>[];
            expect(group['next_node_id']).toBe(22);
            expect(group).not.toHaveProperty('next_node_temp_id');
        });
    });
});
