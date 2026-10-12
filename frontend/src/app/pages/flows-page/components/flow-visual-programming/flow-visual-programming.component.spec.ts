import { HttpErrorResponse } from '@angular/common/http';
import { Component, forwardRef, inject, input, output, signal } from '@angular/core';
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
import { EpicChatService } from '../../../../features/epic-chat/epic-chat.service';
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
import { FlowModel } from '../../../../visual-programming/core/models/flow.model';
import { FlowViewport } from '../../../../visual-programming/core/models/flow-viewport.model';
import { WebhookTriggerNodeModel } from '../../../../visual-programming/core/models/node.model';
import { GetWebhookTriggerNodeRequest } from '../../../../visual-programming/core/models/webhook-trigger';
import { FLOW_EDITOR_STATE_PROVIDERS } from '../../../../visual-programming/core/providers/flow-editor-state.providers';
import { FlowGraphComponent } from '../../../../visual-programming/flow-graph/flow-graph.component';
import { FlowService } from '../../../../visual-programming/services/flow.service';
import { FlowTestRunService } from '../../../../visual-programming/services/flow-test-run.service';
import { NodeAuthorshipStore } from '../../../../visual-programming/services/node-authorship.store';
import { SidePanelService } from '../../../../visual-programming/services/side-panel.service';
import { mapWebhookTriggerNodeToModel } from '../../../../visual-programming/utils/load/nodes/webhook-trigger-node.mapper';
import { livePython, liveTask } from '../../../../visual-programming/utils/testing/live-graph.fixture';
import {
    FlowVisualProgrammingComponent,
    RUN_WHILE_SAVING_MESSAGE,
    TEST_RUN_NODE_GONE_MESSAGE,
    TEST_RUN_PAYLOAD_REJECTED_MESSAGE,
} from './flow-visual-programming.component';

const CAPTURED_VIEWPORT: FlowViewport = { position: { x: 120, y: -40 }, scale: 0.75 };
const VERSION_A: GraphVersionDto = { id: 11, graph_id: 1, name: 'Version A', description: '', created_at: '' };
const VERSION_B: GraphVersionDto = { id: 12, graph_id: 1, name: 'Version B', description: '', created_at: '' };

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
    let runGraph: Record<string, ReturnType<typeof vi.fn>>;
    let runSessionSse: { stopStream: ReturnType<typeof vi.fn>; startStream: ReturnType<typeof vi.fn> };
    let isStreaming: ReturnType<typeof signal<boolean>>;
    let sessionStatus: ReturnType<typeof signal<GraphSessionStatus>>;

    beforeEach(() => {
        FlowGraphStubComponent.instances = [];
        flowsApi = {
            getGraphById: vi.fn().mockReturnValue(of(graphDto())),
            getGraphsLight: vi.fn().mockReturnValue(of([])),
            bulkSaveGraph: vi.fn().mockReturnValue(of(graphDto({ save_version: 2 }))),
            restoreGraphVersion: vi.fn().mockReturnValue(of({ restored: true, graph_id: 1, warnings: [] })),
            saveGraphVersion: vi.fn(),
        };
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
                { provide: FlowsStorageService, useValue: {} },
                { provide: ToastService, useValue: toast },
                { provide: RunGraphService, useValue: runGraph },
                { provide: ConfigService, useValue: { isEpicChatEnabled: false, apiUrl: '/api/' } },
                { provide: EpicChatService, useValue: {} },
                { provide: UnsavedChangesDialogService, useValue: unsavedChangesDialog },
                { provide: CreateGraphWarningsService, useValue: { readPending: () => [] } },
                {
                    provide: RunSessionSSEService,
                    useValue: { ...runSessionSse, isStreaming, status: sessionStatus },
                },
                { provide: PermissionsService, useValue: { can: () => true, canAny: () => true } },
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
                { provide: ProfileService, useValue: { currentUserSignal: signal(null) } },
                { provide: FlowAssistantService, useValue: { isOpen: signal(false), toggle: vi.fn() } },
            ],
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

    describe('version preview', () => {
        function preview(): HTMLElement | null {
            return fixture.nativeElement.querySelector('app-flow-version-preview');
        }

        function makeLiveFlowDirty(): void {
            const flow = flowService.getFlowState();
            flowService.setFlow({
                ...flow,
                nodes: flow.nodes.map((node) => ({ ...node, position: { x: 4242, y: 0 } })),
            });
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
            const event = new KeyboardEvent('keydown', { code: 'KeyS', ctrlKey: true, cancelable: true });

            component.handleCtrlS(event);

            expect(event.defaultPrevented).toBe(true);
            expect(toast['info']).toHaveBeenCalledWith('Exit preview mode to save');
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
            component.isSaving.set(true);

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

            expect(flowService.savedWebhookPythonCode(21)).toEqual(STORED_PYTHON_CODE);

            fixture.destroy();

            expect(flowService.hasSavedGraph()).toBe(false);
            expect(flowService.savedWebhookPythonCode(21)).toBeNull();
        });

        it('drops it when another user saves the graph, until the graph is loaded again', () => {
            loadFlowWithWebhookNode(2);

            remoteSave();

            expect(flowService.hasSavedGraph()).toBe(false);
            expect(flowService.savedWebhookPythonCode(21)).toBeNull();

            loadFlowWithWebhookNode(3);

            expect(flowService.savedWebhookPythonCode(21)).toEqual(STORED_PYTHON_CODE);
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
});
