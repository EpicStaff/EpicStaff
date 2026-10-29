import { Dialog } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationRef, Component, input, NO_ERRORS_SCHEMA, output, Provider, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { FFlowModule, FZoomDirective } from '@foblex/flow';
import { ExecutionTimeoutFieldComponent, ExecutionTimeoutFormField, JsonEditorComponent } from '@shared/components';
import { NodeType } from '@shared/models';
import { FullLLMConfigService } from '@shared/services';
import { of } from 'rxjs';

import { ImportExportService } from '../../../../core/services/import-export.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import {
    provideLoadedExecutionTimeoutLimits,
    TEST_EXECUTION_TIMEOUT_LIMITS,
} from '../../../../shared/services/execution-timeout-limits/execution-timeout-limits.testing';
import { CodeEditorComponent } from '../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import { generatePortsForClassificationDecisionTableNode, generatePortsForNode } from '../../../core/helpers/helpers';
import { CdtExplanation, CdtExplanations } from '../../../core/models/classification-decision-table.model';
import { ConditionGroup } from '../../../core/models/decision-table.model';
import { FlowModel } from '../../../core/models/flow.model';
import { ClassificationDecisionTableNodeModel, NodeModel } from '../../../core/models/node.model';
import { FLOW_EDITOR_PREVIEW } from '../../../core/providers/flow-editor-preview.token';
import { CdtExplainApiService } from '../../../services/cdt-explain-api.service';
import { FlowService } from '../../../services/flow.service';
import { SavedFlowStateService } from '../../../services/saved-flow-state.service';
import { SidePanelService } from '../../../services/side-panel.service';
import { UndoRedoService } from '../../../services/undo-redo.service';
import { createFlowConnection } from '../../../utils/connection.factory';
import { FieldChange, FieldName, NodeDiffStatus } from '../../../utils/diff';
import { buildUuidToBackendIdMap, getConnectionDiff, getNodeDiff } from '../../../utils/save/diff';
import { buildBulkSavePayload } from '../../../utils/save/payload';
import {
    codeMarkDescriptions,
    renderCodeDiffViewWithStubEditor,
    shownCodeDiffs,
} from '../../code-diff-view/code-diff-view.testing';
import { provideChangesTabDiff } from '../../missing-reference-note/missing-reference-note.testing';
import { CDT_ROUTE_CONTINUE_COPY } from './cdt.constants';
import { CdtDecisionTreeBlockComponent } from './cdt-decision-tree-dialog/cdt-decision-tree-block/cdt-decision-tree-block.component';
import { CdtDecisionTreeDialogComponent } from './cdt-decision-tree-dialog/cdt-decision-tree-dialog.component';
import { CdtExportImportService } from './cdt-export-import.service';
import {
    CdtEnableContinueRequest,
    CdtRuleIdentityEdit,
    ClassificationDecisionTableGridComponent,
} from './classification-decision-table-grid/classification-decision-table-grid.component';
import { ClassificationDecisionTableNodePanelComponent } from './classification-decision-table-node-panel.component';

/**
 * The panel half of "Enable Continue": free the route port on the canvas, then
 * adopt the grid's rows. Mounted with the panel's real template and a stand-in for
 * the grid alone (the real one has its own DOM spec): renaming or dropping one of the
 * template's grid bindings fails here. Unknown bindings are errors, not warnings.
 */

/** Stands in for the Monaco-backed editor, which needs a browser runtime the tests do not load. */
@Component({ selector: 'app-code-editor', template: '' })
class CodeEditorStubComponent {
    readonly pythonCode = input<unknown>();
    readonly secretNames = input<unknown>();
    readonly inputMapKeys = input<unknown>();
    readonly readOnly = input(false);
    readonly pythonCodeChange = output<string>();
}

/**
 * Stands in for the grid, with its inputs and outputs: records what the panel hands it
 * and lets a test emit what it emits.
 */
@Component({ selector: 'app-classification-decision-table-grid', template: '' })
class GridStubComponent {
    readonly conditionGroups = input<ConditionGroup[]>([]);
    readonly sections = input<unknown>();
    readonly activeColor = input<unknown>();
    readonly currentNodeId = input<string>();
    readonly storageNodeId = input<unknown>();
    readonly prompts = input<unknown>();
    readonly defaultLlmId = input<unknown>();
    readonly llmConfigs = input<unknown>();
    readonly preInputMapKeys = input<unknown>();
    readonly domainKeys = input<unknown>();
    readonly routePortIdsWithTarget = input<ReadonlySet<string>>(new Set());
    readonly readonly = input(false);
    readonly rowChanges = input<unknown>(null);
    readonly conditionGroupsChange = output<ConditionGroup[]>();
    readonly sectionsChange = output<unknown>();
    readonly enableContinueRequest = output<CdtEnableContinueRequest>();
    readonly ruleIdentityEdit = output<CdtRuleIdentityEdit>();
    readonly promptChange = output<unknown>();
    readonly promptAdd = output<unknown>();
    readonly openPromptLibrary = output<unknown>();
    readonly gridVerticalScroll = output<unknown>();
}

const NODE_ID = 'table1';
const APPROVE_PORT = `${NODE_ID}_decision-route-approve`;

function rule(overrides: Partial<ConditionGroup>): ConditionGroup {
    return {
        group_name: 'Rule',
        group_type: 'simple',
        expression: null,
        conditions: [],
        manipulation: null,
        next_node: null,
        dock_visible: true,
        ...overrides,
    };
}

const CANVAS_ROWS = [
    rule({ group_name: 'Approve', route_code: 'approve', continue_flag: false, next_node: 'py1', order: 1 }),
    rule({ group_name: 'Reject', route_code: 'reject', continue_flag: false, order: 2 }),
];

function tableNode(): ClassificationDecisionTableNodeModel {
    return {
        id: NODE_ID,
        backendId: 21,
        type: NodeType.CLASSIFICATION_TABLE,
        node_name: 'Triage',
        data: { name: 'Triage', table: { condition_groups: CANVAS_ROWS, prompts: {} } },
        position: { x: 0, y: 0 },
        ports: generatePortsForClassificationDecisionTableNode(NODE_ID, CANVAS_ROWS),
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

/** What the grid hands over on confirm: the row ticked, the port's rows without a target. */
function confirmedRows(): ConditionGroup[] {
    return [{ ...CANVAS_ROWS[0], continue_flag: true, next_node: null }, { ...CANVAS_ROWS[1] }];
}

const APPROVE_CONNECTION = createFlowConnection(NODE_ID, 'py1', APPROVE_PORT, 'py1_python-in');
const UNRELATED_CONNECTION = createFlowConnection('py1', 'py2', 'py1_python-out', 'py2_python-in');

/**
 * The panel's real template with the grid and the code editor stubbed. Unknown bindings are errors, not warnings.
 */
function configurePanelTestBed({ isPreview = false, providers = [] as Provider[] } = {}): void {
    TestBed.configureTestingModule({
        errorOnUnknownProperties: true,
        errorOnUnknownElements: true,
        providers: [
            provideHttpClient(),
            provideHttpClientTesting(),
            provideLoadedExecutionTimeoutLimits(),
            { provide: FLOW_EDITOR_PREVIEW, useValue: isPreview },
            { provide: PermissionsService, useValue: { can: () => true, canEditSecrets: () => true } },
            {
                provide: FullLLMConfigService,
                useValue: { fullLLMConfigs: signal([]), getFullLLMConfigs: () => of([]) },
            },
            ...providers,
        ],
    });
    TestBed.overrideComponent(ClassificationDecisionTableNodePanelComponent, {
        remove: { imports: [ClassificationDecisionTableGridComponent, CodeEditorComponent] },
        add: { imports: [GridStubComponent, CodeEditorStubComponent] },
    });
}

describe('ClassificationDecisionTableNodePanelComponent — enabling Continue on a wired route code', () => {
    let fixture: ComponentFixture<ClassificationDecisionTableNodePanelComponent>;
    let panel: ClassificationDecisionTableNodePanelComponent;
    let flowService: FlowService;
    let undoRedo: UndoRedoService;
    let toastError: ReturnType<typeof vi.spyOn>;

    function create(isPreview = false): void {
        configurePanelTestBed({ isPreview });

        flowService = TestBed.inject(FlowService);
        flowService.setFlow({
            nodes: [tableNode(), pythonNode('py1'), pythonNode('py2')],
            connections: [APPROVE_CONNECTION, UNRELATED_CONNECTION],
        });
        undoRedo = TestBed.inject(UndoRedoService);
        toastError = vi.spyOn(TestBed.inject(ToastService), 'error').mockImplementation(() => undefined);

        fixture = TestBed.createComponent(ClassificationDecisionTableNodePanelComponent);
        fixture.componentRef.setInput('node', flowService.nodes()[0]);
        fixture.detectChanges();
        panel = fixture.componentInstance;
        panel.conditionGroups.set(CANVAS_ROWS.map((row) => ({ ...row })));
    }

    function grid(): GridStubComponent {
        return fixture.debugElement.query(By.directive(GridStubComponent)).componentInstance as GridStubComponent;
    }

    /** The wired route ports the panel hands the grid. */
    function portIds(): ReadonlySet<string> {
        fixture.detectChanges();
        return grid().routePortIdsWithTarget();
    }

    /** The rows the panel hands the grid. */
    function rowsHandedToGrid(): ConditionGroup[] {
        fixture.detectChanges();
        return grid().conditionGroups();
    }

    /** What the grid emits once the user confirms Continue. */
    function confirmInGrid(request: CdtEnableContinueRequest): void {
        grid().enableContinueRequest.emit(request);
        fixture.detectChanges();
    }

    /** What the shell does: it feeds the panel the live node from `FlowService`. */
    function feedLiveNode(): void {
        fixture.componentRef.setInput(
            'node',
            flowService.nodes().find((node) => node.id === NODE_ID)
        );
    }

    function connectionIds(): string[] {
        return flowService.connections().map((connection) => connection.id);
    }

    it('removes the connection on the port, with an undo snapshot first, then adopts the rows', () => {
        create();
        const order: string[] = [];
        const stateChanged = vi.spyOn(undoRedo, 'stateChanged').mockImplementation(() => order.push('snapshot'));
        const deleteSelections = vi.spyOn(flowService, 'deleteSelections');
        deleteSelections.mockImplementationOnce((selection) => {
            order.push('delete');
            return FlowService.prototype.deleteSelections.call(flowService, selection);
        });

        confirmInGrid({ portId: APPROVE_PORT, rows: confirmedRows() });

        expect(order).toEqual(['snapshot', 'delete']);
        expect(stateChanged).toHaveBeenCalledTimes(1);
        expect(deleteSelections).toHaveBeenCalledExactlyOnceWith({
            fNodeIds: [],
            fConnectionIds: [APPROVE_CONNECTION.id],
        });
        expect(connectionIds()).toEqual([UNRELATED_CONNECTION.id]);
        expect(rowsHandedToGrid()).toEqual(confirmedRows());
        expect(toastError).not.toHaveBeenCalled();
    });

    it('adopts the rows without a snapshot when the port is already free', () => {
        create();
        const stateChanged = vi.spyOn(undoRedo, 'stateChanged');
        const otherPort = `${NODE_ID}_decision-route-reject`;

        confirmInGrid({ portId: otherPort, rows: confirmedRows() });

        expect(stateChanged).not.toHaveBeenCalled();
        expect(connectionIds()).toEqual([APPROVE_CONNECTION.id, UNRELATED_CONNECTION.id]);
        expect(rowsHandedToGrid()).toEqual(confirmedRows());
    });

    it('says so and keeps the rows unticked when the connection survives', () => {
        create();
        vi.spyOn(flowService, 'deleteSelections').mockImplementation(() => undefined);

        confirmInGrid({ portId: APPROVE_PORT, rows: confirmedRows() });

        expect(toastError).toHaveBeenCalledExactlyOnceWith(
            CDT_ROUTE_CONTINUE_COPY.enableContinueFailed,
            undefined,
            'bottom-right'
        );
        expect(rowsHandedToGrid()[0].continue_flag).toBe(false);
    });

    it('does nothing in a read-only editor', () => {
        create(true);
        const deleteSelections = vi.spyOn(flowService, 'deleteSelections');

        confirmInGrid({ portId: APPROVE_PORT, rows: confirmedRows() });

        expect(deleteSelections).not.toHaveBeenCalled();
        expect(connectionIds()).toContain(APPROVE_CONNECTION.id);
        expect(rowsHandedToGrid()[0].continue_flag).toBe(false);
    });

    describe('wired route ports handed to the grid', () => {
        it('lists a route code wired on the canvas', () => {
            create();

            expect([...portIds()]).toEqual([APPROVE_PORT]);
        });

        it('keeps the same set — so the grid does not refresh — while the answer is unchanged', () => {
            create();
            const before = portIds();

            flowService.removeConnection(UNRELATED_CONNECTION.id);
            feedLiveNode();

            expect(portIds()).toBe(before);
        });

        it('hands over a new set once the route is unwired', () => {
            create();
            const before = portIds();

            flowService.deleteSelections({ fNodeIds: [], fConnectionIds: [APPROVE_CONNECTION.id] });
            feedLiveNode();

            expect(portIds()).not.toBe(before);
            expect(portIds().size).toBe(0);
        });
    });
});

/**
 * Explanations follow a rule whose route code changes: the grid reports the edit,
 * the panel has the store move them, and the shell's autosave pushes the edited
 * rows without putting the old keys back. The decision tree is the real dialog,
 * opened by the panel through the CDK the way the button opens it; Foblex is
 * stripped from it as in its own spec.
 */
describe('ClassificationDecisionTableNodePanelComponent — explanations of a rule whose route code changes', () => {
    const MODEL = 7;
    const OLD_KEY = 'rule:route:approve:decision';
    const NEW_KEY = 'rule:route:approved:decision';
    const EXPLAINED: CdtExplanation = { text: 'Approves confident scores', fingerprint: 'f', generatedBy: 'model' };

    const EXPLAINABLE_ROWS = [
        rule({ group_name: 'Approve', route_code: 'approve', expression: 'score > 0.8', order: 1 }),
        rule({ group_name: 'Reject', route_code: 'reject', expression: 'score < 0.2', order: 2 }),
    ];

    let fixture: ComponentFixture<ClassificationDecisionTableNodePanelComponent>;
    let panel: ClassificationDecisionTableNodePanelComponent;
    let flowService: FlowService;
    let explainApi: { explain: ReturnType<typeof vi.fn> };
    let persistRequests: string[];

    beforeAll(() => {
        // The detail window measures its code block with a ResizeObserver; jsdom has none.
        const scope = globalThis as unknown as { ResizeObserver?: unknown };
        scope.ResizeObserver ??= class {
            observe(): void {}
            unobserve(): void {}
            disconnect(): void {}
        };
    });

    afterEach(() => {
        TestBed.inject(Dialog).closeAll();
        document.querySelectorAll('.cdk-overlay-container').forEach((element) => (element.innerHTML = ''));
        localStorage.clear();
    });

    function create(explanations: CdtExplanations, isPreview = false): void {
        localStorage.clear();
        explainApi = { explain: vi.fn() };
        configurePanelTestBed({ isPreview, providers: [{ provide: CdtExplainApiService, useValue: explainApi }] });
        TestBed.overrideComponent(CdtDecisionTreeDialogComponent, {
            remove: { imports: [FFlowModule, FZoomDirective] },
            add: { schemas: [NO_ERRORS_SCHEMA] },
        });
        TestBed.overrideComponent(CdtDecisionTreeBlockComponent, {
            remove: { imports: [FFlowModule] },
            add: { schemas: [NO_ERRORS_SCHEMA] },
        });

        flowService = TestBed.inject(FlowService);
        flowService.setFlow({
            nodes: [
                {
                    ...tableNode(),
                    data: {
                        name: 'Triage',
                        table: { condition_groups: EXPLAINABLE_ROWS, prompts: {}, default_llm_config: MODEL },
                    },
                    ports: generatePortsForClassificationDecisionTableNode(NODE_ID, EXPLAINABLE_ROWS),
                    explanations,
                } as unknown as ClassificationDecisionTableNodeModel,
            ],
            connections: [],
        });
        persistRequests = [];
        TestBed.inject(SidePanelService).cdtExplanationsSaveRequest$.subscribe((nodeId) =>
            persistRequests.push(nodeId)
        );

        fixture = TestBed.createComponent(ClassificationDecisionTableNodePanelComponent);
        feedLiveNode();
        fixture.detectChanges();
        panel = fixture.componentInstance;
    }

    function grid(): GridStubComponent {
        return fixture.debugElement.query(By.directive(GridStubComponent)).componentInstance as GridStubComponent;
    }

    /** What the shell does once change detection reaches it: feeds the panel the live node. */
    function feedLiveNode(): void {
        fixture.componentRef.setInput(
            'node',
            flowService.nodes().find((node) => node.id === NODE_ID)
        );
    }

    function canvasExplanations(): CdtExplanations {
        const node = flowService.nodes().find((candidate) => candidate.id === NODE_ID);
        return (node as ClassificationDecisionTableNodeModel).explanations ?? {};
    }

    /** What the grid emits for a typed route code: the edit, then the rows. */
    function editRouteCodeInGrid(rowIndex: number, routeCode: string): void {
        const rowsBefore = panel.conditionGroups();
        const rowsAfter = rowsBefore.map((row, index) =>
            index === rowIndex ? { ...row, route_code: routeCode } : { ...row }
        );
        grid().ruleIdentityEdit.emit({ rowsBefore, rowsAfter, rowIndex });
        grid().conditionGroupsChange.emit(rowsAfter);
    }

    /**
     * The shell's autosave: it runs in the change detection pass that will hand the
     * panel the updated canvas node, but before it does — so the panel still holds the
     * node from before the move. Then pushed to the canvas as `onNodePanelAutosaved` does.
     */
    function autosaveAsTheShellDoes(): ClassificationDecisionTableNodeModel {
        const pushed = panel.onSave();
        if (!pushed) throw new Error('the panel saved nothing');
        flowService.updateNode(pushed);
        feedLiveNode();
        fixture.detectChanges();
        return pushed;
    }

    // -- the decision tree, in the CDK overlay ---------------------------------

    function renderOverlay(): void {
        TestBed.inject(ApplicationRef).tick();
    }

    function openTree(): void {
        panel.openDecisionTree();
        renderOverlay();
    }

    function closeTree(): void {
        TestBed.inject(Dialog).closeAll();
        renderOverlay();
    }

    function treeBlock(title: string): HTMLElement {
        const block = [...document.querySelectorAll<HTMLElement>('app-cdt-decision-tree-block')].find(
            (candidate) => candidate.querySelector('.cdt-tree-block__title')?.textContent?.trim() === title
        );
        if (!block) throw new Error(`no block titled ${title}`);
        return block;
    }

    function openTreeBlock(title: string): void {
        treeBlock(title).querySelector<HTMLElement>('.cdt-tree-block__body')!.click();
        renderOverlay();
    }

    function treeDetail(): HTMLElement {
        const detail = document.querySelector<HTMLElement>('app-cdt-decision-tree-detail');
        if (!detail) throw new Error('no detail window');
        return detail;
    }

    it('moves the explanations to the new key on the canvas node, and asks for no persist', () => {
        create({ [OLD_KEY]: EXPLAINED });

        editRouteCodeInGrid(0, 'approved');

        expect(canvasExplanations()).toEqual({ [NEW_KEY]: EXPLAINED });
        expect(persistRequests).toEqual([]);
    });

    it('keeps the moved explanations in the autosave that runs before the canvas node reaches the panel', () => {
        create({ [OLD_KEY]: EXPLAINED });

        editRouteCodeInGrid(0, 'approved');
        const pushed = autosaveAsTheShellDoes();

        expect(pushed.explanations).toEqual({ [NEW_KEY]: EXPLAINED });
        expect(pushed.data.table.condition_groups[0].route_code).toBe('approved');
        expect(canvasExplanations()).toEqual({ [NEW_KEY]: EXPLAINED });
        // Saved with what it pushed, so the panel reads clean once the node arrives.
        expect(panel.isDirty()).toBe(false);
    });

    it('moves nothing in a read-only editor', () => {
        create({ [OLD_KEY]: EXPLAINED }, true);

        editRouteCodeInGrid(0, 'approved');

        expect(canvasExplanations()).toEqual({ [OLD_KEY]: EXPLAINED });
    });

    it('shows a generated explanation as outdated in the decision tree after the route code changes', () => {
        create({});
        explainApi.explain.mockReturnValue(
            of({
                explanations: [{ id: 'row-0:decision', text: 'Approves confident scores', generated_by: 'model' }],
                failures: [],
            })
        );

        openTree();
        openTreeBlock('Approve');
        treeDetail().querySelector<HTMLButtonElement>('.cdt-tree-detail__explain')!.click();
        renderOverlay();
        expect(Object.keys(canvasExplanations())).toEqual([OLD_KEY]);
        expect(treeBlock('Approve').querySelector('.cdt-tree-block__outdated')).toBeNull();
        closeTree();

        editRouteCodeInGrid(0, 'approved');
        autosaveAsTheShellDoes();
        // On the node, which is what a save sends — the cache alone would show it
        // in this browser and lose it everywhere else.
        expect(Object.keys(canvasExplanations())).toEqual([NEW_KEY]);

        openTree();
        expect(treeBlock('Approve').querySelector('.cdt-tree-block__outdated')).not.toBeNull();
        expect(treeBlock('Reject').querySelector('.cdt-tree-block__outdated')).toBeNull();
        openTreeBlock('Approve');
        expect(treeDetail().querySelector('.cdt-tree-detail__explanation')?.textContent?.trim()).toBe(
            'Approves confident scores'
        );
        expect(treeDetail().querySelector('.cdt-tree-detail__outdated')).not.toBeNull();
        // Only the generation asked for a persist; the move rides with the table edit.
        expect(persistRequests).toEqual([NODE_ID]);
    });
});

describe('ClassificationDecisionTableNodePanelComponent — execution timeouts of the pre- and post-computation', () => {
    let panel: ClassificationDecisionTableNodePanelComponent;

    /** The panel's two timeout fields. */
    interface TimeoutPanel {
        preExecutionTimeout: ExecutionTimeoutFormField;
        postExecutionTimeout: ExecutionTimeoutFormField;
    }

    let fixture: ComponentFixture<ClassificationDecisionTableNodePanelComponent>;

    function open(
        preSeconds: number | undefined,
        postSeconds: number | undefined,
        preCode = 'def main(): pass',
        isPreview = false
    ): void {
        configurePanelTestBed({ isPreview });
        const node = tableNode();
        const timedNode = {
            ...node,
            data: {
                ...node.data,
                table: {
                    ...node.data.table,
                    pre_computation: { code: preCode, execution_timeout: preSeconds },
                    post_computation: { code: 'def main(): pass', execution_timeout: postSeconds },
                },
            },
        } as ClassificationDecisionTableNodeModel;
        const flowService = TestBed.inject(FlowService);
        flowService.setFlow({ nodes: [timedNode], connections: [] });
        TestBed.inject(SavedFlowStateService).setSavedFlow(flowService.getFlowState());

        fixture = TestBed.createComponent(ClassificationDecisionTableNodePanelComponent);
        fixture.componentRef.setInput('node', flowService.nodes()[0]);
        fixture.detectChanges();
        panel = fixture.componentInstance;
    }

    function showsTimeoutOnTab(tab: 'precomputation' | 'postcomputation'): boolean {
        panel.activeTab.set(tab);
        fixture.detectChanges();
        return fixture.debugElement.query(By.directive(ExecutionTimeoutFieldComponent)) !== null;
    }

    function fields(): TimeoutPanel {
        return panel as unknown as TimeoutPanel;
    }

    it('shows each stored timeout, and the default for a code without one', () => {
        open(90, undefined);

        expect(fields().preExecutionTimeout.control.value).toBe(90);
        expect(fields().postExecutionTimeout.control.value).toBe(TEST_EXECUTION_TIMEOUT_LIMITS.defaultSeconds);
    });

    it('puts each edited timeout on its own code, and keeps none on a code whose timeout was not edited', () => {
        open(undefined, undefined);

        fields().preExecutionTimeout.edit(300);
        const table = panel.onSaveSilently()?.data.table;

        expect(table?.pre_computation?.execution_timeout).toBe(300);
        expect(table?.post_computation?.execution_timeout).toBeUndefined();

        fields().postExecutionTimeout.edit(45);
        expect(panel.onSaveSilently()?.data.table.post_computation?.execution_timeout).toBe(45);
    });

    it('exports the edited timeouts to CSV', () => {
        open(90, undefined);
        const downloadFile = vi
            .spyOn(TestBed.inject(CdtExportImportService), 'downloadFile')
            .mockImplementation(() => undefined);

        fields().postExecutionTimeout.edit(45);
        panel.exportAsCsv();

        const rows = (downloadFile.mock.calls[0][0] as string).split('\n');
        expect(rows).toContain('pre_python_code_execution_timeout,90');
        expect(rows).toContain('post_python_code_execution_timeout,45');
    });

    it.each([
        ['CSV', (target: ClassificationDecisionTableNodePanelComponent) => target.exportAsCsv()],
        ['JSON', (target: ClassificationDecisionTableNodePanelComponent) => target.exportAsJson()],
    ])('does not export to %s while the flow has unsaved changes, and says to save first', (_format, exportIt) => {
        open(90, undefined);
        const toastWarning = vi.spyOn(TestBed.inject(ToastService), 'warning').mockImplementation(() => undefined);
        const downloadFile = vi
            .spyOn(TestBed.inject(CdtExportImportService), 'downloadFile')
            .mockImplementation(() => undefined);
        const cdtExport = vi.spyOn(TestBed.inject(ImportExportService), 'cdtExport');
        const flowService = TestBed.inject(FlowService);
        flowService.updateNode({ ...flowService.nodes()[0], node_name: 'Renamed after the last save' });

        exportIt(panel);

        expect(toastWarning).toHaveBeenCalledTimes(1);
        expect(toastWarning.mock.calls[0][0]).toBe('Save the flow before exporting');
        expect(downloadFile).not.toHaveBeenCalled();
        expect(cdtExport).not.toHaveBeenCalled();
    });

    /** Types into the timeout input of `tab`, as the user does, and stays in it: no blur, no Enter. */
    function typeTimeout(tab: 'precomputation' | 'postcomputation', text: string): void {
        panel.activeTab.set(tab);
        fixture.detectChanges();
        const input = fixture.debugElement.query(By.css('app-execution-timeout-field input'))
            .nativeElement as HTMLInputElement;
        input.value = text;
        input.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    it('saves timeouts still being typed when the panel closes before the input blurs (Esc, switching nodes)', () => {
        open(undefined, undefined);

        typeTimeout('precomputation', '00:05:00');
        typeTimeout('postcomputation', '00:00:45');

        expect(panel.isDirty()).toBe(true);
        const table = panel.onSave()?.data.table;
        expect(table?.pre_computation?.execution_timeout).toBe(300);
        expect(table?.post_computation?.execution_timeout).toBe(45);
    });

    it('names each timeout by its block, so screen readers tell the two apart', () => {
        open(90, 90);

        const groupLabel = (tab: 'precomputation' | 'postcomputation'): string | null => {
            panel.activeTab.set(tab);
            fixture.detectChanges();
            return (fixture.nativeElement as HTMLElement)
                .querySelector('app-execution-timeout-field [role="group"]')!
                .getAttribute('aria-label');
        };

        expect(groupLabel('precomputation')).toBe('Pre-computation execution timeout');
        expect(groupLabel('postcomputation')).toBe('Post-computation execution timeout');
    });

    /** The pre-computation code the bulk save sends for `node`, a new node of the flow. */
    function sentPreComputation(node: NodeModel): Record<string, unknown> | null {
        const current: FlowModel = { nodes: [node], connections: [] };
        const idMap = buildUuidToBackendIdMap(current.nodes);
        const payload = buildBulkSavePayload(
            1,
            getNodeDiff({ nodes: [], connections: [] }, current),
            getConnectionDiff({ nodes: [], connections: [] }, current, idMap),
            current,
            idMap,
            1
        );
        const [item] = payload['classification_decision_table_node_list'] as Record<string, unknown>[];
        return item['pre_python_code'] as Record<string, unknown> | null;
    }

    it('shows and enables the timeout of every block, with or without code', () => {
        open(90, undefined, '  ');

        expect(showsTimeoutOnTab('precomputation')).toBe(true);
        expect(showsTimeoutOnTab('postcomputation')).toBe(true);
        expect(fields().preExecutionTimeout.control.enabled).toBe(true);
        expect(fields().postExecutionTimeout.control.enabled).toBe(true);
    });

    it('checks the timeout of a block without code like any other visible field', () => {
        open(undefined, undefined, '  ');

        fields().preExecutionTimeout.edit(TEST_EXECUTION_TIMEOUT_LIMITS.minSeconds - 1);

        expect(panel.form.invalid).toBe(true);
        expect(panel.onSaveSilently()).toBeNull();
    });

    it('still checks the timeout once the code of its block is cleared', () => {
        open(90, undefined);
        fields().preExecutionTimeout.edit(TEST_EXECUTION_TIMEOUT_LIMITS.minSeconds - 1);

        panel.onPreCodeChange('');

        expect(showsTimeoutOnTab('precomputation')).toBe(true);
        expect(panel.onSaveSilently()).toBeNull();
    });

    it('keeps the timeout typed into a block without code, and sends it only once the block has code', () => {
        open(undefined, undefined, '  ');
        fields().preExecutionTimeout.edit(300);

        const withoutCode = panel.onSaveSilently()!;
        expect(withoutCode.data.table.pre_computation?.execution_timeout).toBe(300);
        expect(sentPreComputation(withoutCode)).toBeNull();

        panel.insertPreStorageCode('from epicstaff_storage import storage');

        const withCode = panel.onSaveSilently()!;
        expect(withCode.data.table.pre_computation?.execution_timeout).toBe(300);
        expect(sentPreComputation(withCode)?.['execution_timeout']).toBe(300);
    });

    it('disables both timeouts on a read-only flow', () => {
        open(90, undefined, '  ', true);

        expect(fields().preExecutionTimeout.control.disabled).toBe(true);
        expect(fields().postExecutionTimeout.control.disabled).toBe(true);
    });
});

describe('ClassificationDecisionTableNodePanelComponent — the pre- and post-computation on the Changes tab of a version preview', () => {
    type ComputationTab = 'precomputation' | 'postcomputation';

    let fixture: ComponentFixture<ClassificationDecisionTableNodePanelComponent>;

    const changeOf = (field: FieldName, current: unknown, version: unknown): FieldChange => ({
        path: field,
        field,
        status: 'changed',
        current,
        version,
    });
    const CODE_CHANGES: Record<ComputationTab, FieldChange> = {
        precomputation: changeOf('pre_computation.code', 'pre = 1\n', 'pre = 2\n'),
        postcomputation: changeOf('post_computation.code', 'post = 1\n', 'post = 2\n'),
    };

    /** The panel on `tab`, widened unless `expanded` is false; with no diff off the Changes tab. */
    function open(
        tab: ComputationTab | 'table',
        diff: { status: NodeDiffStatus; fields: FieldChange[] } | null,
        expanded = true
    ): HTMLElement {
        configurePanelTestBed({ isPreview: true, providers: diff ? [provideChangesTabDiff(diff)] : [] });
        renderCodeDiffViewWithStubEditor();
        const flowService = TestBed.inject(FlowService);
        flowService.setFlow({ nodes: [tableNode()], connections: [] });
        fixture = TestBed.createComponent(ClassificationDecisionTableNodePanelComponent);
        fixture.componentRef.setInput('node', flowService.nodes()[0]);
        fixture.componentRef.setInput('isExpanded', expanded);
        fixture.detectChanges();
        // The panel opens on the Decision Table tab.
        if (tab !== 'table') {
            const label = tab === 'precomputation' ? 'Pre-computation' : 'Post-computation';
            Array.from(fixture.nativeElement.querySelectorAll('.tab-link') as NodeListOf<HTMLElement>)
                .find((link) => link.textContent!.trim().startsWith(label))!
                .click();
            fixture.detectChanges();
        }
        return fixture.nativeElement;
    }

    const codeEditors = (root: HTMLElement): number => root.querySelectorAll('app-code-editor').length;

    it.each(['precomputation', 'postcomputation'] as const)(
        'shows the changed code of the %s tab as a diff of the current canvas code and the version code, widened',
        (tab) => {
            const root = open(tab, { status: 'changed', fields: Object.values(CODE_CHANGES) });

            expect(shownCodeDiffs(fixture.debugElement)).toEqual([
                { current: CODE_CHANGES[tab].current, version: CODE_CHANGES[tab].version },
            ]);
            expect(codeEditors(root)).toBe(0);
            expect(codeMarkDescriptions(root)).toEqual([]);
        }
    );

    it.each(['precomputation', 'postcomputation'] as const)(
        'marks the code column of the %s tab in the minimized panel, with the expand hint',
        (tab) => {
            const root = open(tab, { status: 'changed', fields: Object.values(CODE_CHANGES) }, false);

            expect(codeMarkDescriptions(root)).toEqual(['Expand the panel to see the changes.']);
            expect(codeEditors(root)).toBe(1);
            expect(shownCodeDiffs(fixture.debugElement)).toEqual([]);
        }
    );

    const KEEPS_EDITOR = [
        {
            case: 'only the other code changed',
            diff: { status: 'changed' as const, fields: [CODE_CHANGES.postcomputation] },
        },
        { case: 'the node is added', diff: { status: 'added' as const, fields: [CODE_CHANGES.precomputation] } },
        { case: 'the node is removed', diff: { status: 'deleted' as const, fields: [CODE_CHANGES.precomputation] } },
        { case: 'off the Changes tab (Preview tab, live editor)', diff: null },
    ].flatMap((keeps) => [true, false].map((expanded) => ({ ...keeps, expanded })));

    it.each(KEEPS_EDITOR)(
        'keeps the normal pre-computation editor when $case (widened: $expanded)',
        ({ diff, expanded }) => {
            const root = open('precomputation', diff, expanded);

            expect(codeEditors(root)).toBe(1);
            expect(codeMarkDescriptions(root)).toEqual([]);
            expect(shownCodeDiffs(fixture.debugElement)).toEqual([]);
        }
    );

    /** The tab links with a "changed" dot, each by its accessible name. */
    const flaggedTabs = (root: HTMLElement): string[] =>
        Array.from(root.querySelectorAll<HTMLElement>('.tab-link'))
            .filter((link) => link.querySelector('.tab-link__changed-dot') !== null)
            .map((link) => link.textContent!.replace(/\s+/g, ' ').trim());

    it.each([
        {
            changed: changeOf('pre_computation.code', 'a', 'b'),
            flagged: ['Pre-computation (restore changes this tab)'],
        },
        {
            changed: changeOf('pre_computation.execution_timeout', 90, null),
            flagged: ['Pre-computation (restore changes this tab)'],
        },
        {
            changed: changeOf('post_use_storage', false, true),
            flagged: ['Post-computation (restore changes this tab)'],
        },
        {
            changed: {
                ...changeOf('prompts[].result_variable', 'a', 'b'),
                path: 'prompts[key=triage].result_variable',
            },
            flagged: ['Prompt library (restore changes this tab)'],
        },
        { changed: changeOf('node_name', 'Triage', 'Sort'), flagged: [] },
    ])('flags the tab of a changed $changed.field, on any tab', ({ changed, flagged }) => {
        expect(flaggedTabs(open('table', { status: 'changed', fields: [changed] }))).toEqual(flagged);
    });

    /** The current canvas value each shown field mark describes, as a screen reader hears it. */
    const markDescriptions = (root: HTMLElement): string[] =>
        Array.from(root.querySelectorAll('.diff-field-mark--shown')).map(
            (mark) => document.getElementById(mark.getAttribute('aria-describedby') ?? '')?.textContent ?? ''
        );

    it.each([
        {
            tab: 'precomputation' as const,
            change: changeOf('pre_computation.output_variable_path', 'pre.out', null),
            description: 'Current canvas: pre.out',
        },
        {
            tab: 'precomputation' as const,
            change: changeOf('pre_computation.secret_names', ['API_KEY'], []),
            description: 'Current canvas: API_KEY',
        },
        {
            tab: 'postcomputation' as const,
            change: changeOf('post_computation.execution_timeout', 30, null),
            description: 'Current canvas: 00:00:30',
        },
        {
            tab: 'postcomputation' as const,
            change: changeOf('post_use_storage', true, false),
            description: 'Current canvas: on',
        },
    ])('marks the changed $change.field on its tab, with the current canvas value', ({ tab, change, description }) => {
        const root = open(tab, { status: 'changed', fields: [change] }, false);

        expect(markDescriptions(root)).toEqual([description]);
    });

    it.each([
        { case: 'on an added node', diff: { status: 'added' as const, fields: [CODE_CHANGES.precomputation] } },
        { case: 'off the Changes tab', diff: null },
    ])('flags no tab $case', ({ diff }) => {
        expect(flaggedTabs(open('table', diff))).toEqual([]);
    });
});

describe('ClassificationDecisionTableNodePanelComponent — the prompts and the default LLM on the Changes tab of a version preview', () => {
    let fixture: ComponentFixture<ClassificationDecisionTableNodePanelComponent>;

    const TRIAGE_PROMPT = {
        prompt_text: 'Sort the ticket',
        llm_config: 3,
        output_schema: { type: 'object' },
        result_variable: 'category',
        variable_mappings: { ticket: 'variables.ticket' },
    };

    const promptChange = (field: string, current: unknown, version: unknown): FieldChange => ({
        path: `prompts[key=triage].${field}`,
        field: `prompts[].${field}` as FieldName,
        status: 'changed',
        current,
        version,
    });
    const defaultLlmChange: FieldChange = {
        path: 'default_llm_config',
        field: 'default_llm_config',
        status: 'changed',
        current: 5,
        version: 7,
    };

    /** The version table with the prompt "triage" and default LLM 7, on the Prompt library tab. */
    function open(diff: { status: NodeDiffStatus; fields: FieldChange[] } | null): HTMLElement {
        configurePanelTestBed({ isPreview: true, providers: diff ? [provideChangesTabDiff(diff)] : [] });
        renderCodeDiffViewWithStubEditor();
        // The JSON editor runs Monaco, which jsdom cannot.
        TestBed.overrideComponent(ClassificationDecisionTableNodePanelComponent, {
            remove: { imports: [JsonEditorComponent] },
            add: { schemas: [NO_ERRORS_SCHEMA] },
        });
        const node = tableNode();
        const flowService = TestBed.inject(FlowService);
        flowService.setFlow({
            nodes: [
                {
                    ...node,
                    data: {
                        ...node.data,
                        table: { ...node.data.table, prompts: { triage: TRIAGE_PROMPT }, default_llm_config: 7 },
                    },
                } as NodeModel,
            ],
            connections: [],
        });
        fixture = TestBed.createComponent(ClassificationDecisionTableNodePanelComponent);
        fixture.componentRef.setInput('node', flowService.nodes()[0]);
        fixture.detectChanges();
        Array.from(fixture.nativeElement.querySelectorAll('.tab-link') as NodeListOf<HTMLElement>)
            .find((link) => link.textContent!.trim().startsWith('Prompt library'))!
            .click();
        fixture.detectChanges();
        return fixture.nativeElement;
    }

    const descriptionOf = (element: Element | null): string =>
        document.getElementById(element?.getAttribute('aria-describedby') ?? '')?.textContent ?? '';
    const card = (root: HTMLElement, promptId: string): HTMLElement =>
        Array.from(root.querySelectorAll<HTMLElement>('.prompt-card')).find(
            (candidate) => candidate.querySelector('.prompt-id')?.textContent?.trim() === promptId
        )!;
    const openCard = (root: HTMLElement): void => {
        card(root, 'triage').querySelector<HTMLElement>('.prompt-card-header')!.click();
        fixture.detectChanges();
    };

    it('marks a changed prompt card with the fields a restore changes, those without a field of their own too', () => {
        const root = open({
            status: 'changed',
            fields: [
                promptChange('prompt_text', 'Sort it', 'Sort the ticket'),
                promptChange('variable_mappings', {}, TRIAGE_PROMPT.variable_mappings),
            ],
        });

        const header = card(root, 'triage').querySelector('.prompt-card-header');
        expect(header?.classList).toContain('diff-field-mark--shown');
        expect(descriptionOf(header)).toBe(
            'Restore changes this field. Changed fields: Prompt text, Variable mappings.'
        );
    });

    it.each(['Enter', ' '])(
        'opens and closes a marked card from the keyboard (%j), as its header is focusable',
        (key) => {
            const root = open({ status: 'changed', fields: [promptChange('result_variable', 'kind', 'category')] });
            const header = card(root, 'triage').querySelector<HTMLElement>('.prompt-card-header')!;
            const press = (): KeyboardEvent => {
                const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
                header.dispatchEvent(event);
                fixture.detectChanges();
                return event;
            };

            expect(header.getAttribute('tabindex')).toBe('0');
            const opening = press();
            expect(card(root, 'triage').querySelector('.prompt-card-body')).not.toBeNull();
            expect(opening.defaultPrevented).toBe(key === ' ');
            press();
            expect(card(root, 'triage').querySelector('.prompt-card-body')).toBeNull();
        }
    );

    it('marks a prompt a restore adds, and shows a canvas prompt it removes as a read-only struck card', () => {
        const root = open({
            status: 'changed',
            fields: [
                {
                    path: 'prompts[key=triage]',
                    field: 'prompts[]',
                    status: 'added',
                    current: null,
                    version: TRIAGE_PROMPT,
                },
                {
                    path: 'prompts[key=legacy]',
                    field: 'prompts[]',
                    status: 'deleted',
                    current: { ...TRIAGE_PROMPT, result_variable: 'old_category' },
                    version: null,
                },
            ],
        });

        const added = card(root, 'triage');
        expect(added.classList).toContain('prompt-card--added');
        expect(added.getAttribute('title')).toBe('Restore adds this prompt');
        const removed = card(root, 'legacy');
        expect(removed.classList).toContain('prompt-card--removed');
        expect(removed.textContent).toContain('old_category');
        expect(removed.querySelector('button')).toBeNull();
    });

    it('marks each changed field of an opened card, an LLM by its name or number', () => {
        const root = open({
            status: 'changed',
            fields: [promptChange('llm_config', 5, 3), promptChange('result_variable', 'kind', 'category')],
        });
        openCard(root);

        const fieldMarks = Array.from(
            card(root, 'triage').querySelectorAll('.prompt-card-body .diff-field-mark--shown')
        );
        expect(fieldMarks.map(descriptionOf)).toEqual(['Current canvas: LLM #5', 'Current canvas: kind']);
    });

    it('shows a changed output schema as a JSON diff in the side editor', () => {
        const root = open({
            status: 'changed',
            fields: [promptChange('output_schema', { type: 'string' }, TRIAGE_PROMPT.output_schema)],
        });
        openCard(root);
        fixture.componentInstance.openSideEditor('triage', 'schema');
        fixture.detectChanges();

        expect(shownCodeDiffs(fixture.debugElement)).toEqual([
            { current: '{\n  "type": "string"\n}', version: '{\n  "type": "object"\n}' },
        ]);
    });

    const defaultLlmLine = (root: HTMLElement): string | null =>
        root.querySelector('.default-llm-line')?.textContent?.trim() ?? null;

    it('shows the default LLM as a marked line when a restore changes it', () => {
        const root = open({ status: 'changed', fields: [defaultLlmChange] });

        expect(defaultLlmLine(root)).toBe('Default LLM: LLM #7');
        expect(descriptionOf(root.querySelector('.default-llm-mark'))).toBe('Current canvas: LLM #5');
    });

    it.each([
        {
            case: 'a restore changes another field',
            diff: { status: 'changed' as const, fields: [promptChange('result_variable', 'a', 'b')] },
        },
        { case: 'the node is added', diff: { status: 'added' as const, fields: [defaultLlmChange] } },
        { case: 'off the Changes tab', diff: null },
    ])('shows no default LLM line when $case', ({ diff }) => {
        expect(defaultLlmLine(open(diff))).toBeNull();
    });
});
