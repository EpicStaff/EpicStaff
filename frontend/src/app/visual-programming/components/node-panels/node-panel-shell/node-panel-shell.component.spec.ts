import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { EndNodeModel, NodeModel } from '../../../core/models/node.model';
import { FLOW_EDITOR_READ_ONLY } from '../../../core/providers/flow-editor-state.providers';
import { FlowService } from '../../../services/flow.service';
import { SidePanelService } from '../../../services/side-panel.service';
import { EndNodePanelComponent } from '../end-node-panel/end-node-panel.component';
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

async function mount(readOnly: boolean): Promise<ComponentFixture<NodePanelShellComponent>> {
    TestBed.configureTestingModule({
        providers: [{ provide: FLOW_EDITOR_READ_ONLY, useValue: readOnly }],
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

    describe('read-only', () => {
        it('disables the panel form, never saves or autosaves, and Ctrl+S / Esc only close', async () => {
            const fixture = await mount(true);
            const shell = fixture.componentInstance;
            const panel = panelOf(fixture);
            const onSave = vi.spyOn(panel, 'onSave');
            const onSaveSilently = vi.spyOn(panel, 'onSaveSilently');
            const emitted: NodeModel[] = [];
            shell.save.subscribe((node) => emitted.push(node));
            shell.autosave.subscribe((node) => emitted.push(node));
            const sidePanel = TestBed.inject(SidePanelService);

            expect(panel.form.disabled).toBe(true);
            // Even with a pending edit (from a widget outside the form) nothing is saved.
            panel.onOutputMapChange('{"changed": "value"}');
            fixture.detectChanges();
            expect(fixture.nativeElement.querySelector('.save-btn')).toBeNull();

            sidePanel.triggerAutosave();
            fixture.detectChanges();
            shell['onShortcutSave']();
            expect(sidePanel.selectedNodeId()).toBeNull();

            sidePanel.setSelectedNodeId(endNode.id);
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
});
