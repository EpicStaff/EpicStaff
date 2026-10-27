import { Type } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { ClassificationDecisionTableNodeModel, DecisionTableNodeModel } from '../../core/models/node.model';
import { FlowService } from '../../services/flow.service';
import { FlowDiffStateService } from '../../services/flow-diff-state.service';
import { FieldChange, NodeDiffStatus } from '../../utils/diff';
import { ClassificationDecisionTableNodePanelComponent } from './classification-decision-table-node-panel/classification-decision-table-node-panel.component';
import { DecisionTableNodePanelComponent } from './decision-table-node-panel/decision-table-node-panel.component';
import {
    ChangesTabOptions,
    fieldChange,
    hoverTooltip,
    liveNodeOfType,
    markedFields,
    openPanelOnChangesTab,
} from './node-panel-diff.testing';

// The Decision Table and Classification Decision Table panels on the Changes tab of a version preview: the name and the
// default and error routes get field marks, a route's tooltip names the node it leads to on the canvas, and the grid
// gets the row changes of the groups. The rows themselves are checked in the grid specs (real ag-grid DOM).

interface Panel {
    name: string;
    type: NodeType.TABLE | NodeType.CLASSIFICATION_TABLE;
    component: Type<DecisionTableNodePanelComponent | ClassificationDecisionTableNodePanelComponent>;
    /** The fixture's only group. */
    groupName: string;
}

const PANELS: Panel[] = [
    { name: 'Decision Table', type: NodeType.TABLE, component: DecisionTableNodePanelComponent, groupName: 'yes' },
    {
        name: 'Classification Decision Table',
        type: NodeType.CLASSIFICATION_TABLE,
        component: ClassificationDecisionTableNodePanelComponent,
        groupName: 'route',
    },
];

/** The match key of the fixture's Task node, as a route in the diff names it. */
const TASK_KEY = 'uuid:task';

/** A group only the canvas has, as the diff compares it. */
const REMOVED_GROUP: FieldChange = {
    path: 'condition_groups[name=gone]',
    field: 'condition_groups[]',
    status: 'deleted',
    current: { position: 2, expression: 'x < 0', manipulation: null, next_node: TASK_KEY },
    version: null,
};

let fixture: ComponentFixture<DecisionTableNodePanelComponent | ClassificationDecisionTableNodePanelComponent>;

afterEach(() => fixture?.destroy());

// jsdom has no ResizeObserver; the grids only need it to exist.
beforeEach(() =>
    vi.stubGlobal(
        'ResizeObserver',
        class {
            observe(): void {}
            unobserve(): void {}
            disconnect(): void {}
        }
    )
);
afterEach(() => vi.unstubAllGlobals());

function open(panel: Panel, fields: FieldChange[], options: ChangesTabOptions = {}): HTMLElement {
    fixture = openPanelOnChangesTab(panel.component, liveNodeOfType(panel.type), fields, options);
    // The diff canvas: the Task node's match key leads to the fixture's Task node on it.
    const task = TestBed.inject(FlowService)
        .nodes()
        .find((node) => node.type === NodeType.TASK)!;
    TestBed.inject(FlowDiffStateService).setState({
        nodes: new Map(),
        connections: new Map(),
        versionOnlyPortIds: new Set(),
        nodeIdByKey: new Map([[TASK_KEY, task.id]]),
    });
    fixture.detectChanges();
    return fixture.nativeElement;
}

/** Whether the grid got row changes for its rows. */
function gridHasRowMarks(root: HTMLElement): boolean {
    return root.querySelector('.decision-grid--diff-rows') !== null;
}

/** The group names a save of the panel writes. */
function savedGroupNames(): string[] {
    const saved = fixture.componentInstance.createUpdatedNode() as
        | DecisionTableNodeModel
        | ClassificationDecisionTableNodeModel;
    return saved.data.table.condition_groups.map((group) => group.group_name);
}

describe.each(PANELS)('$name panel on the Changes tab', (panel) => {
    const routeSelect = (route: 'default_next_node' | 'next_error_node') => `app-select[formcontrolname="${route}"]`;

    it('marks the name and each route a restore changes, and nothing else', () => {
        const root = open(panel, [
            fieldChange('node_name', 'Old', 'New'),
            fieldChange('default_next_node', TASK_KEY, null),
        ]);

        expect(markedFields(root)).toEqual(['node_name', 'default_next_node']);
    });

    it('names the node a route leads to on the canvas in its tooltip', () => {
        open(panel, [fieldChange('default_next_node', TASK_KEY, 'uuid:end')]);

        expect(hoverTooltip(fixture, routeSelect('default_next_node'))).toBe('[Task #2]');
    });

    it.each([
        { current: 'uuid:gone', tooltip: '[a node that no longer exists]' },
        { current: null, tooltip: '[empty]' },
    ])('shows a route to $current as "$tooltip"', ({ current, tooltip }) => {
        open(panel, [fieldChange('next_error_node', current, TASK_KEY)]);

        expect(hoverTooltip(fixture, routeSelect('next_error_node'))).toBe(tooltip);
    });

    it('gives the grid the row changes of the groups', () => {
        const root = open(panel, [
            {
                path: `condition_groups[name=${panel.groupName}].expression`,
                field: 'condition_groups[].expression',
                status: 'changed',
                current: 'x > 1',
                version: null,
            },
        ]);

        expect(gridHasRowMarks(root)).toBe(true);
    });

    it('shows a group a restore removes in the grid, but never saves it', () => {
        const root = open(panel, [REMOVED_GROUP]);

        expect(gridHasRowMarks(root)).toBe(true);
        expect(savedGroupNames()).toEqual([panel.groupName]);
    });

    it.each<{ where: string; options: ChangesTabOptions }>([
        { where: 'on the Preview tab and in the live editor', options: { onChangesTab: false } },
        ...(['added', 'deleted'] as NodeDiffStatus[]).map((status) => ({
            where: `on a node a restore ${status === 'added' ? 'adds' : 'removes'}`,
            options: { status },
        })),
    ])('marks nothing $where', ({ options }) => {
        const root = open(panel, [fieldChange('node_name', 'Old', 'New'), REMOVED_GROUP], options);

        expect(markedFields(root)).toEqual([]);
        expect(gridHasRowMarks(root)).toBe(false);
    });
});
