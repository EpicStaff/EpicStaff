import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { AuthorshipDetailsDialogService } from '@shared/components';
import { NodeType } from '@shared/models';
import { of } from 'rxjs';

import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { EndNodeModel, NodeModel, PythonNodeModel, SubGraphNodeModel } from '../../../core/models/node.model';
import { FLOW_EDITOR_PREVIEW } from '../../../core/providers/flow-editor-preview.token';
import { FlowService } from '../../../services/flow.service';
import { NodeAuthorshipStore } from '../../../services/node-authorship.store';
import { SidePanelService } from '../../../services/side-panel.service';
import { liveEnd, liveGraph, livePython, liveSubgraph } from '../../../utils/testing/live-graph.fixture';
import { ConditionalEdgeNodePanelComponent } from '../conditional-edge-node-panel/conditional-edge-node-panel.component';
import { EndNodePanelComponent } from '../end-node-panel/end-node-panel.component';
import { PythonNodePanelComponent } from '../python-node-panel/python-node-panel.component';
import { SubGraphNodePanelComponent } from '../subgraph-node-panel/subgraph-node-panel.component';
import { NodePanelShellComponent } from './node-panel-shell.component';

// The End panel is the lightest real BaseSidePanel; its template (a JSON editor) is irrelevant
// here, so it is emptied. The shell itself is rendered for real.
const endNode: EndNodeModel = {
    id: 'end-1',
    backendId: null,
    type: NodeType.END,
    node_name: '__end_node__',
    data: { output_map: { answer: 'variables.answer' } },
    position: { x: 0, y: 0 },
    ports: null,
    color: '',
    icon: '',
    size: { width: 200, height: 100 },
    input_map: {},
    output_variable_path: null,
};

async function mount(isPreview: boolean): Promise<ComponentFixture<NodePanelShellComponent>> {
    TestBed.configureTestingModule({
        providers: [
            { provide: FLOW_EDITOR_PREVIEW, useValue: isPreview },
            // A user who may edit flows: read-only below comes from the preview alone.
            { provide: PermissionsService, useValue: { can: () => true } },
            NodeAuthorshipStore,
        ],
        // The shell passes `graphId` to every panel; the End panel does not declare it
        // (a dev-mode console error in the app, a thrown error under TestBed's default).
        errorOnUnknownProperties: false,
    });
    TestBed.overrideComponent(EndNodePanelComponent, { set: { template: '', imports: [] } });
    TestBed.inject(FlowService).setFlow({ nodes: [endNode], connections: [] });
    TestBed.inject(SidePanelService).setSelectedNodeId(endNode.id);

    const fixture = TestBed.createComponent(NodePanelShellComponent);
    fixture.componentRef.setInput('node', endNode);
    fixture.detectChanges();
    // The shell picks up the panel instance in a setTimeout(0) after the outlet renders.
    await new Promise((resolve) => setTimeout(resolve, 0));
    fixture.detectChanges();
    return fixture;
}

function panelOf(fixture: ComponentFixture<NodePanelShellComponent>): EndNodePanelComponent {
    return fixture.debugElement.query((element) => element.componentInstance instanceof EndNodePanelComponent)
        .componentInstance as EndNodePanelComponent;
}

describe('NodePanelShellComponent', () => {
    afterEach(() => vi.restoreAllMocks());

    describe('version preview', () => {
        it('disables the panel form, never saves or autosaves; Ctrl+S explains, Esc closes', async () => {
            const fixture = await mount(true);
            const shell = fixture.componentInstance;
            const panel = panelOf(fixture);
            const onSave = vi.spyOn(panel, 'onSave');
            const onSaveSilently = vi.spyOn(panel, 'onSaveSilently');
            const emitted: NodeModel[] = [];
            shell.save.subscribe((node) => emitted.push(node));
            shell.autosave.subscribe((node) => emitted.push(node));
            const sidePanel = TestBed.inject(SidePanelService);
            const info = vi.spyOn(TestBed.inject(ToastService), 'info').mockImplementation(() => undefined);

            expect(panel.form.disabled).toBe(true);
            // Even with a pending edit (from a widget outside the form) nothing is saved.
            panel.onOutputMapChange('{"changed": "value"}');
            fixture.detectChanges();
            expect(fixture.nativeElement.querySelector('.save-btn')).toBeNull();

            sidePanel.triggerAutosave();
            fixture.detectChanges();
            shell['onShortcutSave']();
            expect(info).toHaveBeenCalledWith(
                expect.stringContaining('Preview mode is read-only'),
                3000,
                'bottom-right'
            );
            expect(sidePanel.selectedNodeId()).toBe(endNode.id);

            shell['onEscape']();
            expect(sidePanel.selectedNodeId()).toBeNull();

            expect(onSave).not.toHaveBeenCalled();
            expect(onSaveSilently).not.toHaveBeenCalled();
            expect(emitted).toEqual([]);
        });
    });

    describe('editable', () => {
        it('keeps the form enabled and autosaves through the panel', async () => {
            const fixture = await mount(false);
            const panel = panelOf(fixture);
            const onSave = vi.spyOn(panel, 'onSave');

            expect(panel.form.enabled).toBe(true);

            panel.onOutputMapChange('{"changed": "value"}');
            fixture.detectChanges();
            TestBed.inject(SidePanelService).triggerAutosave();
            fixture.detectChanges();

            expect(onSave).toHaveBeenCalled();
        });
    });

    describe('expand button', () => {
        // Only the expand-button rule is under test: services are stubbed and the template emptied.
        const shellFor = (type: NodeType): NodePanelShellComponent => {
            TestBed.configureTestingModule({
                providers: [
                    {
                        provide: SidePanelService,
                        useValue: {
                            autosaveTrigger: signal(0),
                            expandRequest: signal(false),
                            clearExpandRequest: vi.fn(),
                        },
                    },
                    { provide: ToastService, useValue: { error: vi.fn() } },
                    NodeAuthorshipStore,
                ],
            });
            TestBed.overrideComponent(NodePanelShellComponent, { set: { template: '' } });
            const fixture = TestBed.createComponent(NodePanelShellComponent);
            fixture.componentRef.setInput('node', { id: 'node-1', type, node_name: 'Node' } as unknown as NodeModel);
            fixture.detectChanges();
            return fixture.componentInstance;
        };

        it('has no expand button for a key-value node, as for a schedule trigger', () => {
            for (const type of [NodeType.KEY_VALUE, NodeType.SCHEDULE_TRIGGER]) {
                expect(shellFor(type).shouldShowExpandButton()).toBe(false);
                TestBed.resetTestingModule();
            }
            expect(shellFor(NodeType.PYTHON).shouldShowExpandButton()).toBe(true);
        });
    });

    describe('node details button', () => {
        const UNKNOWN = { created_by: null, created_at: null, last_edited_by: null, last_edited_at: null };
        // What the store holds for a row of the graph response, which is all the dialog may receive.
        const authorshipOfRow = (row: typeof livePython | typeof liveEnd | typeof liveSubgraph) => ({
            created_by: row.created_by,
            created_at: row.created_at,
            last_edited_by: row.last_edited_by,
            last_edited_at: row.last_edited_at,
        });
        const savedPythonNode = {
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
        } as unknown as PythonNodeModel;
        const subgraphNode = {
            ...endNode,
            id: 'subgraph-1',
            backendId: liveSubgraph.id,
            type: NodeType.SUBGRAPH,
            node_name: 'Subgraph (#2)',
            data: { id: 3, name: 'Other flow' },
        } as unknown as SubGraphNodeModel;

        // The panels' own templates are irrelevant here and emptied; the shell header is rendered for real.
        async function mountDetails(
            node: NodeModel,
            options: { isPreview?: boolean; canUpdateFlows?: boolean; loadedGraph?: boolean } = {}
        ): Promise<{ fixture: ComponentFixture<NodePanelShellComponent>; open: ReturnType<typeof vi.fn> }> {
            const open = vi.fn();
            TestBed.configureTestingModule({
                providers: [
                    { provide: FLOW_EDITOR_PREVIEW, useValue: options.isPreview ?? false },
                    {
                        provide: PermissionsService,
                        useValue: { can: () => options.canUpdateFlows ?? true, canEditSecrets: () => false },
                    },
                    { provide: AuthorshipDetailsDialogService, useValue: { open } },
                    { provide: FlowsApiService, useValue: { getGraphsLight: () => of([]) } },
                    NodeAuthorshipStore,
                ],
                errorOnUnknownProperties: false,
            });
            TestBed.overrideComponent(EndNodePanelComponent, { set: { template: '', imports: [] } });
            TestBed.overrideComponent(PythonNodePanelComponent, { set: { template: '', imports: [] } });
            TestBed.overrideComponent(ConditionalEdgeNodePanelComponent, { set: { template: '', imports: [] } });
            TestBed.overrideComponent(SubGraphNodePanelComponent, { set: { template: '', imports: [] } });
            // The flow page fills the store from every graph response; a version preview never does.
            if (options.loadedGraph ?? true) TestBed.inject(NodeAuthorshipStore).replaceFromGraph(liveGraph);
            TestBed.inject(FlowService).setFlow({ nodes: [node], connections: [] });
            TestBed.inject(SidePanelService).setSelectedNodeId(node.id);

            const fixture = TestBed.createComponent(NodePanelShellComponent);
            fixture.componentRef.setInput('node', node);
            fixture.detectChanges();
            await new Promise((resolve) => setTimeout(resolve, 0));
            fixture.detectChanges();
            return { fixture, open };
        }

        const detailsButton = (fixture: ComponentFixture<NodePanelShellComponent>): HTMLButtonElement | null =>
            fixture.nativeElement.querySelector('button[aria-label="Node details"]');

        it('opens the shared dialog with the loaded authorship and returns focus to the button', async () => {
            const { fixture, open } = await mountDetails(savedPythonNode);
            const button = detailsButton(fixture);

            expect(button).not.toBeNull();
            button!.click();

            expect(open).toHaveBeenCalledWith('Node Details', authorshipOfRow(livePython), button);
        });

        it('opens for every switched-on node type through the same header, e.g. an End node', async () => {
            const { fixture, open } = await mountDetails({ ...endNode, backendId: liveEnd.id });

            detailsButton(fixture)!.click();

            expect(open).toHaveBeenCalledWith('Node Details', authorshipOfRow(liveEnd), detailsButton(fixture));
        });

        it('opens for a Subgraph node with the authorship of its saved row', async () => {
            const { fixture, open } = await mountDetails(subgraphNode);

            detailsButton(fixture)!.click();

            expect(open).toHaveBeenCalledWith('Node Details', authorshipOfRow(liveSubgraph), detailsButton(fixture));
        });

        it('is opt-in per node type: a node type not switched on has no button', async () => {
            const edgeNode = {
                ...endNode,
                type: NodeType.EDGE,
                data: {
                    source: 'a',
                    then: 'b',
                    python_code: { code: '', entrypoint: 'main', libraries: [] },
                    input_map: {},
                },
            } as unknown as NodeModel;
            const { fixture } = await mountDetails(edgeNode);

            // The header itself is rendered, so the missing button is the opt-in, not an empty shell.
            expect(fixture.nativeElement.querySelector('button[aria-label="Close dialog"]')).not.toBeNull();
            expect(detailsButton(fixture)).toBeNull();
        });

        it('is shown to a viewer, since viewing details needs only flow read access', async () => {
            const { fixture, open } = await mountDetails(savedPythonNode, { canUpdateFlows: false });

            detailsButton(fixture)!.click();

            expect(open).toHaveBeenCalledWith('Node Details', authorshipOfRow(livePython), detailsButton(fixture));
        });

        it('is shown in a version preview, whose own store knows no author even for a node with an id', async () => {
            // A real id, so only the preview's empty store (never filled from the live graph) yields the empty values.
            const { fixture, open } = await mountDetails(savedPythonNode, { isPreview: true, loadedGraph: false });

            detailsButton(fixture)!.click();

            expect(open).toHaveBeenCalledWith('Node Details', UNKNOWN, detailsButton(fixture));
        });

        it('shows no author for a node that is not saved yet', async () => {
            const { fixture, open } = await mountDetails({ ...savedPythonNode, backendId: null });

            detailsButton(fixture)!.click();

            expect(open).toHaveBeenCalledWith('Node Details', UNKNOWN, detailsButton(fixture));
        });
    });
});
