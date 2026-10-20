import { Dialog } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { CUSTOM_ELEMENTS_SCHEMA, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FCreateConnectionEvent, FDragStartedEvent, FReassignConnectionEvent } from '@foblex/flow';
import { NodeType, ShortcutSettings } from '@shared/models';
import { EMPTY, of } from 'rxjs';

import { GetGraphLightRequest } from '../../features/flows/models/graph.model';
import { PermissionsService } from '../../services/auth/permissions.service';
import { ProfileService } from '../../services/auth/profile.service';
import { ToastService } from '../../services/notifications';
import { CDT_ROUTE_CONTINUE_COPY } from '../components/node-panels/classification-decision-table-node-panel/cdt.constants';
import { generatePortsForClassificationDecisionTableNode, generatePortsForNode } from '../core/helpers/helpers';
import { subgraphNodeRequest } from '../core/helpers/subgraph-flows.util';
import { ConditionGroup } from '../core/models/decision-table.model';
import { FlowModel } from '../core/models/flow.model';
import { ClassificationDecisionTableNodeModel, GraphNoteModel, NodeModel } from '../core/models/node.model';
import { FLOW_EDITOR_PREVIEW } from '../core/providers/flow-editor-preview.token';
import { ClipboardService } from '../services/clipboard.service';
import { FlowService } from '../services/flow.service';
import { FlowReadOnlyService } from '../services/flow-readonly.service';
import { NodeAuthorshipStore } from '../services/node-authorship.store';
import { SidePanelService } from '../services/side-panel.service';
import { UndoRedoService } from '../services/undo-redo.service';
import { VersionPreviewNodeAuthorshipStore } from '../services/version-preview-node-authorship.store';
import { createFlowConnection } from '../utils/connection.factory';
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

// The real template pulls in the whole Foblex canvas, which jsdom cannot lay out, so the class
// is mounted with plain stand-ins for the canvas host and its minimap. A test whose handler
// reaches the Foblex canvas replaces `fFlowComponent` with a fake for just the calls it makes.
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
            ...(isPreview
                ? [
                      VersionPreviewNodeAuthorshipStore,
                      { provide: NodeAuthorshipStore, useExisting: VersionPreviewNodeAuthorshipStore },
                  ]
                : [NodeAuthorshipStore]),
        ],
    });
    TestBed.overrideComponent(FlowGraphComponent, {
        set: {
            template: '<f-flow #flowHost><f-minimap></f-minimap></f-flow>',
            imports: [],
            schemas: [CUSTOM_ELEMENTS_SCHEMA],
        },
    });
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

    describe('keyboard shortcuts', () => {
        let fixture: ComponentFixture<FlowGraphComponent>;
        let flowService: FlowService;
        const attached: HTMLElement[] = [];

        function press(init: KeyboardEventInit, target: EventTarget = window): void {
            target.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init }));
        }

        function attachInput(): HTMLInputElement {
            const input = document.createElement('input');
            document.body.appendChild(input);
            attached.push(input);
            return input;
        }

        function renameNote(name: string): void {
            const note = flowService.nodes().find((node) => node.id === 'note-1') as NodeModel;
            flowService.updateNode({ ...note, node_name: name });
        }

        function noteName(): string | undefined {
            return flowService.nodes().find((node) => node.id === 'note-1')?.node_name;
        }

        function startMultiSelect(): void {
            fixture.componentInstance['fFlowComponent'] = {
                select: vi.fn(),
            } as unknown as FlowGraphComponent['fFlowComponent'];
            fixture.componentInstance.onToggleMultiSelect();
        }

        beforeEach(() => {
            fixture = mount(false, { nodes: [createStartNode(), noteNode()], connections: [] });
            flowService = TestBed.inject(FlowService);
        });

        afterEach(() => attached.splice(0).forEach((element) => element.remove()));

        it('undoes the last change on Ctrl+Z', () => {
            TestBed.inject(UndoRedoService).stateChanged();
            renameNote('Renamed');

            press({ code: 'KeyZ', key: 'z', ctrlKey: true });

            expect(noteName()).toBe('Note');
        });

        it('undoes the last change on Ctrl+Z on a German layout', () => {
            TestBed.inject(UndoRedoService).stateChanged();
            renameNote('Renamed');

            press({ code: 'KeyY', key: 'z', ctrlKey: true });

            expect(noteName()).toBe('Note');
        });

        it.each([
            ['Backspace', { code: 'Backspace', key: 'Backspace' }],
            ['Delete', { code: 'Delete', key: 'Delete' }],
            ['Ctrl+Z', { code: 'KeyZ', key: 'z', ctrlKey: true }],
        ])('leaves the selected node alone on %s typed in a text field', (_label, init) => {
            fixture.componentInstance['fFlowComponent'] = {
                getSelection: () => ({ fNodeIds: ['note-1'], fGroupIds: [], fConnectionIds: [] }),
                select: vi.fn(),
            } as unknown as FlowGraphComponent['fFlowComponent'];
            TestBed.inject(UndoRedoService).stateChanged();
            renameNote('Renamed');

            press(init, attachInput());

            expect(noteName()).toBe('Renamed');
        });

        it('ends multi-select on Escape', () => {
            startMultiSelect();

            press({ code: 'Escape', key: 'Escape' });

            expect(fixture.componentInstance.selectionManager.multiSelectActive()).toBe(false);
        });

        it('ends multi-select on Escape pressed in a text field', () => {
            startMultiSelect();

            press({ code: 'Escape', key: 'Escape' }, attachInput());

            expect(fixture.componentInstance.selectionManager.multiSelectActive()).toBe(false);
        });

        it('stops handling keys once the editor is left', () => {
            TestBed.inject(UndoRedoService).stateChanged();
            renameNote('Renamed');
            fixture.destroy();

            press({ code: 'KeyZ', key: 'z', ctrlKey: true });

            expect(noteName()).toBe('Renamed');
        });
    });

    describe('node shortcuts', () => {
        const CANVAS_RECT = { left: 0, top: 0, width: 1000, height: 800 };

        let fixture: ComponentFixture<FlowGraphComponent>;
        let flowService: FlowService;
        let nodesBefore: number;

        function setUp(
            options: { isPreview?: boolean; canUpdateFlows?: boolean; beforeCreate?: () => void } = {}
        ): void {
            fixture = mount(
                options.isPreview ?? false,
                { nodes: [createStartNode(), noteNode()], connections: [] },
                options.beforeCreate,
                options.canUpdateFlows ?? true
            );
            TestBed.tick();
            flowService = TestBed.inject(FlowService);
            fixture.componentInstance['fFlowComponent'] = {
                getPositionInFlow: (point: { x: number; y: number }) => point,
                redraw: () => undefined,
            } as unknown as FlowGraphComponent['fFlowComponent'];
            vi.spyOn(canvasHost(), 'getBoundingClientRect').mockReturnValue(
                DOMRect.fromRect({ x: CANVAS_RECT.left, y: CANVAS_RECT.top, ...CANVAS_RECT })
            );
            nodesBefore = flowService.nodes().length;
        }

        function canvasHost(): HTMLElement {
            return fixture.nativeElement.querySelector('f-flow');
        }

        function hoverCanvasAt(clientX: number, clientY: number, target: Element = canvasHost()): void {
            target.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX, clientY }));
        }

        function shownToasts(): string[] {
            let messages: string[] = [];
            TestBed.inject(ToastService)
                .toasts$.subscribe((toasts) => (messages = toasts.map((toast) => toast.message)))
                .unsubscribe();
            return messages;
        }

        function leaveCanvas(): void {
            canvasHost().dispatchEvent(new PointerEvent('pointerleave'));
        }

        function press(init: KeyboardEventInit): void {
            window.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init }));
        }

        function pressShiftA(init: KeyboardEventInit = {}): void {
            press({ code: 'KeyA', key: 'A', shiftKey: true, ...init });
        }

        function pressShiftE(): void {
            press({ code: 'KeyE', key: 'E', shiftKey: true });
        }

        function addedNodes(): NodeModel[] {
            return flowService.nodes().slice(nodesBefore);
        }

        beforeEach(() => vi.useFakeTimers());

        afterEach(() => {
            vi.runOnlyPendingTimers();
            vi.useRealTimers();
        });

        it('adds the bound node where the pointer is on the canvas', () => {
            setUp();
            hoverCanvasAt(400, 300);

            pressShiftA();

            expect(addedNodes().map((node) => [node.type, node.position])).toEqual([
                [NodeType.AGENT, { x: 400, y: 300 }],
            ]);
        });

        it('adds the node at the canvas center once the pointer has left the canvas', () => {
            setUp();
            hoverCanvasAt(400, 300);
            leaveCanvas();

            pressShiftA();

            expect(addedNodes().map((node) => node.position)).toEqual([{ x: 500, y: 400 }]);
        });

        it('adds the node at the canvas center while the pointer is over the minimap', () => {
            setUp();
            hoverCanvasAt(400, 300);
            hoverCanvasAt(950, 750, canvasHost().querySelector('f-minimap') as Element);

            pressShiftA();

            expect(addedNodes().map((node) => node.position)).toEqual([{ x: 500, y: 400 }]);
        });

        it('adds the node by the key label on a layout where that key sits elsewhere (AZERTY Shift+A)', () => {
            setUp();
            hoverCanvasAt(400, 300);

            pressShiftA({ code: 'KeyQ' });

            expect(addedNodes().map((node) => node.type)).toEqual([NodeType.AGENT]);
        });

        it('adds one node when the key is held down', () => {
            setUp();
            hoverCanvasAt(400, 300);

            pressShiftA();
            pressShiftA({ repeat: true });
            pressShiftA({ repeat: true });

            expect(addedNodes()).toHaveLength(1);
        });

        it('removes the added node with one Ctrl+Z', () => {
            setUp();
            hoverCanvasAt(400, 300);
            pressShiftA();

            press({ code: 'KeyZ', key: 'z', ctrlKey: true });

            expect(flowService.nodes()).toHaveLength(nodesBefore);
        });

        it('adds an End node with Shift+E where the pointer is when the flow has none', () => {
            setUp();
            hoverCanvasAt(400, 300);

            pressShiftE();

            expect(addedNodes().map((node) => [node.type, node.position])).toEqual([
                [NodeType.END, { x: 400, y: 300 }],
            ]);
        });

        it('adds no second End node with Shift+E and says only one is allowed', () => {
            setUp();
            hoverCanvasAt(400, 300);
            pressShiftE();

            pressShiftE();

            expect(addedNodes().map((node) => node.type)).toEqual([NodeType.END]);
            expect(shownToasts()).toEqual(['Only one End node is allowed']);
        });

        it('removes the End node added with Shift+E with one Ctrl+Z', () => {
            setUp();
            hoverCanvasAt(400, 300);
            pressShiftE();
            expect(flowService.hasEndNode()).toBe(true);

            press({ code: 'KeyZ', key: 'z', ctrlKey: true });

            expect(flowService.nodes()).toHaveLength(nodesBefore);
            expect(flowService.hasEndNode()).toBe(false);
        });

        it.each([
            [
                'the flow is read-only for this user',
                { canUpdateFlows: false },
                'You have read-only access to this flow.',
            ],
            [
                'the canvas shows a version preview',
                { isPreview: true },
                'Preview mode is read-only. Exit preview to edit the flow',
            ],
        ])('adds nothing and says why when %s', (_label, options, message) => {
            setUp(options);
            hoverCanvasAt(400, 300);

            pressShiftA();

            expect(addedNodes()).toEqual([]);
            expect(shownToasts()).toEqual([message]);
        });

        it('adds nothing while a dialog is open', () => {
            setUp();
            (TestBed.inject(Dialog).openDialogs as unknown[]).push({});
            hoverCanvasAt(400, 300);

            pressShiftA();

            expect(addedNodes()).toEqual([]);
        });

        it('adds nothing while the node menu is open', () => {
            setUp();
            fixture.componentInstance.onContextMenu(new MouseEvent('contextmenu', { clientX: 100, clientY: 500 }));
            hoverCanvasAt(400, 300);

            pressShiftA();

            expect(addedNodes()).toEqual([]);
        });

        it('adds nothing while the flow is being saved', () => {
            setUp();
            fixture.componentRef.setInput('isSaving', true);
            fixture.detectChanges();
            hoverCanvasAt(400, 300);

            pressShiftA();

            expect(addedNodes()).toEqual([]);
        });

        it('still adds a node picked from the node menu where the menu was opened', () => {
            setUp();
            fixture.componentInstance.onContextMenu(new MouseEvent('contextmenu', { clientX: 100, clientY: 500 }));
            hoverCanvasAt(400, 300);

            fixture.componentInstance.onAddNodeFromContextMenu({ type: NodeType.PYTHON });

            expect(addedNodes().map((node) => [node.type, node.position])).toEqual([
                [NodeType.PYTHON, { x: 100, y: 500 }],
            ]);
            expect(fixture.componentInstance['showContextMenu']()).toBe(false);
        });

        describe('Subgraph shortcuts', () => {
            const CURRENT_FLOW: GetGraphLightRequest = { id: 1, uuid: 'uuid-1', name: 'This flow', description: '' };
            const BILLING: GetGraphLightRequest = {
                id: 12,
                uuid: 'uuid-12',
                name: 'Billing',
                description: 'Charges the card',
                tags: ['money'],
                label_ids: [4],
                save_version: 9,
            };
            const SUPPORT: GetGraphLightRequest = { id: 34, uuid: 'uuid-34', name: 'Support', description: '' };

            const SAVED_SHORTCUTS: ShortcutSettings = {
                overrides: {},
                custom: [
                    { action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: BILLING.id } },
                    { action: 'node.subgraph', keys: 'Alt+Digit2', params: { flowId: SUPPORT.id } },
                    { action: 'node.subgraph', keys: 'Alt+Digit3', params: { flowId: 99 } },
                    { action: 'node.subgraph', keys: 'Alt+Digit4', params: { flowId: CURRENT_FLOW.id } },
                ],
            };

            function setUpWithShortcuts(options: { canUpdateFlows?: boolean } = {}): void {
                setUp({
                    ...options,
                    beforeCreate: () =>
                        TestBed.overrideProvider(ProfileService, {
                            useValue: {
                                shortcutSettings: signal(SAVED_SHORTCUTS),
                                updateShortcutSettings: () => EMPTY,
                            },
                        }),
                });
                fixture.componentRef.setInput('currentFlowId', CURRENT_FLOW.id);
                fixture.componentRef.setInput('availableFlows', [CURRENT_FLOW, BILLING, SUPPORT]);
                fixture.detectChanges();
            }

            function pressAltDigit(digit: number): void {
                press({ code: `Digit${digit}`, key: String(digit), altKey: true });
            }

            function addedSubgraphs(): [NodeType, unknown, { x: number; y: number }][] {
                return addedNodes().map((node) => [node.type, node.data, node.position]);
            }

            it('adds a Subgraph node for the flow of the pressed key where the pointer is, as the Flows tab does', () => {
                setUpWithShortcuts();
                hoverCanvasAt(400, 300);

                pressAltDigit(1);
                hoverCanvasAt(100, 600);
                pressAltDigit(2);

                expect(addedSubgraphs()).toEqual([
                    [
                        NodeType.SUBGRAPH,
                        {
                            id: 12,
                            uuid: 'uuid-12',
                            name: 'Billing',
                            description: 'Charges the card',
                            tags: ['money'],
                        },
                        { x: 400, y: 300 },
                    ],
                    [
                        NodeType.SUBGRAPH,
                        { id: 34, uuid: 'uuid-34', name: 'Support', description: '', tags: [] },
                        { x: 100, y: 600 },
                    ],
                ]);
            });

            it('adds the same node data as picking the flow in the Flows tab', () => {
                setUpWithShortcuts();
                hoverCanvasAt(400, 300);
                pressAltDigit(1);
                fixture.componentInstance.onContextMenu(new MouseEvent('contextmenu', { clientX: 100, clientY: 500 }));

                fixture.componentInstance.onAddNodeFromContextMenu(subgraphNodeRequest(BILLING));

                const [fromKey, fromMenu] = addedNodes();
                expect(fromKey.data).toEqual(fromMenu.data);
            });

            it.each([
                ['a flow the user cannot see', 3],
                ['the flow being edited', 4],
            ])('adds nothing and says nothing for %s', (_case, digit) => {
                setUpWithShortcuts();
                hoverCanvasAt(400, 300);

                pressAltDigit(digit);

                expect(addedNodes()).toEqual([]);
                expect(shownToasts()).toEqual([]);
            });

            it('adds nothing and says why when the flow is read-only', () => {
                setUpWithShortcuts({ canUpdateFlows: false });
                hoverCanvasAt(400, 300);

                pressAltDigit(1);

                expect(addedNodes()).toEqual([]);
                expect(shownToasts()).toEqual(['You have read-only access to this flow.']);
            });
        });
    });

    describe('canvas panning', () => {
        let fixture: ComponentFixture<FlowGraphComponent>;
        let canvas: { transform: { position: { x: number; y: number } } };
        const attached: HTMLElement[] = [];

        function setUp(options: { isPreview?: boolean; canUpdateFlows?: boolean } = {}): void {
            fixture = mount(
                options.isPreview ?? false,
                { nodes: [createStartNode(), noteNode()], connections: [] },
                undefined,
                options.canUpdateFlows ?? true
            );
            const fake = {
                transform: { position: { x: 100, y: 100 } },
                getPosition(): { x: number; y: number } {
                    return fake.transform.position;
                },
                redraw: (): void => undefined,
                emitCanvasChangeEvent: (): void => undefined,
            };
            canvas = fake;
            fixture.componentInstance['fCanvasComponent'] = fake as unknown as FlowGraphComponent['fCanvasComponent'];
        }

        function press(init: KeyboardEventInit, target: EventTarget = document.body): KeyboardEvent {
            const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init });
            target.dispatchEvent(event);
            return event;
        }

        function attach<T extends HTMLElement>(element: T, parent: HTMLElement = document.body): T {
            parent.appendChild(element);
            attached.push(element);
            return element;
        }

        afterEach(() => attached.splice(0).forEach((element) => element.remove()));

        it.each([
            ['ArrowRight', {}, { x: 60, y: 100 }],
            ['ArrowLeft', {}, { x: 140, y: 100 }],
            ['ArrowDown', {}, { x: 100, y: 60 }],
            ['ArrowUp', {}, { x: 100, y: 140 }],
            ['ArrowRight', { ctrlKey: true }, { x: -100, y: 100 }],
            ['ArrowUp', { ctrlKey: true }, { x: 100, y: 300 }],
        ] as const)('moves the canvas on %s %o', (key, modifiers, expected) => {
            setUp();

            press({ code: key, key, ...modifiers });

            expect(canvas.transform.position).toEqual(expected);
        });

        it('keeps moving while the key is held', () => {
            setUp();

            press({ code: 'ArrowRight', key: 'ArrowRight' });
            press({ code: 'ArrowRight', key: 'ArrowRight', repeat: true });
            press({ code: 'ArrowRight', key: 'ArrowRight', repeat: true });

            expect(canvas.transform.position).toEqual({ x: -20, y: 100 });
        });

        it.each([
            ['the flow is read-only', { canUpdateFlows: false }],
            ['the canvas shows a version preview', { isPreview: true }],
        ])('still moves the canvas when %s', (_case, options) => {
            setUp(options);

            press({ code: 'ArrowRight', key: 'ArrowRight' });

            expect(canvas.transform.position).toEqual({ x: 60, y: 100 });
        });

        it('does not move the canvas from a text field', () => {
            setUp();
            const input = document.createElement('input');
            document.body.appendChild(input);
            attached.push(input);

            press({ code: 'ArrowRight', key: 'ArrowRight' }, input);

            expect(canvas.transform.position).toEqual({ x: 100, y: 100 });
        });

        it('moves the canvas when the key comes from inside the canvas', () => {
            setUp();
            const insideCanvas = attach(
                document.createElement('button'),
                fixture.nativeElement.querySelector('f-flow') as HTMLElement
            );

            press({ code: 'ArrowRight', key: 'ArrowRight' }, insideCanvas);

            expect(canvas.transform.position).toEqual({ x: 60, y: 100 });
        });

        it('leaves arrows on a focused element outside the canvas to that element', () => {
            setUp();
            const outside = attach(document.createElement('button'));

            const event = press({ code: 'ArrowDown', key: 'ArrowDown' }, outside);

            expect(canvas.transform.position).toEqual({ x: 100, y: 100 });
            expect(event.defaultPrevented).toBe(false);
        });

        it('does not move the canvas while a dialog is open', () => {
            setUp();
            (TestBed.inject(Dialog).openDialogs as unknown[]).push({});

            press({ code: 'ArrowRight', key: 'ArrowRight' });

            expect(canvas.transform.position).toEqual({ x: 100, y: 100 });
        });

        it('does not move the canvas while the node menu is open', () => {
            setUp();
            fixture.componentInstance.onContextMenu(new MouseEvent('contextmenu', { clientX: 100, clientY: 500 }));

            press({ code: 'ArrowRight', key: 'ArrowRight' });

            expect(canvas.transform.position).toEqual({ x: 100, y: 100 });
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

    // The Continue rule's canvas half: a route-code output whose row has Continue on
    // cannot be wired, by drawing a connection or by dragging an existing one onto it.
    describe('Classification Decision Table route ports with Continue on', () => {
        const BLOCKED_PORT = 'table1_decision-route-approve';
        const OPEN_PORT = 'table1_decision-route-reject';

        function rule(routeCode: string, continueFlag: boolean, order: number): ConditionGroup {
            return {
                group_name: routeCode,
                group_type: 'simple',
                expression: null,
                conditions: [],
                manipulation: null,
                next_node: null,
                order,
                route_code: routeCode,
                continue_flag: continueFlag,
                dock_visible: true,
            };
        }

        function tableNode(): ClassificationDecisionTableNodeModel {
            const rows = [rule('approve', true, 1), rule('reject', false, 2)];
            return {
                id: 'table1',
                backendId: null,
                type: NodeType.CLASSIFICATION_TABLE,
                node_name: 'Triage',
                data: { name: 'Triage', table: { condition_groups: rows } },
                position: { x: 0, y: 0 },
                ports: generatePortsForClassificationDecisionTableNode('table1', rows),
                color: '',
                icon: '',
                size: { width: 300, height: 200 },
                input_map: {},
                output_variable_path: null,
            } as unknown as ClassificationDecisionTableNodeModel;
        }

        function pythonNode(id: string): NodeModel {
            return {
                id,
                backendId: null,
                type: NodeType.PYTHON,
                node_name: id,
                data: {},
                position: { x: 400, y: 0 },
                ports: generatePortsForNode(id, NodeType.PYTHON),
                color: '',
                icon: '',
                size: { width: 200, height: 100 },
                input_map: {},
                output_variable_path: null,
            } as unknown as NodeModel;
        }

        let component: FlowGraphComponent;
        let flowService: FlowService;
        let warning: ReturnType<typeof vi.spyOn>;

        function setUp(connections: FlowModel['connections'] = []): void {
            const fixture = mount(false, {
                nodes: [tableNode(), pythonNode('py1'), pythonNode('py2')],
                connections,
            });
            component = fixture.componentInstance;
            flowService = TestBed.inject(FlowService);
            warning = vi.spyOn(TestBed.inject(ToastService), 'warning').mockImplementation(() => undefined);
        }

        function connect(fOutputId: string, fInputId: string): void {
            component.onConnectionAdded({ fOutputId, fInputId } as unknown as FCreateConnectionEvent);
        }

        it('refuses to wire a route code whose row has Continue on, and says why', () => {
            setUp();

            connect(BLOCKED_PORT, 'py1_python-in');

            expect(flowService.connections()).toEqual([]);
            expect(warning).toHaveBeenCalledExactlyOnceWith(
                CDT_ROUTE_CONTINUE_COPY.routePortBlockedByContinue,
                5000,
                'bottom-right'
            );
        });

        it('wires a route code whose row has Continue off', () => {
            setUp();

            connect(OPEN_PORT, 'py1_python-in');

            expect(flowService.connections().map((connection) => connection.sourcePortId)).toEqual([OPEN_PORT]);
            expect(warning).not.toHaveBeenCalled();
        });

        it('leaves connections from other node types alone', () => {
            setUp();

            connect('py1_python-out', 'py2_python-in');

            expect(flowService.connections().map((connection) => connection.sourcePortId)).toEqual(['py1_python-out']);
            expect(warning).not.toHaveBeenCalled();
        });

        it('refuses to move an existing connection onto a blocked route port', () => {
            const existing = createFlowConnection('table1', 'py1', OPEN_PORT, 'py1_python-in');
            setUp([existing]);

            component.onReassignConnection({
                connectionId: existing.id,
                endpoint: 'source',
                nextSourceId: BLOCKED_PORT,
            } as unknown as FReassignConnectionEvent);

            expect(flowService.connections().map((connection) => connection.sourcePortId)).toEqual([OPEN_PORT]);
            expect(warning).toHaveBeenCalledExactlyOnceWith(
                CDT_ROUTE_CONTINUE_COPY.routePortBlockedByContinue,
                5000,
                'bottom-right'
            );
        });

        it('still moves a connection to a new target from an open route port', () => {
            const existing = createFlowConnection('table1', 'py1', OPEN_PORT, 'py1_python-in');
            setUp([existing]);

            component.onReassignConnection({
                connectionId: existing.id,
                endpoint: 'target',
                nextTargetId: 'py2_python-in',
            } as unknown as FReassignConnectionEvent);

            expect(flowService.connections().map((connection) => connection.targetPortId)).toEqual(['py2_python-in']);
            expect(warning).not.toHaveBeenCalled();
        });
    });
});
