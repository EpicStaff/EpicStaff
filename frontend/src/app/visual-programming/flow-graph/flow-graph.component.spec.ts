import { Dialog } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, input, NO_ERRORS_SCHEMA, output } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltipModule } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { FDragStartedEvent, FFlowModule, FNodeDirective, FZoomDirective } from '@foblex/flow';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, NodeType } from '@shared/models';
import { of } from 'rxjs';

import { ImportExportService } from '../../core/services/import-export.service';
import { FlowCopyImportFacadeService } from '../../features/flows/services/flow-copy-import-facade.service';
import { PermissionsService } from '../../services/auth/permissions.service';
import { ToastService } from '../../services/notifications';
import { NodePanelShellComponent } from '../components/node-panels/node-panel-shell/node-panel-shell.component';
import { ScheduleTriggerNodePanelComponent } from '../components/node-panels/schedule-trigger-node-panel/schedule-trigger-node-panel.component';
import { MouseTrackerDirective } from '../core/directives/mouse-tracker.directive';
import { ShortcutListenerDirective } from '../core/directives/shortcut-listener.directive';
import { WaypointTooltipDirective } from '../core/directives/waypoint-tooltip.directive';
import { FlowModel } from '../core/models/flow.model';
import { GraphNoteModel, NodeModel, ScheduleTriggerNodeModel } from '../core/models/node.model';
import { FLOW_EDITOR_PREVIEW } from '../core/providers/flow-editor-preview.token';
import { ClipboardService } from '../services/clipboard.service';
import { FlowService } from '../services/flow.service';
import { FlowReadOnlyService, TRIGGER_NODES_NEED_RUN_MESSAGE } from '../services/flow-readonly.service';
import { NodeAuthorshipStore } from '../services/node-authorship.store';
import { SidePanelService } from '../services/side-panel.service';
import { UndoRedoService } from '../services/undo-redo.service';
import { VersionPreviewNodeAuthorshipStore } from '../services/version-preview-node-authorship.store';
import { createStartNode } from '../utils/load';
import { liveGraph, liveNote, liveStart } from '../utils/testing/live-graph.fixture';
import { FlowGraphComponent } from './flow-graph.component';

const UNKNOWN_AUTHORSHIP = { created_by: null, created_at: null, last_edited_by: null, last_edited_at: null };

const authorshipOfRow = (row: typeof liveStart | typeof liveNote) => ({
    created_by: row.created_by,
    created_at: row.created_at,
    last_edited_by: row.last_edited_by,
    last_edited_at: row.last_edited_at,
});

// The real template pulls in the whole Foblex canvas, which jsdom cannot lay out. Every
// handler under test either returns before it touches a canvas reference or never uses one,
// so the class is mounted with an empty template.
function noteNode(): GraphNoteModel {
    return {
        id: 'note-1',
        backendId: null,
        type: NodeType.NOTE,
        node_name: 'Note',
        data: { content: 'hello' },
        position: { x: 200, y: 0 },
        ports: [],
        color: '',
        icon: '',
        size: { width: 200, height: 100 },
        input_map: {},
        output_variable_path: null,
    };
}

function scheduleTriggerNode(): ScheduleTriggerNodeModel {
    return {
        id: 'schedule-1',
        backendId: 7,
        type: NodeType.SCHEDULE_TRIGGER,
        node_name: 'Schedule #1',
        data: {
            isActive: false,
            runMode: 'once',
            startDateTime: '2026-07-01T12:00:00',
            intervalEvery: null,
            intervalUnit: null,
            weekdays: [],
            endType: 'never',
            endDateTime: null,
            maxRuns: null,
            timezone: 'UTC',
            nextRunDateTime: null,
        },
        position: { x: 0, y: 400 },
        ports: [],
        color: '',
        icon: '',
        size: { width: 200, height: 100 },
        input_map: {},
        output_variable_path: null,
    };
}

function mount(
    isPreview: boolean,
    flowState: FlowModel,
    beforeCreate: () => void = () => undefined,
    canUpdateFlows = true,
    canRunFlows = true
): ComponentFixture<FlowGraphComponent> {
    TestBed.configureTestingModule({
        providers: [
            provideHttpClient(),
            provideHttpClientTesting(),
            { provide: FLOW_EDITOR_PREVIEW, useValue: isPreview },
            // Read-only from permissions (a Viewer, or no Flows:Run) only where a test asks for it.
            {
                provide: PermissionsService,
                useValue: {
                    can: (_resource: unknown, action: ActionCode) =>
                        action === ActionCode.Run ? canRunFlows : canUpdateFlows,
                },
            },
            { provide: Dialog, useValue: { open: vi.fn(), openDialogs: [] } },
            // Provided by the flow page (live editor) or by FLOW_EDITOR_STATE_PROVIDERS (version preview).
            ...(isPreview
                ? [
                      VersionPreviewNodeAuthorshipStore,
                      { provide: NodeAuthorshipStore, useExisting: VersionPreviewNodeAuthorshipStore },
                  ]
                : [NodeAuthorshipStore]),
        ],
    });
    TestBed.overrideComponent(FlowGraphComponent, { set: { template: '', imports: [] } });
    beforeCreate();
    const fixture = TestBed.createComponent(FlowGraphComponent);
    fixture.componentRef.setInput('flowState', flowState);
    fixture.detectChanges();
    return fixture;
}

describe('FlowGraphComponent', () => {
    afterEach(() => vi.restoreAllMocks());

    describe('version preview (FLOW_EDITOR_PREVIEW = true)', () => {
        let component: FlowGraphComponent;
        let flowService: FlowService;
        let stateChanged: ReturnType<typeof vi.spyOn>;
        let dialogOpen: ReturnType<typeof vi.fn>;
        let flowBefore: FlowModel;

        beforeEach(() => {
            const fixture = mount(true, { nodes: [createStartNode(), noteNode()], connections: [] });
            component = fixture.componentInstance;
            flowService = TestBed.inject(FlowService);
            stateChanged = vi.spyOn(TestBed.inject(UndoRedoService), 'stateChanged');
            dialogOpen = (TestBed.inject(Dialog) as unknown as { open: ReturnType<typeof vi.fn> }).open;
            flowBefore = flowService.getFlowState();
        });

        afterEach(() => {
            expect(stateChanged).not.toHaveBeenCalled();
            expect(flowService.getFlowState()).toBe(flowBefore);
        });

        it('does not open the context menu or add a node from it', () => {
            const event = new MouseEvent('contextmenu');
            const preventDefault = vi.spyOn(event, 'preventDefault');

            component.onContextMenu(event);
            component.onAddNodeFromContextMenu({ type: NodeType.PYTHON });

            expect(preventDefault).toHaveBeenCalled();
            expect(component['showContextMenu']()).toBe(false);
        });

        it('does not record an undo step when a drag (pan) starts', () => {
            component.onDragStarted({ fData: { fNodeIds: ['note-1'] } } as unknown as FDragStartedEvent);
        });

        it('copies the selection (for pasting into the live flow) but does not paste', () => {
            const clipboard = TestBed.inject(ClipboardService);
            const paste = vi.spyOn(clipboard, 'paste');
            const copied = vi.fn();
            component.copied.subscribe(copied);
            component['fFlowComponent'] = {
                getSelection: () => ({ fNodeIds: ['note-1'], fGroupIds: [], fConnectionIds: [] }),
            } as unknown as FlowGraphComponent['fFlowComponent'];

            component.onCopy();
            component.onPaste();

            expect(clipboard.getClipboardData()?.nodes.map((node) => node.id)).toEqual(['note-1']);
            expect(copied).toHaveBeenCalledTimes(1);
            expect(paste).not.toHaveBeenCalled();
        });

        it('explains, instead of silently ignoring, blocked editing shortcuts (throttled)', () => {
            const info = vi.spyOn(TestBed.inject(ToastService), 'info').mockImplementation(() => undefined);

            component.onPaste();
            component.onDelete();
            component.onUndo();
            component.onRedo();

            expect(info).toHaveBeenCalledTimes(1);
            expect(info).toHaveBeenCalledWith(expect.stringContaining('read-only'), 3000, 'bottom-right');
        });

        it('does not delete nodes or connections', () => {
            const note = flowService.nodes().find((node) => node.id === 'note-1') as NodeModel;

            component.onDelete();
            component.onDeleteNode(note);
            component.onDeleteConnection(new MouseEvent('click'), 'any-connection');
        });

        it('opens the domain dialog view-only (toolbar and Start node) and ignores its result', () => {
            dialogOpen.mockReturnValue({ closed: of({ variables: { changed: true } }) });
            const [start] = flowService.nodes();

            component.onDomainClick();
            component.onOpenNodePanel(start);

            expect(dialogOpen).toHaveBeenCalledTimes(2);
            // Opened with this editor's injector, so the dialog sees this editor's read-only state.
            for (const [, config] of dialogOpen.mock.calls) {
                expect(config.injector.get(FlowReadOnlyService).isReadOnly()).toBe(true);
                // Nothing filled this preview's own store: the footer shows dashes.
                expect(config.data.authorship).toEqual(UNKNOWN_AUTHORSHIP);
            }
        });

        it('passes the Start authorship the version recorded to the domain dialog (toolbar and Start node)', () => {
            dialogOpen.mockReturnValue({ closed: of(null) });
            const [start] = flowService.nodes();
            const recorded = {
                ...UNKNOWN_AUTHORSHIP,
                created_by: liveStart.created_by,
                created_at: liveStart.created_at,
            };
            TestBed.inject(VersionPreviewNodeAuthorshipStore).replaceFromVersion(new Map([[start.id, recorded]]));

            component.onDomainClick();
            component.onOpenNodePanel(start);

            expect(dialogOpen.mock.calls.map(([, config]) => config.data.authorship)).toEqual([recorded, recorded]);
        });

        it('does not open the note dialog', () => {
            const [, note] = flowService.nodes();

            component.onOpenNodePanel(note);

            expect(dialogOpen).not.toHaveBeenCalled();
        });

        it('ignores panel saves and a full-save request', () => {
            const save = vi.spyOn(component.save, 'emit');
            const [, note] = flowService.nodes();

            component.onNodePanelSaved({ ...note, node_name: 'changed' });
            component.onNodePanelAutosaved({ ...note, node_name: 'changed' });
            component.emitSave();

            expect(save).not.toHaveBeenCalled();
        });
    });

    describe('editable (FLOW_EDITOR_PREVIEW = false)', () => {
        it('passes the saved Start and Note authorship to their windows (Start node and toolbar Domain button)', () => {
            const start = { ...createStartNode(), backendId: liveStart.id };
            const note = { ...noteNode(), backendId: liveNote.id };
            const fixture = mount(false, { nodes: [start, note], connections: [] }, () =>
                TestBed.inject(NodeAuthorshipStore).replaceFromGraph(liveGraph)
            );
            const component = fixture.componentInstance;
            const dialogOpen = (TestBed.inject(Dialog) as unknown as { open: ReturnType<typeof vi.fn> }).open;
            dialogOpen.mockReturnValue({ closed: of(null) });

            component.onOpenNodePanel(start);
            component.onDomainClick();
            component.onOpenNodePanel(note);

            const startAuthorship = authorshipOfRow(liveStart);
            expect(dialogOpen.mock.calls.map(([, config]) => config.data.authorship)).toEqual([
                startAuthorship,
                startAuthorship,
                authorshipOfRow(liveNote),
            ]);
        });

        it('passes dashes to the window of a node that is not saved yet', () => {
            const fixture = mount(false, { nodes: [createStartNode(), noteNode()], connections: [] }, () =>
                TestBed.inject(NodeAuthorshipStore).replaceFromGraph(liveGraph)
            );
            const dialogOpen = (TestBed.inject(Dialog) as unknown as { open: ReturnType<typeof vi.fn> }).open;
            dialogOpen.mockReturnValue({ closed: of(null) });

            fixture.componentInstance.onOpenNodePanel(noteNode());

            expect(dialogOpen.mock.calls[0][1].data.authorship).toEqual(UNKNOWN_AUTHORSHIP);
        });

        it('does not replay an earlier full-save request when the canvas is re-created', () => {
            const emitSave = vi.spyOn(FlowGraphComponent.prototype, 'emitSave').mockImplementation(() => undefined);

            // A save requested while an earlier canvas instance was alive.
            const fixture = mount(false, { nodes: [createStartNode()], connections: [] }, () =>
                TestBed.inject(SidePanelService).requestFullSave()
            );
            TestBed.tick();
            expect(emitSave).not.toHaveBeenCalled();

            // The effect is still live for requests made after creation.
            TestBed.inject(SidePanelService).requestFullSave();
            fixture.detectChanges();
            TestBed.tick();
            expect(emitSave).toHaveBeenCalledTimes(1);
        });
    });

    describe('viewport', () => {
        function fakeCanvas(): {
            transform: { position: { x: number; y: number }; scaledPosition: { x: number; y: number }; scale: number };
            redraw: ReturnType<typeof vi.fn>;
            fitToScreen: ReturnType<typeof vi.fn>;
            setScale: ReturnType<typeof vi.fn>;
        } {
            return {
                transform: { position: { x: 5, y: 5 }, scaledPosition: { x: 1, y: 2 }, scale: 1 },
                redraw: vi.fn(),
                fitToScreen: vi.fn(),
                setScale: vi.fn(),
            };
        }

        afterEach(() => vi.useRealTimers());

        it('applies initialViewport instead of fitting to screen, and captures it back', () => {
            const fixture = mount(false, { nodes: [createStartNode(), noteNode()], connections: [] });
            const component = fixture.componentInstance;
            const canvas = fakeCanvas();
            component['fCanvasComponent'] = canvas as unknown as FlowGraphComponent['fCanvasComponent'];
            component.initialViewport = { position: { x: -120, y: 40 }, scale: 0.6 };

            vi.useFakeTimers();
            component.onInitialized();
            vi.runAllTimers();

            expect(canvas.fitToScreen).not.toHaveBeenCalled();
            expect(canvas.redraw).toHaveBeenCalled();
            expect(component.captureViewport()).toEqual({ position: { x: -120, y: 40 }, scale: 0.6 });
        });

        it('fits to screen when no initialViewport is given', () => {
            const fixture = mount(false, { nodes: [createStartNode(), noteNode()], connections: [] });
            const component = fixture.componentInstance;
            const canvas = fakeCanvas();
            component['fCanvasComponent'] = canvas as unknown as FlowGraphComponent['fCanvasComponent'];

            vi.useFakeTimers();
            component.onInitialized();
            vi.runAllTimers();

            expect(canvas.fitToScreen).toHaveBeenCalled();
            // position + scaledPosition, as Foblex reports it
            expect(component.captureViewport()).toEqual({ position: { x: 6, y: 7 }, scale: 1 });
        });
    });

    describe('Viewer (no Flows:Update) in the live editor', () => {
        it('blocks edits with the read-only-access message, shown once, and still copies', () => {
            const fixture = mount(false, { nodes: [createStartNode(), noteNode()], connections: [] }, undefined, false);
            const component = fixture.componentInstance;
            const info = vi.spyOn(TestBed.inject(ToastService), 'info').mockImplementation(() => undefined);
            const copy = vi.spyOn(TestBed.inject(ClipboardService), 'copy');
            component['fFlowComponent'] = {
                getSelection: () => ({ fNodeIds: ['note-1'], fGroupIds: [], fConnectionIds: [] }),
            } as unknown as FlowGraphComponent['fFlowComponent'];

            component.onPaste();
            component.onDelete();
            component.onCopy();

            expect(component.editGestureTrigger()).toBe(false);
            expect(info).toHaveBeenCalledTimes(1);
            expect(info).toHaveBeenCalledWith('You have read-only access to this flow.');
            expect(copy).toHaveBeenCalled();
        });
    });

    describe('Flows:Update without Flows:Run (trigger nodes are read-only)', () => {
        let component: FlowGraphComponent;
        let flowService: FlowService;
        let toast: ToastService;

        beforeEach(() => {
            const fixture = mount(
                false,
                { nodes: [createStartNode(), noteNode(), scheduleTriggerNode()], connections: [] },
                // The real schedule panel, opened in the real panel shell by a test below; its form is not under test.
                () =>
                    TestBed.overrideComponent(ScheduleTriggerNodePanelComponent, {
                        set: { template: '', imports: [] },
                    }),
                true,
                false
            );
            component = fixture.componentInstance;
            flowService = TestBed.inject(FlowService);
            toast = TestBed.inject(ToastService);
        });

        function node(id: string): NodeModel {
            return flowService.nodes().find((candidate) => candidate.id === id) as NodeModel;
        }

        it('keeps a trigger node in place when a selection drag carries it along, but moves the others', () => {
            const info = vi.spyOn(toast, 'info').mockImplementation(() => undefined);
            const trigger = node('schedule-1');
            const note = node('note-1');

            component.onNodePositionChanged({ x: 600, y: 600 }, trigger);
            component.onNodePositionChanged({ x: 600, y: 0 }, note);

            expect(node('schedule-1').position).toEqual(trigger.position);
            // A new object, so Foblex takes the unchanged position again.
            expect(node('schedule-1').position).not.toBe(trigger.position);
            expect(node('note-1').position).toEqual({ x: 600, y: 0 });
            expect(info).toHaveBeenCalledWith(TRIGGER_NODES_NEED_RUN_MESSAGE);
        });

        it('does not add a trigger node from the context menu', () => {
            vi.spyOn(toast, 'info').mockImplementation(() => undefined);
            const nodesBefore = flowService.nodes();

            component.onAddNodeFromContextMenu({ type: NodeType.WEBHOOK_TRIGGER });

            expect(flowService.nodes()).toBe(nodesBefore);
        });

        it('pastes the copied nodes without the trigger nodes and says so', () => {
            const warning = vi.spyOn(toast, 'warning').mockImplementation(() => undefined);
            component['fFlowComponent'] = {
                getSelection: () => ({ fNodeIds: ['note-1', 'schedule-1'], fGroupIds: [], fConnectionIds: [] }),
                getPositionInFlow: (point: { x: number; y: number }) => point,
                select: vi.fn(),
                redraw: vi.fn(),
            } as unknown as FlowGraphComponent['fFlowComponent'];

            vi.useFakeTimers();

            component.onCopy();
            component.onPaste();
            // The paste selects the new nodes once they are on the canvas.
            vi.runAllTimers();
            vi.useRealTimers();

            const pastedTypes = flowService
                .nodes()
                .filter((candidate) => candidate.type !== NodeType.START)
                .filter((candidate) => !['note-1', 'schedule-1'].includes(candidate.id))
                .map((candidate) => candidate.type);
            expect(pastedTypes).toEqual([NodeType.NOTE]);
            expect(warning).toHaveBeenCalledWith(
                `1 trigger node was not pasted. ${TRIGGER_NODES_NEED_RUN_MESSAGE}`,
                6000,
                'bottom-right'
            );
        });

        it('blocks auto arrange instead of moving the trigger nodes', () => {
            const info = vi.spyOn(toast, 'info').mockImplementation(() => undefined);
            const nodesBefore = flowService.nodes();

            component.onAutoArrange();

            expect(component['isAutoArrangeBlockedByReadOnlyNodes']()).toBe(true);
            expect(flowService.nodes()).toBe(nodesBefore);
            expect(info).toHaveBeenCalledWith(
                expect.stringContaining('Auto arrange would move trigger nodes'),
                5000,
                'bottom-right'
            );
        });

        it('does not extract a selection with a trigger node into a subflow', () => {
            vi.spyOn(toast, 'info').mockImplementation(() => undefined);
            const extract = vi.fn();
            component.extractToSubflow.subscribe(extract);
            component['selectedNodeIds'].set(['note-1', 'schedule-1']);

            component['onExtractToSubflow']();

            expect(extract).not.toHaveBeenCalled();
        });

        it('saves the flow while a trigger node panel is open, as the read-only panel has nothing to commit', async () => {
            const shellFixture = TestBed.createComponent(NodePanelShellComponent);
            shellFixture.componentRef.setInput('node', node('schedule-1'));
            shellFixture.detectChanges();
            // The shell picks up the panel instance in a setTimeout(0) after the outlet renders.
            await new Promise((resolve) => setTimeout(resolve, 0));
            shellFixture.detectChanges();
            component['nodePanelShell'] = shellFixture.componentInstance;
            const save = vi.fn();
            component.save.subscribe(save);

            component.emitSave();

            expect(shellFixture.componentInstance.hasPanelInstance()).toBe(true);
            expect(shellFixture.componentInstance.isNodeReadOnly()).toBe(true);
            expect(save).toHaveBeenCalledWith(flowService.getFlowState());
            shellFixture.destroy();
        });

        it('still deletes a trigger node', () => {
            component['fFlowComponent'] = { select: vi.fn() } as unknown as FlowGraphComponent['fFlowComponent'];

            component.onDeleteNode(node('schedule-1'));

            expect(flowService.nodes().some((candidate) => candidate.id === 'schedule-1')).toBe(false);
        });
    });

    describe('partial import', () => {
        it('imports through the copy/import facade, which explains a refusal over trigger nodes to a user without Flows:Run', () => {
            const fixture = mount(false, { nodes: [createStartNode()], connections: [] });
            const component = fixture.componentInstance;
            component.currentFlowId = 3;
            const facadeImport = vi
                .spyOn(TestBed.inject(FlowCopyImportFacadeService), 'partialImport')
                .mockReturnValue(of({}));
            const directImport = vi.spyOn(TestBed.inject(ImportExportService), 'partialImport');
            vi.spyOn(TestBed.inject(ToastService), 'success').mockImplementation(() => undefined);
            const importComplete = vi.fn();
            component.importComplete.subscribe(importComplete);
            const file = new File(['{}'], 'nodes.json');

            component['doPartialImport'](file);

            expect(facadeImport).toHaveBeenCalledWith(3, file);
            expect(directImport).not.toHaveBeenCalled();
            expect(importComplete).toHaveBeenCalledTimes(1);
        });
    });

    describe('canvas template', () => {
        /** Stands in for the node body, which is not under test; Foblex's fNode sits on the same element. */
        @Component({ selector: 'app-flow-base-node', template: '' })
        class FlowBaseNodeStubComponent {
            readonly node = input<NodeModel>();
            readonly multiSelectActive = input<boolean>(false);
            readonly portMouseenter = output<void>();
            readonly editClicked = output<NodeModel>();
            readonly deleteClicked = output<NodeModel>();
            readonly unpackClicked = output<void>();
        }

        afterEach(() => vi.unstubAllGlobals());

        function draggingDisabledByNodeId(canRunFlows: boolean): Record<string, boolean> {
            // jsdom has neither layout nor ResizeObserver; Foblex only needs the observer to exist.
            vi.stubGlobal(
                'ResizeObserver',
                class {
                    observe(): void {}
                    unobserve(): void {}
                    disconnect(): void {}
                }
            );
            // Foblex warns that a canvas jsdom cannot lay out has zero height.
            vi.spyOn(console, 'warn').mockImplementation(() => undefined);
            vi.spyOn(console, 'error').mockImplementation(() => undefined);
            TestBed.configureTestingModule({
                providers: [
                    provideHttpClient(),
                    provideHttpClientTesting(),
                    {
                        provide: PermissionsService,
                        useValue: {
                            can: (_resource: unknown, action: ActionCode) => action !== ActionCode.Run || canRunFlows,
                            canAny: () => true,
                        },
                    },
                    { provide: Dialog, useValue: { open: vi.fn(), openDialogs: [] } },
                    NodeAuthorshipStore,
                ],
            });
            // The real template with the real Foblex canvas; the editor's other children render as unknown elements.
            TestBed.overrideComponent(FlowGraphComponent, {
                set: {
                    imports: [
                        FFlowModule,
                        FZoomDirective,
                        MatTooltipModule,
                        HasPermissionDirective,
                        ShortcutListenerDirective,
                        MouseTrackerDirective,
                        WaypointTooltipDirective,
                        FlowBaseNodeStubComponent,
                    ],
                    schemas: [NO_ERRORS_SCHEMA],
                },
            });
            const fixture = TestBed.createComponent(FlowGraphComponent);
            fixture.componentRef.setInput('flowState', {
                nodes: [noteNode(), scheduleTriggerNode()],
                connections: [],
            });
            fixture.detectChanges();
            const result = Object.fromEntries(
                fixture.debugElement.queryAll(By.directive(FNodeDirective)).map((element) => {
                    const fNode = element.injector.get(FNodeDirective);
                    return [fNode.fId(), fNode.fDraggingDisabled()];
                })
            );
            fixture.destroy();
            return result;
        }

        it('disables dragging on the trigger node only, for a user without Flows:Run', () => {
            expect(draggingDisabledByNodeId(false)).toEqual(
                expect.objectContaining({ 'note-1': false, 'schedule-1': true })
            );
        });

        it('lets a user who may run flows drag the trigger node', () => {
            expect(draggingDisabledByNodeId(true)).toEqual(
                expect.objectContaining({ 'note-1': false, 'schedule-1': false })
            );
        });
    });
});
