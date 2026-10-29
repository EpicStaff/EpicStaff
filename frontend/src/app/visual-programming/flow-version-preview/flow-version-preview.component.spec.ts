import { Dialog } from '@angular/cdk/dialog';
import { Type } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { FDragStartedEvent } from '@foblex/flow';
import { NodeType, UserSummary } from '@shared/models';
import { Subject } from 'rxjs';

import { GetGraphLightRequest, GraphVersionDto, RestoreWarning } from '../../features/flows/models/graph.model';
import {
    GraphVersionSnapshot,
    PreviewGraphVersionResponse,
    SnapshotNodeAuthorship,
} from '../../features/flows/models/graph-version-preview.model';
import { FlowsApiService } from '../../features/flows/services/flows-api.service';
import { PermissionsService } from '../../services/auth/permissions.service';
import { ToastService } from '../../services/notifications';
import { FlowModel } from '../core/models/flow.model';
import { FlowGraphComponent } from '../flow-graph/flow-graph.component';
import { CdtExplanationStoreService } from '../services/cdt-explanation-store.service';
import { ClipboardService } from '../services/clipboard.service';
import { FlowService } from '../services/flow.service';
import { FlowDiffStateService } from '../services/flow-diff-state.service';
import { FlowReadOnlyService } from '../services/flow-readonly.service';
import { FlowTestRunService } from '../services/flow-test-run.service';
import { NodeAuthorshipStore } from '../services/node-authorship.store';
import { NodeFactoryService } from '../services/node-factory.service';
import { SavedFlowStateService } from '../services/saved-flow-state.service';
import { ScheduleTriggerRuntimeService } from '../services/schedule-trigger-runtime.service';
import { SidePanelService } from '../services/side-panel.service';
import { UndoRedoService } from '../services/undo-redo.service';
import { buildPreviewFlowModel } from '../utils/load';
import { liveClassificationTable, liveKeyValue, livePython, liveWebhook } from '../utils/testing/live-graph.fixture';
import { exported, liveGraphSnapshot } from '../utils/testing/version-snapshot.fixture';
import { FlowVersionPreviewComponent } from './flow-version-preview.component';

const EDITOR_SERVICES: Type<unknown>[] = [
    FlowService,
    UndoRedoService,
    FlowReadOnlyService,
    SidePanelService,
    SavedFlowStateService,
    ScheduleTriggerRuntimeService,
    ClipboardService,
    NodeFactoryService,
    CdtExplanationStoreService,
    FlowTestRunService,
    FlowDiffStateService,
];

const CREATOR: UserSummary = { id: 7, display_name: 'Ivan Bohun', avatar_url: null };
const LAST_EDITOR: UserSummary = { id: 8, display_name: 'Olena Pchilka', avatar_url: null };
const NOTHING_RECORDED: SnapshotNodeAuthorship = {
    created_by: null,
    created_at: null,
    last_edited_by: null,
    last_edited_at: null,
};

function version(id: number): GraphVersionDto {
    return { id, graph_id: 1, name: `Version ${id}`, description: '', created_at: '2026-01-01T00:00:00Z' };
}

const START_UUID = '00000000-0000-4000-8000-000000000001';
const PYTHON_UUID = '00000000-0000-4000-8000-000000000002';
const KEY_VALUE_UUID = '00000000-0000-4000-8000-000000000003';

/** A snapshot with a Start node and one Python node named after the version. */
function snapshotFor(pythonNodeName: string): GraphVersionSnapshot {
    return {
        nodes: [
            { id: 1, uuid: START_UUID, node_type: 'StartNode', node_name: '__start__', variables: {}, metadata: {} },
            {
                id: 2,
                uuid: PYTHON_UUID,
                node_type: 'PythonNode',
                node_number: 1,
                node_name: pythonNodeName,
                metadata: {},
                input_map: {},
                output_variable_path: null,
                test_input: {},
                python_code: { code: 'def main(): pass', entrypoint: 'main', libraries: '' },
            },
        ],
        edge_list: [],
    };
}

/** A snapshot with a Start node and one Python node per `[number, name]`; the number keys its id and uuid. */
function snapshotWithPythons(pythons: ReadonlyArray<[number, string]>): GraphVersionSnapshot {
    const [startNode, pythonTemplate] = snapshotFor('Template').nodes;
    return {
        nodes: [
            startNode,
            ...pythons.map(([number, name]) => ({
                ...pythonTemplate,
                id: 10 + number,
                uuid: `00000000-0000-4000-8000-${String(100 + number).padStart(12, '0')}`,
                node_number: number,
                node_name: name,
            })),
        ],
        edge_list: [],
    };
}

/** A live canvas with the nodes of `snapshotWithPythons(pythons)` (same uuids, other canvas ids). */
function liveCanvasOf(pythons: ReadonlyArray<[number, string]>): FlowModel {
    return buildPreviewFlowModel(snapshotWithPythons(pythons), new Map(), []).flow;
}

/** The canvas with its Start node only. */
function onlyStart(flow: FlowModel): FlowModel {
    return { nodes: flow.nodes.filter((node) => node.type === NodeType.START), connections: [] };
}

/** The same snapshot saved before nodes had a uuid. */
function oldSnapshotFor(pythonNodeName: string): GraphVersionSnapshot {
    const snapshot = snapshotFor(pythonNodeName);
    return { ...snapshot, nodes: snapshot.nodes.map((node) => ({ ...node, uuid: undefined })) };
}

/** `snapshotFor(pythonNodeName)` plus a Key-Value node (snapshot id 3) whose stored table the backend could not re-bind. */
function snapshotWithUnboundTable(pythonNodeName: string): GraphVersionSnapshot {
    const snapshot = snapshotFor(pythonNodeName);
    const keyValueNode = exported('KeyValueNode', {
        ...liveKeyValue,
        id: 3,
        uuid: KEY_VALUE_UUID,
        node_name: 'Remember',
        key_value_table: null,
        key_value_table_name: 'Customers',
    });
    return { ...snapshot, nodes: [...snapshot.nodes, keyValueNode] };
}

/** A `venv_ref_cleared` warning on a node of `liveGraphSnapshot`, for the venv of the code `field` names. */
function clearedVenvWarning(nodeId: number, nodeName: string, field: string): RestoreWarning {
    return {
        type: 'venv_ref_cleared',
        node_id: nodeId,
        node_name: nodeName,
        field,
        missing_id: 31,
        reason: 'venv not found or not in org',
    };
}

/** Venv warnings on each node type whose code has one: only the Python panel shows the venv field. */
const CLEARED_VENV_WARNINGS: RestoreWarning[] = [
    clearedVenvWarning(livePython.id, 'Python', 'python_code'),
    clearedVenvWarning(liveWebhook.id, 'Webhook', 'python_code'),
    clearedVenvWarning(liveClassificationTable.id, 'Classify', 'pre_python_code'),
    clearedVenvWarning(liveClassificationTable.id, 'Classify', 'post_python_code'),
];

const BINNED_SECRET_WARNING: RestoreWarning = {
    type: 'secret_in_recycle_bin',
    node_id: 2,
    node_name: 'Python',
    field: 'python_code',
    reason: 'Secret "API_KEY" is in the recycle bin.',
};

// jsdom has no ResizeObserver; the dialog buttons' collapse-on-overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

/** Spies on every method of a root service instance. */
function spyOnAllMethods(service: object): ReturnType<typeof vi.spyOn>[] {
    const prototype = Object.getPrototypeOf(service) as object;
    return Object.getOwnPropertyNames(prototype)
        .filter((name) => name !== 'constructor')
        .filter((name) => typeof Object.getOwnPropertyDescriptor(prototype, name)?.value === 'function')
        .map((name) => vi.spyOn(service as Record<string, () => unknown>, name));
}

/** A live canvas holding the same nodes as `snapshotFor(pythonNodeName)` (same uuids, other canvas ids). */
function liveCanvasWith(pythonNodeName: string): FlowModel {
    return buildPreviewFlowModel(snapshotFor(pythonNodeName), new Map(), []).flow;
}

describe('FlowVersionPreviewComponent', () => {
    let responses: Map<number, Subject<PreviewGraphVersionResponse>>;
    let fixture: ComponentFixture<FlowVersionPreviewComponent>;
    let liveFlow: FlowModel;

    beforeEach(() => {
        responses = new Map();
        liveFlow = { nodes: [], connections: [] };
        TestBed.configureTestingModule({
            providers: [
                {
                    provide: FlowsApiService,
                    useValue: {
                        previewGraphVersion: (versionId: number) => {
                            const response = new Subject<PreviewGraphVersionResponse>();
                            responses.set(versionId, response);
                            return response;
                        },
                    },
                },
                { provide: Dialog, useValue: { open: vi.fn(), openDialogs: [] } },
                // A user who may edit flows: any read-only below comes from the preview itself.
                { provide: PermissionsService, useValue: { can: () => true } },
                // The live editor's store, which the flow page around the preview provides.
                NodeAuthorshipStore,
            ],
        });
        // jsdom cannot lay out the Foblex canvas; the handlers under test do not need it.
        TestBed.overrideComponent(FlowGraphComponent, { set: { template: '', imports: [] } });
    });

    afterEach(() => vi.restoreAllMocks());

    async function render(versionId: number): Promise<void> {
        fixture.componentRef.setInput('liveFlow', liveFlow);
        fixture.componentRef.setInput('version', version(versionId));
        fixture.detectChanges();
        // Not whenStable(): a loading resource keeps the app unstable until its response arrives.
        TestBed.tick();
        await Promise.resolve();
    }

    async function respond(versionId: number, pythonNodeName: string, warnings: RestoreWarning[] = []): Promise<void> {
        await respondWith(versionId, snapshotFor(pythonNodeName), warnings);
    }

    async function respondWith(
        versionId: number,
        snapshot: GraphVersionSnapshot,
        warnings: RestoreWarning[] = [],
        nodeAuthorship: Record<string, SnapshotNodeAuthorship> = {},
        resolvedSecrets: Record<string, number> = {}
    ): Promise<void> {
        const response = responses.get(versionId)!;
        response.next({ snapshot, warnings, node_authorship: nodeAuthorship, resolved_secrets: resolvedSecrets });
        response.complete();
        await fixture.whenStable();
        fixture.detectChanges();
    }

    function previewFlowService(): FlowService {
        return fixture.debugElement.injector.get(FlowService);
    }

    function flowGraph(): FlowGraphComponent {
        return fixture.debugElement.query(By.directive(FlowGraphComponent)).componentInstance as FlowGraphComponent;
    }

    function element(): HTMLElement {
        return fixture.nativeElement as HTMLElement;
    }

    type PreviewTab = 'Preview' | 'Changes';

    function tabButton(tab: PreviewTab): HTMLButtonElement {
        return Array.from(element().querySelectorAll<HTMLButtonElement>('.preview-bar__tabs button')).find(
            (button) => button.textContent?.trim() === tab
        )!;
    }

    function activeTab(): string | null {
        return element().querySelector('.preview-bar__tabs button[aria-pressed="true"]')?.textContent?.trim() ?? null;
    }

    /** Whether Esc, pressed with nothing else open, exits the preview. */
    function exitsOnEscape(): boolean {
        const closed = vi.fn();
        const subscription = fixture.componentInstance.closed.subscribe(closed);
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        subscription.unsubscribe();
        return closed.mock.calls.length === 1;
    }

    /**
     * The fit-to-screen spy of the shown graph. jsdom cannot lay out the Foblex canvas (the graph template is
     * emptied above), so the graph gets a stand-in canvas that only records being asked to fit.
     */
    function canvasFit(): ReturnType<typeof vi.fn> | null {
        const graph = fixture.debugElement.query(By.directive(FlowGraphComponent))?.componentInstance as
            | FlowGraphComponent
            | undefined;
        if (!graph) return null;
        graph['fCanvasComponent'] ??= { fitToScreen: vi.fn() } as unknown as FlowGraphComponent['fCanvasComponent'];
        return graph['fCanvasComponent'].fitToScreen as unknown as ReturnType<typeof vi.fn>;
    }

    function openTab(tab: PreviewTab): void {
        canvasFit();
        tabButton(tab).click();
        fixture.detectChanges();
    }

    function summaryText(): string | null {
        return element().querySelector('.preview-changes__summary')?.textContent?.trim() ?? null;
    }

    function hintText(): string | null {
        return element().querySelector('.preview-changes__hint')?.textContent?.trim() ?? null;
    }

    function previewNode(type: NodeType) {
        return previewFlowService()
            .nodes()
            .find((node) => node.type === type)!;
    }

    function statusOf(type: NodeType) {
        return fixture.debugElement.injector.get(FlowDiffStateService).nodeStatus(previewNode(type).id);
    }

    describe('Preview and Changes tabs', () => {
        it('opens on the Preview tab, showing the version as saved', async () => {
            liveFlow = liveCanvasWith('Live python');
            fixture = TestBed.createComponent(FlowVersionPreviewComponent);
            await render(1);
            await respond(1, 'Version python');

            expect(activeTab()).toBe('Preview');
            expect(previewNode(NodeType.PYTHON).node_name).toBe('Version python');
            expect(flowGraph().diffState()).toBeNull();
            expect(statusOf(NodeType.PYTHON)).toBeNull();
            expect(summaryText()).toBeNull();
        });

        it('shows what a restore does to the live canvas on Changes, and the version as saved again on Preview', async () => {
            liveFlow = liveCanvasWith('Live python');
            fixture = TestBed.createComponent(FlowVersionPreviewComponent);
            await render(1);
            await respond(1, 'Version python');
            const plainNodeIds = previewFlowService()
                .nodes()
                .map((node) => node.id);

            openTab('Changes');

            expect(activeTab()).toBe('Changes');
            expect(previewNode(NodeType.PYTHON).node_name).toBe('Version python');
            expect(statusOf(NodeType.PYTHON)).toBe('changed');
            expect(statusOf(NodeType.START)).toBe('unchanged');
            expect(flowGraph().diffState()).not.toBeNull();
            expect(summaryText()).toBe('Restoring this version will change 1 node.');

            openTab('Preview');

            expect(activeTab()).toBe('Preview');
            expect(flowGraph().diffState()).toBeNull();
            expect(summaryText()).toBeNull();
            expect(
                previewFlowService()
                    .nodes()
                    .map((node) => node.id)
            ).toEqual(plainNodeIds);
        });

        it('fits the canvas to the screen after each switch', async () => {
            fixture = TestBed.createComponent(FlowVersionPreviewComponent);
            await render(1);
            await respond(1, 'Python');
            const fitToScreen = canvasFit()!;

            openTab('Changes');
            await new Promise((resolve) => setTimeout(resolve));
            expect(fitToScreen).toHaveBeenCalledTimes(1);

            openTab('Preview');
            await new Promise((resolve) => setTimeout(resolve));
            expect(fitToScreen).toHaveBeenCalledTimes(2);
        });

        it('keeps a multi-selection when the open tab is clicked again', async () => {
            fixture = TestBed.createComponent(FlowVersionPreviewComponent);
            await render(1);
            await respond(1, 'Python');
            openTab('Changes');
            const selection = flowGraph().selectionManager;
            selection.multiSelectActive.set(true);
            selection.selectedNodeIds.set([previewNode(NodeType.PYTHON).id]);

            openTab('Changes');

            expect(selection.multiSelectActive()).toBe(true);
            expect(selection.selectedNodeIds()).toEqual([previewNode(NodeType.PYTHON).id]);
        });

        it('shows a node only the live canvas has, which a restore removes', async () => {
            liveFlow = liveCanvasWith('Python');
            fixture = TestBed.createComponent(FlowVersionPreviewComponent);
            await render(1);
            await respondWith(1, { ...snapshotFor('Python'), nodes: snapshotFor('Python').nodes.slice(0, 1) });

            openTab('Changes');

            expect(previewNode(NodeType.PYTHON).node_name).toBe('Python');
            expect(statusOf(NodeType.PYTHON)).toBe('deleted');
        });

        it('keeps the canvas (and its node ids) when the live canvas changes while previewing', async () => {
            liveFlow = liveCanvasWith('Python');
            fixture = TestBed.createComponent(FlowVersionPreviewComponent);
            await render(1);
            await respond(1, 'Python');
            openTab('Changes');
            const idsBefore = previewFlowService()
                .nodes()
                .map((node) => node.id);

            fixture.componentRef.setInput('liveFlow', liveCanvasWith('Python after a save'));
            fixture.detectChanges();

            expect(
                previewFlowService()
                    .nodes()
                    .map((node) => node.id)
            ).toEqual(idsBefore);
            expect(statusOf(NodeType.PYTHON)).toBe('unchanged');
        });

        it('stays on Changes when another version is previewed, and compares that version', async () => {
            liveFlow = liveCanvasWith('Python');
            fixture = TestBed.createComponent(FlowVersionPreviewComponent);
            await render(1);
            await respond(1, 'Python');
            openTab('Changes');
            expect(statusOf(NodeType.PYTHON)).toBe('unchanged');

            await render(2);
            await respond(2, 'Renamed python');

            expect(activeTab()).toBe('Changes');
            expect(previewNode(NodeType.PYTHON).node_name).toBe('Renamed python');
            expect(statusOf(NodeType.PYTHON)).toBe('changed');
            expect(summaryText()).toBe('Restoring this version will change 1 node.');
        });

        it('compares with the live canvas as it is when Changes is first opened', async () => {
            liveFlow = liveCanvasWith('Python');
            fixture = TestBed.createComponent(FlowVersionPreviewComponent);
            await render(1);
            await respond(1, 'Python');

            fixture.componentRef.setInput('liveFlow', liveCanvasWith('Renamed on the live canvas'));
            fixture.detectChanges();
            openTab('Changes');

            expect(statusOf(NodeType.PYTHON)).toBe('changed');
            expect(summaryText()).toBe('Restoring this version will change 1 node.');
        });

        it('shows the same comparison (and node ids) after going to Preview and back to Changes', async () => {
            liveFlow = liveCanvasWith('Python');
            fixture = TestBed.createComponent(FlowVersionPreviewComponent);
            await render(1);
            await respond(1, 'Python');
            openTab('Changes');
            const diffNodeIds = previewFlowService()
                .nodes()
                .map((node) => node.id);
            openTab('Preview');

            fixture.componentRef.setInput('liveFlow', liveCanvasWith('Renamed on the live canvas'));
            fixture.detectChanges();
            openTab('Changes');

            expect(
                previewFlowService()
                    .nodes()
                    .map((node) => node.id)
            ).toEqual(diffNodeIds);
            expect(statusOf(NodeType.PYTHON)).toBe('unchanged');
        });

        describe('with a node panel open', () => {
            function openPanelNodeId(): string | null {
                return fixture.debugElement.injector.get(SidePanelService).selectedNodeId();
            }

            it('keeps the panel on the same node across both switches', async () => {
                liveFlow = liveCanvasWith('Live python');
                fixture = TestBed.createComponent(FlowVersionPreviewComponent);
                await render(1);
                await respond(1, 'Version python');
                flowGraph().openNodePanel(previewNode(NodeType.PYTHON).id);
                const plainPythonId = previewNode(NodeType.PYTHON).id;

                openTab('Changes');

                expect(openPanelNodeId()).toBe(previewNode(NodeType.PYTHON).id);
                expect(openPanelNodeId()).not.toBe(plainPythonId);

                openTab('Preview');

                expect(openPanelNodeId()).toBe(plainPythonId);
            });

            it('closes the panel of a node only the live canvas has, and Esc exits afterwards', async () => {
                liveFlow = liveCanvasWith('Python');
                fixture = TestBed.createComponent(FlowVersionPreviewComponent);
                const closed = vi.fn();
                fixture.componentInstance.closed.subscribe(closed);
                await render(1);
                await respondWith(1, { ...snapshotFor('Python'), nodes: snapshotFor('Python').nodes.slice(0, 1) });
                openTab('Changes');
                expect(statusOf(NodeType.PYTHON)).toBe('deleted');
                flowGraph().openNodePanel(previewNode(NodeType.PYTHON).id);

                openTab('Preview');

                expect(openPanelNodeId()).toBeNull();
                document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
                expect(closed).toHaveBeenCalledTimes(1);
            });

            it('clears a multi-selection made on the previous canvas', async () => {
                fixture = TestBed.createComponent(FlowVersionPreviewComponent);
                await render(1);
                await respond(1, 'Python');
                const selection = flowGraph().selectionManager;
                selection.multiSelectActive.set(true);
                selection.selectedNodeIds.set([previewNode(NodeType.PYTHON).id]);

                openTab('Changes');

                expect(selection.multiSelectActive()).toBe(false);
                expect(selection.selectedNodeIds()).toEqual([]);
            });
        });

        it('opens on Preview again in a preview opened after the preview is closed', async () => {
            fixture = TestBed.createComponent(FlowVersionPreviewComponent);
            // The host page destroys the preview when it emits closed.
            fixture.componentInstance.closed.subscribe(() => fixture.destroy());
            await render(1);
            await respond(1, 'Python');
            openTab('Changes');
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));

            fixture = TestBed.createComponent(FlowVersionPreviewComponent);
            await render(1);
            await respond(1, 'Python');

            expect(activeTab()).toBe('Preview');
            expect(flowGraph().diffState()).toBeNull();
        });

        describe('summary (nodes only)', () => {
            const versionWithoutPython: GraphVersionSnapshot = {
                ...snapshotFor('Python'),
                nodes: snapshotFor('Python').nodes.slice(0, 1),
            };
            // The version has an edge Start → Python the live canvas lacks; the nodes are the same.
            const versionWithEdge: GraphVersionSnapshot = {
                ...snapshotFor('Python'),
                edge_list: [{ id: 1, start_node_id: 1, end_node_id: 2, metadata: {} }],
            } as GraphVersionSnapshot;

            it.each<{ diff: string; live: () => FlowModel; snapshot: GraphVersionSnapshot; expected: string }>([
                {
                    diff: 'one renamed node',
                    live: () => liveCanvasWith('Live python'),
                    snapshot: snapshotFor('Version python'),
                    expected: 'Restoring this version will change 1 node.',
                },
                {
                    diff: 'one node only the live canvas has',
                    live: () => liveCanvasWith('Python'),
                    snapshot: versionWithoutPython,
                    expected: 'Restoring this version will remove 1 node.',
                },
                {
                    diff: 'two version-only nodes and a renamed one',
                    live: () => liveCanvasOf([[1, 'First']]),
                    snapshot: snapshotWithPythons([
                        [1, 'First renamed'],
                        [2, 'Second'],
                        [3, 'Third'],
                    ]),
                    expected: 'Restoring this version will add 2 nodes and change 1 node.',
                },
                {
                    diff: 'nodes of every kind',
                    live: () =>
                        liveCanvasOf([
                            [1, 'One'],
                            [2, 'Two'],
                            [3, 'Three'],
                            [6, 'Only live'],
                        ]),
                    snapshot: snapshotWithPythons([
                        [1, 'One v2'],
                        [2, 'Two v2'],
                        [3, 'Three v2'],
                        [4, 'Four'],
                        [5, 'Five'],
                    ]),
                    expected: 'Restoring this version will add 2 nodes, remove 1 node and change 3 nodes.',
                },
                {
                    diff: 'only an edge',
                    live: () => liveCanvasWith('Python'),
                    snapshot: versionWithEdge,
                    expected: 'Restoring this version will only change connections, no nodes.',
                },
                {
                    diff: 'nothing',
                    live: () => liveCanvasWith('Python'),
                    snapshot: snapshotFor('Python'),
                    expected: 'Restoring this version will not change any nodes or connections.',
                },
            ])('reads "$expected" when $diff differs', async ({ live, snapshot, expected }) => {
                liveFlow = live();
                fixture = TestBed.createComponent(FlowVersionPreviewComponent);
                await render(1);
                await respondWith(1, snapshot);
                expect(summaryText()).toBeNull();

                openTab('Changes');

                expect(summaryText()).toBe(expected);
                // An empty diff still shows the canvas.
                expect(element().querySelector('app-flow-graph')).not.toBeNull();
            });

            it('does not count a missing reference as a change', async () => {
                liveFlow = buildPreviewFlowModel(snapshotWithUnboundTable('Python'), new Map(), []).flow;
                fixture = TestBed.createComponent(FlowVersionPreviewComponent);
                await render(1);
                await respondWith(1, snapshotWithUnboundTable('Python'));

                openTab('Changes');

                expect(summaryText()).toBe('Restoring this version will not change any nodes or connections.');
            });
        });

        describe('old-snapshot hint', () => {
            const HINT =
                'This version was saved before nodes could be matched, so every node shows as added or removed.';

            it('explains why every node is added or removed when the version predates node matching', async () => {
                liveFlow = liveCanvasWith('Python');
                fixture = TestBed.createComponent(FlowVersionPreviewComponent);
                await render(1);
                await respondWith(1, oldSnapshotFor('Python'));
                expect(hintText()).toBeNull();

                openTab('Changes');

                // The Start nodes are still paired (by type); every other node is added or removed.
                expect(summaryText()).toBe('Restoring this version will add 1 node and remove 1 node.');
                expect(hintText()).toBe(HINT);

                openTab('Preview');
                expect(hintText()).toBeNull();
            });

            it.each<[string, () => FlowModel, GraphVersionSnapshot]>([
                ['the nodes match', () => liveCanvasWith('Python'), snapshotFor('Python')],
                [
                    'the live canvas has only its Start node',
                    () => onlyStart(liveCanvasWith('Python')),
                    oldSnapshotFor('Python'),
                ],
                [
                    'the version has only its Start node',
                    () => liveCanvasWith('Python'),
                    { ...oldSnapshotFor('Python'), nodes: oldSnapshotFor('Python').nodes.slice(0, 1) },
                ],
            ])('is not shown when %s', async (_case, live, snapshot) => {
                liveFlow = live();
                fixture = TestBed.createComponent(FlowVersionPreviewComponent);
                await render(1);
                await respondWith(1, snapshot);

                openTab('Changes');

                expect(summaryText()).not.toBeNull();
                expect(hintText()).toBeNull();
            });
        });

        it('leaves the version as saved working when the comparison fails', async () => {
            const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
            liveFlow = { nodes: [null], connections: [] } as unknown as FlowModel;
            fixture = TestBed.createComponent(FlowVersionPreviewComponent);
            await render(1);
            await respond(1, 'Python');

            expect(element().querySelector('.preview-state--error')).toBeNull();
            expect(previewNode(NodeType.PYTHON).node_name).toBe('Python');

            openTab('Changes');

            expect(element().querySelector('.preview-state--error')?.textContent).toContain(
                'The changes could not be shown. Switch to Preview to see the version.'
            );
            expect(consoleError).toHaveBeenCalled();

            openTab('Preview');

            expect(element().querySelector('.preview-state--error')).toBeNull();
            expect(element().querySelector('app-flow-graph')).not.toBeNull();
        });
    });

    describe('missing-reference markers', () => {
        const DROPPED_SECRET_WARNING: RestoreWarning = {
            type: 'secret_declaration_dropped',
            node_id: 2,
            node_name: 'Python',
            field: 'python_code',
            missing_name: 'GONE_KEY',
            reason: 'Secret "GONE_KEY" no longer exists.',
        };

        function markedNodeTypes(): NodeType[] {
            const diffState = fixture.debugElement.injector.get(FlowDiffStateService);
            return previewFlowService()
                .nodes()
                .filter((node) => diffState.hasMissingReferences(node.id))
                .map((node) => node.type);
        }

        // Read from the preview's own FlowDiffStateService, which the nodes read for their marker: the graph
        // template is emptied in this spec (jsdom cannot lay out the Foblex canvas), so no node is in the DOM.
        it.each<{ steps: string; tabs: PreviewTab[] }>([
            { steps: 'Preview', tabs: [] },
            { steps: 'Changes', tabs: ['Changes'] },
            { steps: 'Changes, then back to Preview', tabs: ['Changes', 'Preview'] },
        ])(
            'on $steps, marks the node with a deleted secret and the one with an unbound Key-Value table',
            async ({ tabs }) => {
                liveFlow = buildPreviewFlowModel(snapshotWithUnboundTable('Python'), new Map(), []).flow;
                fixture = TestBed.createComponent(FlowVersionPreviewComponent);
                await render(1);
                await respondWith(1, snapshotWithUnboundTable('Python'), [DROPPED_SECRET_WARNING]);

                tabs.forEach(openTab);

                expect(markedNodeTypes()).toEqual([NodeType.PYTHON, NodeType.KEY_VALUE]);
            }
        );

        it('shows only the markers on Preview: no statuses and no diff', async () => {
            liveFlow = buildPreviewFlowModel(snapshotWithUnboundTable('Live python'), new Map(), []).flow;
            fixture = TestBed.createComponent(FlowVersionPreviewComponent);
            await render(1);
            await respondWith(1, snapshotWithUnboundTable('Version python'), [DROPPED_SECRET_WARNING]);

            const diffState = fixture.debugElement.injector.get(FlowDiffStateService);
            expect(markedNodeTypes()).toEqual([NodeType.PYTHON, NodeType.KEY_VALUE]);
            expect(diffState.isActive()).toBe(false);
            expect(
                previewFlowService()
                    .nodes()
                    .map((node) => diffState.nodeStatus(node.id))
            ).toEqual([null, null, null]);
            expect(flowGraph().diffState()).toBeNull();
        });

        // The webhook and table panels have no venv field, so this marker and the warnings dialog are where
        // their cleared venv shows.
        it.each<{ steps: string; tabs: PreviewTab[] }>([
            { steps: 'Preview', tabs: [] },
            { steps: 'Changes', tabs: ['Changes'] },
        ])('on $steps, marks every node whose venv is gone, with or without a venv field', async ({ tabs }) => {
            fixture = TestBed.createComponent(FlowVersionPreviewComponent);
            await render(1);
            await respondWith(1, liveGraphSnapshot, CLEARED_VENV_WARNINGS);

            tabs.forEach(openTab);

            expect(markedNodeTypes().sort()).toEqual(
                [NodeType.PYTHON, NodeType.WEBHOOK_TRIGGER, NodeType.CLASSIFICATION_TABLE].sort()
            );
        });

        it('does not mark a node whose secret is only in the recycle bin', async () => {
            fixture = TestBed.createComponent(FlowVersionPreviewComponent);
            await render(1);
            await respond(1, 'Python', [BINNED_SECRET_WARNING]);

            expect(markedNodeTypes()).toEqual([]);
        });
    });

    it('gets its own instance of every flow-editor service', () => {
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);
        for (const service of EDITOR_SERVICES) {
            expect(fixture.debugElement.injector.get(service)).not.toBe(TestBed.inject(service));
        }
    });

    it('is read-only inside (panels, grids, dialogs) while the live editor stays editable', () => {
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);

        expect(fixture.debugElement.injector.get(FlowReadOnlyService).isReadOnly()).toBe(true);
        expect(TestBed.inject(FlowReadOnlyService).isReadOnly()).toBe(false);
    });

    it('never touches the live (root) editor services', async () => {
        const rootSpies = EDITOR_SERVICES.flatMap((service) => spyOnAllMethods(TestBed.inject(service) as object));
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);

        await render(1);
        await respond(1, 'Preview python');
        const graph = flowGraph();
        const pythonNode = previewFlowService()
            .nodes()
            .find((node) => node.type === NodeType.PYTHON)!;
        expect(pythonNode.node_name).toBe('Preview python');

        // Empty selection: a real copy is handed to the live clipboard on purpose (covered below).
        graph['fFlowComponent'] = {
            getSelection: () => ({ fNodeIds: [], fGroupIds: [], fConnectionIds: [] }),
        } as unknown as FlowGraphComponent['fFlowComponent'];
        graph.onOpenNodePanel(pythonNode);
        graph.onDragStarted({ fData: { fNodeIds: [pythonNode.id] } } as unknown as FDragStartedEvent);
        graph.onCopy();
        graph.onDelete();
        graph.onDeleteNode(pythonNode);
        graph.onUndo();
        fixture.detectChanges();

        expect(fixture.debugElement.injector.get(SidePanelService).selectedNodeId()).toBe(pythonNode.id);
        for (const spy of rootSpies) {
            expect(spy, spy.getMockName()).not.toHaveBeenCalled();
        }
    });

    it('renders only the latest version when the version changes before the first loads', async () => {
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);
        await render(1);
        const firstResponse = responses.get(1)!;
        await render(2);

        expect(firstResponse.observed).toBe(false);
        await respond(2, 'Second');
        firstResponse.next({ snapshot: snapshotFor('First'), warnings: [], node_authorship: {}, resolved_secrets: {} });
        fixture.detectChanges();

        const names = previewFlowService()
            .nodes()
            .map((node) => node.node_name);
        expect(names).toContain('Second');
        expect(names).not.toContain('First');
    });

    it('shows the tabs and the warning count', async () => {
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);
        await render(1);
        await respond(1, 'Python', [
            { type: 'fk_nulled', node_id: 2, reason: 'LLM config is missing' },
            { type: 'node_skipped', reason: 'Unsupported node' },
        ]);

        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelector('.preview-bar__warnings')?.textContent).toContain('2 warnings');
        expect(
            Array.from(element.querySelectorAll('.preview-bar__tabs button')).map((tab) => tab.textContent?.trim())
        ).toEqual(['Preview', 'Changes']);
    });

    describe('warnings dialog', () => {
        beforeEach(() => {
            // The real dialog, so the warnings are read and clicked like a user does.
            TestBed.overrideProvider(Dialog, { useFactory: () => new Dialog() });
            vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        });

        afterEach(() => {
            TestBed.inject(Dialog).closeAll();
            vi.unstubAllGlobals();
        });

        function openWarnings(): HTMLElement[] {
            (element().querySelector('.preview-bar__warnings') as HTMLButtonElement).click();
            TestBed.tick();
            return Array.from(document.querySelectorAll<HTMLElement>('app-restore-warnings-dialog .warning-item'));
        }

        function warningText(item: HTMLElement): string {
            return item.textContent!.replace(/\s+/g, ' ').trim();
        }

        it('lists the backend warnings and the Key-Value table only the frontend finds, as text', async () => {
            fixture = TestBed.createComponent(FlowVersionPreviewComponent);
            await render(1);
            await respondWith(1, snapshotWithUnboundTable('Python'), [BINNED_SECRET_WARNING]);

            expect(element().querySelector('.preview-bar__warnings')?.textContent).toContain('2 warnings');
            expect(openWarnings().map(warningText)).toEqual([
                'In node Python, Secret "API_KEY" is in the recycle bin.',
                'In node Remember, Key-Value table "Customers" no longer exists or cannot be used, so the node has no table.',
            ]);
        });

        it('lists a cleared venv with the backend reason, for every node type', async () => {
            fixture = TestBed.createComponent(FlowVersionPreviewComponent);
            await render(1);
            await respondWith(1, liveGraphSnapshot, CLEARED_VENV_WARNINGS);

            const reason = 'venv not found or not in org';
            expect(openWarnings().map(warningText)).toEqual([
                `In node Python, ${reason}`,
                `In node Webhook, ${reason}`,
                `In node Classify, ${reason}`,
                `In node Classify, ${reason}`,
            ]);
        });

        it('shows the warnings button for a Key-Value table alone', async () => {
            fixture = TestBed.createComponent(FlowVersionPreviewComponent);
            await render(1);
            await respondWith(1, snapshotWithUnboundTable('Python'));

            expect(element().querySelector('.preview-bar__warnings')?.textContent).toContain('1 warning');
        });

        it('renders a table name as text, never as markup', async () => {
            const snapshot = snapshotWithUnboundTable('Python');
            const keyValueNode = { ...snapshot.nodes[2], key_value_table_name: '<img src=x onerror=alert(1)>' };
            fixture = TestBed.createComponent(FlowVersionPreviewComponent);
            await render(1);
            await respondWith(1, { ...snapshot, nodes: [...snapshot.nodes.slice(0, 2), keyValueNode] });

            const [item] = openWarnings();
            expect(item.querySelector('img')).toBeNull();
            expect(warningText(item)).toContain('Key-Value table "<img src=x onerror=alert(1)>"');
        });

        it.each([
            { mode: 'the version as saved', showChanges: false, entry: 0, type: NodeType.PYTHON },
            { mode: 'the version as saved', showChanges: false, entry: 1, type: NodeType.KEY_VALUE },
            { mode: 'the changes', showChanges: true, entry: 0, type: NodeType.PYTHON },
            { mode: 'the changes', showChanges: true, entry: 1, type: NodeType.KEY_VALUE },
        ])(
            'on $mode, opens the $type node of a clicked warning on the shown canvas',
            async ({ showChanges, entry, type }) => {
                liveFlow = liveCanvasWith('Live python');
                fixture = TestBed.createComponent(FlowVersionPreviewComponent);
                await render(1);
                await respondWith(1, snapshotWithUnboundTable('Python'), [BINNED_SECRET_WARNING]);
                if (showChanges) openTab('Changes');

                openWarnings()[entry].click();
                fixture.detectChanges();

                expect(fixture.debugElement.injector.get(SidePanelService).selectedNodeId()).toBe(previewNode(type).id);
                expect(TestBed.inject(SidePanelService).selectedNodeId()).toBeNull();
            }
        );
    });

    it('hands nodes copied in the preview to the live clipboard and says so', async () => {
        const info = vi.fn();
        const success = vi.spyOn(TestBed.inject(ToastService), 'success').mockImplementation(info);
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);
        await render(1);
        await respond(1, 'Copied python');
        const pythonNode = previewFlowService()
            .nodes()
            .find((node) => node.type === NodeType.PYTHON)!;
        const previewClipboard = fixture.debugElement.injector.get(ClipboardService);
        previewClipboard.copy({ fNodeIds: [pythonNode.id], fGroupIds: [], fConnectionIds: [] });

        flowGraph().copied.emit();

        const liveClipboard = TestBed.inject(ClipboardService);
        expect(liveClipboard).not.toBe(previewClipboard);
        expect(liveClipboard.getClipboardData()?.nodes.map((node) => node.node_name)).toEqual(['Copied python']);
        expect(success).toHaveBeenCalledWith('Copied', 2000, 'bottom-right');
    });

    it('does not reload when the previewed version is only renamed', async () => {
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);
        await render(1);
        const firstResponse = responses.get(1)!;
        await respond(1, 'Python');

        fixture.componentRef.setInput('version', { ...version(1), name: 'Renamed' });
        fixture.detectChanges();
        TestBed.tick();

        expect(responses.get(1)).toBe(firstResponse);
    });

    // F-01: slow network, then the user exits before the response arrives.
    it('shows the loading state with Esc available, and cancels the request on exit', async () => {
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);
        await render(1);
        const element = fixture.nativeElement as HTMLElement;

        expect(element.querySelector('app-spinner')).not.toBeNull();
        expect(exitsOnEscape()).toBe(true);

        fixture.destroy();
        expect(responses.get(1)!.observed).toBe(false);
    });

    // F-06: six fast clicks; only the last version's request stays alive and renders.
    it('keeps only the last of several fast version switches', async () => {
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);
        for (let versionId = 1; versionId <= 6; versionId++) {
            await render(versionId);
        }

        for (let versionId = 1; versionId <= 5; versionId++) {
            expect(responses.get(versionId)!.observed).toBe(false);
        }
        await respond(6, 'Sixth');
        expect(
            previewFlowService()
                .nodes()
                .map((node) => node.node_name)
        ).toContain('Sixth');
    });

    // The secrets list needs a permission members and viewers lack; the preview response alone is enough.
    it('links the declared secrets the backend resolved, and leaves out the ones it did not', async () => {
        const snapshot: GraphVersionSnapshot = {
            ...snapshotFor('Python'),
            secret_declarations: { nodes: { '2': { python_code: ['API_KEY', 'GONE_KEY'] } } },
        };
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);
        await render(1);
        await respondWith(1, snapshot, [], {}, { API_KEY: 12 });

        const pythonNode = previewFlowService()
            .nodes()
            .find((node) => node.type === NodeType.PYTHON)!;
        expect(pythonNode.data).toEqual(expect.objectContaining({ secret_ids: [12], secret_names: ['API_KEY'] }));
    });

    it('keeps Esc available when the version fails to load', async () => {
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);
        await render(1);
        responses.get(1)!.error(new Error('boom'));
        await fixture.whenStable();
        fixture.detectChanges();

        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelector('.preview-state--error')).not.toBeNull();
        expect(exitsOnEscape()).toBe(true);
    });

    it('previews an old snapshot that lacks fields newer exports carry', async () => {
        // Older exports: no graph metadata, edge lists or secret declarations; nodes without metadata
        // or the newer optional fields; python code without libraries.
        const oldSnapshot = {
            nodes: [
                { id: 1, node_type: 'StartNode', node_name: '__start__', variables: {} },
                {
                    id: 2,
                    node_type: 'PythonNode',
                    node_name: 'Old python',
                    input_map: {},
                    python_code: { code: 'def main(): pass', entrypoint: 'main' },
                },
            ],
        } as unknown as GraphVersionSnapshot;
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);
        await render(1);
        await respondWith(1, oldSnapshot);

        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelector('.preview-state--error')).toBeNull();
        expect(
            previewFlowService()
                .nodes()
                .map((node) => node.node_name)
        ).toContain('Old python');
    });

    it('shows the error state, not a crash, when the snapshot cannot be mapped', async () => {
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
        const brokenSnapshot = { nodes: [null], edge_list: [] } as unknown as GraphVersionSnapshot;
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);
        await render(1);
        await respondWith(1, brokenSnapshot);

        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelector('.preview-state--error')).not.toBeNull();
        expect(element.querySelector('app-flow-graph')).toBeNull();
        expect(exitsOnEscape()).toBe(true);
        expect(consoleError).toHaveBeenCalled();
    });

    describe('node authorship', () => {
        /** What this preview's own store gives the node details of the Start node (snapshot id 1) and the Python node (2). */
        function previewAuthorshipOfNodes(): SnapshotNodeAuthorship[] {
            const store = fixture.debugElement.injector.get(NodeAuthorshipStore);
            return previewFlowService()
                .nodes()
                .map((node) => store.authorshipOf(node));
        }

        beforeEach(() => {
            fixture = TestBed.createComponent(FlowVersionPreviewComponent);
        });

        it('gives each node the authorship the version recorded for it, and dashes to a node it has none for', async () => {
            const pythonAuthorship: SnapshotNodeAuthorship = {
                created_by: CREATOR,
                created_at: '2026-03-12T13:28:23Z',
                last_edited_by: LAST_EDITOR,
                last_edited_at: '2026-04-01T09:05:00Z',
            };
            await render(1);
            await respondWith(1, snapshotFor('Python'), [], { '2': pythonAuthorship });

            expect(previewAuthorshipOfNodes()).toEqual([NOTHING_RECORDED, pythonAuthorship]);
        });

        it('keeps the moment of a user who left the organization, whose user the version holds as null', async () => {
            const leftAuthorship: SnapshotNodeAuthorship = {
                created_by: null,
                created_at: '2026-03-12T13:28:23Z',
                last_edited_by: null,
                last_edited_at: '2026-04-01T09:05:00Z',
            };
            await render(1);
            await respondWith(1, snapshotFor('Python'), [], { '2': leftAuthorship });

            expect(previewAuthorshipOfNodes()[1]).toEqual(leftAuthorship);
        });

        it('gives every node dashes for a version saved before node authorship was recorded', async () => {
            await render(1);
            await respondWith(1, snapshotFor('Python'), [], {});

            expect(previewAuthorshipOfNodes()).toEqual([NOTHING_RECORDED, NOTHING_RECORDED]);
        });

        it('keeps each node its recorded authorship when the canvas is rebuilt with new node ids', async () => {
            const pythonAuthorship: SnapshotNodeAuthorship = { ...NOTHING_RECORDED, created_by: CREATOR };
            await render(1);
            await respondWith(1, snapshotFor('Python'), [], { '2': pythonAuthorship });
            const pythonNodeBefore = previewFlowService()
                .nodes()
                .find((node) => node.type === NodeType.PYTHON)!;

            // A new list of flows the user can open rebuilds the preview canvas.
            fixture.componentRef.setInput('flowsLight', [{ id: 99 } as GetGraphLightRequest]);
            fixture.detectChanges();

            const pythonNodeAfter = previewFlowService()
                .nodes()
                .find((node) => node.type === NodeType.PYTHON)!;
            expect(pythonNodeAfter.id).not.toBe(pythonNodeBefore.id);
            expect(previewAuthorshipOfNodes()).toEqual([NOTHING_RECORDED, pythonAuthorship]);
        });

        it('never writes the live (flow page) store', async () => {
            const liveStore = TestBed.inject(NodeAuthorshipStore);
            const liveStoreSpies = spyOnAllMethods(liveStore);
            await render(1);
            await respondWith(1, snapshotFor('Python'), [], { '2': { ...NOTHING_RECORDED, created_by: CREATOR } });

            expect(fixture.debugElement.injector.get(NodeAuthorshipStore)).not.toBe(liveStore);
            for (const spy of liveStoreSpies) {
                expect(spy, spy.getMockName()).not.toHaveBeenCalled();
            }
        });

        it('drops the authorship of the previous version when another version is previewed', async () => {
            const firstAuthorship: SnapshotNodeAuthorship = { ...NOTHING_RECORDED, created_by: CREATOR };
            const secondAuthorship: SnapshotNodeAuthorship = { ...NOTHING_RECORDED, created_by: LAST_EDITOR };
            await render(1);
            await respondWith(1, snapshotFor('First'), [], { '2': firstAuthorship });
            const firstPythonNode = previewFlowService()
                .nodes()
                .find((node) => node.type === NodeType.PYTHON)!;

            await render(2);
            await respondWith(2, snapshotFor('Second'), [], { '2': secondAuthorship });

            const store = fixture.debugElement.injector.get(NodeAuthorshipStore);
            expect(store.authorshipOf(firstPythonNode)).toEqual(NOTHING_RECORDED);
            expect(previewAuthorshipOfNodes()).toEqual([NOTHING_RECORDED, secondAuthorship]);
        });
    });

    describe('Esc', () => {
        let closed: ReturnType<typeof vi.fn<() => void>>;

        beforeEach(async () => {
            fixture = TestBed.createComponent(FlowVersionPreviewComponent);
            closed = vi.fn<() => void>();
            fixture.componentInstance.closed.subscribe(closed);
            await render(1);
            await respond(1, 'Python');
        });

        function pressEscape(target: EventTarget = document): void {
            target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        }

        it('exits the preview', () => {
            pressEscape();
            expect(closed).toHaveBeenCalledTimes(1);
        });

        it('ignores other keys', () => {
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            expect(closed).not.toHaveBeenCalled();
        });

        it('leaves an open dialog to close first', () => {
            (TestBed.inject(Dialog).openDialogs as unknown[]).push({});
            pressEscape();
            expect(closed).not.toHaveBeenCalled();
        });

        it('leaves an open node panel to close first', () => {
            fixture.debugElement.injector.get(SidePanelService).setSelectedNodeId(previewFlowService().nodes()[1].id);
            pressEscape();
            expect(closed).not.toHaveBeenCalled();
        });

        it('leaves an active multi-select to clear first', () => {
            flowGraph().selectionManager.multiSelectActive.set(true);
            pressEscape();
            expect(closed).not.toHaveBeenCalled();
        });

        it('does nothing while the user is typing in a field', () => {
            const input = document.body.appendChild(document.createElement('input'));
            pressEscape(input);
            input.remove();
            expect(closed).not.toHaveBeenCalled();
        });

        it('leaves Esc pressed in the shortcuts popover to the popover', () => {
            const popover = document.body.appendChild(document.createElement('app-shortcuts-modal'));
            const button = popover.appendChild(document.createElement('button'));
            pressEscape(button);
            popover.remove();
            expect(closed).not.toHaveBeenCalled();
        });

        it('exits when pressed on a tab after clicking it', () => {
            openTab('Changes');
            pressEscape(tabButton('Changes'));
            expect(closed).toHaveBeenCalledTimes(1);
        });

        it('stops listening once the preview is gone', () => {
            fixture.destroy();
            pressEscape();
            expect(closed).not.toHaveBeenCalled();
        });
    });
});
