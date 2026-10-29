import { NgTemplateOutlet } from '@angular/common';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { NO_ERRORS_SCHEMA, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormArray, ReactiveFormsModule } from '@angular/forms';
import { By } from '@angular/platform-browser';
import {
    ConfirmationDialogService,
    CustomInputComponent,
    ExecutionTimeoutFieldComponent,
    ExecutionTimeoutFormField,
    SelectComponent,
} from '@shared/components';
import { NodeType } from '@shared/models';
import { of, Subject } from 'rxjs';

import { GraphDto } from '../../../../features/flows/models/graph.model';
import { GraphSessionService } from '../../../../features/flows/services/flows-sessions.service';
import { Venv, VenvStatus } from '../../../../features/virtual-environments/models/venv.model';
import { VenvsApiService } from '../../../../features/virtual-environments/services/venvs-api.service';
import { RunSessionSSEService } from '../../../../pages/running-graph/services/graph-session-sse.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { typeIntoExecutionTimeout } from '../../../../shared/components/execution-timeout-field/execution-timeout-field.testing';
import {
    provideLoadedExecutionTimeoutLimits,
    TEST_EXECUTION_TIMEOUT_LIMITS,
} from '../../../../shared/services/execution-timeout-limits/execution-timeout-limits.testing';
import { PythonNodeModel } from '../../../core/models/node.model';
import { PythonNode } from '../../../core/models/python-node.model';
import { FLOW_EDITOR_PREVIEW } from '../../../core/providers/flow-editor-preview.token';
import { FlowService } from '../../../services/flow.service';
import { PollEvent, PythonCodeRunService } from '../../../services/python-code-run.service';
import { SidePanelService } from '../../../services/side-panel.service';
import { FieldChange, FieldName, NodeDiffStatus } from '../../../utils/diff';
import { mapPythonNodeToModel } from '../../../utils/load/nodes/python-node.mapper';
import { CodeDiffViewComponent } from '../../code-diff-view/code-diff-view.component';
import {
    codeMarkDescriptions,
    renderCodeDiffViewWithStubEditor,
    shownCodeDiffs,
} from '../../code-diff-view/code-diff-view.testing';
import { DiffFieldMarkComponent } from '../../diff-field-mark/diff-field-mark.component';
import { InputMapComponent } from '../../input-map/input-map.component';
import { provideChangesTabDiff } from '../../missing-reference-note/missing-reference-note.testing';
import { NodeSecretsFieldComponent } from '../../node-secrets-field/node-secrets-field.component';
import { NodeStorageSectionComponent } from '../../node-storage-section/node-storage-section.component';
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
            provideLoadedExecutionTimeoutLimits(),
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
    uuid: '00000000-0000-4000-8000-000000000031',
    node_number: 1,
    node_name: 'Python #1',
    graph: 1,
    python_code: { id: 5, code: 'def main(count): return count', entrypoint: 'main' },
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
                provideLoadedExecutionTimeoutLimits(),
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

    it('blocks the run after a code or secrets edit', () => {
        open();

        panel.onPythonCodeChange('def main(count): return count + 1');
        expect(blocker()).toBe(SAVE_TO_RUN_LATEST_CODE_MESSAGE);

        panel.onPythonCodeChange(STORED_NODE.python_code.code);
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

    describe('execution timeout', () => {
        const TIMED_NODE: PythonNode = {
            ...STORED_NODE,
            python_code: { ...STORED_NODE.python_code, execution_timeout: 90 },
        };

        function timeoutField(): ExecutionTimeoutFormField {
            return (panel as unknown as { executionTimeout: ExecutionTimeoutFormField }).executionTimeout;
        }

        function startRun(): void {
            const start$ = new Subject<{ execution_id: string }>();
            runService.runPythonCode.mockReturnValue(start$);
            panel.onRunTest({ count: '3' });
            start$.next({ execution_id: 'exec-1' });
        }

        it('shows the stored timeout of the code', () => {
            bindStoredGraph(TIMED_NODE);
            open(mapPythonNodeToModel(TIMED_NODE));

            expect(timeoutField().control.value).toBe(90);
            expect(panel.onSaveSilently()?.data.execution_timeout).toBe(90);
        });

        it('shows the default for a code without a timeout, and keeps none on it until edited', () => {
            open();

            expect(timeoutField().control.value).toBe(TEST_EXECUTION_TIMEOUT_LIMITS.defaultSeconds);
            expect(panel.onSaveSilently()?.data.execution_timeout).toBeUndefined();
        });

        it('puts the edited timeout on the code of the node it saves', () => {
            open();

            timeoutField().edit(300);

            expect(panel.onSaveSilently()?.data.execution_timeout).toBe(300);
        });

        it('saves a timeout still being typed when the panel closes before the input blurs (Esc, switching nodes)', () => {
            open();

            typeIntoExecutionTimeout(timeoutField(), '00:05:00');

            expect(panel.isDirty()).toBe(true);
            expect(panel.onSave()?.data.execution_timeout).toBe(300);
        });

        it('waits for the result as long as the stored code may run', () => {
            bindStoredGraph(TIMED_NODE);
            open(mapPythonNodeToModel(TIMED_NODE));

            startRun();

            expect(runService.pollResultWithEvents).toHaveBeenCalledWith('exec-1', 90);
        });

        it('waits for a stored code without a timeout as long as the default the backend applies to it', () => {
            open();

            startRun();

            expect(runService.pollResultWithEvents).toHaveBeenCalledWith(
                'exec-1',
                TEST_EXECUTION_TIMEOUT_LIMITS.defaultSeconds
            );
        });

        it('blocks the run after an unsaved timeout edit, until it is back to the stored one', () => {
            open();

            timeoutField().edit(300);
            expect(blocker()).toBe(SAVE_TO_RUN_LATEST_CODE_MESSAGE);

            timeoutField().edit(TEST_EXECUTION_TIMEOUT_LIMITS.defaultSeconds);
            expect(blocker()).toBeNull();
        });

        it('runs a stored timeout above the maximum for the maximum, without asking to save it', () => {
            const longNode: PythonNode = {
                ...STORED_NODE,
                python_code: { ...STORED_NODE.python_code, execution_timeout: 7200 },
            };
            bindStoredGraph(longNode);
            open(mapPythonNodeToModel(longNode));

            expect(blocker()).toBeNull();
            startRun();
            expect(runService.pollResultWithEvents).toHaveBeenCalledWith(
                'exec-1',
                TEST_EXECUTION_TIMEOUT_LIMITS.maxSeconds
            );
        });
    });
});

describe('PythonNodePanelComponent node name', () => {
    function openPanelBesideNodeNamed(otherNodeName: string): PythonNodePanelComponent {
        TestBed.configureTestingModule({
            providers: [
                { provide: FLOW_EDITOR_PREVIEW, useValue: false },
                { provide: PermissionsService, useValue: { can: () => true, canEditSecrets: () => true } },
                provideLoadedExecutionTimeoutLimits(),
            ],
        });
        TestBed.overrideComponent(PythonNodePanelComponent, { set: { template: '', imports: [] } });
        const otherNode = { ...pythonNode, id: 'python-2', node_name: otherNodeName };
        TestBed.inject(FlowService).setFlow({ nodes: [pythonNode, otherNode], connections: [] });
        const fixture = TestBed.createComponent(PythonNodePanelComponent);
        fixture.componentRef.setInput('node', pythonNode);
        fixture.detectChanges();
        return fixture.componentInstance;
    }

    it('accepts a name another node in the flow already has: the #N under the name tells them apart', () => {
        const panel = openPanelBesideNodeNamed('Fetch orders');

        panel.form.controls['node_name'].setValue('Fetch orders');

        expect(panel.form.controls['node_name'].valid).toBe(true);
    });

    it.each([
        { name: '', valid: false },
        { name: '   ', valid: false },
        { name: 'x'.repeat(255), valid: true },
        { name: 'x'.repeat(256), valid: false },
    ])('validates a name of $name.length characters as valid=$valid', ({ name, valid }) => {
        const panel = openPanelBesideNodeNamed('Other');

        panel.form.controls['node_name'].setValue(name);

        expect(panel.form.controls['node_name'].valid).toBe(valid);
    });
});

describe('PythonNodePanelComponent Input List and main() signature', () => {
    let fixture: ComponentFixture<PythonNodePanelComponent>;
    let panel: PythonNodePanelComponent;

    afterEach(() => {
        fixture.destroy();
        vi.useRealTimers();
    });

    /** Opens a Python node with only its Input List rendered, as the user sees it. */
    function open(code: string, inputMap: Record<string, string>, isPreview = false): void {
        vi.useFakeTimers();
        TestBed.configureTestingModule({
            providers: [
                provideLoadedExecutionTimeoutLimits(),
                { provide: FLOW_EDITOR_PREVIEW, useValue: isPreview },
                { provide: PermissionsService, useValue: { can: () => true, canEditSecrets: () => true } },
                { provide: PythonCodeRunService, useValue: {} },
                { provide: GraphSessionService, useValue: {} },
                { provide: RunSessionSSEService, useValue: { status: signal(null) } },
            ],
        });
        TestBed.overrideComponent(PythonNodePanelComponent, {
            set: {
                template: `<form [formGroup]="form">
                    <app-input-map
                        [readonly]="isReadOnly()"
                        [showTestMode]="true"
                        [testMode]="isOpenTestMode()"
                        (testModeChange)="isOpenTestMode.set($event)"
                    />
                </form>`,
                imports: [ReactiveFormsModule, InputMapComponent],
            },
        });
        TestBed.overrideComponent(InputMapComponent, {
            set: { imports: [ReactiveFormsModule], schemas: [NO_ERRORS_SCHEMA] },
        });
        fixture = TestBed.createComponent(PythonNodePanelComponent);
        fixture.componentRef.setInput('node', {
            ...pythonNode,
            data: { ...pythonNode.data, code },
            input_map: inputMap,
        } as PythonNodeModel);
        fixture.detectChanges();
        panel = fixture.componentInstance;
    }

    /** What the code editor emits once the user stopped typing for the debounce. */
    function editCode(code: string): void {
        panel.onPythonCodeChange(code);
        vi.advanceTimersByTime(300);
        fixture.detectChanges();
    }

    function rows(name: 'input_map' | 'test_input' = 'input_map'): { key: string; value: string }[] {
        return (panel.form.get(name) as FormArray).getRawValue() as { key: string; value: string }[];
    }

    function typeKey(rowIndex: number, text: string): void {
        const input = fixture.nativeElement.querySelectorAll('input[formControlName="key"]')[
            rowIndex
        ] as HTMLInputElement;
        input.value = text;
        input.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    function click(selector: string, index = 0): void {
        (fixture.nativeElement.querySelectorAll(selector)[index] as HTMLElement).click();
        fixture.detectChanges();
    }

    /** What the Test mode switch does; the panel is expanded, as Test mode asks the shell to. */
    function toggleTestMode(on: boolean): void {
        fixture.componentRef.setInput('isExpanded', true);
        fixture.debugElement.query(By.directive(InputMapComponent)).componentInstance.onTestModeToggle(on);
        fixture.detectChanges();
    }

    describe('when the code changes', () => {
        it('leaves a node whose list and signature disagree as it is when opened and echoed by the editor', () => {
            const code = 'def main(count: int = 1):\n    return count\n';
            open(code, { other: 'variables.other' });

            editCode(code);

            expect(panel.pythonCode).toBe(code);
            expect(rows()).toEqual([{ key: 'other', value: 'variables.other' }]);
            expect(panel.isDirty()).toBe(false);
        });

        it('follows the signature only once the typing stops: a rename keeps the path, a new name gets a row', () => {
            open('def main(count: int = 1, *args):\n    return count\n', { count: 'variables.count' });

            panel.onPythonCodeChange('def main(total: int = 1, name, *args):\n    return total\n');
            vi.advanceTimersByTime(299);
            expect(rows()).toEqual([{ key: 'count', value: 'variables.count' }]);

            vi.advanceTimersByTime(1);
            expect(rows()).toEqual([
                { key: 'total', value: 'variables.count' },
                { key: 'name', value: 'variables.' },
            ]);
            expect(panel.isDirty()).toBe(true);
        });

        it('keeps each path on its name when the parameters are reordered', () => {
            open('def main(a, b):\n    pass\n', { a: 'variables.a', b: 'variables.b' });

            editCode('def main(b, a):\n    pass\n');

            expect(rows()).toEqual([
                { key: 'a', value: 'variables.a' },
                { key: 'b', value: 'variables.b' },
            ]);
        });

        it('removes the row of a removed parameter and gives its path back when the name returns', () => {
            open('def main(count, name):\n    pass\n', { count: 'variables.count', name: 'variables.name' });

            editCode('def main(name):\n    pass\n');
            expect(rows()).toEqual([{ key: 'name', value: 'variables.name' }]);

            editCode('def main():\n    pass\n');
            editCode('def main(c):\n    pass\n');
            editCode('def main(count, c):\n    pass\n');
            expect(rows()).toEqual([
                { key: 'c', value: 'variables.' },
                { key: 'count', value: 'variables.count' },
            ]);
        });

        it('gives a path back to a new row renamed into a removed name', () => {
            open('def main(count):\n    pass\n', { count: 'variables.count' });

            editCode('def main():\n    pass\n');
            editCode('def main(co):\n    pass\n');
            editCode('def main(count):\n    pass\n');

            expect(rows()).toEqual([{ key: 'count', value: 'variables.count' }]);
        });

        it('only adds rows while **kwargs takes any row', () => {
            open('def main(**kwargs):\n    pass\n', { a: 'variables.a', b: 'variables.b' });

            editCode('def main(x, **kwargs):\n    pass\n');

            expect(rows()).toEqual([
                { key: 'a', value: 'variables.a' },
                { key: 'b', value: 'variables.b' },
                { key: 'x', value: 'variables.' },
            ]);
        });

        it('only adds rows for the first signature of a node opened without one', () => {
            open('# write main() here\n', { a: 'variables.a', b: 'variables.b' });

            editCode('def main(x):\n    pass\n');

            expect(rows().map((row) => row.key)).toEqual(['a', 'b', 'x']);
        });

        it.each([
            ['does not parse', 'def main(count, total: dict = {'],
            ['repeats a name', 'def main(count, count):'],
        ])('keeps every row while the signature %s', (_case, code) => {
            open('def main(count):\n    pass\n', { count: 'variables.count' });

            editCode(code);

            expect(rows()).toEqual([{ key: 'count', value: 'variables.count' }]);
        });

        it('syncs the test values in Test mode, and the Input List gets them when it is left', () => {
            open('def main(count):\n    pass\n', { count: 'variables.count' });
            toggleTestMode(true);

            editCode('def main(count, extra):\n    pass\n');
            expect(rows('test_input').map((row) => row.key)).toEqual(['count', 'extra']);

            toggleTestMode(false);
            expect(rows()).toEqual([
                { key: 'count', value: 'variables.count' },
                { key: 'extra', value: 'variables.' },
            ]);
        });

        it('does not sync in a read-only version preview', () => {
            open('def main(count):\n    pass\n', { count: 'variables.count' }, true);

            editCode('def main(total):\n    pass\n');

            expect(rows()).toEqual([{ key: 'count', value: 'variables.count' }]);
        });
    });

    describe('when the Input List changes', () => {
        const CODE = 'def main(count: int, *args):\n    return count\n';

        it('rewrites only the signature when a row is renamed, added or removed', () => {
            open(CODE, { count: 'variables.count' });

            typeKey(0, 'total');
            expect(panel.pythonCode).toBe('def main(total: int, *args):\n    return count\n');

            click('.add-pair-btn');
            typeKey(1, 'name');
            expect(panel.pythonCode).toBe('def main(total: int, name, *args):\n    return count\n');

            click('.delete-icon', 0);
            expect(panel.pythonCode).toBe('def main(name, *args):\n    return count\n');
            expect(panel.isDirty()).toBe(true);
        });

        it('renames the parameter of that name whatever the order of the rows', () => {
            open('def main(a: int, b: str = "x"):\n    pass\n', { b: 'variables.b', a: 'variables.a' });

            typeKey(0, 'c');

            expect(panel.pythonCode).toBe('def main(a: int, c: str = "x"):\n    pass\n');
        });

        it('waits while a key is not a valid name yet, then applies the rename', () => {
            open(CODE, { count: 'variables.count' });

            typeKey(0, 'count-');
            expect(panel.pythonCode).toBe(CODE);

            typeKey(0, 'counter');
            expect(panel.pythonCode).toBe('def main(counter: int, *args):\n    return count\n');
        });

        it('leaves the code alone rather than add a parameter without a default after a defaulted one', () => {
            const code = 'def main(a, b="x"):\n    pass\n';
            open(code, { a: 'variables.a', b: 'variables.b' });

            click('.add-pair-btn');
            typeKey(2, 'c');

            expect(panel.pythonCode).toBe(code);
        });

        it('leaves a signature edit still waiting for its sync to the code editor', () => {
            open(CODE, { count: 'variables.count' });

            panel.onPythonCodeChange('def main(count: int, extra, *args):\n    return count\n');
            typeKey(0, 'total');

            expect(panel.pythonCode).toBe('def main(count: int, extra, *args):\n    return count\n');
        });
    });
});

type DrawnBoxStyle = 'display' | 'paddingTop';
/** What jsdom resolves of a value box the mark draws: while marked, and without the mark. */
interface DrawnBox {
    marked: Partial<Record<DrawnBoxStyle, string>>;
    plain: Partial<Record<DrawnBoxStyle, string>>;
}

describe('PythonNodePanelComponent on the Changes tab of a version preview', () => {
    let fixture: ComponentFixture<PythonNodePanelComponent>;

    afterEach(() => fixture.destroy());

    function change(field: FieldName, current: unknown, version: unknown): FieldChange {
        return { path: field, field, status: 'changed', current, version };
    }

    /**
     * Opens the node with its own template and the fields it marks real (the code editor is not rendered), narrow
     * unless `expanded`; with no diff off the Changes tab (the Preview tab, the live editor).
     */
    function open(
        status: NodeDiffStatus,
        fields: FieldChange[],
        { expanded = false, onChangesTab = true } = {}
    ): HTMLElement {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                provideLoadedExecutionTimeoutLimits(),
                { provide: FLOW_EDITOR_PREVIEW, useValue: true },
                { provide: PermissionsService, useValue: { can: () => true, canEditSecrets: () => false } },
                { provide: PythonCodeRunService, useValue: {} },
                { provide: GraphSessionService, useValue: {} },
                { provide: RunSessionSSEService, useValue: { status: signal(null) } },
                ...(onChangesTab ? [provideChangesTabDiff({ status, fields })] : []),
            ],
        });
        renderCodeDiffViewWithStubEditor();
        TestBed.overrideComponent(PythonNodePanelComponent, {
            set: {
                imports: [
                    ReactiveFormsModule,
                    CustomInputComponent,
                    InputMapComponent,
                    NodeSecretsFieldComponent,
                    ExecutionTimeoutFieldComponent,
                    NodeStorageSectionComponent,
                    DiffFieldMarkComponent,
                    CodeDiffViewComponent,
                    SelectComponent,
                ],
                schemas: [NO_ERRORS_SCHEMA],
            },
        });
        TestBed.overrideComponent(InputMapComponent, {
            set: {
                imports: [ReactiveFormsModule, NgTemplateOutlet, DiffFieldMarkComponent],
                schemas: [NO_ERRORS_SCHEMA],
            },
        });
        fixture = TestBed.createComponent(PythonNodePanelComponent);
        fixture.componentRef.setInput('node', {
            ...pythonNode,
            input_map: { user: 'variables.account', kept: 'variables.kept' },
        } as PythonNodeModel);
        fixture.componentRef.setInput('isExpanded', expanded);
        fixture.detectChanges();
        return fixture.nativeElement;
    }

    /** Each marked field, named by its form control or, for a field without one, by its element. */
    const markedFields = (root: HTMLElement): string[] =>
        Array.from(root.querySelectorAll('app-diff-field-mark.diff-field-mark--shown'), (mark) => {
            const field = mark.firstElementChild!;
            return field.getAttribute('formcontrolname') ?? field.tagName.toLowerCase();
        });

    /**
     * Where each field draws its mark: the value box gets the border and the badge (`badgeOn`, the box or an element
     * around it that does not clip the badge); the label stays outside. jsdom does not resolve the border colour
     * (a CSS variable), so the badge's anchor (`position: relative` only while marked) shows which element is marked.
     * A field whose value has no box of its own gets one drawn (`drawnBox`: what jsdom resolves of it, marked and
     * plain). The timeout control and the secrets picker only change their border colour, which jsdom cannot
     * resolve, so only their badge anchor is checked.
     */
    const READ_ONLY_VALUE_BOX: DrawnBox = {
        marked: { display: 'block', paddingTop: '8px' },
        plain: { display: 'inline', paddingTop: '0' },
    };
    const FIELDS: {
        change: FieldChange;
        marked: string;
        badgeOn: string;
        label: string | null;
        drawnBox: DrawnBox | null;
    }[] = [
        {
            change: change('node_name', 'Fetch', 'Fetch v2'),
            marked: 'node_name',
            badgeOn: '.readonly-value',
            label: 'label',
            drawnBox: READ_ONLY_VALUE_BOX,
        },
        {
            change: change('output_variable_path', null, 'variables.result'),
            marked: 'output_variable_path',
            badgeOn: '.readonly-value',
            label: 'label',
            drawnBox: READ_ONLY_VALUE_BOX,
        },
        {
            change: change('python_code.venv_id', 3, null),
            marked: 'venv',
            badgeOn: '.selector__readonly-value',
            label: 'app-tooltip',
            drawnBox: null,
        },
        {
            change: change('python_code.secret_names', ['DB_PASS'], ['STRIPE_KEY']),
            marked: 'app-node-secrets-field',
            badgeOn: '.secrets-trigger',
            label: '.label-container label',
            drawnBox: null,
        },
        {
            change: change('python_code.execution_timeout', 30, 60),
            marked: 'app-execution-timeout-field',
            // The border goes on the control inside the group; not checked (see above).
            badgeOn: '.execution-timeout__group',
            label: 'app-tooltip',
            drawnBox: null,
        },
        // A toggle has no value box: its row, label included, is boxed.
        {
            change: change('use_storage', false, true),
            marked: 'app-node-storage-section',
            badgeOn: '.storage-header',
            label: null,
            // The row stays a flex row; only the box is drawn around it.
            drawnBox: { marked: { paddingTop: '8px' }, plain: { paddingTop: '0' } },
        },
    ];

    const positionOf = (element: Element): string => getComputedStyle(element).position;
    /** The styles of `element` named in `expected`, to compare with it. */
    const stylesOf = (element: Element, expected: Partial<Record<DrawnBoxStyle, string>>) =>
        Object.fromEntries(
            Object.keys(expected).map((name) => [name, getComputedStyle(element)[name as DrawnBoxStyle]])
        );

    it.each(FIELDS)(
        'marks $change.field, and only it, when a restore changes it',
        ({ change: fieldChange, marked }) => {
            expect(markedFields(open('changed', [fieldChange]))).toEqual([marked]);
        }
    );

    it.each(FIELDS)(
        'draws the mark of $change.field on its value, not on its label',
        ({ change: fieldChange, badgeOn, label, drawnBox }) => {
            const mark = open('changed', [fieldChange]).querySelector('app-diff-field-mark.diff-field-mark--shown')!;
            const valueBox = mark.querySelector(badgeOn)!;

            expect(positionOf(valueBox)).toBe('relative');
            if (drawnBox) expect(stylesOf(valueBox, drawnBox.marked)).toEqual(drawnBox.marked);
            if (label === null) return;
            const labelElement = mark.querySelector(label)!;
            expect(valueBox.contains(labelElement)).toBe(false);
            expect(positionOf(labelElement)).toBe('static');
        }
    );

    it('leaves every field as it is without a field change, as in the live editor', () => {
        const root = open('changed', []);

        expect(root.querySelector('.diff-value-marked')).toBeNull();
        for (const { badgeOn, drawnBox } of FIELDS) {
            const valueBoxes = Array.from(root.querySelectorAll(badgeOn));
            expect(valueBoxes.length).toBeGreaterThan(0);
            expect(valueBoxes.map(positionOf)).toEqual(valueBoxes.map(() => 'static'));
            if (!drawnBox) continue;
            for (const valueBox of valueBoxes) expect(stylesOf(valueBox, drawnBox.plain)).toEqual(drawnBox.plain);
        }
    });

    /** Hovers the marked field; its tooltip's current value, struck parts in brackets. */
    function hoverTooltip(root: HTMLElement): string {
        root.querySelector('app-diff-field-mark.diff-field-mark--shown')!.dispatchEvent(new Event('mouseenter'));
        fixture.detectChanges();
        return Array.from(document.querySelectorAll<HTMLElement>('.diff-field-mark__tooltip-value > span'))
            .map((part) =>
                part.classList.contains('diff-field-mark__struck') ? `[${part.textContent}]` : part.textContent
            )
            .join('');
    }

    it.each([
        { kind: 'a timeout of its own', current: 90, version: 600, shown: '[00:01:30]' },
        // The field shows the default timeout then (120 seconds in these limits), and so does the tooltip.
        { kind: 'no timeout of its own', current: null, version: 600, shown: '[00:02:00]' },
        // A restore pins the default: the same clock, so nothing is struck.
        {
            kind: 'no timeout of its own, the version pinning the default',
            current: null,
            version: 120,
            shown: '00:02:00',
        },
    ])(
        'shows the current execution timeout of a node with $kind as the clock the field shows',
        ({ current, version, shown }) => {
            const root = open('changed', [change('python_code.execution_timeout', current, version)]);

            expect(hoverTooltip(root)).toBe(shown);
        }
    );

    describe('a changed venv', () => {
        /** Answers the panel's venv list request with venv 3, "data-science". */
        function respondWithVenvs(): void {
            TestBed.inject(HttpTestingController)
                .expectOne((request) => request.url.endsWith('venvs/'))
                .flush({
                    count: 1,
                    limit: 100,
                    offset: 0,
                    next: null,
                    previous: null,
                    result: [{ id: 3, name: 'data-science' }],
                });
            fixture.detectChanges();
        }

        it.each([
            { kind: 'a listed venv by its name', current: 3, version: null, shown: '[data-science]' },
            { kind: 'a venv the list does not hold by its id', current: 9, version: 3, shown: '[venv #9]' },
            { kind: 'no venv as empty', current: null, version: 3, shown: '[empty]' },
        ])('names $kind in the tooltip', ({ current, version, shown }) => {
            const root = open('changed', [change('python_code.venv_id', current, version)]);
            respondWithVenvs();

            expect(hoverTooltip(root)).toBe(shown);
        });
    });

    describe('a changed code', () => {
        const CODE_CHANGE = change('python_code.code', 'a = 1\n', 'a = 2\n');
        const codeEditors = (root: HTMLElement): number => root.querySelectorAll('app-code-editor').length;

        it('marks the code editor of the narrow panel, and only it, with the expand hint', () => {
            const root = open('changed', [CODE_CHANGE]);

            expect(markedFields(root)).toEqual(['app-code-editor']);
            expect(codeMarkDescriptions(root)).toEqual(['Expand the panel to see the changes.']);
            expect(shownCodeDiffs(fixture.debugElement)).toEqual([]);
        });

        it('is shown as a diff of the current canvas code and the version code in the widened panel', () => {
            const root = open('changed', [CODE_CHANGE], { expanded: true });

            expect(shownCodeDiffs(fixture.debugElement)).toEqual([{ current: 'a = 1\n', version: 'a = 2\n' }]);
            expect(codeEditors(root)).toBe(0);
            expect(markedFields(root)).toEqual([]);
        });

        it('switches between the mark and the diff as the panel is widened and narrowed', () => {
            const root = open('changed', [CODE_CHANGE]);

            fixture.componentRef.setInput('isExpanded', true);
            fixture.detectChanges();
            expect(shownCodeDiffs(fixture.debugElement)).toHaveLength(1);

            fixture.componentRef.setInput('isExpanded', false);
            fixture.detectChanges();
            expect(shownCodeDiffs(fixture.debugElement)).toEqual([]);
            expect(codeMarkDescriptions(root)).toEqual(['Expand the panel to see the changes.']);
        });

        const KEEPS_EDITOR = [
            { case: 'the code is unchanged', status: 'changed' as const, fields: [change('node_name', 'a', 'b')] },
            { case: 'the node is added', status: 'added' as const, fields: [CODE_CHANGE] },
            { case: 'the node is removed', status: 'deleted' as const, fields: [CODE_CHANGE] },
        ].flatMap((keeps) => [false, true].map((expanded) => ({ ...keeps, expanded })));

        it.each(KEEPS_EDITOR)(
            'keeps the normal editor when $case (widened: $expanded)',
            ({ status, fields, expanded }) => {
                const root = open(status, fields, { expanded });

                expect(codeEditors(root)).toBe(1);
                expect(codeMarkDescriptions(root)).toEqual([]);
                expect(shownCodeDiffs(fixture.debugElement)).toEqual([]);
            }
        );

        it('keeps the normal editor off the Changes tab (Preview tab, live editor)', () => {
            const root = open('changed', [CODE_CHANGE], { expanded: true, onChangesTab: false });

            expect(codeEditors(root)).toBe(1);
            expect(shownCodeDiffs(fixture.debugElement)).toEqual([]);
        });
    });

    it('marks the Input List per row, not as a whole field', () => {
        const root = open('changed', [
            change(
                'input_map',
                { user: 'variables.user', kept: 'variables.kept', gone: 'variables.gone' },
                { user: 'variables.account', kept: 'variables.kept' }
            ),
        ]);

        expect(markedFields(root)).toEqual([]);
        const rowMarks = Array.from(root.querySelectorAll<HTMLElement>('.readonly-row'), (row) => [
            Array.from(row.querySelectorAll('.readonly-cell'), (cell) =>
                cell.textContent?.replace(/\s+/g, ' ').trim()
            ).join(' '),
            row.classList.contains('diff-field-mark--shown') || row.classList.contains('readonly-row--removed'),
        ]);
        expect(rowMarks).toEqual([
            ['user variables.account', true],
            ['kept variables.kept', false],
            ['Restore removes this input: gone variables.gone', true],
        ]);
    });

    it.each(['added', 'deleted'] as const)('marks nothing on a node whose status is %s', (status) => {
        const root = open(status, [
            change('node_name', 'Fetch', 'Fetch v2'),
            change('input_map', { user: 'variables.user' }, { user: 'variables.account' }),
        ]);

        expect(markedFields(root)).toEqual([]);
        expect(root.querySelector('.readonly-row.diff-field-mark--shown, .readonly-row--removed')).toBeNull();
    });
});

describe('PythonNodePanelComponent venv selection', () => {
    function venv(id: number, name: string, status: VenvStatus): Venv {
        return { id, name, libs: [], status, error: null, owner: null, created_at: null, is_favorite: false };
    }

    const BUILDING = venv(5, 'ml base', 'processing');
    const READY = venv(6, 'web', 'completed');
    const QUEUED = venv(7, 'queued base', 'declared');

    /** The panel with a stubbed sandbox and a dialog that answers `confirmed` without opening. */
    function create(confirmed: boolean, venvs: Venv[] = [BUILDING, READY]) {
        const confirm = vi.fn(() => of(confirmed));
        const getVenvs = vi.fn(() => of(venvs));
        TestBed.configureTestingModule({
            providers: [
                provideLoadedExecutionTimeoutLimits(),
                { provide: FLOW_EDITOR_PREVIEW, useValue: false },
                { provide: PermissionsService, useValue: { can: () => true, canEditSecrets: () => true } },
                { provide: VenvsApiService, useValue: { getVenvs } },
                { provide: ConfirmationDialogService, useValue: { confirm } },
            ],
        });
        TestBed.overrideComponent(PythonNodePanelComponent, { set: { template: '', imports: [] } });
        const fixture = TestBed.createComponent(PythonNodePanelComponent);
        fixture.componentRef.setInput('node', pythonNode);
        fixture.detectChanges();
        return { panel: fixture.componentInstance, confirm, getVenvs };
    }

    it('keeps a venv that is still building once the warning is accepted', () => {
        const { panel, confirm } = create(true);

        // The picker writes the value and then reports it, so the test does the same.
        panel.form.get('venv')!.setValue(BUILDING.id);
        panel.onVenvChanged(BUILDING.id);

        expect(confirm).toHaveBeenCalledOnce();
        expect(panel.form.get('venv')!.value).toBe(BUILDING.id);
    });

    it('puts the previous venv back when the warning is declined', () => {
        const { panel } = create(false);
        panel.form.get('venv')!.setValue(READY.id);
        panel.onVenvChanged(READY.id);

        // The picker writes before asking, so declining has to undo the write.
        panel.form.get('venv')!.setValue(BUILDING.id);
        panel.onVenvChanged(BUILDING.id);

        expect(panel.form.get('venv')!.value).toBe(READY.id);
    });

    // Declared means the build has not even started: the flow waits just the same, so the
    // warning has to cover it and not only a build already running.
    it('warns before a venv whose build has not started yet is used', () => {
        const { panel, confirm } = create(true, [QUEUED, READY]);

        panel.form.get('venv')!.setValue(QUEUED.id);
        panel.onVenvChanged(QUEUED.id);

        expect(confirm).toHaveBeenCalledOnce();
        expect(panel.form.get('venv')!.value).toBe(QUEUED.id);
    });

    it('says nothing about a venv that is built', () => {
        const { panel, confirm } = create(true);

        panel.form.get('venv')!.setValue(READY.id);
        panel.onVenvChanged(READY.id);

        expect(confirm).not.toHaveBeenCalled();
        expect(panel.form.get('venv')!.value).toBe(READY.id);
    });

    it('reloads the venvs when the picker opens', () => {
        const { panel, getVenvs } = create(true);
        getVenvs.mockReturnValue(of([READY]));

        panel.onVenvDropdownOpened();

        // Asserted on the state, not on the call: a build finished since the panel opened.
        expect(panel.venvs()).toEqual([READY]);
    });
});
