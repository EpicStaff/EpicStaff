import { Dialog } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationRef, Component, input, NO_ERRORS_SCHEMA, output, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { AbstractControl } from '@angular/forms';
import { By } from '@angular/platform-browser';
import { FFlowModule, FZoomDirective } from '@foblex/flow';
import { InputNumberComponent } from '@shared/components';
import { NodeType } from '@shared/models';
import { FullLLMConfigService } from '@shared/services';
import { of } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { generatePortsForClassificationDecisionTableNode, generatePortsForNode } from '../../../core/helpers/helpers';
import { CdtExplanation, CdtExplanations } from '../../../core/models/classification-decision-table.model';
import { ConditionGroup } from '../../../core/models/decision-table.model';
import { ClassificationDecisionTableNodeModel, NodeModel } from '../../../core/models/node.model';
import { FLOW_EDITOR_PREVIEW } from '../../../core/providers/flow-editor-preview.token';
import { CdtExplainApiService } from '../../../services/cdt-explain-api.service';
import { FlowService } from '../../../services/flow.service';
import { SidePanelService } from '../../../services/side-panel.service';
import { UndoRedoService } from '../../../services/undo-redo.service';
import { createFlowConnection } from '../../../utils/connection.factory';
import {
    provideLoadedSandboxLimits,
    TEST_MAX_EXECUTION_TIMEOUT_MINUTES,
} from '../../../utils/testing/sandbox-limits.testing';
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
        execution_timeout: 3,
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

describe('ClassificationDecisionTableNodePanelComponent — enabling Continue on a wired route code', () => {
    let fixture: ComponentFixture<ClassificationDecisionTableNodePanelComponent>;
    let panel: ClassificationDecisionTableNodePanelComponent;
    let flowService: FlowService;
    let undoRedo: UndoRedoService;
    let toastError: ReturnType<typeof vi.spyOn>;

    function create(isPreview = false): void {
        TestBed.configureTestingModule({
            errorOnUnknownProperties: true,
            errorOnUnknownElements: true,
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                provideLoadedSandboxLimits(),
                { provide: FLOW_EDITOR_PREVIEW, useValue: isPreview },
                { provide: PermissionsService, useValue: { can: () => true, canEditSecrets: () => true } },
                {
                    provide: FullLLMConfigService,
                    useValue: { fullLLMConfigs: signal([]), getFullLLMConfigs: () => of([]) },
                },
            ],
        });
        TestBed.overrideComponent(ClassificationDecisionTableNodePanelComponent, {
            remove: { imports: [ClassificationDecisionTableGridComponent] },
            add: { imports: [GridStubComponent] },
        });

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
        TestBed.configureTestingModule({
            errorOnUnknownProperties: true,
            errorOnUnknownElements: true,
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                provideLoadedSandboxLimits(),
                { provide: FLOW_EDITOR_PREVIEW, useValue: isPreview },
                { provide: PermissionsService, useValue: { can: () => true, canEditSecrets: () => true } },
                {
                    provide: FullLLMConfigService,
                    useValue: { fullLLMConfigs: signal([]), getFullLLMConfigs: () => of([]) },
                },
                { provide: CdtExplainApiService, useValue: explainApi },
            ],
        });
        TestBed.overrideComponent(ClassificationDecisionTableNodePanelComponent, {
            remove: { imports: [ClassificationDecisionTableGridComponent] },
            add: { imports: [GridStubComponent] },
        });
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

describe('ClassificationDecisionTableNodePanelComponent — execution timeout', () => {
    let fixture: ComponentFixture<ClassificationDecisionTableNodePanelComponent>;
    let panel: ClassificationDecisionTableNodePanelComponent;

    function open(executionTimeout: number | null): void {
        TestBed.configureTestingModule({
            errorOnUnknownProperties: true,
            errorOnUnknownElements: true,
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                provideLoadedSandboxLimits(),
                { provide: FLOW_EDITOR_PREVIEW, useValue: false },
                { provide: PermissionsService, useValue: { can: () => true, canEditSecrets: () => true } },
                {
                    provide: FullLLMConfigService,
                    useValue: { fullLLMConfigs: signal([]), getFullLLMConfigs: () => of([]) },
                },
            ],
        });
        TestBed.overrideComponent(ClassificationDecisionTableNodePanelComponent, {
            remove: { imports: [ClassificationDecisionTableGridComponent] },
            add: { imports: [GridStubComponent] },
        });
        const flowService = TestBed.inject(FlowService);
        flowService.setFlow({ nodes: [{ ...tableNode(), execution_timeout: executionTimeout }], connections: [] });

        fixture = TestBed.createComponent(ClassificationDecisionTableNodePanelComponent);
        fixture.componentRef.setInput('node', flowService.nodes()[0]);
        fixture.detectChanges();
        panel = fixture.componentInstance;
    }

    function timeoutInput(): InputNumberComponent {
        return fixture.debugElement.query(By.css('app-execution-timeout-field app-input-number'))
            .componentInstance as InputNumberComponent;
    }

    function timeoutControl(): AbstractControl {
        return panel.form.get('execution_timeout')!;
    }

    it('shows the stored timeout and says it applies to each code step separately', () => {
        open(3);

        expect(timeoutInput().value()).toBe(3);
        expect(timeoutInput().max()).toBe(TEST_MAX_EXECUTION_TIMEOUT_MINUTES);
        expect(timeoutInput().tooltipText()).toContain('each code step separately');
    });

    it('shows a table saved before nodes had a timeout at the ceiling', () => {
        open(null);

        expect(timeoutInput().value()).toBe(TEST_MAX_EXECUTION_TIMEOUT_MINUTES);
    });

    it('puts an edited timeout on the node it saves', () => {
        open(3);

        timeoutControl().setValue(8);

        expect(panel.onSaveSilently()?.execution_timeout).toBe(8);
    });

    it('keeps a timeout saved under a higher ceiling, with a warning, and closes with it and the other edits', () => {
        const aboveCeiling = TEST_MAX_EXECUTION_TIMEOUT_MINUTES + 30;
        open(aboveCeiling);

        expect(timeoutControl().valid).toBe(true);
        expect(timeoutInput().isAboveWarning()).toBe(true);
        panel.form.patchValue({ node_name: 'Renamed' });
        const saved = panel.onSave();

        expect(saved?.execution_timeout).toBe(aboveCeiling);
        expect(saved?.node_name).toBe('Renamed');
    });

    it('exports the edited timeout to CSV', () => {
        open(3);
        const downloadFile = vi
            .spyOn(TestBed.inject(CdtExportImportService), 'downloadFile')
            .mockImplementation(() => undefined);

        timeoutControl().setValue(8);
        panel.exportAsCsv();

        expect(downloadFile).toHaveBeenCalledTimes(1);
        expect((downloadFile.mock.calls[0][0] as string).split('\n')).toContain('execution_timeout,8');
    });
});
