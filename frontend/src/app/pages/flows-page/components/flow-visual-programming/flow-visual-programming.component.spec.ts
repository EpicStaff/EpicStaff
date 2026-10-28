import { Dialog as CdkDialog, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, forwardRef, inject, input, NO_ERRORS_SCHEMA, output, signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltipModule } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { ActivatedRoute, convertToParamMap, Router } from '@angular/router';
import {
    AppSvgIconComponent,
    ConfirmationDialogService,
    ConfirmationResult,
    SpinnerComponent,
    UnsavedChangesDialogService,
} from '@shared/components';
import { ActionCode, BulkDeleteResponse, GraphSessionStatus, NodeType, ResourceCode } from '@shared/models';
import { LlmConfigStorageService } from '@shared/services';
import { BehaviorSubject, Observable, of, Subject, throwError } from 'rxjs';

import { UnsavedChangesRegistry } from '../../../../core/services/unsaved-changes-registry.service';
import { AgentDefinitionsApiService } from '../../../../features/agent-definitions/services/agent-definitions-api.service';
import { FlowAssistantService } from '../../../../features/flow-assistant/flow-assistant.service';
import { FlowSessionsListComponent } from '../../../../features/flows/components/flow-sessions-dialog/flow-sessions-list.component';
import { VersionHistoryPanelComponent } from '../../../../features/flows/components/version-history-panel/version-history-panel.component';
import { GetGraphLightRequest, GraphDto, GraphVersionDto } from '../../../../features/flows/models/graph.model';
import { SnapshotWebhookTriggerNode } from '../../../../features/flows/models/graph-version-preview.model';
import { CreateGraphWarningsService } from '../../../../features/flows/services/create-graph-warnings.service';
import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import { FlowsStorageService } from '../../../../features/flows/services/flows-storage.service';
import { GraphCollaborationWsService } from '../../../../features/flows/services/graph-collaboration.ws.service';
import { RunGraphService } from '../../../../features/flows/services/run-graph-session.service';
import { FlowMessagesPanelComponent } from '../../../../pages/running-graph/components/flow-messages-panel/flow-messages-panel.component';
import { GraphMessagesComponent } from '../../../../pages/running-graph/components/graph-messages/graph-messages.component';
import { RunSessionSSEService } from '../../../../pages/running-graph/services/graph-session-sse.service';
import { PermissionRequirement, PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import {
    provideLoadedExecutionTimeoutLimits,
    TEST_EXECUTION_TIMEOUT_LIMITS,
} from '../../../../shared/services/execution-timeout-limits/execution-timeout-limits.testing';
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
    PythonNodeModel,
    ScheduleTriggerNodeModel,
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
import { ScheduleTriggerRuntimeService } from '../../../../visual-programming/services/schedule-trigger-runtime.service';
import { SidePanelService } from '../../../../visual-programming/services/side-panel.service';
import { UndoRedoService } from '../../../../visual-programming/services/undo-redo.service';
import { mapClassificationDecisionTableNodeToModel } from '../../../../visual-programming/utils/load/nodes/classification-decision-table-node.mapper';
import { mapGraphNoteToModel } from '../../../../visual-programming/utils/load/nodes/graph-note.mapper';
import { mapWebhookTriggerNodeToModel } from '../../../../visual-programming/utils/load/nodes/webhook-trigger-node.mapper';
import {
    liveAgent,
    liveClassificationTable,
    liveGraph,
    livePython,
    liveStart,
    liveTask,
} from '../../../../visual-programming/utils/testing/live-graph.fixture';
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
            uuid: '00000000-0000-4000-8000-000000000099',
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
    readonly initialViewport = input<FlowViewport | null>(null);
    readonly isSaving = input(false);
    readonly hasUnsavedChanges = input(false);
    readonly save = output<FlowModel>();
    readonly openShortcuts = output<DOMRect>();
    readonly requestReload = output<void>();

    commitSidePanelToFlow = vi.fn((): boolean => true);
    captureViewport = vi.fn((): FlowViewport | null => CAPTURED_VIEWPORT);
    emitSave = vi.fn();
    closeNodesSearch = vi.fn();
    openNodePanel = vi.fn();
    readonly isNodeMenuOpen = signal(false);

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
    readonly liveFlow = input.required<FlowModel>();
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

@Component({ selector: 'app-flow-assistant-panel', template: '' })
class FlowAssistantPanelStubComponent {}

@Component({ selector: 'app-shortcuts-modal', template: '' })
class ShortcutsModalStubComponent {
    readonly open = input(false);
    readonly pos = input<unknown>(null);
    readonly heading = input('');
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
    let queryParamMap$: BehaviorSubject<ReturnType<typeof convertToParamMap>>;
    /** A signal, so FlowReadOnlyService's computed re-reads it when a test revokes Flows:Update. */
    let canUpdateFlows: WritableSignal<boolean>;
    let runGraph: Record<string, ReturnType<typeof vi.fn>>;
    let runSessionSse: { stopStream: ReturnType<typeof vi.fn>; startStream: ReturnType<typeof vi.fn> };
    let isStreaming: ReturnType<typeof signal<boolean>>;
    let sessionStatus: ReturnType<typeof signal<GraphSessionStatus>>;
    // A signal, so FlowReadOnlyService's computed permissions follow a change made inside a test.
    let canRunFlows: WritableSignal<boolean>;
    let explanationsApi: { saveExplanations: ReturnType<typeof vi.fn> };
    let flowsStorage: { bulkDelete: ReturnType<typeof vi.fn> };

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
        flowsStorage = {
            bulkDelete: vi.fn((ids: number[]) =>
                of<BulkDeleteResponse>({
                    dry_run: false,
                    deleted_count: ids.length,
                    deleted_ids: ids,
                    deletable_ids: [],
                    not_found_ids: [],
                    skipped: [],
                    usage: {},
                })
            ),
        };
        unsavedChangesDialog = { confirm: vi.fn(), confirmUnsavedChanges: vi.fn() };
        toast = { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() };
        runGraph = { runGraph: vi.fn(), runTestSession: vi.fn() };
        runSessionSse = { stopStream: vi.fn(), startStream: vi.fn() };
        isStreaming = signal(false);
        sessionStatus = signal(GraphSessionStatus.RUNNING);
        canRunFlows = signal(true);
        const paramMap = convertToParamMap({ id: '1' });
        paramMap$ = new BehaviorSubject(paramMap);
        const queryParamMap = convertToParamMap({});
        queryParamMap$ = new BehaviorSubject(queryParamMap);

        TestBed.configureTestingModule({
            imports: [FlowVisualProgrammingComponent],
            providers: [
                provideLoadedExecutionTimeoutLimits(),
                // The sessions panel is the real one; it loads the sessions and stops one over HTTP.
                provideHttpClient(),
                provideHttpClientTesting(),
                {
                    provide: ActivatedRoute,
                    useValue: {
                        paramMap: paramMap$,
                        queryParamMap: queryParamMap$,
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
                    useValue: {
                        // Use follows its own signal; the other actions follow the update signal.
                        can: (_resource: ResourceCode, action: ActionCode) =>
                            action === ActionCode.Use ? canRunFlows() : canUpdateFlows(),
                        canAny: (_resource: ResourceCode, actions: ActionCode[]) =>
                            actions.some((action) => (action === ActionCode.Use ? canRunFlows() : canUpdateFlows())),
                        meets: (requirement: PermissionRequirement) =>
                            requirement.anyOf.some((action) =>
                                action === ActionCode.Use ? canRunFlows() : canUpdateFlows()
                            ),
                        canEditSecrets: () => false,
                    },
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
        // The message stream of a session is not what these tests look at.
        TestBed.overrideComponent(FlowMessagesPanelComponent, {
            remove: { imports: [GraphMessagesComponent] },
            add: { schemas: [NO_ERRORS_SCHEMA] },
        });
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
                    FlowAssistantPanelStubComponent,
                    FlowMessagesPanelComponent,
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

        it('gives the preview the live canvas, unsaved edits included, to compare the version with', () => {
            const savedFlow = flowService.getFlowState();
            const editedFlow = {
                ...savedFlow,
                nodes: savedFlow.nodes.map((node) => ({ ...node, node_name: 'Edited' })),
            };
            flowService.setFlow(editedFlow);

            enterPreview();

            const previewComponent = fixture.debugElement.query(By.directive(FlowVersionPreviewStubComponent))
                .componentInstance as FlowVersionPreviewStubComponent;
            expect(previewComponent.liveFlow()).toBe(editedFlow);
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

        /** As the user does it: opens the version history from the header and picks Restore on a version. */
        function requestRestore(version: GraphVersionDto): void {
            const header = fixture.debugElement.query(By.directive(FlowHeaderStubComponent))
                .componentInstance as FlowHeaderStubComponent;
            header.viewVersionHistory.emit();
            fixture.detectChanges();
            const history = fixture.debugElement.query(By.directive(VersionHistoryStubComponent))
                .componentInstance as VersionHistoryStubComponent;
            history.restoreRequested.emit(version);
            fixture.detectChanges();
        }

        describe('restoring a version with trigger nodes', () => {
            const WEBHOOK_SNAPSHOT: SnapshotWebhookTriggerNode = {
                id: 21,
                node_type: 'WebhookTriggerNode',
                node_name: 'Orders hook',
                metadata: {},
                node_number: null,
                webhook_trigger: null,
                input_map: {},
                output_variable_path: null,
                python_code: { code: 'def main(): pass', entrypoint: 'main', libraries: '' },
            };
            let previewGraphVersion: ReturnType<typeof vi.fn>;
            let confirm: ReturnType<typeof vi.spyOn>;

            beforeEach(() => {
                previewGraphVersion = vi.fn();
                flowsApi['previewGraphVersion'] = previewGraphVersion;
                confirm = vi
                    .spyOn(TestBed.inject(ConfirmationDialogService), 'confirm')
                    .mockReturnValue(of<ConfirmationResult>('close'));
                unsavedChangesDialog.confirm.mockReturnValue(of('save'));
                flowsApi['getGraphById'].mockReturnValue(of(RESTORED_GRAPH));
            });

            function versionHolding(...nodes: SnapshotWebhookTriggerNode[]): void {
                previewGraphVersion.mockReturnValue(of({ snapshot: { nodes }, warnings: [], node_authorship: {} }));
            }

            it('refuses it without Run before the backup question, keeping the preview and saving nothing', () => {
                canRunFlows.set(false);
                versionHolding(WEBHOOK_SNAPSHOT);
                enterPreview(VERSION_A);
                makeLiveFlowDirty();

                requestRestore(VERSION_A);

                expect(previewGraphVersion).toHaveBeenCalledExactlyOnceWith(VERSION_A.id);
                expect(confirm).toHaveBeenCalledExactlyOnceWith(
                    expect.objectContaining({
                        message: 'This version contains trigger nodes (Webhook, Telegram, Schedule).',
                        caution: '<strong>Restoring</strong> it requires the <strong>Use</strong> permission on flows.',
                    })
                );
                expect(unsavedChangesDialog.confirm).not.toHaveBeenCalled();
                expect(preview()).not.toBeNull();
                expect(flowsApi['bulkSaveGraph']).not.toHaveBeenCalled();
                expect(flowsApi['restoreGraphVersion']).not.toHaveBeenCalled();
                expect(toast['success']).not.toHaveBeenCalled();
                expect(toast['error']).not.toHaveBeenCalled();
                expect(toast['warning']).not.toHaveBeenCalled();
            });

            it('restores a version without trigger nodes as before for a user without Run', () => {
                canRunFlows.set(false);
                versionHolding();
                enterPreview(VERSION_A);
                unsavedChangesDialog.confirm.mockReturnValue(of('dont-save'));

                requestRestore(VERSION_A);

                expect(confirm).not.toHaveBeenCalled();
                expect(unsavedChangesDialog.confirm).toHaveBeenCalledOnce();
                expect(flowsApi['restoreGraphVersion']).toHaveBeenCalledWith(VERSION_A.id, false, 1);
                expect(preview()).toBeNull();
                expect(toast['success']).toHaveBeenCalledWith('Version restored successfully');
            });

            it('restores a version with trigger nodes for a user who can run flows', () => {
                versionHolding(WEBHOOK_SNAPSHOT);
                enterPreview(VERSION_A);
                unsavedChangesDialog.confirm.mockReturnValue(of('dont-save'));

                requestRestore(VERSION_A);

                expect(confirm).not.toHaveBeenCalled();
                expect(flowsApi['restoreGraphVersion']).toHaveBeenCalledWith(VERSION_A.id, false, 1);
                expect(preview()).toBeNull();
                expect(toast['success']).toHaveBeenCalledWith('Version restored successfully');
            });
        });

        it('explains a restore refused over trigger nodes, with no toast and nothing reloaded', () => {
            enterPreview(VERSION_A);
            const graphLoadsBefore = flowsApi['getGraphById'].mock.calls.length;
            const confirm = vi
                .spyOn(TestBed.inject(ConfirmationDialogService), 'confirm')
                .mockReturnValue(of<ConfirmationResult>('close'));
            flowsApi['restoreGraphVersion'].mockReturnValue(
                throwError(
                    () =>
                        new HttpErrorResponse({
                            status: 403,
                            error: {
                                status_code: 403,
                                code: 'flow_with_trigger_nodes_requires_use_permission',
                                message: 'This flow contains trigger nodes.',
                            },
                        })
                )
            );
            unsavedChangesDialog.confirm.mockReturnValue(of('dont-save'));

            requestRestore(VERSION_A);

            expect(confirm).toHaveBeenCalledExactlyOnceWith(
                expect.objectContaining({
                    message: 'This version contains trigger nodes (Webhook, Telegram, Schedule).',
                    caution: '<strong>Restoring</strong> it requires the <strong>Use</strong> permission on flows.',
                    hideConfirm: true,
                })
            );
            expect(toast['error']).not.toHaveBeenCalled();
            expect(toast['success']).not.toHaveBeenCalled();
            expect(toast['warning']).not.toHaveBeenCalled();
            expect(flowsApi['getGraphById'].mock.calls.length).toBe(graphLoadsBefore);
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
        it('gives the shortcuts list its heading without a native tooltip on the whole popover', () => {
            const element = fixture.debugElement.query(By.directive(ShortcutsModalStubComponent));

            expect(element.nativeElement.hasAttribute('title')).toBe(false);
            expect((element.componentInstance as ShortcutsModalStubComponent).heading()).toBe('Command & Shortcuts');
        });

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

    describe('header button shortcuts', () => {
        const START_VARIABLES = { topic: 'pricing' };
        const CTRL_ENTER: KeyboardEventInit = { code: 'Enter', key: 'Enter', ctrlKey: true };
        const ALT_S: KeyboardEventInit = { code: 'KeyS', key: 's', altKey: true };
        const ALT_C: KeyboardEventInit = { code: 'KeyC', key: 'c', altKey: true };
        const ALT_K: KeyboardEventInit = { code: 'KeyK', key: 'k', altKey: true };
        let openDialog: ReturnType<typeof vi.spyOn>;
        let confirm: ReturnType<typeof vi.spyOn>;
        let copyToClipboard: ReturnType<typeof vi.fn>;
        let isAssistantOpen: WritableSignal<boolean>;

        beforeEach(() => {
            const startNodeList = [{ ...liveStart, variables: START_VARIABLES }];
            flowsApi['getGraphById'].mockReturnValue(of(graphDto({ start_node_list: startNodeList })));
            flowsApi['bulkSaveGraph'].mockReturnValue(
                of(graphDto({ save_version: 2, start_node_list: startNodeList }))
            );
            component.refreshCurrentFlow();
            fixture.detectChanges();
            // The refresh says "Flow refreshed"; the tests look at what the keys say.
            Object.values(toast).forEach((show) => show.mockClear());
            runGraph['runGraph'].mockReturnValue(of({ session_id: 7 }));
            openDialog = vi
                .spyOn(TestBed.inject(CdkDialog), 'open')
                .mockReturnValue({ closed: of(undefined) } as unknown as DialogRef<unknown, unknown>);
            confirm = vi
                .spyOn(TestBed.inject(ConfirmationDialogService), 'confirm')
                .mockReturnValue(of<ConfirmationResult>('close'));
            copyToClipboard = vi.fn().mockResolvedValue(undefined);
            Object.defineProperty(navigator, 'clipboard', {
                value: { writeText: copyToClipboard },
                configurable: true,
            });
            // Toggles like the real service, so a test sees the chat open and close.
            const assistant = TestBed.inject(FlowAssistantService) as unknown as {
                isOpen: WritableSignal<boolean>;
                toggle: ReturnType<typeof vi.fn>;
            };
            isAssistantOpen = assistant.isOpen;
            assistant.toggle.mockImplementation(() => isAssistantOpen.update((open) => !open));
        });

        afterEach(() => {
            Reflect.deleteProperty(navigator, 'clipboard');
        });

        function press(init: KeyboardEventInit, target: EventTarget = window): KeyboardEvent {
            const event = new KeyboardEvent('keydown', { ...init, bubbles: true, cancelable: true });
            target.dispatchEvent(event);
            return event;
        }

        function header(): FlowHeaderStubComponent {
            return fixture.debugElement.query(By.directive(FlowHeaderStubComponent))
                .componentInstance as FlowHeaderStubComponent;
        }

        function enterPreview(): void {
            component.onVersionPreviewRequested(VERSION_A);
            fixture.detectChanges();
        }

        function sessionsListOpened(): boolean {
            return openDialog.mock.calls.some(
                ([dialogComponent]: unknown[]) => dialogComponent === FlowSessionsListComponent
            );
        }

        function useRefusalShown(): boolean {
            return confirm.mock.calls.some(
                ([dialog]: unknown[]) => (dialog as { title?: string }).title === 'Use permission required'
            );
        }

        it('Ctrl+Enter runs the flow with its start variables and shows the run, as the Run button does', () => {
            const event = press(CTRL_ENTER);

            expect(event.defaultPrevented).toBe(true);
            expect(runGraph['runGraph']).toHaveBeenCalledExactlyOnceWith(1, START_VARIABLES);
            expect(runSessionSse.startStream).toHaveBeenCalledWith('7');
            expect(component.isPanelCollapsed()).toBe(false);
        });

        it('Ctrl+Enter and the Run button start the same run', () => {
            header().run.emit();
            press(CTRL_ENTER);

            const [buttonRun, keyRun] = runGraph['runGraph'].mock.calls;
            expect(keyRun).toEqual(buttonRun);
        });

        it('Ctrl+Enter saves unsaved changes before the run starts', () => {
            makeLiveFlowDirty();

            press(CTRL_ENTER);

            expect(flowsApi['bulkSaveGraph']).toHaveBeenCalledTimes(1);
            expect(runGraph['runGraph']).toHaveBeenCalledTimes(1);
        });

        it('no header key fires while the node menu is open, as its backdrop covers the buttons', () => {
            liveCanvas()!.isNodeMenuOpen.set(true);

            const run = press(CTRL_ENTER);
            const sessions = press(ALT_S);

            expect(runGraph['runGraph']).not.toHaveBeenCalled();
            expect(sessionsListOpened()).toBe(false);
            expect([run.defaultPrevented, sessions.defaultPrevented]).toEqual([false, false]);
        });

        it('no header key fires before the flow has loaded, as the header is not there yet', () => {
            component.isLoaded.set(false);

            const run = press(CTRL_ENTER);
            press(ALT_K);

            expect(runGraph['runGraph']).not.toHaveBeenCalled();
            expect(copyToClipboard).not.toHaveBeenCalled();
            expect(run.defaultPrevented).toBe(false);
        });

        it('Alt+S opens the sessions list of the flow', () => {
            press(ALT_S);

            expect(openDialog).toHaveBeenCalledWith(
                FlowSessionsListComponent,
                expect.objectContaining({ data: { flow: expect.objectContaining({ id: 1 }) } })
            );
        });

        it('Alt+C opens the chat, and pressed again closes it', () => {
            press(ALT_C);
            expect(isAssistantOpen()).toBe(true);
            fixture.detectChanges();
            expect(header().isAssistantOpen()).toBe(true);

            press(ALT_C);
            expect(isAssistantOpen()).toBe(false);
        });

        it('Alt+K copies the cURL command that starts this flow', async () => {
            press(ALT_K);
            await Promise.resolve();

            const command = copyToClipboard.mock.calls[0][0] as string;
            expect(command).toContain('"graph_uuid": "graph-uuid"');
            expect(command).toContain('"topic": "pricing"');
            expect(command).toContain('/api/run-session/');
            expect(toast['success']).toHaveBeenCalledWith('cURL command copied to clipboard!');
        });

        it.each([
            ['Ctrl+Enter', CTRL_ENTER],
            ['Alt+K', ALT_K],
        ])('%s says the Use permission is required and does nothing for a user who cannot run flows', (_key, init) => {
            canRunFlows.set(false);

            press(init);

            expect(confirm).toHaveBeenCalledExactlyOnceWith(
                expect.objectContaining({ title: 'Use permission required', hideConfirm: true })
            );
            expect(runGraph['runGraph']).not.toHaveBeenCalled();
            expect(copyToClipboard).not.toHaveBeenCalled();
            expect(toast['success']).not.toHaveBeenCalled();
        });

        it('Alt+S and Alt+C need no Use permission, like their buttons', () => {
            canRunFlows.set(false);

            press(ALT_S);
            press(ALT_C);

            expect(sessionsListOpened()).toBe(true);
            expect(isAssistantOpen()).toBe(true);
            expect(useRefusalShown()).toBe(false);
        });

        it.each([
            ['Ctrl+Enter', CTRL_ENTER, 'Exit preview mode to run the flow'],
            ['Alt+S', ALT_S, 'Exit preview mode to view sessions'],
            ['Alt+K', ALT_K, 'Exit preview mode to get the cURL command'],
        ])('%s in a version preview says what the disabled button says and does nothing', (_key, init, message) => {
            enterPreview();

            press(init);

            expect(toast['info']).toHaveBeenCalledExactlyOnceWith(message);
            expect(runGraph['runGraph']).not.toHaveBeenCalled();
            expect(sessionsListOpened()).toBe(false);
            expect(copyToClipboard).not.toHaveBeenCalled();
        });

        it('Alt+C toggles the chat in a version preview too, like its button', () => {
            enterPreview();

            press(ALT_C);

            expect(isAssistantOpen()).toBe(true);
            expect(toast['info']).not.toHaveBeenCalled();
        });

        it('Ctrl+Enter starts no second run while the first one is starting', () => {
            runGraph['runGraph'].mockReturnValue(new Subject());

            press(CTRL_ENTER);
            press(CTRL_ENTER);

            expect(runGraph['runGraph']).toHaveBeenCalledTimes(1);
        });

        it('a held Ctrl+Enter starts one run', () => {
            press(CTRL_ENTER);
            press({ ...CTRL_ENTER, repeat: true });

            expect(runGraph['runGraph']).toHaveBeenCalledTimes(1);
        });

        it('Ctrl+Enter starts no run while the flow is being saved, and says why', () => {
            flowsApi['bulkSaveGraph'].mockReturnValue(new Subject<GraphDto>());
            component.onGraphSave(flowService.getFlowState());

            press(CTRL_ENTER);

            expect(toast['info']).toHaveBeenCalledExactlyOnceWith(RUN_WHILE_SAVING_MESSAGE);
            expect(runGraph['runGraph']).not.toHaveBeenCalled();
        });

        it.each([
            ['Ctrl+Enter', CTRL_ENTER],
            ['Alt+S', ALT_S],
            ['Alt+C', ALT_C],
            ['Alt+K', ALT_K],
        ])('%s does nothing while typing in a text field', (_key, init) => {
            const field = document.body.appendChild(document.createElement('input'));

            const event = press(init, field);
            field.remove();

            expect(event.defaultPrevented).toBe(false);
            expect(runGraph['runGraph']).not.toHaveBeenCalled();
            expect(sessionsListOpened()).toBe(false);
            expect(isAssistantOpen()).toBe(false);
            expect(copyToClipboard).not.toHaveBeenCalled();
        });

        it('work while focus is in the node side panel outside a text field', () => {
            const panel = document.body.appendChild(document.createElement('app-node-panel-shell'));
            const panelButton = panel.appendChild(document.createElement('button'));

            press(ALT_C, panelButton);
            press(CTRL_ENTER, panelButton);
            panel.remove();

            expect(isAssistantOpen()).toBe(true);
            expect(liveCanvas()!.commitSidePanelToFlow).toHaveBeenCalled();
            expect(runGraph['runGraph']).toHaveBeenCalledTimes(1);
        });
    });

    describe('Stop session key', () => {
        const CTRL_SHIFT_ENTER: KeyboardEventInit = { code: 'Enter', key: 'Enter', ctrlKey: true, shiftKey: true };
        const STOP_URL = '/api/sessions/7/stop/';
        let httpMock: HttpTestingController;
        let confirm: ReturnType<typeof vi.spyOn>;

        beforeEach(() => {
            httpMock = TestBed.inject(HttpTestingController);
            confirm = vi
                .spyOn(TestBed.inject(ConfirmationDialogService), 'confirm')
                .mockReturnValue(of<ConfirmationResult>('close'));
        });

        function press(init: KeyboardEventInit, target: EventTarget = window): KeyboardEvent {
            const event = new KeyboardEvent('keydown', { ...init, bubbles: true, cancelable: true });
            target.dispatchEvent(event);
            return event;
        }

        /** Opens the sessions panel as its toggle does; it selects the newest of `sessionStatuses`, ids 7, 6, … */
        function openSessionsPanel(sessionStatuses: readonly GraphSessionStatus[]): void {
            fixture.nativeElement.querySelector('.collapse-toggle').click();
            fixture.detectChanges();
            httpMock
                .expectOne((request) => request.method === 'GET' && request.url === '/api/sessions/')
                .flush({
                    count: sessionStatuses.length,
                    next: null,
                    previous: null,
                    results: sessionStatuses.map((status, index) => ({
                        id: 7 - index,
                        graph_id: 1,
                        graph_name: 'Flow',
                        status,
                        status_updated_at: '2026-01-01T00:00:00Z',
                        created_at: `2026-01-0${7 - index}T00:00:00Z`,
                        finished_at: null,
                        trigger: null,
                    })),
                });
            fixture.detectChanges();
        }

        function stopButton(): HTMLButtonElement | null {
            return fixture.nativeElement.querySelector('app-flow-messages-panel app-stop-button button');
        }

        it('Ctrl+Shift+Enter stops the selected running session, and the Stop button goes away, as after its click', () => {
            openSessionsPanel([GraphSessionStatus.RUNNING, GraphSessionStatus.ENDED]);

            const event = press(CTRL_SHIFT_ENTER);
            httpMock.expectOne({ method: 'POST', url: STOP_URL }).flush(null);
            fixture.detectChanges();

            expect(event.defaultPrevented).toBe(true);
            expect(stopButton()).toBeNull();
            expect(runGraph['runGraph']).not.toHaveBeenCalled();
            expect(confirm).not.toHaveBeenCalled();
        });

        it('Ctrl+Shift+Enter stops a session that waits for the user', () => {
            openSessionsPanel([GraphSessionStatus.WAITING_FOR_USER]);

            press(CTRL_SHIFT_ENTER);

            httpMock.expectOne({ method: 'POST', url: STOP_URL });
        });

        it.each([
            ['the sessions panel is closed', null, true],
            ['the selected session has ended', [GraphSessionStatus.ENDED], true],
            ['the selected session was stopped', [GraphSessionStatus.STOP], true],
            ['the flow has no session', [], true],
            ['the sessions panel is closed, for a user without Use', null, false],
            ['the selected session has ended, for a user without Use', [GraphSessionStatus.ENDED], false],
        ] as const)(
            'Ctrl+Shift+Enter does nothing and says nothing when %s, as there is no Stop button',
            (_case, sessionStatuses, canUse) => {
                canRunFlows.set(canUse);
                if (sessionStatuses) {
                    openSessionsPanel(sessionStatuses);
                }

                const event = press(CTRL_SHIFT_ENTER);

                expect(event.defaultPrevented).toBe(false);
                httpMock.expectNone({ method: 'POST' });
                expect(confirm).not.toHaveBeenCalled();
                expect(toast['info']).not.toHaveBeenCalled();
            }
        );

        it('Ctrl+Shift+Enter says the Use permission is required and stops nothing for a user who cannot run flows', () => {
            canRunFlows.set(false);
            openSessionsPanel([GraphSessionStatus.RUNNING]);

            press(CTRL_SHIFT_ENTER);

            expect(confirm).toHaveBeenCalledExactlyOnceWith(
                expect.objectContaining({
                    title: 'Use permission required',
                    message:
                        '<strong>Stopping</strong> a session of this flow requires the <strong>Use</strong> permission on flows.',
                    hideConfirm: true,
                })
            );
            httpMock.expectNone({ method: 'POST' });
        });

        it('Ctrl+Shift+Enter does nothing while typing in a text field', () => {
            openSessionsPanel([GraphSessionStatus.RUNNING]);
            const field = document.body.appendChild(document.createElement('input'));

            const event = press(CTRL_SHIFT_ENTER, field);
            field.remove();

            expect(event.defaultPrevented).toBe(false);
            httpMock.expectNone({ method: 'POST' });
        });

        it('Ctrl+Shift+Enter does nothing while the node menu is open, as its backdrop covers the panel', () => {
            openSessionsPanel([GraphSessionStatus.RUNNING]);
            liveCanvas()!.isNodeMenuOpen.set(true);

            press(CTRL_SHIFT_ENTER);

            httpMock.expectNone({ method: 'POST' });
        });

        it('Ctrl+Shift+Enter stops the session in a version preview too, like the Stop button', () => {
            openSessionsPanel([GraphSessionStatus.RUNNING]);
            component.onVersionPreviewRequested(VERSION_A);
            fixture.detectChanges();

            press(CTRL_SHIFT_ENTER);

            httpMock.expectOne({ method: 'POST', url: STOP_URL });
            expect(toast['info']).not.toHaveBeenCalled();
        });

        it('names the key in the Stop button tooltip', () => {
            openSessionsPanel([GraphSessionStatus.RUNNING]);

            expect(stopButton()!.getAttribute('aria-label')).toBe('Stop session (Ctrl + Shift + Enter)');
        });
    });

    describe('test run from a trigger node', () => {
        const savedWebhook: GetWebhookTriggerNodeRequest = {
            id: 21,
            uuid: '00000000-0000-4000-8000-000000000021',
            graph: 1,
            node_number: 1,
            node_name: 'Webhook Trigger #1',
            python_code: { id: 5, code: 'def main(trigger_payload): pass', entrypoint: 'main' },
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
        const STORED_PYTHON_CODE = { id: 55, code: 'def main(**kwargs): pass', entrypoint: 'main' };

        function loadFlowWithWebhookNode(graphId: number): void {
            flowsApi['getGraphById'].mockReturnValue(
                of(
                    graphDto({
                        id: graphId,
                        webhook_trigger_node_list: [
                            {
                                id: 21,
                                uuid: '00000000-0000-4000-8000-000000000021',
                                graph: graphId,
                                node_number: 1,
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
                    uuid: '00000000-0000-4000-8000-000000000077',
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

        it('names a plugin that saved the flow and never takes it for the signed-in person', () => {
            // No profile is loaded here (the current user id is undefined), the case a loose `==` would take for "me".
            TestBed.inject(GraphCollaborationWsService).graphSaved$.next({
                type: 'graph_saved',
                graph_id: 1,
                new_save_version: 2,
                saved_by: { user_id: null, display_name: 'Weather (plugin)', avatar_url: null },
                saved_at: '',
            });
            fixture.detectChanges();

            expect(toast['info']).toHaveBeenCalledWith('Graph was saved by Weather (plugin)', 4000, 'bottom-right');
            expect(showsRemoteSave()).toBe(true);
        });

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

    describe('a link to one node of the flow', () => {
        it('opens the node with that backend id, not another node with the same name', () => {
            queryParamMap$.next(convertToParamMap({ nodeId: '42' }));
            flowsApi['getGraphById'].mockReturnValue(
                of(
                    graphDto({
                        id: 5,
                        python_node_list: [
                            { ...livePython, id: 41, node_number: 1, node_name: 'Fetch' },
                            { ...livePython, id: 42, node_number: 2, node_name: 'Fetch' },
                        ],
                    })
                )
            );
            paramMap$.next(convertToParamMap({ id: '5' }));
            fixture.detectChanges();

            const linkedNode = flowService.getFlowState().nodes.find((node) => node.backendId === 42)!;
            expect(liveCanvas()!.initialNodeId()).toBe(linkedNode.id);
        });
    });

    describe('save blocked by an invalid node', () => {
        let nextRouteId = 300;

        function openFlow(graph: GraphDto): void {
            flowsApi['getGraphById'].mockReturnValue(of(graph));
            paramMap$.next(convertToParamMap({ id: String(nextRouteId++) }));
            fixture.detectChanges();
        }

        function saveAndReadToast(): string {
            component.onGraphSave(flowService.getFlowState());
            expect(flowsApi['bulkSaveGraph']).not.toHaveBeenCalled();
            return toast['error'].mock.calls.at(-1)![0] as string;
        }

        it('names a nameless task by its badge number, like the badge on the canvas', () => {
            openFlow(graphDto({ task_node_list: [{ ...liveTask, node_name: '  ', node_number: 8 }] }));

            expect(saveAndReadToast()).toContain('"Untitled task #8" is missing node name');
        });

        it('names a nameless agent by its badge number', () => {
            openFlow(graphDto({ agent_node_list: [{ ...liveAgent, node_name: '', node_number: 9 }] }));

            expect(saveAndReadToast()).toContain('"Untitled agent #9" is missing node name');
        });

        it('shows the position in parentheses when a nameless node has no badge number yet', () => {
            openFlow(graphDto({ task_node_list: [{ ...liveTask, node_name: '' }] }));
            const flow = flowService.getFlowState();
            flowService.setFlow({
                ...flow,
                nodes: flow.nodes.map((node) => ({ ...node, nodeNumber: undefined })),
            });
            const position = flow.nodes.findIndex((node) => node.type === NodeType.TASK) + 1;

            expect(saveAndReadToast()).toContain(`"Untitled task (${position})" is missing node name`);
        });

        it('keeps the trimmed name and its badge number for a named node', () => {
            openFlow(
                graphDto({
                    task_node_list: [{ ...liveTask, node_name: ' Summarise ', node_number: 4, instructions: '' }],
                })
            );

            expect(saveAndReadToast()).toContain('"Summarise #4" is missing instructions');
        });
    });

    describe('graph node counter', () => {
        // The graph has issued numbers up to 12 (nodes since deleted); the canvas only holds #1.
        const counterGraph = graphDto({ python_node_list: [livePython], node_number_seq: 12 });
        let nextRouteId = 200;
        const livePythonNode = () => flowService.getFlowState().nodes.find((node) => node.type === NodeType.PYTHON)!;

        function openFlow(graph: GraphDto): void {
            flowsApi['getGraphById'].mockReturnValue(of(graph));
            paramMap$.next(convertToParamMap({ id: String(nextRouteId++) }));
            fixture.detectChanges();
        }

        it('numbers a new node after the loaded graph counter, not after the canvas', () => {
            openFlow(counterGraph);

            expect(flowService.getNextNodeNumber()).toBe(13);
        });

        it('continues from the counter a flow save returns', () => {
            openFlow(counterGraph);
            flowsApi['bulkSaveGraph'].mockReturnValue(
                of(graphDto({ save_version: 2, python_node_list: [livePython], node_number_seq: 20 }))
            );

            component.onGraphSave(flowService.getFlowState());

            expect(flowService.getNextNodeNumber()).toBe(21);
        });

        it('continues from the counter a single-node save returns', () => {
            openFlow(counterGraph);
            flowsApi['bulkSaveGraph'].mockReturnValue(
                of(graphDto({ save_version: 2, python_node_list: [livePython], node_number_seq: 30 }))
            );

            TestBed.inject(SidePanelService).requestSaveNode({ ...livePythonNode(), node_name: 'Renamed' });

            expect(flowService.getNextNodeNumber()).toBe(31);
        });

        describe('a new node the save numbers', () => {
            const NEW_NODE_ID = 'new-python';
            const newNode = () => flowService.getFlowState().nodes.find((node) => node.id === NEW_NODE_ID)!;

            /** The canvas holds the saved #1 plus a new node showing #4, which the counter at 12 has already issued. */
            function openFlowWithNewNode(): void {
                openFlow(counterGraph);
                const flow = flowService.getFlowState();
                const unsaved = { ...livePythonNode(), id: NEW_NODE_ID, backendId: null, nodeNumber: 4 };
                flowService.setFlow({ ...flow, nodes: [...flow.nodes, unsaved] });
            }

            /** The server ordered the new node by hint 4 and numbered it #13, the next one its counter issues. */
            function respondWithNodeNumbered13(): void {
                flowsApi['bulkSaveGraph'].mockReturnValue(
                    of(
                        graphDto({
                            save_version: 2,
                            python_node_list: [livePython, { ...livePython, id: 40, node_number: 13 }],
                            node_number_seq: 13,
                        })
                    )
                );
            }

            it('sends the number it shows as a hint, then shows the number the flow save gave it, saved', () => {
                openFlowWithNewNode();
                respondWithNodeNumbered13();

                component.onGraphSave(flowService.getFlowState());

                const payload = flowsApi['bulkSaveGraph'].mock.calls[0][1] as Record<string, unknown>;
                expect(payload['python_node_list']).toEqual([
                    expect.objectContaining({ id: null, temp_id: NEW_NODE_ID, node_number_hint: 4 }),
                ]);
                expect(newNode()).toEqual(expect.objectContaining({ backendId: 40, nodeNumber: 13 }));
                expect(component.hasUnsavedChangesSignal()).toBe(false);
            });

            it('shows the number a single-node save gave it, saved', () => {
                openFlowWithNewNode();
                respondWithNodeNumbered13();

                TestBed.inject(SidePanelService).requestSaveNode(newNode());

                expect(newNode()).toEqual(expect.objectContaining({ backendId: 40, nodeNumber: 13 }));
                expect(component.hasUnsavedChangesSignal()).toBe(false);
            });

            it('changes no other number after a full save when no unsaved node is left', () => {
                openFlowWithNewNode();
                respondWithNodeNumbered13();

                component.onGraphSave(flowService.getFlowState());

                const shownNumbers = flowService.getFlowState().nodes.flatMap((node) => node.nodeNumber ?? []);
                expect(shownNumbers).toEqual([1, 13]);
                expect(flowService.getNextNodeNumber()).toBe(14);
            });

            it('moves an unsaved table off the number a single-node save gave another, each layout with it', () => {
                localStorage.clear();
                openFlow(counterGraph);
                const table = mapClassificationDecisionTableNodeToModel(liveClassificationTable);
                const flow = flowService.getFlowState();
                flowService.setFlow({
                    ...flow,
                    nodes: [
                        ...flow.nodes,
                        { ...table, id: 'table-a', backendId: null, nodeNumber: 13 },
                        { ...table, id: 'table-b', backendId: null, nodeNumber: 14 },
                    ],
                });
                localStorage.setItem('cdt-grid-state-1_13', 'layout of A');
                localStorage.setItem('cdt-grid-state-1_14', 'layout of B');
                // Only B is saved; the server numbers it from its counter: #13, the number A shows.
                flowsApi['bulkSaveGraph'].mockReturnValue(
                    of(
                        graphDto({
                            save_version: 2,
                            python_node_list: [livePython],
                            classification_decision_table_node_list: [
                                { ...liveClassificationTable, id: 42, node_number: 13 },
                            ],
                            node_number_seq: 13,
                        })
                    )
                );
                const tableNode = (id: string) => flowService.getFlowState().nodes.find((node) => node.id === id)!;

                TestBed.inject(SidePanelService).requestSaveNode(tableNode('table-b'));

                expect(tableNode('table-b')).toEqual(expect.objectContaining({ backendId: 42, nodeNumber: 13 }));
                expect(tableNode('table-a')).toEqual(expect.objectContaining({ backendId: null, nodeNumber: 14 }));
                expect(localStorage.getItem('cdt-grid-state-1_13')).toBe('layout of B');
                expect(localStorage.getItem('cdt-grid-state-1_14')).toBe('layout of A');
                expect(component.hasUnsavedChangesSignal()).toBe(true);
                localStorage.clear();
            });

            it('keeps the layout key of a saved table when an unsaved table showing its number moves off it', () => {
                localStorage.clear();
                const savedTableDto = { ...liveClassificationTable, id: 31, node_number: 13 };
                const graph = graphDto({
                    python_node_list: [livePython],
                    classification_decision_table_node_list: [savedTableDto],
                    node_number_seq: 13,
                });
                openFlow(graph);
                const flow = flowService.getFlowState();
                const unsavedTable = {
                    ...mapClassificationDecisionTableNodeToModel(liveClassificationTable),
                    id: 'unsaved-table',
                    backendId: null,
                    nodeNumber: 13,
                };
                flowService.setFlow({ ...flow, nodes: [...flow.nodes, unsavedTable] });
                localStorage.setItem('cdt-grid-state-1_13', 'layout of the saved table');
                flowsApi['bulkSaveGraph'].mockReturnValue(of({ ...graph, save_version: 2 }));

                TestBed.inject(SidePanelService).requestSaveNode({ ...livePythonNode(), node_name: 'Renamed' });

                const unsaved = flowService.getFlowState().nodes.find((node) => node.id === 'unsaved-table')!;
                expect(unsaved.nodeNumber).toBe(14);
                expect(localStorage.getItem('cdt-grid-state-1_13')).toBe('layout of the saved table');
                localStorage.clear();
            });

            it('never writes a new table layout over the key a saved table without a server number shows', () => {
                localStorage.clear();
                // A saved table the server never numbered: the loader shows it #13, past the canvas, which
                // the counter (12) has not issued yet; its layout is stored under that number.
                const unnumberedTable = { ...liveClassificationTable, id: 30, node_number: null };
                openFlow(
                    graphDto({
                        python_node_list: [{ ...livePython, node_number: 12 }],
                        classification_decision_table_node_list: [unnumberedTable],
                        node_number_seq: 12,
                    })
                );
                const savedTable = () => flowService.getFlowState().nodes.find((node) => node.backendId === 30)!;
                expect(savedTable().nodeNumber).toBe(13);
                localStorage.setItem('cdt-grid-state-1_13', 'layout of the saved table');
                const flow = flowService.getFlowState();
                const newTable = {
                    ...mapClassificationDecisionTableNodeToModel(liveClassificationTable),
                    id: 'new-table',
                    backendId: null,
                    nodeNumber: 14,
                };
                flowService.setFlow({ ...flow, nodes: [...flow.nodes, newTable] });
                localStorage.setItem('cdt-grid-state-1_14', 'layout of the new table');
                // The server numbers the new table from its counter: #13, the number the saved one shows.
                flowsApi['bulkSaveGraph'].mockReturnValue(
                    of(
                        graphDto({
                            save_version: 2,
                            python_node_list: [{ ...livePython, node_number: 12 }],
                            classification_decision_table_node_list: [
                                unnumberedTable,
                                { ...liveClassificationTable, id: 41, node_number: 13 },
                            ],
                            node_number_seq: 13,
                        })
                    )
                );

                component.onGraphSave(flowService.getFlowState());

                expect(localStorage.getItem('cdt-grid-state-1_13')).toBe('layout of the saved table');
                localStorage.clear();
            });

            it('keeps the grid layout of a new decision table the save renumbers', () => {
                localStorage.clear();
                const cdtDto: GetClassificationDecisionTableNodeRequest = {
                    ...liveClassificationTable,
                    id: 41,
                    node_number: 13,
                };
                openFlow(counterGraph);
                const flow = flowService.getFlowState();
                const unsavedCdt = {
                    ...mapClassificationDecisionTableNodeToModel(liveClassificationTable),
                    id: 'new-cdt',
                    backendId: null,
                    nodeNumber: 4,
                };
                flowService.setFlow({ ...flow, nodes: [...flow.nodes, unsavedCdt] });
                localStorage.setItem('cdt-grid-state-1_4', '{"widths":{"group_name":240}}');
                flowsApi['bulkSaveGraph'].mockReturnValue(
                    of(
                        graphDto({
                            save_version: 2,
                            python_node_list: [livePython],
                            classification_decision_table_node_list: [cdtDto],
                            node_number_seq: 13,
                        })
                    )
                );

                component.onGraphSave(flowService.getFlowState());

                expect(localStorage.getItem('cdt-grid-state-1_13')).toBe('{"widths":{"group_name":240}}');
                localStorage.clear();
            });
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

    describe('trigger nodes and the Use permission on flows', () => {
        const savedWebhook = liveGraph.webhook_trigger_node_list![0];
        const savedSchedule = liveGraph.schedule_trigger_node_list![0];
        let nextRouteId = 500;
        const TRIGGER_CHANGES_WARNING =
            'This change includes trigger nodes, which need the Use permission on flows. Remove or revert the trigger node changes to save.';

        function openFlow(graph: GraphDto): void {
            flowsApi['getGraphById'].mockReturnValue(of(graph));
            paramMap$.next(convertToParamMap({ id: String(nextRouteId++) }));
            fixture.detectChanges();
        }

        function nodeOfType<T extends FlowModel['nodes'][number]>(type: NodeType): T {
            return flowService.nodes().find((node) => node.type === type) as T;
        }

        function savedPayload(): Record<string, unknown[]> {
            return flowsApi['bulkSaveGraph'].mock.calls.at(-1)![1] as Record<string, unknown[]>;
        }

        function deletedWebhookIds(): unknown {
            const payload = flowsApi['bulkSaveGraph'].mock.calls.at(-1)![1] as { deleted: Record<string, unknown> };
            return payload.deleted['webhook_trigger_node_ids'];
        }

        /** As the canvas does it when the user saves. */
        function saveLiveFlow(): void {
            liveCanvas()!.save.emit(flowService.getFlowState());
        }

        /** What the page hands its header: the unsaved-changes mark and the saving state. */
        function header(): FlowHeaderStubComponent {
            fixture.detectChanges();
            return fixture.debugElement.query(By.directive(FlowHeaderStubComponent))
                .componentInstance as FlowHeaderStubComponent;
        }

        function warningsShown(): unknown[] {
            return toast['warning'].mock.calls.map(([message]) => message);
        }

        describe('a legacy "at HH:MM" once-schedule name', () => {
            const legacyName = 'Once on 05 Oct 2026 at 14:30';
            const legacyGraph = graphDto({ schedule_trigger_node_list: [{ ...savedSchedule, node_name: legacyName }] });

            it.each([
                [
                    'rewritten for a user who can run flows, leaving the flow to be saved',
                    true,
                    'Once on 05 Oct 2026 at 14-30',
                    true,
                ],
                ['kept for a user who cannot run flows, so the flow stays clean', false, legacyName, false],
            ])('is %s', (_case, canRun, shownName, unsaved) => {
                canRunFlows.set(canRun);
                openFlow(legacyGraph);

                expect(nodeOfType(NodeType.SCHEDULE_TRIGGER).node_name).toBe(shownName);
                expect(header().hasUnsavedChanges()).toBe(unsaved);
            });
        });

        describe('unpacking a subflow', () => {
            const SUBFLOW_ID = 40;
            const parentGraph = graphDto({
                subgraph_node_list: [{ ...liveGraph.subgraph_node_list![0], subgraph: SUBFLOW_ID }],
            });
            const subflowWithoutTriggers = graphDto({
                id: SUBFLOW_ID,
                python_node_list: [{ ...livePython, graph: SUBFLOW_ID, node_name: 'Sub python' }],
            });
            const subflowWithTrigger = graphDto({
                ...subflowWithoutTriggers,
                webhook_trigger_node_list: [{ ...savedWebhook, graph: SUBFLOW_ID, node_name: 'Sub webhook' }],
                edge_list: [
                    {
                        id: 9,
                        graph: SUBFLOW_ID,
                        start_node_id: savedWebhook.id,
                        end_node_id: livePython.id,
                        metadata: {},
                    },
                ],
            });
            let bulkDelete: ReturnType<typeof vi.fn>;
            let confirm: ReturnType<typeof vi.spyOn>;
            let confirmWithOptions: ReturnType<typeof vi.spyOn>;

            beforeEach(() => {
                openFlow(parentGraph);
                // Used by this flow only, so an allowed unpack asks nothing and deletes the subflow.
                flowsApi['getSubflowUsage'] = vi.fn().mockReturnValue(of({ parent_flow_ids: [1] }));
                bulkDelete = flowsStorage.bulkDelete;
                const dialogs = TestBed.inject(ConfirmationDialogService);
                confirm = vi.spyOn(dialogs, 'confirm').mockReturnValue(of<ConfirmationResult>('close'));
                confirmWithOptions = vi
                    .spyOn(dialogs, 'confirmWithOptions')
                    .mockReturnValue(of({ confirmed: true, checked: false }));
            });

            function unpack(subflow: GraphDto): void {
                flowsApi['getGraphById'].mockReturnValue(of(subflow));
                flowsApi['bulkSaveGraph'].mockClear();
                // The canvas stub declares no unpackSubflow output, so the handler its (unpackSubflow) binding calls
                // is called directly.
                component.onUnpackSubflow(nodeOfType(NodeType.SUBGRAPH).id);
            }

            it('brings in the trigger nodes and deletes the unused subflow for a user who can run flows', () => {
                unpack(subflowWithTrigger);

                expect(savedPayload()['webhook_trigger_node_list']).toHaveLength(1);
                expect(savedPayload()['edge_list']).toHaveLength(1);
                expect(bulkDelete).toHaveBeenCalledWith([SUBFLOW_ID]);
                expect(confirm).not.toHaveBeenCalled();
                expect(toast['success']).toHaveBeenCalledWith(
                    'Unpacked "Sub" into the current graph and deleted the subflow'
                );
            });

            it('refuses a subflow with trigger nodes without Run, before asking anything, and changes nothing', () => {
                canRunFlows.set(false);
                // Used elsewhere too: the usage question would come next, but the refusal comes first.
                flowsApi['getSubflowUsage'].mockReturnValue(of({ parent_flow_ids: [1, 77] }));
                const flowBefore = flowService.getFlowState();

                unpack(subflowWithTrigger);

                expect(confirm).toHaveBeenCalledExactlyOnceWith(
                    expect.objectContaining({
                        title: 'Use permission required',
                        message: 'This subflow contains trigger nodes (Webhook, Telegram, Schedule).',
                        caution: '<strong>Unpacking</strong> it requires the <strong>Use</strong> permission on flows.',
                        hideConfirm: true,
                    })
                );
                expect(flowsApi['getSubflowUsage']).not.toHaveBeenCalled();
                expect(confirmWithOptions).not.toHaveBeenCalled();
                expect(flowsApi['bulkSaveGraph']).not.toHaveBeenCalled();
                expect(bulkDelete).not.toHaveBeenCalled();
                expect(flowService.getFlowState()).toEqual(flowBefore);
                expect(toast['success']).not.toHaveBeenCalled();
                expect(toast['error']).not.toHaveBeenCalled();
                expect(toast['warning']).not.toHaveBeenCalled();
            });

            it('unpacks a subflow without trigger nodes as before for a user without Run', () => {
                canRunFlows.set(false);

                unpack(subflowWithoutTriggers);

                expect(confirm).not.toHaveBeenCalled();
                expect(savedPayload()['python_node_list']).toEqual([
                    expect.objectContaining({ node_name: 'Sub python' }),
                ]);
                expect(bulkDelete).toHaveBeenCalledWith([SUBFLOW_ID]);
                expect(toast['success']).toHaveBeenCalledWith(
                    'Unpacked "Sub" into the current graph and deleted the subflow'
                );
            });

            it('still asks about a subflow used elsewhere, and keeps it unless told to delete it', () => {
                flowsApi['getSubflowUsage'].mockReturnValue(of({ parent_flow_ids: [1, 77] }));

                unpack(subflowWithTrigger);

                expect(confirmWithOptions).toHaveBeenCalledOnce();
                expect(savedPayload()['webhook_trigger_node_list']).toHaveLength(1);
                expect(bulkDelete).not.toHaveBeenCalled();
                expect(toast['success']).toHaveBeenCalledWith('Unpacked "Sub" into the current graph');
            });
        });

        describe('a schedule the backend switches off while saving', () => {
            const activeGraph = graphDto({ schedule_trigger_node_list: [{ ...savedSchedule, is_active: true }] });

            beforeEach(() => {
                openFlow(activeGraph);
                const schedule = nodeOfType<ScheduleTriggerNodeModel>(NodeType.SCHEDULE_TRIGGER);
                flowService.updateNode({ ...schedule, node_name: 'Nightly' });
                flowsApi['bulkSaveGraph'].mockReturnValue(
                    of(
                        graphDto({
                            save_version: 2,
                            schedule_trigger_node_list: [{ ...savedSchedule, node_name: 'Nightly', is_active: false }],
                        })
                    )
                );
                saveLiveFlow();
            });

            it('takes the backend value on the canvas and in the saved baseline, leaving the flow clean', () => {
                expect(nodeOfType<ScheduleTriggerNodeModel>(NodeType.SCHEDULE_TRIGGER).data.isActive).toBe(false);
                expect(header().hasUnsavedChanges()).toBe(false);
            });

            it('sends no schedule update with the next save', () => {
                saveLiveFlow();

                expect(flowsApi['bulkSaveGraph']).toHaveBeenCalledTimes(2);
                expect(savedPayload()['schedule_trigger_node_list']).toEqual([]);
            });
        });

        describe('a schedule the backend changes while the flow is open', () => {
            beforeEach(() => {
                openFlow(graphDto({ schedule_trigger_node_list: [{ ...savedSchedule, is_active: true }] }));
                canRunFlows.set(false);
                // As the open schedule panel does after reading the node back from the backend.
                TestBed.inject(ScheduleTriggerRuntimeService).apply(nodeOfType(NodeType.SCHEDULE_TRIGGER).id, {
                    isActive: false,
                    nextRunDateTime: '2026-10-14T09:00:00',
                    currentRuns: savedSchedule.current_runs + 1,
                });
            });

            it('is not an unsaved change', () => {
                expect(nodeOfType<ScheduleTriggerNodeModel>(NodeType.SCHEDULE_TRIGGER).data.isActive).toBe(false);
                expect(header().hasUnsavedChanges()).toBe(false);
            });

            it('is not in the next save, which a user without Run can therefore send', () => {
                saveLiveFlow();

                expect(flowsApi['bulkSaveGraph']).toHaveBeenCalledTimes(1);
                expect(savedPayload()['schedule_trigger_node_list']).toEqual([]);
                expect(warningsShown()).not.toContain(TRIGGER_CHANGES_WARNING);
            });
        });

        describe('saving without the Use permission', () => {
            const webhookGraph = graphDto({ webhook_trigger_node_list: [savedWebhook] });

            beforeEach(() => canRunFlows.set(false));

            function expectSaveRefused(): void {
                expect(flowsApi['bulkSaveGraph']).not.toHaveBeenCalled();
                expect(warningsShown()).toEqual([TRIGGER_CHANGES_WARNING]);
                expect(header().hasUnsavedChanges()).toBe(true);
                expect(header().isSaving()).toBe(false);
            }

            it('refuses to send a new trigger node, keeping the unsaved changes', () => {
                const created: WebhookTriggerNodeModel = {
                    ...mapWebhookTriggerNodeToModel(savedWebhook),
                    backendId: null,
                };
                flowService.setFlow({ ...flowService.getFlowState(), nodes: [created] });

                saveLiveFlow();

                expectSaveRefused();
            });

            it('refuses to send a changed trigger node', () => {
                openFlow(webhookGraph);
                const webhook = nodeOfType<WebhookTriggerNodeModel>(NodeType.WEBHOOK_TRIGGER);
                flowService.updateNode({ ...webhook, node_name: 'Renamed webhook' });

                saveLiveFlow();

                expectSaveRefused();
            });

            it('refuses a trigger node that undo brought back after its deletion was saved', () => {
                openFlow(webhookGraph);
                const webhook = nodeOfType<WebhookTriggerNodeModel>(NodeType.WEBHOOK_TRIGGER);
                flowService.setFlow({ ...flowService.getFlowState(), nodes: [] });
                flowsApi['bulkSaveGraph'].mockReturnValue(of(graphDto({ save_version: 2 })));
                saveLiveFlow();
                expect(deletedWebhookIds()).toEqual([savedWebhook.id]);
                flowsApi['bulkSaveGraph'].mockClear();

                flowService.setFlow({ ...flowService.getFlowState(), nodes: [webhook] });
                saveLiveFlow();

                expectSaveRefused();
            });

            it('still saves the deletion of a trigger node', () => {
                openFlow(webhookGraph);
                flowService.setFlow({ ...flowService.getFlowState(), nodes: [] });

                saveLiveFlow();

                expect(flowsApi['bulkSaveGraph']).toHaveBeenCalledTimes(1);
                expect(deletedWebhookIds()).toEqual([savedWebhook.id]);
                expect(toast['warning']).not.toHaveBeenCalled();
            });

            it('refuses the single-node save of a trigger node from its panel', () => {
                openFlow(webhookGraph);
                const webhook = nodeOfType<WebhookTriggerNodeModel>(NodeType.WEBHOOK_TRIGGER);

                TestBed.inject(SidePanelService).requestSaveNode({ ...webhook, node_name: 'Renamed webhook' });

                expect(flowsApi['bulkSaveGraph']).not.toHaveBeenCalled();
                expect(warningsShown()).toEqual([TRIGGER_CHANGES_WARNING]);
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

    describe('full save of a python code with an execution timeout', () => {
        function loadPythonNodeWithTimeout(executionTimeout: number | undefined): void {
            flowsApi['getGraphById'].mockReturnValue(of(graphDto({ python_node_list: [livePython] })));
            component.refreshCurrentFlow();
            const python = flowService.nodes().find((node) => node.backendId === livePython.id) as PythonNodeModel;
            flowService.updateNode({ ...python, data: { ...python.data, execution_timeout: executionTimeout } });
        }

        it('refuses to save a code whose timeout is below the minimum, and names its node', () => {
            loadPythonNodeWithTimeout(0);

            component.onGraphSave(flowService.getFlowState());

            expect(flowsApi['bulkSaveGraph']).not.toHaveBeenCalled();
            expect(toast['error']).toHaveBeenCalledExactlyOnceWith(
                `Cannot save flow — fix the following node(s) first: "${livePython.node_name}" needs an execution timeout of at least ${TEST_EXECUTION_TIMEOUT_LIMITS.minSeconds} seconds.`
            );
        });

        it('saves a timeout above the maximum for the backend to lower, so a lowered maximum never blocks a save', () => {
            const aboveMaximum = TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds! + 600;
            loadPythonNodeWithTimeout(aboveMaximum);

            component.onGraphSave(flowService.getFlowState());

            expect(flowsApi['bulkSaveGraph']).toHaveBeenCalledTimes(1);
            const payload = flowsApi['bulkSaveGraph'].mock.calls[0][1] as Record<string, unknown>;
            expect(payload['python_node_list']).toEqual([
                expect.objectContaining({
                    id: livePython.id,
                    python_code: expect.objectContaining({ execution_timeout: aboveMaximum }),
                }),
            ]);
        });
    });

    describe('full save of an agent node', () => {
        const SAVED_AGENT: AgentNode = {
            ...UNEDITED_NODE,
            uuid: '00000000-0000-4000-8000-000000000041',
            id: 50,
            metadata: {},
            node_number: 1,
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
                uuid: '00000000-0000-4000-8000-000000000042',
                id,
                graph: 1,
                node_number: id,
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
            node_number_seq: 22,
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

            it('numbers the new subgraph node after the parent graph counter', () => {
                component.onExtractToSubflow(new Set([table(21).id]));
                answerSubflowSave();

                const subgraphNode = flowService.nodes().find((node) => node.type === NodeType.SUBGRAPH);
                expect(subgraphNode?.nodeNumber).toBe(23);
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
                uuid: '00000000-0000-4000-8000-000000000043',
                id: 41,
                node_number: 1,
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
                expect(flowsStorage.bulkDelete).toHaveBeenCalledWith([9]);
                expect(component.isSaving()).toBe(false);
            });

            it('numbers the inlined nodes after the parent graph counter and keeps their names', () => {
                component.onUnpackSubflow(subgraphNodeOnCanvas()!.id);

                const inlined = flowService.nodes().find((node) => node.node_name === 'Inner');
                // The inner flow numbered it #31; in the parent it takes the next number after #22.
                expect(inlined?.nodeNumber).toBe(23);
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
