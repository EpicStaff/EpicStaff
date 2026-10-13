import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, input, output, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { NodeType } from '@shared/models';
import { FullLLMConfigService } from '@shared/services';
import { of } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { generatePortsForClassificationDecisionTableNode, generatePortsForNode } from '../../../core/helpers/helpers';
import { ConditionGroup } from '../../../core/models/decision-table.model';
import { ClassificationDecisionTableNodeModel, NodeModel } from '../../../core/models/node.model';
import { FLOW_EDITOR_PREVIEW } from '../../../core/providers/flow-editor-preview.token';
import { FlowService } from '../../../services/flow.service';
import { UndoRedoService } from '../../../services/undo-redo.service';
import { createFlowConnection } from '../../../utils/connection.factory';
import { CDT_ROUTE_CONTINUE_COPY } from './cdt.constants';
import {
    CdtEnableContinueRequest,
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
