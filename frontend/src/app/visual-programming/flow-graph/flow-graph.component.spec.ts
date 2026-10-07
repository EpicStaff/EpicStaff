import { Dialog } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FDragStartedEvent } from '@foblex/flow';
import { NodeType } from '@shared/models';
import { of } from 'rxjs';

import { PermissionsService } from '../../services/auth/permissions.service';
import { ToastService } from '../../services/notifications';
import { FlowModel } from '../core/models/flow.model';
import { GraphNoteModel, NodeModel } from '../core/models/node.model';
import { FLOW_EDITOR_PREVIEW } from '../core/providers/flow-editor-preview.token';
import { ClipboardService } from '../services/clipboard.service';
import { FlowService } from '../services/flow.service';
import { FlowReadOnlyService } from '../services/flow-readonly.service';
import { NodeAuthorshipStore } from '../services/node-authorship.store';
import { SidePanelService } from '../services/side-panel.service';
import { UndoRedoService } from '../services/undo-redo.service';
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

function mount(
    isPreview: boolean,
    flowState: FlowModel,
    beforeCreate: () => void = () => undefined,
    canUpdateFlows = true
): ComponentFixture<FlowGraphComponent> {
    TestBed.configureTestingModule({
        providers: [
            provideHttpClient(),
            provideHttpClientTesting(),
            { provide: FLOW_EDITOR_PREVIEW, useValue: isPreview },
            // Read-only from permissions (a Viewer) only where a test asks for it.
            { provide: PermissionsService, useValue: { can: () => canUpdateFlows } },
            { provide: Dialog, useValue: { open: vi.fn(), openDialogs: [] } },
            // Provided by the flow page (live editor) or by FLOW_EDITOR_STATE_PROVIDERS (version preview).
            NodeAuthorshipStore,
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
                // The preview's own store is never filled (a snapshot has no authorship): the footer shows dashes.
                expect(config.data.authorship).toEqual(UNKNOWN_AUTHORSHIP);
            }
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
});
