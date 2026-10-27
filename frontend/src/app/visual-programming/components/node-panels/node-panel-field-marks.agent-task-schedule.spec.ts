import { Provider, signal, Type } from '@angular/core';
import { ComponentFixture } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { NodeModel } from '../../core/models/node.model';
import { NODE_PANEL_DIFF, NodePanelDiff } from '../../core/providers/node-panel-diff.token';
import { FieldChange } from '../../utils/diff';
import { shownCodeDiffLanguages, shownCodeDiffs } from '../code-diff-view/code-diff-view.testing';
import { AgentNodePanelComponent } from './agent-node-panel/agent-node-panel.component';
import {
    AGENT_TASKS,
    agentNodeWithTasks,
    ChangesTabOptions,
    fieldChange,
    hoverTooltip,
    liveNodeOfType,
    markedFields,
    openPanelOnChangesTab,
    respond,
    scheduleNodeWith,
    SHOWN_DIFF_MARKS,
} from './node-panel-diff.testing';
import { ScheduleTriggerNodePanelComponent } from './schedule-trigger-node-panel/schedule-trigger-node-panel.component';
import { TaskNodePanelComponent } from './task-node-panel/task-node-panel.component';

// The Agent, Task and Schedule panels on the Changes tab of a version preview: each field a restore changes is
// marked on its value, and nothing else is. The panels show the version; the changes say what the canvas holds now.

interface Panel {
    name: string;
    component: Type<unknown>;
    /** The version node the panel shows. */
    node: () => NodeModel;
    /** What the panel needs from the backend to show the version's values (the options it loads). */
    load?: () => void;
}

const page = <T>(results: T[]) => ({ count: results.length, next: null, previous: null, results });

/** The agents and surfaces the Agent and Task panels load, to name a linked agent or surface. */
function loadAgentsAndSurfaces(): void {
    respond(
        'agent-definitions/',
        page([
            { id: 41, name: 'Researcher' },
            { id: 7, name: 'Old agent' },
        ])
    );
    respond(
        'surfaces/',
        page([
            { id: 51, name: 'Sales', owner_agent: null },
            { id: 52, name: 'Archive', owner_agent: null },
        ])
    );
}

const AGENT: Panel = {
    name: 'Agent',
    component: AgentNodePanelComponent,
    node: () => agentNodeWithTasks(),
    load: loadAgentsAndSurfaces,
};
const TASK: Panel = {
    name: 'Task',
    component: TaskNodePanelComponent,
    node: () => liveNodeOfType(NodeType.TASK),
    load: loadAgentsAndSurfaces,
};
// Repeats weekly on Monday and Wednesday until a date, so the panel shows the repeat settings, weekdays and end date.
const SCHEDULE: Panel = {
    name: 'Schedule',
    component: ScheduleTriggerNodePanelComponent,
    node: () => scheduleNodeWith({ intervalUnit: 'weeks', weekdays: ['mon', 'wed'] }),
};

let fixture: ComponentFixture<unknown>;

afterEach(() => fixture?.destroy());

function open(
    panel: Panel,
    fields: FieldChange[],
    options: ChangesTabOptions = {},
    node = panel.node(),
    providers: Provider[] = []
): HTMLElement {
    fixture = openPanelOnChangesTab(panel.component, node, fields, options, providers);
    panel.load?.();
    fixture.detectChanges();
    return fixture.nativeElement;
}

/** The node without its local surface, as a version a restore that removes the local surface brings back. */
function withoutLocalSurface(node: NodeModel): NodeModel {
    return { ...node, data: { ...(node.data as object), inline_surface: null } } as NodeModel;
}

/** The fixed text a mark shows and reads instead of a value, through its description. */
function descriptionOf(mark: Element): string | null | undefined {
    return document.getElementById(mark.getAttribute('aria-describedby') ?? '')?.textContent;
}

/** A field change, the element its mark wraps (form control or element), and the tooltip it shows. */
interface FieldCase {
    panel: Panel;
    change: FieldChange;
    marked: string;
    tooltip: string;
    /** A version node that shows the field, when the panel's own does not. */
    node?: () => NodeModel;
}

const NAME_CHANGE = fieldChange('node_name', 'Old name', 'New name');

const FIELD_CASES: FieldCase[] = [
    ...[AGENT, TASK].flatMap((panel): FieldCase[] => [
        { panel, change: NAME_CHANGE, marked: 'node_name', tooltip: '[Old] name' },
        {
            panel,
            change: fieldChange('output_variable_path', 'variables.old', null),
            marked: 'output_variable_path',
            tooltip: '[variables.old]',
        },
        {
            panel,
            change: fieldChange('agent_definition', 7, 41),
            marked: 'app-select-dropdown',
            tooltip: '[Old agent]',
        },
        // An agent the list does not hold (deleted) shows by id, as the missing-reference notes do.
        {
            panel,
            change: fieldChange('agent_definition', 8, 41),
            marked: 'app-select-dropdown',
            tooltip: '[agent #8]',
        },
        {
            panel,
            change: fieldChange('surface_list', [52, 53], [51]),
            marked: 'app-multi-select',
            tooltip: '[Archive], [surface #53], Local surface',
        },
        // The local surface shows in the same field as the surfaces, as one item: its instructions and tools are not
        // listed, so a change inside it marks the field with nothing struck.
        {
            panel,
            change: fieldChange('inline_surface.instructions', 'Be long', 'Be brief'),
            marked: 'app-multi-select',
            tooltip: 'Sales, Local surface',
        },
        {
            panel,
            change: fieldChange('inline_surface.python_tools', [{ python_tool: 22, mode: 'deny' }], []),
            marked: 'app-multi-select',
            tooltip: 'Sales, Local surface',
        },
        // A local surface a restore removes is struck.
        {
            panel,
            change: {
                path: 'inline_surface',
                field: 'inline_surface',
                status: 'deleted',
                current: { instructions: 'Be brief', python_tools: [], mcp_tools: [] },
                version: null,
            },
            marked: 'app-multi-select',
            tooltip: 'Sales, [Local surface]',
            node: () => withoutLocalSurface(panel.node()),
        },
    ]),
    {
        panel: TASK,
        change: fieldChange('instructions', 'Do it now', 'Do it'),
        marked: 'instructions',
        tooltip: 'Do it[ now]',
    },
    { panel: TASK, change: fieldChange('remember_output', true, false), marked: 'div.field', tooltip: '[on]' },
    { panel: SCHEDULE, change: NAME_CHANGE, marked: 'node_name', tooltip: '[Old] name' },
    // A date and a time picker hold one value: one mark around both, as the pickers show it.
    {
        panel: SCHEDULE,
        change: fieldChange('start_date_time', '2026-06-30T08:15:00', '2026-07-01T12:00:00'),
        marked: 'div.date-time-row',
        tooltip: '[30.06.2026 at 08:15]',
    },
    {
        panel: SCHEDULE,
        change: fieldChange('end_date_time', null, '2026-12-01T12:00:00'),
        marked: 'div.date-time-row',
        tooltip: '[empty]',
    },
    {
        panel: SCHEDULE,
        change: fieldChange('timezone', 'Europe/Berlin', 'Europe/Kyiv'),
        marked: 'timezone',
        tooltip: 'Europe/[Berlin]',
    },
    {
        panel: SCHEDULE,
        change: fieldChange('run_mode', 'once', 'repeat'),
        marked: 'div.next-run-row',
        tooltip: '[Once]',
    },
    { panel: SCHEDULE, change: fieldChange('interval_every', 2, 1), marked: 'repeat_every', tooltip: '[2]' },
    {
        panel: SCHEDULE,
        change: fieldChange('interval_unit', 'days', 'weeks'),
        marked: 'repeat_unit',
        tooltip: '[Days]',
    },
    // The days by name, the ones a restore removes struck.
    {
        panel: SCHEDULE,
        change: fieldChange('weekdays', ['mon', 'fri'], ['mon', 'wed']),
        marked: 'div.weekday-row',
        tooltip: 'Monday, [Friday]',
    },
    {
        panel: SCHEDULE,
        change: fieldChange('end_type', 'after_n_runs', 'on_date'),
        marked: 'div.next-run-row',
        tooltip: '[After N runs]',
    },
    {
        panel: SCHEDULE,
        change: fieldChange('max_runs', 3, 5),
        marked: 'max_runs',
        tooltip: '[3]',
        node: () => scheduleNodeWith({ endType: 'after_n_runs', endDateTime: null, maxRuns: 5 }),
    },
    { panel: SCHEDULE, change: fieldChange('is_active', false, true), marked: 'div.toggle-stack', tooltip: '[off]' },
];

describe('Agent, Task and Schedule panels on the Changes tab of a version preview', () => {
    it.each(FIELD_CASES)(
        '$panel.name: marks $change.field, and only it, when a restore changes it',
        ({ panel, change, marked, node }) => {
            expect(markedFields(open(panel, [change], {}, node?.()))).toEqual([marked]);
        }
    );

    it.each(FIELD_CASES)(
        '$panel.name: shows the current $change.field in the tooltip as the field shows it ($tooltip)',
        ({ panel, change, marked, tooltip, node }) => {
            open(panel, [change], {}, node?.());

            expect(hoverTooltip(fixture, `[formcontrolname="${marked}"], ${marked.replace('div.', '.')}`)).toBe(
                tooltip
            );
        }
    );

    const PANELS = [AGENT, TASK, SCHEDULE];

    it.each(
        PANELS.flatMap((panel) => [
            { panel, case: 'off the Changes tab (Preview tab, live editor)', options: { onChangesTab: false } },
            { panel, case: 'on a node a restore adds', options: { status: 'added' as const } },
            { panel, case: 'on a node a restore removes', options: { status: 'deleted' as const } },
        ])
    )('$panel.name: shows no mark $case', ({ panel, options }) => {
        const root = open(panel, [...FIELD_CASES.map(({ change }) => change), ...TASK_ROW_CHANGES, SCHEMA_CHANGE], {
            ...options,
            expanded: true,
        });

        expect(root.querySelectorAll(SHOWN_DIFF_MARKS)).toHaveLength(0);
        expect(root.querySelector('.diff-value-marked, .diff-field-mark--group, .att--diff')).toBeNull();
    });

    it.each(PANELS)('$name: shows no mark without a field change', (panel) => {
        const root = open(panel, []);

        expect(root.querySelectorAll(SHOWN_DIFF_MARKS)).toHaveLength(0);
    });
});

const SCHEMA_CHANGE = fieldChange('output_schema', { type: 'string' }, {});
const REVIEW_TASK = { name: 'Review', instructions: 'Check it', output_schema: {}, context_tasks: [1, 2] };
const TASK_ROW_CHANGES: FieldChange[] = [
    { path: 'tasks[1].name', field: 'tasks[].name', status: 'changed', current: 'Old research', version: 'Research' },
    {
        path: 'tasks[1].instructions',
        field: 'tasks[].instructions',
        status: 'changed',
        current: 'Find one source',
        version: 'Find three sources',
    },
    { path: 'tasks[2]', field: 'tasks[]', status: 'added', current: null, version: REVIEW_TASK },
    { path: 'tasks[3]', field: 'tasks[]', status: 'deleted', current: REVIEW_TASK, version: null },
];

describe('Agent tasks on the Changes tab', () => {
    /** Each task row: how it is marked, what a screen reader reads first, and its cells' text. */
    function taskRows(root: HTMLElement): { status: string; text: string }[] {
        return Array.from(root.querySelectorAll<HTMLElement>('.att-body .att-row'), (row) => ({
            status: row.classList.contains('diff-field-mark--shown')
                ? 'changed'
                : row.classList.contains('att-row--added')
                  ? 'added'
                  : row.classList.contains('att-row--removed')
                    ? 'removed'
                    : 'kept',
            text: [
                row.querySelector(':scope > .visually-hidden')?.textContent?.trim() ?? '',
                ...Array.from(row.querySelectorAll<HTMLElement>('input.att-input, .att-removed-text'), (cell) =>
                    cell instanceof HTMLInputElement ? cell.value : (cell.textContent?.trim() ?? '')
                ),
            ]
                .filter((part) => part)
                .join(' | '),
        }));
    }

    it.each([false, true])('marks a row per task, paired by position (widened: %s)', (expanded) => {
        const root = open(AGENT, TASK_ROW_CHANGES, { expanded });

        expect(taskRows(root)).toEqual([
            { status: 'changed', text: 'Research' },
            { status: 'added', text: 'Restore adds this task: | Write' },
            { status: 'removed', text: 'Restore removes this task: | Review | Check it' },
        ]);
        expect(markedFields(root)).toEqual([]);
    });

    it('names the changed columns in the row tooltip and description, not their values', () => {
        const root = open(AGENT, TASK_ROW_CHANGES);
        const row = root.querySelector('.att-row.diff-field-mark--shown')!;

        row.dispatchEvent(new Event('mouseenter'));
        fixture.detectChanges();

        expect(document.querySelector('.diff-field-mark__tooltip-hint')?.textContent).toBe(
            'Changed columns: Name, Instructions.'
        );
        expect(descriptionOf(row)).toBe('Restore changes this field. Changed columns: Name, Instructions.');
    });

    it('shows a removed task with the positions of its context tasks', () => {
        const root = open(AGENT, TASK_ROW_CHANGES);

        const removed = root.querySelector('.att-row--removed')!;
        expect(removed.querySelector('.att-row-number')?.textContent?.trim()).toBe('3');
        expect(Array.from(removed.querySelectorAll('.att-context-chip__order'), (chip) => chip.textContent)).toEqual([
            '1',
            '2',
        ]);
    });

    it('marks no row when only another field changes', () => {
        const root = open(AGENT, [NAME_CHANGE]);

        expect(taskRows(root).map(({ status }) => status)).toEqual(AGENT_TASKS.map(() => 'kept'));
        expect(root.querySelector('.att--diff')).toBeNull();
    });
});

describe('Agent task output schema in the widened panel on the Changes tab', () => {
    /** A restore changes the Output Schema of the task at `position` from `current` (the canvas) to the version's. */
    const taskSchemaChange = (position: number, current: unknown, version: unknown): FieldChange => ({
        path: `tasks[${position}].output_schema`,
        field: 'tasks[].output_schema',
        status: 'changed',
        current,
        version,
    });
    // The version's second task has `{ type: 'object' }` as its schema; the canvas has another one.
    const WRITE_SCHEMA_CHANGE = taskSchemaChange(2, { type: 'string' }, { type: 'object' });
    const WRITE_SCHEMA_DIFF = { current: '{\n  "type": "string"\n}', version: '{\n  "type": "object"\n}' };

    /** Opens a cell of a task row in the right pane, as its expand button does. */
    function showInRightPane(root: HTMLElement, taskIndex: number, field: 'instructions' | 'schema'): void {
        const row = root.querySelectorAll('.att-body .att-row')[taskIndex];
        row.querySelector<HTMLElement>(`.att-cell--${field} .att-expand-icon`)!.click();
        fixture.detectChanges();
    }

    const schemaEditorShown = (root: HTMLElement): boolean =>
        root.querySelector('.main-editor-pane app-json-editor') !== null;

    it('shows a JSON diff of the canvas and the version schema of the selected task when its schema changed', () => {
        const root = open(AGENT, [WRITE_SCHEMA_CHANGE], { expanded: true });

        showInRightPane(root, 1, 'schema');

        expect(shownCodeDiffs(fixture.debugElement)).toEqual([WRITE_SCHEMA_DIFF]);
        expect(shownCodeDiffLanguages(fixture.debugElement)).toEqual(['json']);
        expect(schemaEditorShown(root)).toBe(false);
    });

    it('switches the diff with the selected task, and shows the editor for a task whose schema is unchanged', () => {
        const root = open(AGENT, [WRITE_SCHEMA_CHANGE], { expanded: true });

        showInRightPane(root, 0, 'schema');
        expect(shownCodeDiffs(fixture.debugElement)).toEqual([]);
        expect(schemaEditorShown(root)).toBe(true);

        showInRightPane(root, 1, 'schema');
        expect(shownCodeDiffs(fixture.debugElement)).toEqual([WRITE_SCHEMA_DIFF]);

        showInRightPane(root, 0, 'schema');
        expect(shownCodeDiffs(fixture.debugElement)).toEqual([]);
        expect(schemaEditorShown(root)).toBe(true);
    });

    it('shows the diff of each selected task when both schemas changed', () => {
        const root = open(AGENT, [taskSchemaChange(1, { type: 'number' }, {}), WRITE_SCHEMA_CHANGE], {
            expanded: true,
        });

        showInRightPane(root, 0, 'schema');
        expect(shownCodeDiffs(fixture.debugElement)).toEqual([{ current: '{\n  "type": "number"\n}', version: '{}' }]);

        showInRightPane(root, 1, 'schema');
        expect(shownCodeDiffs(fixture.debugElement)).toEqual([WRITE_SCHEMA_DIFF]);
    });

    it("keeps the instructions in the right pane when the task's instructions are shown", () => {
        const root = open(AGENT, [WRITE_SCHEMA_CHANGE], { expanded: true });

        showInRightPane(root, 1, 'instructions');

        expect(shownCodeDiffs(fixture.debugElement)).toEqual([]);
        expect(root.querySelector('.main-editor-pane__title')?.textContent?.trim()).toBe('Instructions');
    });

    it.each<{ case: string; fields: FieldChange[]; options: ChangesTabOptions }>([
        {
            case: 'only another field of the task changed',
            fields: [{ ...taskSchemaChange(2, 'Old', 'Write'), path: 'tasks[2].name', field: 'tasks[].name' }],
            options: {},
        },
        {
            case: 'a restore adds the task',
            fields: [
                {
                    path: 'tasks[2]',
                    field: 'tasks[]',
                    status: 'added',
                    current: null,
                    version: { name: 'Write', instructions: '', output_schema: { type: 'object' }, context_tasks: [] },
                },
            ],
            options: {},
        },
        { case: 'off the Changes tab', fields: [WRITE_SCHEMA_CHANGE], options: { onChangesTab: false } },
        { case: 'the node is added', fields: [WRITE_SCHEMA_CHANGE], options: { status: 'added' } },
    ])('shows the JSON editor when $case', ({ fields, options }) => {
        const root = open(AGENT, fields, { ...options, expanded: true });

        showInRightPane(root, 1, 'schema');

        expect(shownCodeDiffs(fixture.debugElement)).toEqual([]);
        expect(schemaEditorShown(root)).toBe(true);
    });
});

describe('Task output schema on the Changes tab', () => {
    const HINT = 'Expand editor to see the changes.';

    /** Widened panel: the big pane's own button swaps the instructions it shows for the schema. */
    function showSchemaInBigPane(root: HTMLElement): void {
        root.querySelector<HTMLButtonElement>('.main-editor-pane button[title="Collapse"]')!.click();
        fixture.detectChanges();
    }

    it.each([
        { layout: 'narrow', expanded: false },
        { layout: 'widened, instructions in the big pane', expanded: true },
    ])('$layout: opens the schema section and marks its small editor with the expand hint', ({ expanded }) => {
        const root = open(TASK, [SCHEMA_CHANGE], { expanded });

        expect(markedFields(root)).toEqual(['app-json-editor']);
        const mark = root.querySelector('app-diff-field-mark.diff-field-mark--shown')!;
        expect(mark.classList).toContain('diff-field-mark--draws-badge');
        expect(descriptionOf(mark)).toBe(HINT);
        expect(shownCodeDiffs(fixture.debugElement)).toEqual([]);
    });

    it('keeps the schema section closed once the user closes it, when the diff is given again', () => {
        const diff = signal<NodePanelDiff>({ status: 'changed', fields: [SCHEMA_CHANGE], missingReferences: [] });
        const root = open(TASK, [], {}, TASK.node(), [{ provide: NODE_PANEL_DIFF, useValue: diff.asReadonly() }]);
        const schemaEditor = () => root.querySelector('.output-schema-section app-json-editor');
        expect(schemaEditor()).not.toBeNull();

        root.querySelector<HTMLButtonElement>('.output-schema-toggle')!.click();
        fixture.detectChanges();
        diff.set({ status: 'changed', fields: [SCHEMA_CHANGE, NAME_CHANGE], missingReferences: [] });
        fixture.detectChanges();

        expect(schemaEditor()).toBeNull();
    });

    it('shows a JSON diff of the current canvas and the version schema in the big pane', () => {
        const root = open(TASK, [SCHEMA_CHANGE], { expanded: true });

        showSchemaInBigPane(root);

        expect(shownCodeDiffs(fixture.debugElement)).toEqual([{ current: '{\n  "type": "string"\n}', version: '{}' }]);
        expect(shownCodeDiffLanguages(fixture.debugElement)).toEqual(['json']);
        expect(root.querySelector('.main-editor-pane app-json-editor')).toBeNull();
    });

    it.each<{ case: string; fields: FieldChange[]; options: ChangesTabOptions }>([
        { case: 'the schema is unchanged', fields: [], options: {} },
        { case: 'off the Changes tab', fields: [SCHEMA_CHANGE], options: { onChangesTab: false } },
        { case: 'the node is added', fields: [SCHEMA_CHANGE], options: { status: 'added' } },
    ])('keeps the section closed and the big pane an editor when $case', ({ fields, options }) => {
        const root = open(TASK, fields, { ...options, expanded: true });

        expect(root.querySelector('.output-schema-section app-json-editor')).toBeNull();
        showSchemaInBigPane(root);
        expect(root.querySelector('.main-editor-pane app-json-editor')).not.toBeNull();
        expect(shownCodeDiffs(fixture.debugElement)).toEqual([]);
    });
});

describe('Task instructions in the widened panel', () => {
    it('boxes the big instructions pane, inside the pane that clips what sticks out', () => {
        const root = open(TASK, [fieldChange('instructions', 'Do it now', 'Do it')], { expanded: true });

        expect(markedFields(root)).toEqual(['div.main-editor-pane__body']);
        const mark = root.querySelector('app-diff-field-mark.diff-field-mark--shown')!;
        expect(mark.classList).toContain('instructions-mark');
        expect(mark.classList).toContain('diff-field-mark--group');
    });
});

/**
 * Where each newly marked form component draws its mark: the value box gets the border and the badge, the label stays
 * outside. jsdom does not resolve the border colour (a CSS variable), so the styles that only the mark gives show which
 * element is marked: the badge's anchor (`position: relative`), the box drawn around a value shown as plain text (its
 * padding), and a disabled field no longer faded as a whole.
 */
describe('The value box each newly marked form component draws its mark on', () => {
    type BoxStyle = 'position' | 'paddingLeft' | 'paddingTop' | 'opacity';
    const BOXES: {
        panel: Panel;
        change: FieldChange;
        box: string;
        marked: Partial<Record<BoxStyle, string>>;
        plain: Partial<Record<BoxStyle, string>>;
    }[] = [
        {
            panel: AGENT,
            change: fieldChange('agent_definition', 7, 41),
            box: '.dropdown-trigger',
            marked: { paddingTop: '8px', position: 'relative' },
            plain: { paddingTop: '0px' },
        },
        {
            panel: TASK,
            change: fieldChange('surface_list', [52], [51]),
            box: '.multi-select__btn',
            marked: { position: 'relative' },
            plain: { position: 'static' },
        },
        {
            panel: TASK,
            change: fieldChange('instructions', 'Do it now', 'Do it'),
            box: '.vht-field',
            marked: { opacity: '1' },
            plain: { opacity: '0.7' },
        },
        {
            panel: SCHEDULE,
            change: fieldChange('interval_every', 2, 1),
            box: '.number-stepper__control',
            marked: { paddingLeft: '12px', position: 'relative' },
            // No padding of its own.
            plain: { paddingLeft: '0' },
        },
        {
            panel: SCHEDULE,
            change: fieldChange('timezone', 'Europe/Berlin', 'Europe/Kyiv'),
            box: '.tz-selector__btn',
            marked: { paddingLeft: '12px' },
            plain: { paddingLeft: '0px' },
        },
    ];
    const stylesOf = (element: Element, expected: Partial<Record<BoxStyle, string>>) =>
        Object.fromEntries(Object.keys(expected).map((name) => [name, getComputedStyle(element)[name as BoxStyle]]));

    it.each(BOXES)('$panel.name $change.field: on $box', ({ panel, change, box, marked }) => {
        const mark = open(panel, [change]).querySelector('app-diff-field-mark.diff-field-mark--shown')!;

        expect(stylesOf(mark.querySelector(box)!, marked)).toEqual(marked);
    });

    it.each(BOXES)('$panel.name: leaves $box as it is without a change', ({ panel, box, plain }) => {
        const valueBox = open(panel, []).querySelector(box)!;

        expect(stylesOf(valueBox, plain)).toEqual(plain);
    });
});
