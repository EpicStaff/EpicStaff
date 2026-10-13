import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { FormArray } from '@angular/forms';
import { NodeType } from '@shared/models';
import { Subject } from 'rxjs';

import { GraphDto } from '../../../../features/flows/models/graph.model';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { PythonNodeModel } from '../../../core/models/node.model';
import { PythonNode } from '../../../core/models/python-node.model';
import { FLOW_EDITOR_PREVIEW } from '../../../core/providers/flow-editor-preview.token';
import { FlowService } from '../../../services/flow.service';
import { PollEvent, PythonCodeRunService } from '../../../services/python-code-run.service';
import { SidePanelService } from '../../../services/side-panel.service';
import { mapPythonNodeToModel } from '../../../utils/load/nodes/python-node.mapper';
import {
    NODE_SAVING_MESSAGE,
    SAVE_GRAPH_BEFORE_CODE_RUN_MESSAGE,
    SAVE_NODE_BEFORE_CODE_RUN_MESSAGE,
    SAVE_TO_RUN_LATEST_CODE_MESSAGE,
    STORED_GRAPH_OUTDATED_MESSAGE,
} from '../shared/python-code-test-run/stored-python-code';
import { PythonNodePanelComponent } from './python-node-panel.component';

const pythonNode = {
    id: 'python-1',
    backendId: null,
    type: NodeType.PYTHON,
    node_name: 'Python #1',
    data: {
        code: 'def main(): pass',
        entrypoint: 'main',
        libraries: [],
        secret_ids: [7],
        secret_names: ['STRIPE_KEY'],
    },
    test_input: {},
    position: { x: 0, y: 0 },
    ports: null,
    color: '',
    icon: '',
    size: { width: 200, height: 100 },
    input_map: {},
    output_variable_path: null,
} as unknown as PythonNodeModel;

// A user with Secrets:Use who may edit flows: any read-only here comes from the preview.
function create(isPreview: boolean): PythonNodePanelComponent {
    TestBed.configureTestingModule({
        providers: [
            { provide: FLOW_EDITOR_PREVIEW, useValue: isPreview },
            { provide: PermissionsService, useValue: { can: () => true, canEditSecrets: () => true } },
        ],
    });
    TestBed.overrideComponent(PythonNodePanelComponent, { set: { template: '', imports: [] } });
    const fixture = TestBed.createComponent(PythonNodePanelComponent);
    fixture.componentRef.setInput('node', pythonNode);
    fixture.detectChanges();
    return fixture.componentInstance;
}

describe('PythonNodePanelComponent secrets', () => {
    it('is read-only in a version preview and shows the names saved on the node', () => {
        const panel = create(true);

        expect(panel.canEditSecrets()).toBe(false);
        expect(panel.secretNames()).toEqual(['STRIPE_KEY']);
        expect(panel.secretsTooltip()).toBe('Secrets assigned to this Python code.');
    });

    it('stays editable in the live editor for a user with Secrets:Use', () => {
        expect(create(false).canEditSecrets()).toBe(true);
    });
});

/** The Python node as the backend stores it. */
const STORED_NODE: PythonNode = {
    id: 31,
    node_name: 'Python #1',
    graph: 1,
    python_code: { id: 5, libraries: ['requests'], code: 'def main(count): return count', entrypoint: 'main' },
    input_map: {},
    test_input: { count: '3' },
    output_variable_path: null,
    metadata: {},
    use_storage: false,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
};

describe('PythonNodePanelComponent test run', () => {
    let runService: { runPythonCode: ReturnType<typeof vi.fn>; pollResultWithEvents: ReturnType<typeof vi.fn> };
    let panel: PythonNodePanelComponent;

    /** The member the template binds the input map's Run to. */
    interface TestRunPanel {
        runTestBlocker(): string | null;
    }

    beforeEach(() => {
        runService = {
            runPythonCode: vi.fn(() => new Subject<{ execution_id: string }>()),
            pollResultWithEvents: vi.fn(() => new Subject<PollEvent>()),
        };
        TestBed.configureTestingModule({
            providers: [
                { provide: FLOW_EDITOR_PREVIEW, useValue: false },
                { provide: PermissionsService, useValue: { can: () => true, canEditSecrets: () => true } },
                { provide: PythonCodeRunService, useValue: runService },
            ],
        });
        TestBed.overrideComponent(PythonNodePanelComponent, { set: { template: '', imports: [] } });
        bindStoredGraph(STORED_NODE);
    });

    /** What the flows page binds: its graph as the backend last returned it. */
    function bindStoredGraph(...pythonNodes: PythonNode[]): void {
        TestBed.inject(FlowService).bindSavedGraph(signal({ python_node_list: pythonNodes } as unknown as GraphDto));
    }

    function open(node: PythonNodeModel = mapPythonNodeToModel(STORED_NODE)): void {
        const fixture = TestBed.createComponent(PythonNodePanelComponent);
        fixture.componentRef.setInput('node', node);
        fixture.detectChanges();
        panel = fixture.componentInstance;
    }

    function blocker(): string | null {
        return (panel as unknown as TestRunPanel).runTestBlocker();
    }

    it('runs the stored code of the node, by its backend id, with the parsed test values', () => {
        open();

        panel.onRunTest({ count: '3', name: 'Ada' });

        expect(runService.runPythonCode).toHaveBeenCalledWith({
            target: { type: 'python_node', id: STORED_NODE.id },
            variables: { count: 3, name: 'Ada' },
        });
    });

    it('is not blocked by an unsaved test value: the values are sent with the run', () => {
        open();

        (panel.form.get('test_input') as FormArray).at(0).patchValue({ value: '4' });

        expect(panel.testInputDirty()).toBe(true);
        expect(blocker()).toBeNull();
    });

    describe('after toggling storage', () => {
        it('blocks the run until the node is saved, instead of running with the stored flag', () => {
            open();

            panel.onStorageToggle(true);
            panel.onRunTest({ count: '3' });

            expect(blocker()).toBe(SAVE_TO_RUN_LATEST_CODE_MESSAGE);
            expect(runService.runPythonCode).not.toHaveBeenCalled();
        });

        it('says the node is being saved while its save is in flight', () => {
            open();
            panel.onStorageToggle(true);

            TestBed.inject(SidePanelService).markNodeSaving(panel.node().id);

            expect(blocker()).toBe(NODE_SAVING_MESSAGE);
        });

        it('runs once the stored node has the new flag', () => {
            open();
            panel.onStorageToggle(true);

            bindStoredGraph({ ...STORED_NODE, use_storage: true });
            panel.onRunTest({ count: '3' });

            expect(blocker()).toBeNull();
            expect(runService.runPythonCode).toHaveBeenCalledTimes(1);
        });

        it('clears when the toggle is undone', () => {
            open();

            panel.onStorageToggle(true);
            panel.onStorageToggle(false);

            expect(blocker()).toBeNull();
        });

        it('offers Save when the panel is reopened with a toggle that only reached the flow', () => {
            const autosaved = mapPythonNodeToModel(STORED_NODE);
            open({ ...autosaved, data: { ...autosaved.data, use_storage: true } });

            expect(panel.isDirty()).toBe(false);
            expect(panel.needsSave()).toBe(true);
            expect(blocker()).toBe(SAVE_TO_RUN_LATEST_CODE_MESSAGE);
        });
    });

    it('blocks the run after a code, libraries or secrets edit', () => {
        open();

        panel.onPythonCodeChange('def main(count): return count + 1');
        expect(blocker()).toBe(SAVE_TO_RUN_LATEST_CODE_MESSAGE);

        panel.onPythonCodeChange(STORED_NODE.python_code.code);
        panel.form.patchValue({ libraries: 'requests, pandas' });
        expect(blocker()).toBe(SAVE_TO_RUN_LATEST_CODE_MESSAGE);

        panel.form.patchValue({ libraries: 'requests' });
        expect(blocker()).toBeNull();
        panel.onSecretsChange([7]);
        expect(blocker()).toBe(SAVE_TO_RUN_LATEST_CODE_MESSAGE);
    });

    it('asks to save a node without a backend id, offers Save for it, and does not run it', () => {
        open(pythonNode);

        panel.onRunTest({});

        expect(blocker()).toBe(SAVE_NODE_BEFORE_CODE_RUN_MESSAGE);
        expect(panel.needsSave()).toBe(true);
        expect(runService.runPythonCode).not.toHaveBeenCalled();
    });

    it('asks for a graph save for a node that is not in the stored graph (deleted, then restored)', () => {
        bindStoredGraph();
        open();

        expect(blocker()).toBe(SAVE_GRAPH_BEFORE_CODE_RUN_MESSAGE);
        expect(panel.needsSave()).toBe(false);
    });

    it('runs again after the Save round trip of a storage toggle', () => {
        open();
        const sidePanelService = TestBed.inject(SidePanelService);
        panel.onStorageToggle(true);
        expect(panel.isDirty()).toBe(true);

        // What the flows page does for the shell's Save: mark it saving, take the saved graph, clear the mark.
        sidePanelService.markNodeSaving(panel.node().id);
        TestBed.tick();
        expect(blocker()).toBe(NODE_SAVING_MESSAGE);
        bindStoredGraph({ ...STORED_NODE, use_storage: true });
        sidePanelService.clearNodeSaving();
        TestBed.tick();

        expect(blocker()).toBeNull();
        expect(panel.needsSave()).toBe(false);
        expect(panel.isDirty()).toBe(false);
    });

    it('asks to refresh while the stored graph is outdated (another user saved it)', () => {
        TestBed.inject(FlowService).bindSavedGraph(signal(null));

        open();

        expect(blocker()).toBe(STORED_GRAPH_OUTDATED_MESSAGE);
    });
});
