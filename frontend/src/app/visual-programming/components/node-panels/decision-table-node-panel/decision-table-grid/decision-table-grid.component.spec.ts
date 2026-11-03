import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ConditionGroup } from '../../../../core/models/decision-table.model';
import { FlowService } from '../../../../services/flow.service';
import { DecisionTableGridComponent } from './decision-table-grid.component';

/**
 * Deleting a condition from the keyboard, through the real ag-grid DOM: Enter or
 * Space on the focused delete cell does what a click on it does, and the focus stays
 * in the table.
 *
 * Timers are faked so rendering and ag-grid's own scheduling advance deterministically.
 */

/** Each test renders the real ag-grid in jsdom, which can take seconds on a loaded machine. */
const GRID_TEST_TIMEOUT_MS = 20_000;

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
