import { HttpErrorResponse } from '@angular/common/http';
import { Component, forwardRef, inject, input, output, signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltipModule } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { ActivatedRoute, convertToParamMap, Router } from '@angular/router';
import { AppSvgIconComponent, SpinnerComponent, UnsavedChangesDialogService } from '@shared/components';
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
import { GraphNoteModel } from '../../../../visual-programming/core/models/node.model';
import { FLOW_EDITOR_STATE_PROVIDERS } from '../../../../visual-programming/core/providers/flow-editor-state.providers';
import { FlowGraphComponent } from '../../../../visual-programming/flow-graph/flow-graph.component';
import { FlowService } from '../../../../visual-programming/services/flow.service';
import { SidePanelService } from '../../../../visual-programming/services/side-panel.service';
import { mapGraphNoteToModel } from '../../../../visual-programming/utils/load/nodes/graph-note.mapper';
import { FlowVisualProgrammingComponent } from './flow-visual-programming.component';

/** Past the page's private 1.5 s autosave debounce. */
const NODE_AUTOSAVE_WAIT_MS = 2000;
const CAPTURED_VIEWPORT: FlowViewport = { position: { x: 120, y: -40 }, scale: 0.75 };
const VERSION_A: GraphVersionDto = { id: 11, graph_id: 1, name: 'Version A', description: '', created_at: '' };
const VERSION_B: GraphVersionDto = { id: 12, graph_id: 1, name: 'Version B', description: '', created_at: '' };

function graphDto(overrides: Partial<GraphDto> = {}): GraphDto {
    return { id: 1, uuid: 'graph-uuid', name: 'Flow', description: '', save_version: 1, ...overrides } as GraphDto;
}

const RESTORED_GRAPH = graphDto({
    save_version: 2,
    graph_note_list: [{ id: 99, node_name: 'Restored note', graph: 1, content: 'restored', metadata: {} }],
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

describe('FlowVisualProgrammingComponent — version preview', () => {
    let fixture: ComponentFixture<FlowVisualProgrammingComponent>;
    let component: FlowVisualProgrammingComponent;
    let flowService: FlowService;
    let flowsApi: Record<string, ReturnType<typeof vi.fn>>;
    let unsavedChangesDialog: { confirm: ReturnType<typeof vi.fn>; confirmUnsavedChanges: ReturnType<typeof vi.fn> };
    let toast: Record<string, ReturnType<typeof vi.fn>>;
    let paramMap$: BehaviorSubject<ReturnType<typeof convertToParamMap>>;
    /** A signal, so FlowReadOnlyService's computed re-reads it when a test revokes Flows:Update. */
    let canUpdateFlows: WritableSignal<boolean>;

    beforeEach(() => {
        FlowGraphStubComponent.instances = [];
        canUpdateFlows = signal(true);
        flowsApi = {
            getGraphById: vi.fn().mockReturnValue(of(graphDto())),
            getGraphsLight: vi.fn().mockReturnValue(of([])),
            bulkSaveGraph: vi.fn().mockReturnValue(of(graphDto({ save_version: 2 }))),
            restoreGraphVersion: vi.fn().mockReturnValue(of({ restored: true, graph_id: 1, warnings: [] })),
            saveGraphVersion: vi.fn(),
        };
        unsavedChangesDialog = { confirm: vi.fn(), confirmUnsavedChanges: vi.fn() };
        toast = { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() };
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
                { provide: RunGraphService, useValue: {} },
                { provide: ConfigService, useValue: { isEpicChatEnabled: false, apiUrl: '/api/' } },
                { provide: EpicChatService, useValue: {} },
                { provide: UnsavedChangesDialogService, useValue: unsavedChangesDialog },
                { provide: CreateGraphWarningsService, useValue: { readPending: () => [] } },
                { provide: RunSessionSSEService, useValue: { stopStream: vi.fn() } },
                { provide: PermissionsService, useValue: { can: () => canUpdateFlows(), canAny: () => true } },
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

    // Nested here for the shared TestBed setup; nothing below involves a preview.
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

        it('drops an autosave in a read-only editor without a message', () => {
            vi.useFakeTimers();
            canUpdateFlows.set(false);
            const updateNode = vi.spyOn(flowService, 'updateNode');

            sidePanelService.requestNodeAutosave(note);
            vi.advanceTimersByTime(NODE_AUTOSAVE_WAIT_MS);

            expect(flowsApi['bulkSaveGraph']).not.toHaveBeenCalled();
            expect(updateNode).not.toHaveBeenCalled();
            expect(toast['info']).not.toHaveBeenCalledWith(READ_ONLY_MESSAGE);
        });

        it('still autosaves when the editor may change the flow', () => {
            vi.useFakeTimers();

            sidePanelService.requestNodeAutosave(note);
            vi.advanceTimersByTime(NODE_AUTOSAVE_WAIT_MS);

            expect(flowsApi['bulkSaveGraph']).toHaveBeenCalledTimes(1);
            expect(toast['success']).not.toHaveBeenCalled();
        });
    });
});
