import { NgZone, provideZoneChangeDetection, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { ConditionGroup } from '../../../../core/models/decision-table.model';
import { FlowService } from '../../../../services/flow.service';
import { ConditionGroupGridRowChanges } from '../../shared/condition-group-row-marks/condition-group-row-marks';
import {
    conditionGroupsDiff,
    cutOffCellText,
    gridCell,
    gridRowChanges,
    movePointerOnto,
    rowMark,
    rowOf,
    rowStatusOf,
    shownGridRows,
    shownGridTooltip,
    shownRowTooltip,
    shownTooltipHeading,
    shownTooltipText,
} from '../../shared/condition-group-row-marks/condition-group-row-marks.testing';
import { DecisionTableGridComponent } from './decision-table-grid.component';
import { decisionTableRowChanges } from './decision-table-row-changes';

/** Each test renders the real ag-grid in jsdom, which can take seconds on a loaded machine; the default 5 s is too tight. */
const GRID_TEST_TIMEOUT_MS = 20_000;

/**
 * The row marks of the Decision Table grid on the Changes tab of a version preview, driven through the real ag-grid
 * DOM and the real tooltip overlay (CDK, in `document.body`). Timers are faked, so ag-grid's own scheduling advances
 * deterministically. Not covered: pixel layout and colours, which jsdom does not compute.
 */

const NODE_ID = 'table1';

function group(name: string, order: number, overrides: Partial<ConditionGroup> = {}): ConditionGroup {
    return {
        group_name: name,
        group_type: 'complex',
        expression: `x > ${order}`,
        conditions: [],
        manipulation: null,
        next_node: null,
        order,
        ...overrides,
    };
}

const VERSION_GROUPS = [group('yes', 1), group('maybe', 2), group('no', 3)];

/** "yes" changed, "maybe" added; "gone" only on the canvas, third there. */
const ROW_CHANGES = gridRowChanges(
    [
        [VERSION_GROUPS[0], rowMark('changed', 'Changed columns: Expression, Next Node.')],
        [VERSION_GROUPS[1], rowMark('added')],
    ],
    [group('gone', 3, { expression: 'x < 0' })]
);

/** The events the row tooltips listen to on the grid element. */
const TOOLTIP_EVENTS = new Set(['mouseover', 'mouseleave', 'focusin', 'focusout', 'keydown', 'scroll']);

/**
 * Records the tooltip event listeners added to and removed from a grid element (`ag-grid-angular`), and whether each
 * was added inside Angular's zone: a listener added there runs a change detection of the whole app on every event.
 * `take()` gives the records since the last call.
 */
function recordGridListeners(): { take: () => string[] } {
    let records: string[] = [];
    const isGrid = (target: EventTarget): boolean =>
        target instanceof HTMLElement && target.tagName === 'AG-GRID-ANGULAR';
    const add = EventTarget.prototype.addEventListener;
    const remove = EventTarget.prototype.removeEventListener;
    vi.spyOn(EventTarget.prototype, 'addEventListener').mockImplementation(function (
        this: EventTarget,
        ...args: Parameters<EventTarget['addEventListener']>
    ) {
        if (isGrid(this) && TOOLTIP_EVENTS.has(args[0])) {
            records.push(`add ${args[0]} ${NgZone.isInAngularZone() ? 'inside' : 'outside'} the zone`);
        }
        add.apply(this, args);
    });
    vi.spyOn(EventTarget.prototype, 'removeEventListener').mockImplementation(function (
        this: EventTarget,
        ...args: Parameters<EventTarget['removeEventListener']>
    ) {
        if (isGrid(this) && TOOLTIP_EVENTS.has(args[0])) records.push(`remove ${args[0]}`);
        remove.apply(this, args);
    });
    return {
        take: () => {
            const taken = records;
            records = [];
            return taken;
        },
    };
}

describe('DecisionTableGridComponent — version diff row marks', { timeout: GRID_TEST_TIMEOUT_MS }, () => {
    let fixture: ComponentFixture<DecisionTableGridComponent>;
    let host: HTMLElement;
    let emitted: ConditionGroup[][];

    beforeAll(() => {
        // ag-grid sizes itself with a ResizeObserver; jsdom has none and lays nothing out anyway.
        const scope = globalThis as unknown as { ResizeObserver?: unknown };
        scope.ResizeObserver ??= class {
            observe(): void {}
            unobserve(): void {}
            disconnect(): void {}
        };
    });

    beforeEach(() => vi.useFakeTimers());

    afterEach(() => {
        fixture?.destroy();
        vi.restoreAllMocks();
        vi.useRealTimers();
        document.querySelectorAll('.cdk-overlay-container').forEach((element) => (element.innerHTML = ''));
    });

    async function settle(): Promise<void> {
        for (let round = 0; round < 5; round++) {
            await vi.advanceTimersByTimeAsync(50);
            fixture.detectChanges();
        }
    }

    async function render(
        rowChanges: ConditionGroupGridRowChanges | null,
        {
            readonly = true,
            groups = VERSION_GROUPS,
            zoned = false,
        }: { readonly?: boolean; groups?: ConditionGroup[]; zoned?: boolean } = {}
    ): Promise<void> {
        TestBed.resetTestingModule();
        // The app runs change detection from zone.js, as `app.config.ts` sets it up.
        if (zoned)
            TestBed.configureTestingModule({ providers: [provideZoneChangeDetection({ eventCoalescing: true })] });
        fixture = TestBed.createComponent(DecisionTableGridComponent);
        host = fixture.nativeElement;
        emitted = [];
        fixture.componentInstance.conditionGroupsChange.subscribe((groups) => emitted.push(groups));
        fixture.componentRef.setInput('currentNodeId', NODE_ID);
        // The groups themselves, as a panel gives them: the row changes hold their marks by them.
        fixture.componentRef.setInput('conditionGroups', groups);
        fixture.componentRef.setInput('readonly', readonly);
        fixture.componentRef.setInput('rowChanges', rowChanges);
        await settle();
    }

    async function hover(rowIndex: number): Promise<void> {
        gridCell(host, rowIndex, 'expression').dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
        await settle();
    }

    it('marks each row with what a restore does to it, the removed group last, numbered by its canvas place', async () => {
        await render(ROW_CHANGES);

        expect(shownGridRows(host)).toEqual([
            { name: 'yes', mark: 'changed' },
            { name: 'maybe', mark: 'added' },
            { name: 'no', mark: null },
            { name: 'gone', mark: 'removed' },
        ]);
        expect(gridCell(host, 3, 'index').textContent?.trim()).toBe('3');
    });

    it('gives each marked row its row number as its first cell, which the styles draw the status badge in', async () => {
        await render(ROW_CHANGES);

        for (const rowIndex of [0, 1, 3]) {
            expect(rowOf(host, rowIndex).querySelector('[role="gridcell"]')?.getAttribute('col-id')).toBe('index');
        }
    });

    it('tells screen readers what a restore does to each marked row, before its name', async () => {
        await render(ROW_CHANGES);

        expect(rowStatusOf(host, 0)).toBe('Restore changes this condition. Changed columns: Expression, Next Node.');
        expect(rowStatusOf(host, 1)).toBe('Restore adds this condition.');
        expect(rowStatusOf(host, 2)).toBeNull();
        expect(rowStatusOf(host, 3)).toBe('Restore removes this condition.');
    });

    it('shows the changed columns above a changed row while the pointer is over it', async () => {
        await render(ROW_CHANGES);

        await hover(0);
        expect(shownRowTooltip()).toBe('Changed columns: Expression, Next Node.');

        host.querySelector('ag-grid-angular')!.dispatchEvent(new MouseEvent('mouseleave'));
        await settle();
        expect(shownRowTooltip()).toBeNull();
    });

    it.each([
        { row: 'an added', rowIndex: 1 },
        { row: 'a kept', rowIndex: 2 },
        { row: 'a removed', rowIndex: 3 },
    ])('shows no tooltip over $row row', async ({ rowIndex }) => {
        await render(ROW_CHANGES);

        await hover(rowIndex);

        expect(shownRowTooltip()).toBeNull();
    });

    it('shows the tooltip while a cell of the row has keyboard focus; Esc closes it and not the panel', async () => {
        await render(ROW_CHANGES);
        const panelEscapes: KeyboardEvent[] = [];
        const onDocumentKeydown = (event: KeyboardEvent): void => {
            if (event.key === 'Escape') panelEscapes.push(event);
        };
        document.addEventListener('keydown', onDocumentKeydown);

        const cell = gridCell(host, 0, 'manipulation');
        cell.dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
        await settle();
        expect(shownRowTooltip()).toBe('Changed columns: Expression, Next Node.');

        cell.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        await settle();
        document.removeEventListener('keydown', onDocumentKeydown);

        expect(shownRowTooltip()).toBeNull();
        expect(panelEscapes).toEqual([]);
    });

    it('closes the tooltip when the focus leaves the grid', async () => {
        await render(ROW_CHANGES);
        const cell = gridCell(host, 0, 'manipulation');
        cell.dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
        await settle();

        cell.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: document.body }));
        await settle();

        expect(shownRowTooltip()).toBeNull();
    });

    describe('the tooltip of each cell of a changed row', () => {
        /** "yes": the expression and the route changed; the manipulation kept. "maybe": added. "gone": removed. */
        const CANVAS_GROUPS = [
            group('yes', 1, { expression: 'amount > 100', manipulation: 'y = 1', next_node: 'node-a' }),
            group('gone', 2),
        ];
        const CELL_GROUPS = [
            group('yes', 1, { expression: 'amount > 200', manipulation: 'y = 1', next_node: 'node-b' }),
            group('maybe', 2),
        ];
        const CELL_ROW_CHANGES = decisionTableRowChanges(
            conditionGroupsDiff(NodeType.TABLE, CANVAS_GROUPS, CELL_GROUPS),
            CELL_GROUPS,
            () => null,
            (value) => `Node ${String(value)}`
        );
        const SUMMARY = 'Changed columns: Expression, Next Node.';

        async function pointAt(rowIndex: number, colId: string): Promise<void> {
            gridCell(host, rowIndex, colId).dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
            await settle();
        }

        async function focus(rowIndex: number, colId: string): Promise<void> {
            gridCell(host, rowIndex, colId).dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
            await settle();
        }

        /** The description a screen reader hears for the cell, by its `aria-describedby`. */
        function descriptionOf(rowIndex: number, colId: string): string | null {
            const ids = gridCell(host, rowIndex, colId).getAttribute('aria-describedby');
            if (!ids) return null;
            return ids
                .split(' ')
                .map((id) => document.getElementById(id)?.textContent ?? '')
                .join(' ');
        }

        it('shows the current canvas value of a changed cell, the replaced part struck, and the summary elsewhere', async () => {
            await render(CELL_ROW_CHANGES, { groups: CELL_GROUPS });

            await pointAt(0, 'expression');
            expect(shownTooltipText()).toBe('Current canvas: amount > ~~1~~00');

            await pointAt(0, 'manipulation');
            expect(shownTooltipText()).toBe(SUMMARY);

            await pointAt(0, 'next_node');
            expect(shownTooltipText()).toBe('Current canvas: ~~Node node-a~~');

            await pointAt(0, 'group_name');
            expect(shownTooltipText()).toBe(SUMMARY);
        });

        it('switches the text as the keyboard focus moves between the cells of the row; a changed cell is described by it', async () => {
            await render(CELL_ROW_CHANGES, { groups: CELL_GROUPS });

            await focus(0, 'expression');
            expect(shownTooltipText()).toBe('Current canvas: amount > ~~1~~00');
            expect(descriptionOf(0, 'expression')).toBe('Current canvas: amount > 100');

            await focus(0, 'manipulation');
            expect(shownTooltipText()).toBe(SUMMARY);
            expect(descriptionOf(0, 'expression')).toBeNull();
            expect(descriptionOf(0, 'manipulation')).toBeNull();
            expect(rowStatusOf(host, 0)).toBe(`Restore changes this condition. ${SUMMARY}`);
        });

        it.each<{ way: string; close: (cell: HTMLElement) => void }>([
            {
                way: 'the pointer leaves the grid',
                close: () => host.querySelector('ag-grid-angular')!.dispatchEvent(new MouseEvent('mouseleave')),
            },
            {
                way: 'Esc',
                close: (cell) => cell.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })),
            },
            {
                way: 'the focus leaves the grid',
                close: (cell) =>
                    cell.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: document.body })),
            },
            {
                way: 'new row changes',
                close: () => {
                    fixture.componentRef.setInput('rowChanges', gridRowChanges([]));
                    fixture.detectChanges();
                },
            },
            { way: 'the grid is destroyed', close: () => fixture.destroy() },
        ])('stops describing a changed cell when its tooltip closes: $way', async ({ close }) => {
            await render(CELL_ROW_CHANGES, { groups: CELL_GROUPS });
            await focus(0, 'expression');
            const cell = gridCell(host, 0, 'expression');
            expect(descriptionOf(0, 'expression')).toBe('Current canvas: amount > 100');

            close(cell);
            await vi.advanceTimersByTimeAsync(250);

            expect(shownTooltipText()).toBeNull();
            expect(cell.getAttribute('aria-describedby')).toBeNull();
        });

        it.each([
            { row: 'an added', rowIndex: 1 },
            { row: 'a removed', rowIndex: 2 },
        ])('shows no tooltip over the cells of $row row', async ({ rowIndex }) => {
            await render(CELL_ROW_CHANGES, { groups: CELL_GROUPS });

            await pointAt(rowIndex, 'expression');
            expect(shownTooltipText()).toBeNull();
            await focus(rowIndex, 'next_node');
            expect(shownTooltipText()).toBeNull();
        });

        describe("next to the grid's own tooltip of a cut-off cell (Condition Name, Next Node)", () => {
            /** Points at a cell as a user does and waits past ag-grid's tooltip delay. */
            async function hoverCell(rowIndex: number, colId: string): Promise<void> {
                movePointerOnto(host, rowIndex, colId);
                await settle();
                await vi.advanceTimersByTimeAsync(2000);
                fixture.detectChanges();
            }

            it('shows only the row tooltip over a cut-off name of a changed row, with the full name above', async () => {
                await render(CELL_ROW_CHANGES, { groups: CELL_GROUPS });
                cutOffCellText(host, 0, 'group_name');

                await hoverCell(0, 'group_name');

                expect(shownGridTooltip()).toBeNull();
                expect(shownTooltipHeading()).toBe('yes');
                expect(shownTooltipText()).toBe(SUMMARY);
                // A little stronger than the text below it, so it reads as the row's name.
                const heading = document.querySelector('.diff-field-mark__tooltip-heading')!;
                expect(getComputedStyle(heading).fontWeight).toBe('var(--text-body-small-large-weight)');
            });

            it('shows only the row tooltip over a cut-off next node of a changed row, with the full node above', async () => {
                await render(CELL_ROW_CHANGES, { groups: CELL_GROUPS });
                cutOffCellText(host, 0, 'next_node');

                await hoverCell(0, 'next_node');

                expect(shownGridTooltip()).toBeNull();
                expect(shownTooltipHeading()).toBe('node-b');
                expect(shownTooltipText()).toBe('Current canvas: ~~Node node-a~~');
            });

            it('adds no full text to the row tooltip over a name the cell shows whole', async () => {
                await render(CELL_ROW_CHANGES, { groups: CELL_GROUPS });

                await hoverCell(0, 'group_name');

                expect(shownTooltipHeading()).toBeNull();
                expect(shownTooltipText()).toBe(SUMMARY);
            });

            it.each([
                { row: 'an added', rowIndex: 1, name: 'maybe' },
                { row: 'a removed', rowIndex: 2, name: 'gone' },
            ])(
                "shows the grid's own tooltip over a cut-off name of $row row, which has no row tooltip",
                async ({ rowIndex, name }) => {
                    await render(CELL_ROW_CHANGES, { groups: CELL_GROUPS });
                    cutOffCellText(host, rowIndex, 'group_name');

                    await hoverCell(rowIndex, 'group_name');

                    expect(shownGridTooltip()).toBe(name);
                    expect(shownTooltipText()).toBeNull();
                }
            );

            it('shows no grid tooltip over a name the cell shows whole', async () => {
                await render(CELL_ROW_CHANGES, { groups: CELL_GROUPS });

                await hoverCell(1, 'group_name');

                expect(shownGridTooltip()).toBeNull();
            });

            it("keeps the grid's own tooltip over a cut-off name in the live editor", async () => {
                await render(null, { groups: CELL_GROUPS });
                cutOffCellText(host, 0, 'group_name');

                await hoverCell(0, 'group_name');

                expect(shownGridTooltip()).toBe('yes');
            });
        });

        it('shows no tooltip over a cell in the live editor', async () => {
            await render(null, { groups: CELL_GROUPS });

            await pointAt(0, 'expression');
            await focus(0, 'next_node');

            expect(shownTooltipText()).toBeNull();
            expect(descriptionOf(0, 'next_node')).toBeNull();
        });
    });

    it('never edits, emits or saves a removed row, even in an editable grid', async () => {
        await render(ROW_CHANGES, { readonly: false });

        const removedName = gridCell(host, 3, 'group_name');
        removedName.focus();
        removedName.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        await settle();
        expect(gridCell(host, 3, 'group_name').querySelector('textarea, input')).toBeNull();

        // Deleting a kept row emits the table's rows: the removed group is not one of them.
        gridCell(host, 2, 'actions').click();
        await settle();
        expect(emitted.at(-1)?.map((emittedGroup) => emittedGroup.group_name)).toEqual(['yes', 'maybe']);
    });

    it('shows the plain table outside the Changes tab: no marks, no extra rows, no tooltips', async () => {
        await render(null);

        expect(shownGridRows(host)).toEqual([
            { name: 'yes', mark: null },
            { name: 'maybe', mark: null },
            { name: 'no', mark: null },
        ]);
        expect(rowStatusOf(host, 0)).toBeNull();
        await hover(0);
        expect(shownRowTooltip()).toBeNull();
    });

    it('marks a group whose stored name has spaces around it, though the grid shows the name trimmed', async () => {
        const canvasGroups = [group(' yes ', 1), group('no', 2)];
        const versionGroups = [group(' yes ', 1, { expression: 'x > 9' }), group('no', 2)];
        const rowChanges = decisionTableRowChanges(
            conditionGroupsDiff(NodeType.TABLE, canvasGroups, versionGroups),
            versionGroups,
            () => null,
            String
        );

        await render(rowChanges, { groups: versionGroups });

        expect(shownGridRows(host)).toEqual([
            { name: 'yes', mark: 'changed' },
            { name: 'no', mark: null },
        ]);
        await hover(0);
        expect(shownTooltipText()).toBe('Current canvas: x > ~~1~~');
    });

    it("listens to the grid only on the Changes tab, outside Angular's zone; to scrolling only under a tooltip", async () => {
        const listeners = recordGridListeners();
        await render(null, { zoned: true });
        await hover(0);
        expect(listeners.take()).toEqual([]);

        fixture.componentRef.setInput('rowChanges', ROW_CHANGES);
        await settle();
        expect(listeners.take()).toEqual(
            ['mouseover', 'mouseleave', 'focusin', 'focusout', 'keydown'].map((type) => `add ${type} outside the zone`)
        );

        await hover(0);
        expect(listeners.take()).toEqual(['add scroll outside the zone']);
        host.querySelector('ag-grid-angular')!.dispatchEvent(new MouseEvent('mouseleave'));
        await settle();
        expect(listeners.take()).toEqual(['remove scroll']);

        fixture.componentRef.setInput('rowChanges', null);
        await settle();
        expect(listeners.take()).toEqual(
            ['mouseover', 'mouseleave', 'focusin', 'focusout', 'keydown'].map((type) => `remove ${type}`)
        );
    });

    it('follows new row changes: marks drawn again, the open tooltip closed', async () => {
        await render(ROW_CHANGES);
        await hover(0);

        fixture.componentRef.setInput(
            'rowChanges',
            gridRowChanges([[VERSION_GROUPS[2], rowMark('changed', 'Moved (current canvas: position 1).')]])
        );
        await settle();

        expect(shownRowTooltip()).toBeNull();
        expect(shownGridRows(host).map(({ mark }) => mark)).toEqual([null, null, 'changed']);
        expect(rowOf(host, 2).classList).toContain('condition-group-row--changed');
    });
});

/**
 * Deleting a condition from the keyboard, through the real ag-grid DOM: Enter or
 * Space on the focused delete cell does what a click on it does, and the focus stays
 * in the table.
 *
 * Timers are faked so rendering and ag-grid's own scheduling advance deterministically.
 */

function condition(name: string, order: number): ConditionGroup {
    return {
        group_name: name,
        group_type: 'complex',
        expression: 'x > 1',
        conditions: [],
        manipulation: null,
        next_node: null,
        order,
    };
}

describe(
    'DecisionTableGridComponent — deleting a condition from the keyboard',
    { timeout: GRID_TEST_TIMEOUT_MS },
    () => {
        let fixture: ComponentFixture<DecisionTableGridComponent>;
        let host: HTMLElement;
        let emitted: ConditionGroup[][];

        beforeAll(() => {
            // ag-grid sizes itself with a ResizeObserver; jsdom has none and lays nothing out anyway.
            const scope = globalThis as unknown as { ResizeObserver?: unknown };
            scope.ResizeObserver ??= class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            };
        });

        beforeEach(() => vi.useFakeTimers());

        afterEach(() => vi.useRealTimers());

        async function settle(): Promise<void> {
            for (let round = 0; round < 5; round++) {
                await vi.advanceTimersByTimeAsync(50);
                fixture.detectChanges();
            }
        }

        async function render(names: string[], options: { readonly?: boolean } = {}): Promise<void> {
            TestBed.configureTestingModule({
                providers: [{ provide: FlowService, useValue: { nodes: signal([]), connections: signal([]) } }],
            });
            fixture = TestBed.createComponent(DecisionTableGridComponent);
            host = fixture.nativeElement;
            emitted = [];
            fixture.componentInstance.conditionGroupsChange.subscribe((groups) => emitted.push(groups));
            fixture.componentRef.setInput('currentNodeId', 'table1');
            fixture.componentRef.setInput(
                'conditionGroups',
                names.map((name, index) => condition(name, index + 1))
            );
            fixture.componentRef.setInput('readonly', options.readonly ?? false);
            await settle();
        }

        function cell(rowIndex: number, colId: string): HTMLElement {
            const found = host.querySelector<HTMLElement>(
                `.ag-row[row-index="${rowIndex}"] [role="gridcell"][col-id="${colId}"]`
            );
            if (!found) throw new Error(`no ${colId} cell in row ${rowIndex}`);
            return found;
        }

        function shownNames(): string[] {
            return Array.from(host.querySelectorAll<HTMLElement>('.ag-row [role="gridcell"][col-id="group_name"]'))
                .sort(
                    (a, b) =>
                        Number(a.closest('.ag-row')?.getAttribute('row-index')) -
                        Number(b.closest('.ag-row')?.getAttribute('row-index'))
                )
                .map((element) => element.textContent?.trim() ?? '');
        }

        function focusedCell(): { rowIndex: number; colId: string } | null {
            const focused = document.activeElement?.closest('[role="gridcell"]');
            if (!focused) return null;
            return {
                rowIndex: Number(focused.closest('.ag-row')?.getAttribute('row-index')),
                colId: focused.getAttribute('col-id') ?? '',
            };
        }

        async function pressOn(target: HTMLElement, key: string, init: KeyboardEventInit = {}): Promise<KeyboardEvent> {
            target.focus();
            await settle();
            const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
            target.dispatchEvent(event);
            await settle();
            return event;
        }

        it.each([
            ['Enter', 'Enter'],
            ['Space', ' '],
        ])('deletes the row on %s and reports the renumbered rows', async (_name, key) => {
            await render(['First', 'Second', 'Third']);

            const event = await pressOn(cell(1, 'actions'), key);

            expect(shownNames()).toEqual(['First', 'Third']);
            expect(emitted.at(-1)?.map((group) => [group.group_name, group.order])).toEqual([
                ['First', 1],
                ['Third', 2],
            ]);
            // Space would otherwise scroll the panel.
            expect(event.defaultPrevented).toBe(true);
        });

        it('keeps the focus on the delete cell of the row that moved up', async () => {
            await render(['First', 'Second', 'Third']);

            await pressOn(cell(1, 'actions'), 'Enter');

            expect(focusedCell()).toEqual({ rowIndex: 1, colId: 'actions' });
        });

        it('moves the focus to the delete cell of the new last row when the last row is deleted', async () => {
            await render(['First', 'Second', 'Third']);

            await pressOn(cell(2, 'actions'), 'Enter');

            expect(shownNames()).toEqual(['First', 'Second']);
            expect(focusedCell()).toEqual({ rowIndex: 1, colId: 'actions' });
        });

        it('moves the focus to the Condition Name header when no rows remain', async () => {
            await render(['Only']);

            await pressOn(cell(0, 'actions'), 'Enter');

            expect(shownNames()).toEqual([]);
            expect(document.activeElement).toBe(host.querySelector('.ag-header-cell[col-id="group_name"]'));
        });

        it.each([
            ['Ctrl', { ctrlKey: true }],
            ['Alt', { altKey: true }],
            ['Meta', { metaKey: true }],
            ['Shift', { shiftKey: true }],
            ['a held key', { repeat: true }],
        ])('does not delete with %s', async (_name, init) => {
            await render(['First', 'Second']);

            await pressOn(cell(0, 'actions'), 'Enter', init);

            expect(shownNames()).toEqual(['First', 'Second']);
            expect(emitted).toEqual([]);
        });

        it('does not delete on any other key', async () => {
            await render(['First', 'Second']);

            await pressOn(cell(0, 'actions'), 'a');

            expect(shownNames()).toEqual(['First', 'Second']);
            expect(emitted).toEqual([]);
        });

        it('does not delete on Space in another column', async () => {
            await render(['First', 'Second']);

            await pressOn(cell(0, 'next_node'), ' ');

            expect(shownNames()).toEqual(['First', 'Second']);
            expect(emitted).toEqual([]);
        });

        it('offers no delete cell in a read-only table', async () => {
            await render(['First', 'Second'], { readonly: true });

            expect(host.querySelector('[role="gridcell"][col-id="actions"]')).toBeNull();
        });
    }
);
