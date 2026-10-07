import { NgTemplateOutlet } from '@angular/common';
import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { NO_ERRORS_SCHEMA, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { SecretsStorageService } from '@shared/services';
import { Subject } from 'rxjs';

import { GraphDto } from '../../../../features/flows/models/graph.model';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { RuffDiagnosticsService } from '../../../../shared/ruff-linter/services/ruff-diagnostics.service';
import { RuffWasmService } from '../../../../shared/ruff-linter/services/ruff-wasm.service';
import { CodeEditorComponent } from '../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import { WebhookTriggerNodeModel } from '../../../core/models/node.model';
import { GetWebhookTriggerNodeRequest } from '../../../core/models/webhook-trigger';
import { FlowService } from '../../../services/flow.service';
import { PollEvent, PythonCodeRunService } from '../../../services/python-code-run.service';
import { SidePanelService } from '../../../services/side-panel.service';
import { mapWebhookTriggerNodeToModel } from '../../../utils/load/nodes/webhook-trigger-node.mapper';
import { FIX_TEST_PAYLOAD_JSON_MESSAGE, formatTestPayload } from '../../../utils/test-run';
import { PythonCodeTestRun } from '../shared/python-code-test-run/python-code-test-run';
import {
    INVALID_TEST_PAYLOAD_NOT_SAVED_MESSAGE,
    TEST_PAYLOAD_SAVED_OTHER_CHANGES_NOT_SAVED_MESSAGE,
    TriggerTestPayloadState,
} from '../shared/test-payload-section/trigger-test-payload.state';
import {
    PYTHON_CODE_RUNNING_MESSAGE,
    RUN_PYTHON_CODE_LABEL,
    SAVE_GRAPH_BEFORE_CODE_RUN_MESSAGE,
    SAVE_NODE_BEFORE_CODE_RUN_MESSAGE,
    SAVE_TO_RUN_LATEST_CODE_MESSAGE,
    STORED_GRAPH_OUTDATED_MESSAGE,
    WebhookTriggerNodePanelComponent,
} from './webhook-trigger-node-panel.component';

const SAVED_PAYLOAD = { order: { id: '104' } };

const DTO: GetWebhookTriggerNodeRequest = {
    id: 21,
    graph: 1,
    node_name: 'Webhook Trigger #1',
    python_code: { id: 5, libraries: [], code: 'def main(trigger_payload): pass', entrypoint: 'main' },
    input_map: {},
    output_variable_path: null,
    webhook_trigger_path: '',
    metadata: {},
    webhook_trigger: null,
    test_payload: SAVED_PAYLOAD,
};

/** The template-facing members the panel's test payload editor binds to. */
interface TestPayloadPanel {
    testPayload: TriggerTestPayloadState;
    onTestPayloadTextChange(text: string): void;
}

describe('WebhookTriggerNodePanelComponent test payload', () => {
    let fixture: ComponentFixture<WebhookTriggerNodePanelComponent>;
    let panel: WebhookTriggerNodePanelComponent;
    let toast: Record<string, ReturnType<typeof vi.fn>>;

    beforeEach(() => {
        toast = { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() };
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ToastService, useValue: toast },
                {
                    provide: PermissionsService,
                    useValue: { can: () => true, canAny: () => true, canEditSecrets: () => true },
                },
                {
                    provide: SecretsStorageService,
                    useValue: { secrets: signal([]), namesForIds: () => [], getSecrets: vi.fn() },
                },
            ],
        });
        // The editors (Monaco) and shared controls are not under test: only the panel's state wiring is.
        TestBed.overrideComponent(WebhookTriggerNodePanelComponent, { set: { template: '', imports: [] } });
        fixture = TestBed.createComponent(WebhookTriggerNodePanelComponent);
        panel = fixture.componentInstance;
        fixture.componentRef.setInput('node', mapWebhookTriggerNodeToModel(DTO));
        fixture.detectChanges();
    });

    function editor(): TestPayloadPanel {
        return panel as unknown as TestPayloadPanel;
    }

    function savedTestPayload(): WebhookTriggerNodeModel['data']['test_payload'] {
        return panel.onSaveSilently()!.data.test_payload;
    }

    it('shows the saved payload and saves it unchanged while not edited', () => {
        expect(editor().testPayload.text()).toBe(formatTestPayload(SAVED_PAYLOAD));
        expect(panel.isDirty()).toBe(false);
        expect(savedTestPayload()).toEqual(SAVED_PAYLOAD);
    });

    it('saves an edited payload that parses', () => {
        editor().onTestPayloadTextChange('{"order": {"id": "200"}}');

        expect(panel.isDirty()).toBe(true);
        expect(savedTestPayload()).toEqual({ order: { id: '200' } });
    });

    it('stays dirty with an invalid edit, keeps the saved payload and says it was not saved', () => {
        editor().onTestPayloadTextChange('{"order": ');
        expect(panel.isDirty()).toBe(true);

        const savedNode = panel.onSave();

        expect(savedNode!.data.test_payload).toEqual(SAVED_PAYLOAD);
        expect(toast['warning']).toHaveBeenCalledWith(INVALID_TEST_PAYLOAD_NOT_SAVED_MESSAGE);
        // Still not saved: the panel keeps counting it as an unsaved change.
        expect(panel.isDirty()).toBe(true);
    });

    it('says an invalid payload edit was not saved on Ctrl+S as well', () => {
        panel.form.patchValue({ node_name: 'Renamed' });
        editor().onTestPayloadTextChange('{"order": ');

        const savedNode = panel.onSaveSilently();

        expect(savedNode!.node_name).toBe('Renamed');
        expect(savedNode!.data.test_payload).toEqual(SAVED_PAYLOAD);
        expect(toast['warning']).toHaveBeenCalledTimes(1);
        expect(toast['warning']).toHaveBeenCalledWith(INVALID_TEST_PAYLOAD_NOT_SAVED_MESSAGE);
        expect(panel.isDirty()).toBe(true);
    });

    it('is clean again once an invalid edit is fixed back to the saved payload', () => {
        editor().onTestPayloadTextChange('nope');
        editor().onTestPayloadTextChange(JSON.stringify(SAVED_PAYLOAD));

        expect(panel.isDirty()).toBe(false);
    });

    it('does not warn when a valid edit is saved', () => {
        editor().onTestPayloadTextChange('{}');

        panel.onSaveSilently();
        panel.onSave();

        expect(toast['warning']).not.toHaveBeenCalled();
    });

    describe('while the form is invalid', () => {
        const EDITED_PAYLOAD = { order: { id: '200' } };

        function invalidateForm(): void {
            panel.form.patchValue({ node_name: '', libraries: 'requests' });
            expect(panel.form.invalid).toBe(true);
        }

        it('onSave (close, Esc, autosave) saves a valid payload edit alone onto the last saved node', () => {
            const lastSavedNode = panel.node();
            invalidateForm();
            editor().onTestPayloadTextChange(JSON.stringify(EDITED_PAYLOAD));

            const savedNode = panel.onSave();

            expect(savedNode).toEqual({
                ...lastSavedNode,
                data: { ...lastSavedNode.data, test_payload: EDITED_PAYLOAD },
            });
            expect(toast['warning']).toHaveBeenCalledTimes(1);
            expect(toast['warning']).toHaveBeenCalledWith(TEST_PAYLOAD_SAVED_OTHER_CHANGES_NOT_SAVED_MESSAGE);
            // The other edits are still unsaved; the payload is not saved again.
            expect(panel.isDirty()).toBe(true);
            expect(panel.onSave()).toBeNull();
            expect(toast['warning']).toHaveBeenCalledTimes(1);
        });

        it('onSaveSilently (Ctrl+S) saves nothing and leaves every edit as it was', () => {
            invalidateForm();
            editor().onTestPayloadTextChange(JSON.stringify(EDITED_PAYLOAD));

            expect(panel.onSaveSilently()).toBeNull();

            expect(toast['warning']).not.toHaveBeenCalled();
            expect(panel.isDirty()).toBe(true);
            expect(panel.form.value).toEqual(expect.objectContaining({ node_name: '', libraries: 'requests' }));
            expect(editor().testPayload.text()).toBe(JSON.stringify(EDITED_PAYLOAD));
            expect(editor().testPayload.isEdited()).toBe(true);
            // The payload edit is still unsaved: closing the panel saves it.
            expect(panel.onSave()!.data.test_payload).toEqual(EDITED_PAYLOAD);
        });

        it('shows no toast when the payload was the only edit', () => {
            fixture.componentRef.setInput('node', mapWebhookTriggerNodeToModel({ ...DTO, node_name: '' }));
            fixture.detectChanges();
            expect(panel.form.invalid).toBe(true);
            editor().onTestPayloadTextChange(JSON.stringify(EDITED_PAYLOAD));

            panel.onSave();

            expect(toast['warning']).not.toHaveBeenCalled();
            expect(panel.isDirty()).toBe(false);
        });

        it('saves nothing for payload text that is not valid JSON', () => {
            invalidateForm();
            editor().onTestPayloadTextChange('{"order": ');

            expect(panel.onSave()).toBeNull();
            expect(panel.onSaveSilently()).toBeNull();
            expect(toast['warning']).not.toHaveBeenCalled();
        });

        it('saves nothing when the payload was not edited', () => {
            invalidateForm();

            expect(panel.onSave()).toBeNull();
            expect(panel.onSaveSilently()).toBeNull();
            expect(toast['warning']).not.toHaveBeenCalled();
        });

        it('saves nothing when the payload was edited back to the saved one', () => {
            invalidateForm();
            editor().onTestPayloadTextChange(JSON.stringify(SAVED_PAYLOAD));

            expect(panel.onSave()).toBeNull();
        });

        it('saves the whole node, payload included, once the form is valid again', () => {
            invalidateForm();
            editor().onTestPayloadTextChange(JSON.stringify(EDITED_PAYLOAD));
            panel.onSave();

            panel.form.patchValue({ node_name: 'Fixed name' });
            const savedNode = panel.onSave();

            expect(savedNode!.node_name).toBe('Fixed name');
            expect(savedNode!.data.python_code.libraries).toEqual(['requests']);
            expect(savedNode!.data.test_payload).toEqual(EDITED_PAYLOAD);
            expect(panel.isDirty()).toBe(false);
        });
    });
});

describe('WebhookTriggerNodePanelComponent code editor header', () => {
    let fixture: ComponentFixture<WebhookTriggerNodePanelComponent>;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ToastService, useValue: {} },
                {
                    provide: PermissionsService,
                    useValue: { can: () => true, canAny: () => true, canEditSecrets: () => true },
                },
                {
                    provide: SecretsStorageService,
                    useValue: { secrets: signal([]), namesForIds: () => [], getSecrets: vi.fn() },
                },
                { provide: RuffWasmService, useValue: { check: () => Promise.resolve([]) } },
                { provide: RuffDiagnosticsService, useValue: { setMarkers: () => {}, hasSyntaxErrors: () => false } },
            ],
        });
        // Real panel template, but only the code editor is a real (empty, Monaco-free) component: the
        // other controls render as unknown elements.
        TestBed.overrideComponent(WebhookTriggerNodePanelComponent, {
            set: { imports: [NgTemplateOutlet, CodeEditorComponent], schemas: [NO_ERRORS_SCHEMA] },
        });
        TestBed.overrideComponent(CodeEditorComponent, { set: { template: '', imports: [] } });
        fixture = TestBed.createComponent(WebhookTriggerNodePanelComponent);
        fixture.componentRef.setInput('node', mapWebhookTriggerNodeToModel(DTO));
    });

    function codeEditors(): CodeEditorComponent[] {
        return fixture.debugElement
            .queryAll(By.directive(CodeEditorComponent))
            .map((editorElement) => editorElement.componentInstance as CodeEditorComponent);
    }

    it('uses the JSON-style header for the code card of the small panel', () => {
        fixture.detectChanges();

        const editors = codeEditors();
        expect(editors).toHaveLength(1);
        expect(editors[0].compactHeader()).toBe(true);
    });

    it('uses the JSON-style header for the code editor in the big pane of the expanded panel', () => {
        fixture.componentRef.setInput('isExpanded', true);
        fixture.detectChanges();

        const editors = codeEditors();
        expect(editors).toHaveLength(1);
        expect(editors[0].expandLabel()).toBe('Swap with test payload');
        expect(editors[0].compactHeader()).toBe(true);
    });

    it('uses the JSON-style header for the code card moved to the left column of the expanded panel', () => {
        fixture.componentRef.setInput('isExpanded', true);
        (fixture.componentInstance as unknown as { expandPane(pane: 'payload'): void }).expandPane('payload');
        fixture.detectChanges();

        const editors = codeEditors();
        expect(editors).toHaveLength(1);
        expect(editors[0].editorHeight()).toBe(220);
        expect(editors[0].compactHeader()).toBe(true);
    });
});

describe('WebhookTriggerNodePanelComponent run python code', () => {
    let fixture: ComponentFixture<WebhookTriggerNodePanelComponent>;
    let start$: Subject<{ execution_id: string }>;
    let poll$: Subject<PollEvent>;
    let runService: { runPythonCode: ReturnType<typeof vi.fn>; pollResultWithEvents: ReturnType<typeof vi.fn> };
    let canUpdateFlows: boolean;

    /** The members the template binds the run action and its terminal to. */
    interface RunCodePanel {
        codeTestRun: PythonCodeTestRun;
        runCodeBlocker(): string | null;
        onTestPayloadTextChange(text: string): void;
        expandPane(pane: 'code' | 'payload'): void;
    }

    beforeEach(() => {
        canUpdateFlows = true;
        start$ = new Subject();
        poll$ = new Subject();
        runService = { runPythonCode: vi.fn(() => start$), pollResultWithEvents: vi.fn(() => poll$) };
        TestBed.configureTestingModule({
            providers: [
                { provide: ToastService, useValue: { warning: vi.fn() } },
                {
                    provide: PermissionsService,
                    useValue: { can: () => canUpdateFlows, canAny: () => true, canEditSecrets: () => true },
                },
                {
                    provide: SecretsStorageService,
                    useValue: { secrets: signal([]), namesForIds: () => [], getSecrets: vi.fn() },
                },
                { provide: PythonCodeRunService, useValue: runService },
            ],
        });
        // Real panel template; the code editor is a real (empty, Monaco-free) component so its inputs can be
        // read, the other controls (the terminal included) render as unknown elements.
        TestBed.overrideComponent(WebhookTriggerNodePanelComponent, {
            set: { imports: [NgTemplateOutlet, CodeEditorComponent], schemas: [NO_ERRORS_SCHEMA] },
        });
        TestBed.overrideComponent(CodeEditorComponent, { set: { template: '', imports: [] } });
        bindStoredGraph(asStored(DTO));
    });

    /** `node` as the backend returns it after a save: DRF's CharField stores the code stripped. */
    function asStored(
        node: GetWebhookTriggerNodeRequest,
        pythonCode: Partial<GetWebhookTriggerNodeRequest['python_code']> = {}
    ): GetWebhookTriggerNodeRequest {
        const stored = { ...node.python_code, ...pythonCode };
        return { ...node, python_code: { ...stored, code: stored.code.trim() } };
    }

    /** What the flows page binds: its graph as the backend last returned it. */
    function bindStoredGraph(...webhookNodes: GetWebhookTriggerNodeRequest[]): void {
        TestBed.inject(FlowService).bindSavedGraph(
            signal({ webhook_trigger_node_list: webhookNodes } as unknown as GraphDto)
        );
    }

    function open(node: WebhookTriggerNodeModel = mapWebhookTriggerNodeToModel(DTO)): RunCodePanel {
        fixture = TestBed.createComponent(WebhookTriggerNodePanelComponent);
        fixture.componentRef.setInput('node', node);
        fixture.detectChanges();
        return fixture.componentInstance as unknown as RunCodePanel;
    }

    function panel(): WebhookTriggerNodePanelComponent {
        return fixture.componentInstance;
    }

    function codeEditor(): CodeEditorComponent {
        return fixture.debugElement.query(By.directive(CodeEditorComponent)).componentInstance as CodeEditorComponent;
    }

    function terminals(): number {
        return fixture.debugElement.queryAll(By.css('app-python-terminal')).length;
    }

    function logMessages(runPanel: RunCodePanel): string[] {
        return runPanel.codeTestRun.logs().map((entry) => `${entry.type}: ${entry.message}`);
    }

    function runFromEditor(): void {
        codeEditor().action.emit();
        fixture.detectChanges();
    }

    function openExpanded(): RunCodePanel {
        const runPanel = open();
        fixture.componentRef.setInput('isExpanded', true);
        fixture.detectChanges();
        return runPanel;
    }

    it('offers no run action in the small panel', () => {
        open();

        expect(codeEditor().actionIcon()).toBeNull();
    });

    it('puts "Run python code" in the code editor header, enabled for a saved node with a valid payload', () => {
        openExpanded();

        expect(codeEditor().actionIcon()).toBe('play-outline');
        expect(codeEditor().actionLabel()).toBe(RUN_PYTHON_CODE_LABEL);
        expect(codeEditor().actionDisabledReason()).toBeNull();
    });

    it('shows the action on the code editor of both expanded layouts', () => {
        openExpanded();
        expect(codeEditor().actionIcon()).toBe('play-outline');

        (panel() as unknown as RunCodePanel).expandPane('payload');
        fixture.detectChanges();
        expect(codeEditor().actionIcon()).toBe('play-outline');
    });

    it('is hidden for a user who cannot edit the flow', () => {
        canUpdateFlows = false;
        open();

        expect(codeEditor().actionIcon()).toBeNull();
    });

    describe('disabled reason', () => {
        it('asks to save the node when it is new', () => {
            const runPanel = open({ ...mapWebhookTriggerNodeToModel(DTO), id: 'new-node', backendId: null });

            expect(runPanel.runCodeBlocker()).toBe(SAVE_NODE_BEFORE_CODE_RUN_MESSAGE);
            expect(codeEditor().actionDisabledReason()).toBe(SAVE_NODE_BEFORE_CODE_RUN_MESSAGE);
        });

        it('asks to save the node for a pasted copy of a saved node', () => {
            // A paste keeps the copied node's data and gets no backend id until it is saved.
            const copied = mapWebhookTriggerNodeToModel(DTO);
            const runPanel = open({ ...copied, id: 'pasted-node', backendId: null });

            expect(runPanel.runCodeBlocker()).toBe(SAVE_NODE_BEFORE_CODE_RUN_MESSAGE);
        });

        it('asks for a graph save for a node that is not in the stored graph (deleted, then restored)', () => {
            bindStoredGraph();
            const runPanel = open();

            expect(runPanel.runCodeBlocker()).toBe(SAVE_GRAPH_BEFORE_CODE_RUN_MESSAGE);
        });

        it('asks to save after a code edit, and clears once the edit is undone', () => {
            const runPanel = open();

            panel().onPythonCodeChange('def main(trigger_payload, **kwargs): return 1');
            expect(runPanel.runCodeBlocker()).toBe(SAVE_TO_RUN_LATEST_CODE_MESSAGE);

            panel().onPythonCodeChange(DTO.python_code.code);
            expect(runPanel.runCodeBlocker()).toBeNull();
        });

        it('asks to save after a libraries or secrets edit', () => {
            const runPanel = open();

            panel().form.patchValue({ libraries: 'requests' });
            expect(runPanel.runCodeBlocker()).toBe(SAVE_TO_RUN_LATEST_CODE_MESSAGE);

            panel().form.patchValue({ libraries: '' });
            panel().onSecretsChange([7]);
            expect(runPanel.runCodeBlocker()).toBe(SAVE_TO_RUN_LATEST_CODE_MESSAGE);
        });

        it('keeps asking after the panel is closed and reopened before the graph is saved', () => {
            open();
            panel().onPythonCodeChange('def main(**kwargs): return 2');
            // Closing the panel puts the edit in the flow, not on the backend.
            const editedNode = panel().onSave()!;
            fixture.destroy();

            const reopened = open(editedNode);

            expect(reopened.runCodeBlocker()).toBe(SAVE_TO_RUN_LATEST_CODE_MESSAGE);
        });

        it('clears once the saved graph has the edited code, libraries and secrets', () => {
            open();
            panel().onPythonCodeChange('def main(**kwargs): return 2');
            panel().form.patchValue({ libraries: 'requests, pandas' });
            panel().onSecretsChange([9, 7]);

            bindStoredGraph(
                asStored(DTO, {
                    code: 'def main(**kwargs): return 2',
                    libraries: ['requests', 'pandas'],
                    secrets: [
                        { id: 7, name: 'A' },
                        { id: 9, name: 'B' },
                    ],
                })
            );
            fixture.detectChanges();

            expect(codeEditor().actionDisabledReason()).toBeNull();
        });

        it('is enabled for code the backend stored stripped of its surrounding whitespace', () => {
            // A new node's default code ends with a newline; the backend keeps it stripped.
            const typed = '\n# handler\ndef main(trigger_payload, **kwargs):\n    return {}\n';
            const node = mapWebhookTriggerNodeToModel({ ...DTO, python_code: { ...DTO.python_code, code: typed } });
            bindStoredGraph(asStored(DTO, { code: typed }));

            const runPanel = open(node);

            expect(runPanel.runCodeBlocker()).toBeNull();
        });

        it('still sees a change inside the code', () => {
            bindStoredGraph(asStored(DTO, { code: 'def main(trigger_payload):  pass' }));

            expect(open().runCodeBlocker()).toBe(SAVE_TO_RUN_LATEST_CODE_MESSAGE);
        });

        it('asks to refresh while the stored graph is outdated (another user saved it)', () => {
            TestBed.inject(FlowService).bindSavedGraph(signal(null));

            expect(open().runCodeBlocker()).toBe(STORED_GRAPH_OUTDATED_MESSAGE);
        });

        it('asks to save when undo after a save brings back code the backend no longer has', () => {
            // Saved: the edited code. The flow (after Ctrl+Z) holds the code from before the edit.
            bindStoredGraph(asStored(DTO, { code: 'def main(**kwargs): return 2' }));

            const runPanel = open(mapWebhookTriggerNodeToModel(DTO));

            expect(runPanel.runCodeBlocker()).toBe(SAVE_TO_RUN_LATEST_CODE_MESSAGE);
        });

        it('asks to fix a test payload that is not valid JSON', () => {
            const runPanel = open();

            runPanel.onTestPayloadTextChange('{"order": ');

            expect(runPanel.runCodeBlocker()).toBe(FIX_TEST_PAYLOAD_JSON_MESSAGE);
        });

        it('is not blocked by an unsaved test payload edit: the payload is sent with the run', () => {
            const runPanel = open();

            runPanel.onTestPayloadTextChange('{"order": {"id": "300"}}');

            expect(runPanel.runCodeBlocker()).toBeNull();
        });

        it('says the code is running while a run is in flight', () => {
            const runPanel = open();

            runFromEditor();

            expect(runPanel.runCodeBlocker()).toBe(PYTHON_CODE_RUNNING_MESSAGE);
            expect(codeEditor().actionDisabledReason()).toBe(PYTHON_CODE_RUNNING_MESSAGE);
        });
    });

    it('runs the stored code with the test payload as trigger_payload', () => {
        const runPanel = open();
        runPanel.onTestPayloadTextChange('{"order": {"id": "300"}}');

        runFromEditor();

        expect(runService.runPythonCode).toHaveBeenCalledTimes(1);
        expect(runService.runPythonCode).toHaveBeenCalledWith(
            expect.objectContaining({
                python_code_id: 5,
                variables: { trigger_payload: { order: { id: '300' } } },
            })
        );
    });

    it('does not run while blocked', () => {
        const runPanel = open();
        runPanel.onTestPayloadTextChange('nope');

        runFromEditor();

        expect(runService.runPythonCode).not.toHaveBeenCalled();
        expect(terminals()).toBe(0);
    });

    describe('Save (the panel shell header button)', () => {
        let requestSaveNode: ReturnType<typeof vi.spyOn>;

        beforeEach(() => {
            requestSaveNode = vi.spyOn(TestBed.inject(SidePanelService), 'requestSaveNode');
        });

        /** What the flows page does after a successful single-node save: the node gets its backend id and the stored graph has it. */
        function completeSave(savedNode: WebhookTriggerNodeModel, backendId: number): void {
            bindStoredGraph(
                asStored({
                    ...DTO,
                    id: backendId,
                    python_code: { ...DTO.python_code, code: savedNode.data.python_code.code },
                })
            );
            fixture.componentRef.setInput('node', { ...savedNode, backendId });
            fixture.detectChanges();
        }

        it('is offered for a new node with no edit, and saves it so its code can run', () => {
            const newNode = { ...mapWebhookTriggerNodeToModel(DTO), id: 'new-node', backendId: null };
            const runPanel = open(newNode);
            expect(panel().isDirty()).toBe(false);
            expect(panel().needsSave()).toBe(true);

            panel().onSaveClick();

            expect(requestSaveNode).toHaveBeenCalledTimes(1);
            const savedNode = requestSaveNode.mock.calls[0][0] as WebhookTriggerNodeModel;
            expect(savedNode).toEqual(expect.objectContaining({ id: 'new-node', backendId: null }));

            completeSave(savedNode, 40);

            expect(panel().needsSave()).toBe(false);
            expect(panel().isDirty()).toBe(false);
            expect(runPanel.runCodeBlocker()).toBeNull();
        });

        it('is offered after a code, libraries or secrets edit and saves the edited node', () => {
            const runPanel = open();
            expect(panel().needsSave()).toBe(false);

            panel().onPythonCodeChange('def main(**kwargs): return 2\n');
            panel().form.patchValue({ libraries: 'requests' });
            panel().onSecretsChange([7]);
            expect(panel().isDirty()).toBe(true);
            expect(panel().needsSave()).toBe(true);

            panel().onSaveClick();

            const savedNode = requestSaveNode.mock.calls[0][0] as WebhookTriggerNodeModel;
            expect(savedNode.data.python_code).toEqual(
                expect.objectContaining({
                    code: 'def main(**kwargs): return 2\n',
                    libraries: ['requests'],
                    secret_ids: [7],
                })
            );
            // Saved into the flow at once, as Ctrl+S does: the panel is clean.
            expect(panel().isDirty()).toBe(false);

            bindStoredGraph(
                asStored(DTO, {
                    code: 'def main(**kwargs): return 2\n',
                    libraries: ['requests'],
                    secrets: [{ id: 7, name: 'A' }],
                })
            );

            expect(panel().needsSave()).toBe(false);
            expect(runPanel.runCodeBlocker()).toBeNull();
        });

        it('saves a test payload edit alone and is then no longer offered', () => {
            const runPanel = open();
            runPanel.onTestPayloadTextChange('{"order": {"id": "300"}}');
            expect(panel().isDirty()).toBe(true);

            panel().onSaveClick();

            const savedNode = requestSaveNode.mock.calls[0][0] as WebhookTriggerNodeModel;
            expect(savedNode.data.test_payload).toEqual({ order: { id: '300' } });
            expect(panel().isDirty()).toBe(false);
            expect(panel().needsSave()).toBe(false);
        });

        it('keeps an invalid test payload edit unsaved and reported, as on close', () => {
            const runPanel = open();
            runPanel.onTestPayloadTextChange('{"order": ');

            panel().onSaveClick();

            const savedNode = requestSaveNode.mock.calls[0][0] as WebhookTriggerNodeModel;
            expect(savedNode.data.test_payload).toEqual(SAVED_PAYLOAD);
            expect(TestBed.inject(ToastService).warning).toHaveBeenCalledWith(INVALID_TEST_PAYLOAD_NOT_SAVED_MESSAGE);
            expect(panel().isDirty()).toBe(true);
        });

        it('saves nothing while the form is invalid, keeping every edit', () => {
            open();
            panel().form.patchValue({ node_name: '' });
            panel().onPythonCodeChange('def main(**kwargs): return 2');

            panel().onSaveClick();

            expect(requestSaveNode).not.toHaveBeenCalled();
            expect(panel().isDirty()).toBe(true);
            expect(panel().form.get('node_name')!.touched).toBe(true);
        });

        it('does not save again while the node is being saved', () => {
            open();
            panel().onPythonCodeChange('def main(**kwargs): return 2');
            TestBed.inject(SidePanelService).markNodeSaving(panel().node().id);

            expect(panel().isSaving()).toBe(true);
            panel().onSaveClick();

            expect(requestSaveNode).not.toHaveBeenCalled();
        });

        it('is not offered to a user who cannot edit the flow', () => {
            canUpdateFlows = false;
            open({ ...mapWebhookTriggerNodeToModel(DTO), id: 'new-node', backendId: null });

            expect(panel().needsSave()).toBe(false);
            panel().onSaveClick();
            expect(requestSaveNode).not.toHaveBeenCalled();
        });

        it('stays clean when a graph save gives the node its backend id', () => {
            open({ ...mapWebhookTriggerNodeToModel(DTO), id: 'new-node', backendId: null });

            completeSave(panel().node(), 41);

            expect(panel().isDirty()).toBe(false);
        });
    });

    describe('terminal', () => {
        it('is not shown in the small panel, even after a run', () => {
            openExpanded();
            codeEditor().action.emit();
            fixture.componentRef.setInput('isExpanded', false);
            fixture.detectChanges();

            expect(terminals()).toBe(0);
        });

        it('is not shown before a run', () => {
            open();

            expect(terminals()).toBe(0);
        });

        it('appears under the code editor once run, and logs a completed run', () => {
            const runPanel = openExpanded();

            runFromEditor();
            start$.next({ execution_id: 'exec-1' });
            poll$.next({
                type: 'result',
                data: {
                    execution_id: 'exec-1',
                    status: 'completed',
                    result_data: '{"handled": true}',
                    returncode: 0,
                    stdout: 'hello',
                    stderr: '',
                },
            });
            fixture.detectChanges();

            expect(terminals()).toBe(1);
            expect(fixture.nativeElement.querySelector('.code-editor-column app-python-terminal')).not.toBeNull();
            expect(logMessages(runPanel)).toEqual([
                'info: Starting function main()...',
                'info: Parameters: {"trigger_payload":{"order":{"id":"104"}}}',
                'stdout: hello',
                'result: {"handled": true}',
            ]);
            expect(runPanel.codeTestRun.status()).toBe('done');
        });

        it('logs a failed run', () => {
            const runPanel = open();

            runFromEditor();
            start$.next({ execution_id: 'exec-1' });
            poll$.next({
                type: 'result',
                data: {
                    execution_id: 'exec-1',
                    status: 'error',
                    result_data: null,
                    returncode: 1,
                    stdout: '',
                    stderr: 'KeyError: order',
                },
            });

            expect(logMessages(runPanel).slice(2)).toEqual([
                'stderr: KeyError: order',
                'error: Execution failed (return code: 1)',
            ]);
            expect(runPanel.codeTestRun.status()).toBe('error');
        });

        it('logs an HTTP error', () => {
            const runPanel = open();
            const httpError = new HttpErrorResponse({ status: 403, url: '/run-python-code/' });

            runFromEditor();
            start$.error(httpError);

            expect(logMessages(runPanel).at(-1)).toBe(`error: Error: ${httpError.message}`);
            expect(runPanel.runCodeBlocker()).toBeNull();
        });

        it('stops a run in flight when another webhook node is selected', () => {
            const runPanel = open();
            runFromEditor();
            expect(runPanel.runCodeBlocker()).toBe(PYTHON_CODE_RUNNING_MESSAGE);

            fixture.componentRef.setInput('node', { ...mapWebhookTriggerNodeToModel(DTO), id: 'other-node' });
            fixture.detectChanges();
            // The first node's run answers after the switch: nothing of it reaches the other node.
            start$.next({ execution_id: 'exec-1' });

            expect(runService.pollResultWithEvents).not.toHaveBeenCalled();
            expect(runPanel.codeTestRun.isRunning()).toBe(false);
            expect(runPanel.codeTestRun.logs()).toEqual([]);
            expect(runPanel.runCodeBlocker()).toBeNull();
            expect(terminals()).toBe(0);
        });

        it('starts hidden and empty again when another webhook node is selected', () => {
            const runPanel = open();
            runFromEditor();
            start$.error(new Error('boom'));

            fixture.componentRef.setInput('node', { ...mapWebhookTriggerNodeToModel(DTO), id: 'other-node' });
            fixture.detectChanges();

            expect(terminals()).toBe(0);
            expect(runPanel.codeTestRun.logs()).toEqual([]);
        });

        it('stays under the code editor when the panel is expanded, in either pane', () => {
            open();
            runFromEditor();

            fixture.componentRef.setInput('isExpanded', true);
            fixture.detectChanges();
            expect(fixture.nativeElement.querySelector('.code-editor-column app-python-terminal')).not.toBeNull();
            expect(terminals()).toBe(1);

            (panel() as unknown as RunCodePanel).expandPane('payload');
            fixture.detectChanges();
            expect(
                fixture.nativeElement.querySelector('.form-fields .code-card-group app-python-terminal')
            ).not.toBeNull();
            expect(terminals()).toBe(1);
        });
    });
});
