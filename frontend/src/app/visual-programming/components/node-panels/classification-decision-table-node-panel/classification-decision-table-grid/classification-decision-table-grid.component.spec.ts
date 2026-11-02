import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ConditionGroup } from '../../../../core/models/decision-table.model';
import { CDT_ROUTE_CONTINUE_COPY } from '../cdt.constants';
import {
    CdtEnableContinueRequest,
    CdtRuleIdentityEdit,
    ClassificationDecisionTableGridComponent,
} from './classification-decision-table-grid.component';

/**
 * The Route Code / Continue columns, driven through the real ag-grid DOM and the
 * real confirmation dialog (CDK overlay in `document.body`).
 *
 * Timers are faked, so rendering, ag-grid's own scheduling and the tooltip delay
 * advance deterministically. Not covered here: pixel layout and colours, which
 * jsdom does not compute.
 */

const NODE_ID = 'table1';
const APPROVE_PORT = `${NODE_ID}_decision-route-approve`;
const CONFLICT_PORT = `${NODE_ID}_decision-route-conflict`;

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

/** One row per state the two columns can be in. */
function rows(): ConditionGroup[] {
    return [
        rule({ group_name: 'Approve', route_code: 'approve', continue_flag: false, next_node: 'review', order: 1 }),
        rule({ group_name: 'Approve too', route_code: 'approve', continue_flag: false, next_node: 'review', order: 2 }),
        rule({ group_name: 'Reject', route_code: 'reject', continue_flag: false, order: 3 }),
        rule({ group_name: 'Nowhere', route_code: '', continue_flag: false, order: 4 }),
        rule({ group_name: 'Ignored', route_code: 'later', continue_flag: true, order: 5 }),
        rule({ group_name: 'Conflict', route_code: 'conflict', continue_flag: true, next_node: 'x', order: 6 }),
    ];
}

const ROW = { approve: 0, approveToo: 1, reject: 2, nowhere: 3, ignored: 4, conflict: 5 } as const;

/**
 * Each test renders the real ag-grid in jsdom, which takes seconds of real time on a
 * loaded machine even with the timers faked; the default 5 s is too tight for that.
 */
const GRID_TEST_TIMEOUT_MS = 20_000;

describe(
    'ClassificationDecisionTableGridComponent — Route Code and Continue',
    { timeout: GRID_TEST_TIMEOUT_MS },
    () => {
        let fixture: ComponentFixture<ClassificationDecisionTableGridComponent>;
        let host: HTMLElement;
        let enableRequests: CdtEnableContinueRequest[];
        let rowChanges: ConditionGroup[][];
        let identityEdits: CdtRuleIdentityEdit[];
        /** Which output fired, in order. */
        let emitted: string[];

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
            vi.useRealTimers();
            document.querySelectorAll('.cdk-overlay-container').forEach((element) => (element.innerHTML = ''));
            localStorage.clear();
        });

        /** Rendering and ag-grid's own scheduling both run on (faked) timers; a few rounds settle them. */
        async function settle(): Promise<void> {
            for (let round = 0; round < 5; round++) {
                await vi.advanceTimersByTimeAsync(50);
                fixture.detectChanges();
            }
        }

        async function render(
            options: { readonly?: boolean; wired?: string[]; groups?: ConditionGroup[] } = {}
        ): Promise<void> {
            // A test may render again over what its `beforeEach` rendered.
            TestBed.resetTestingModule();
            TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
            fixture = TestBed.createComponent(ClassificationDecisionTableGridComponent);
            host = fixture.nativeElement;
            enableRequests = [];
            rowChanges = [];
            identityEdits = [];
            emitted = [];
            fixture.componentInstance.enableContinueRequest.subscribe((request) => enableRequests.push(request));
            fixture.componentInstance.conditionGroupsChange.subscribe((groups) => {
                rowChanges.push(groups);
                emitted.push('rows');
            });
            fixture.componentInstance.ruleIdentityEdit.subscribe((edit) => {
                identityEdits.push(edit);
                emitted.push('identity');
            });
            fixture.componentRef.setInput('currentNodeId', NODE_ID);
            fixture.componentRef.setInput('conditionGroups', options.groups ?? rows());
            fixture.componentRef.setInput(
                'routePortIdsWithTarget',
                new Set(options.wired ?? [APPROVE_PORT, CONFLICT_PORT])
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

        function continueBox(rowIndex: number): HTMLInputElement {
            const box = cell(rowIndex, 'continue_flag').querySelector<HTMLInputElement>('input[type="checkbox"]');
            if (!box) throw new Error(`no Continue checkbox in row ${rowIndex}`);
            return box;
        }

        async function clickContinue(rowIndex: number): Promise<void> {
            continueBox(rowIndex).click();
            await settle();
        }

        function dialog(): HTMLElement | null {
            return document.querySelector<HTMLElement>('app-confirmation-dialog');
        }

        async function pressInDialog(selector: string): Promise<void> {
            const button = dialog()?.querySelector<HTMLElement>(selector);
            if (!button) throw new Error(`no ${selector} in the dialog`);
            button.click();
            await settle();
        }

        /** Edits a text cell the way a keyboard user does: focus the cell, Enter, type, Enter. */
        async function typeInCell(rowIndex: number, colId: string, text: string): Promise<void> {
            const target = cell(rowIndex, colId);
            target.focus();
            target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await settle();
            const input = cell(rowIndex, colId).querySelector<HTMLInputElement>('input');
            if (!input) throw new Error(`no ${colId} editor`);
            input.value = text;
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await settle();
        }

        async function typeRouteCode(rowIndex: number, text: string): Promise<void> {
            await typeInCell(rowIndex, 'route_code', text);
        }

        describe('ticking Continue on a wired route code', () => {
            beforeEach(() => render());

            it('asks first, in the raised warning dialog, and leaves the box unticked while it asks', async () => {
                await clickContinue(ROW.approve);

                expect(dialog()?.querySelector('.dialog-title')?.textContent).toContain(
                    CDT_ROUTE_CONTINUE_COPY.enableContinueDialog.title
                );
                expect(dialog()?.querySelector('.dialog-container')?.classList).toContain('raised');
                expect(continueBox(ROW.approve).checked).toBe(false);
                expect(enableRequests).toEqual([]);
            });

            it('changes nothing when the user cancels', async () => {
                await clickContinue(ROW.approve);
                await pressInDialog('.cancel-button');

                expect(dialog()).toBeNull();
                expect(continueBox(ROW.approve).checked).toBe(false);
                expect(enableRequests).toEqual([]);
                expect(rowChanges).toEqual([]);
            });

            it('changes nothing when the user closes the dialog', async () => {
                await clickContinue(ROW.approve);
                await pressInDialog('.close-button');

                expect(dialog()).toBeNull();
                expect(continueBox(ROW.approve).checked).toBe(false);
                expect(enableRequests).toEqual([]);
            });

            it('on confirm, asks the parent to free the port with the rows as they should end up', async () => {
                // Gapped orders, as a table edited over time has them: what is handed over is renumbered.
                await render({ groups: rows().map((row, index) => ({ ...row, order: (index + 1) * 10 })) });

                await clickContinue(ROW.approve);
                await pressInDialog('.confirm-button');

                expect(enableRequests).toHaveLength(1);
                const [request] = enableRequests;
                expect(request.portId).toBe(APPROVE_PORT);
                expect(request.rows.map((row) => row.order)).toEqual([1, 2, 3, 4, 5, 6]);
                expect(request.rows[ROW.approve]).toEqual(
                    expect.objectContaining({ continue_flag: true, next_node: null })
                );
                // Shares the port, so it loses its target too — or the next autosave would restore it.
                expect(request.rows[ROW.approveToo]).toEqual(
                    expect.objectContaining({ continue_flag: false, next_node: null })
                );
                expect(request.rows[ROW.conflict].next_node).toBe('x');
                // The grid commits nothing itself; the parent feeds the rows back once the port is free.
                expect(continueBox(ROW.approve).checked).toBe(false);
                expect(rowChanges).toEqual([]);
            });

            it('drops a confirmation whose rows were replaced while the dialog was open', async () => {
                await clickContinue(ROW.approve);
                fixture.componentRef.setInput('conditionGroups', rows());
                await settle();
                await pressInDialog('.confirm-button');

                expect(enableRequests).toEqual([]);
            });
        });

        it('ticks Continue on an unwired route code straight away, without asking', async () => {
            await render();

            await clickContinue(ROW.reject);

            expect(dialog()).toBeNull();
            expect(continueBox(ROW.reject).checked).toBe(true);
            expect(enableRequests).toEqual([]);
            expect(rowChanges.at(-1)?.[ROW.reject].continue_flag).toBe(true);
        });

        it('does nothing in a read-only grid', async () => {
            await render({ readonly: true });

            await clickContinue(ROW.approve);
            await clickContinue(ROW.reject);

            expect(dialog()).toBeNull();
            expect(continueBox(ROW.reject).checked).toBe(false);
            expect(enableRequests).toEqual([]);
            expect(rowChanges).toEqual([]);
        });

        describe('editing a route code', () => {
            beforeEach(() => render());

            it('stores it trimmed and unticks Continue when a route is named', async () => {
                await typeRouteCode(ROW.ignored, '  refund  ');

                const emitted = rowChanges.at(-1)!;
                expect(emitted[ROW.ignored]).toEqual(
                    expect.objectContaining({ route_code: 'refund', continue_flag: false })
                );
                expect(continueBox(ROW.ignored).checked).toBe(false);
            });

            it('ticks Continue back when the route code is cleared', async () => {
                await typeRouteCode(ROW.reject, '   ');

                const emitted = rowChanges.at(-1)!;
                expect(emitted[ROW.reject]).toEqual(expect.objectContaining({ route_code: '', continue_flag: true }));
                expect(continueBox(ROW.reject).checked).toBe(true);
            });
        });

        describe('editing what a rule is told apart by', () => {
            beforeEach(() => render());

            /** Every row but the edited one, which the two sides must agree on. */
            function othersThan(rowIndex: number, rowsOnOneSide: ConditionGroup[]): ConditionGroup[] {
                return rowsOnOneSide.filter((_, index) => index !== rowIndex);
            }

            it('reports a new route code with the rows either side of it, just before the rows', async () => {
                await typeRouteCode(ROW.reject, 'refused');

                expect(identityEdits).toHaveLength(1);
                const [edit] = identityEdits;
                expect(edit.rowIndex).toBe(ROW.reject);
                expect(edit.rowsBefore[ROW.reject].route_code).toBe('reject');
                expect(edit.rowsAfter[ROW.reject].route_code).toBe('refused');
                expect(othersThan(ROW.reject, edit.rowsBefore)).toEqual(othersThan(ROW.reject, edit.rowsAfter));
                expect(edit.rowsAfter).toEqual(rowChanges.at(-1));
                expect(emitted).toEqual(['identity', 'rows']);
            });

            it('reports a renamed rule', async () => {
                await typeInCell(ROW.nowhere, 'group_name', 'Somewhere');

                expect(identityEdits).toHaveLength(1);
                const [edit] = identityEdits;
                expect(edit.rowIndex).toBe(ROW.nowhere);
                expect(edit.rowsBefore[ROW.nowhere].group_name).toBe('Nowhere');
                expect(edit.rowsAfter[ROW.nowhere].group_name).toBe('Somewhere');
                expect(othersThan(ROW.nowhere, edit.rowsBefore)).toEqual(othersThan(ROW.nowhere, edit.rowsAfter));
            });

            it('reports nothing when the value is typed again unchanged', async () => {
                await typeRouteCode(ROW.reject, 'reject');
                await typeInCell(ROW.reject, 'group_name', 'Reject');

                expect(identityEdits).toEqual([]);
            });

            it('reports nothing for an edit to any other column', async () => {
                await clickContinue(ROW.reject);

                expect(rowChanges).toHaveLength(1);
                expect(identityEdits).toEqual([]);
            });
        });

        describe('what the Route Code cell shows', () => {
            beforeEach(() => render());

            it('marks a row that neither routes nor continues red', () => {
                expect(cell(ROW.nowhere, 'route_code').classList).toContain('cell-required-invalid');
                expect(cell(ROW.approve, 'route_code').classList).not.toContain('cell-required-invalid');
            });

            it('marks a wired route code with Continue on red, with a conflict icon that says how to fix it', () => {
                const routeCell = cell(ROW.conflict, 'route_code');
                const status = routeCell.querySelector('.cdt-route-code-cell__status');

                expect(routeCell.classList).toContain('cell-required-invalid');
                expect(status?.classList).toContain('cdt-route-code-cell__status--conflict');
                expect(status?.getAttribute('aria-label')).toBe(CDT_ROUTE_CONTINUE_COPY.routeContinueConflict);
            });

            it('dims an unwired route code with Continue on, with the thin warning icon and its reason', () => {
                const routeCell = cell(ROW.ignored, 'route_code');
                const status = routeCell.querySelector('.cdt-route-code-cell__status');

                expect(routeCell.classList).not.toContain('cell-required-invalid');
                expect(routeCell.querySelector('.cdt-route-code-cell__code')?.classList).toContain(
                    'cdt-route-code-cell__code--ignored'
                );
                expect(routeCell.querySelector('.cdt-route-code-cell__code')?.textContent).toBe('later');
                expect(status?.getAttribute('aria-label')).toBe(CDT_ROUTE_CONTINUE_COPY.routeCodeIgnored);
                expect(status?.querySelector('use')?.getAttribute('href')).toBe('#icon-thin-warning');
            });

            it('shows the reason in a tooltip once the status icon is hovered', async () => {
                const status = cell(ROW.ignored, 'route_code').querySelector<HTMLElement>(
                    '.cdt-route-code-cell__status'
                );
                if (!status) throw new Error('no status icon');

                status.dispatchEvent(new MouseEvent('mouseenter'));
                await settle();

                expect(document.querySelector('.mat-mdc-tooltip')?.textContent?.trim()).toBe(
                    CDT_ROUTE_CONTINUE_COPY.routeCodeIgnored
                );
            });

            it('keeps the status icon out of the tab order, so keyboard focus stays on the grid cell', () => {
                const routeCell = cell(ROW.conflict, 'route_code');

                expect(routeCell.querySelector('.cdt-route-code-cell__status')).not.toBeNull();
                expect(routeCell.querySelector('button, a[href], [tabindex]:not([tabindex="-1"])')).toBeNull();
            });

            it('follows the canvas: wiring the dimmed route code turns it into a conflict', async () => {
                fixture.componentRef.setInput(
                    'routePortIdsWithTarget',
                    new Set([APPROVE_PORT, CONFLICT_PORT, `${NODE_ID}_decision-route-later`])
                );
                await settle();

                expect(cell(ROW.ignored, 'route_code').classList).toContain('cell-required-invalid');
                expect(cell(ROW.ignored, 'route_code').querySelector('.cdt-route-code-cell__code--ignored')).toBeNull();
            });
        });
    }
);

/**
 * The header row from the keyboard, through the real ag-grid DOM and the real CDK
 * menus. jsdom lays nothing out, so CDK's focus trap finds no tabbable item on its
 * own; the tests move the focus into a menu themselves, as the trap would.
 */
describe(
    'ClassificationDecisionTableGridComponent — header row from the keyboard',
    { timeout: GRID_TEST_TIMEOUT_MS },
    () => {
        let fixture: ComponentFixture<ClassificationDecisionTableGridComponent>;
        let host: HTMLElement;

        beforeAll(() => {
            const scope = globalThis as unknown as { ResizeObserver?: unknown };
            scope.ResizeObserver ??= class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            };
        });

        beforeEach(async () => {
            vi.useFakeTimers();
            TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
            fixture = TestBed.createComponent(ClassificationDecisionTableGridComponent);
            host = fixture.nativeElement;
            fixture.componentRef.setInput('currentNodeId', NODE_ID);
            fixture.componentRef.setInput('conditionGroups', [
                rule({ group_name: 'Approve', route_code: 'approve', order: 1 }),
            ]);
            await settle();
        });

        afterEach(() => {
            vi.useRealTimers();
            document.querySelectorAll('.cdk-overlay-container').forEach((element) => (element.innerHTML = ''));
            localStorage.clear();
        });

        async function settle(): Promise<void> {
            for (let round = 0; round < 5; round++) {
                await vi.advanceTimersByTimeAsync(50);
                fixture.detectChanges();
            }
        }

        function headerCell(colId: string): HTMLElement {
            const found = host.querySelector<HTMLElement>(`.ag-header-cell[col-id="${colId}"]`);
            if (!found) throw new Error(`no ${colId} header`);
            return found;
        }

        function paramsGroupHeaderCell(): HTMLElement {
            const found = host.querySelector('app-params-group-header')?.closest<HTMLElement>('.ag-header-group-cell');
            if (!found) throw new Error('no params group header');
            return found;
        }

        async function focusHeader(target: HTMLElement): Promise<void> {
            target.focus();
            await settle();
        }

        async function press(key: string, init: KeyboardEventInit = {}): Promise<void> {
            const target = document.activeElement;
            if (!target) throw new Error('nothing has the focus');
            target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init }));
            await settle();
        }

        function menuItems(): HTMLElement[] {
            return Array.from(
                document.querySelectorAll<HTMLElement>(
                    '.cdk-overlay-container [role="menuitem"], .cdk-overlay-container [role="menuitemradio"]'
                )
            );
        }

        function menuLabels(): string[] {
            return menuItems().map((item) => item.textContent?.trim() ?? '');
        }

        function menuItem(label: string): HTMLElement {
            const found = menuItems().find((item) => item.textContent?.trim() === label);
            if (!found) throw new Error(`no "${label}" in the menu`);
            return found;
        }

        /** Picks a menu item the way a keyboard user does: the focus is on it when it is activated. */
        async function choose(label: string): Promise<void> {
            const item = menuItem(label);
            item.focus();
            item.click();
            await settle();
        }

        function focusedHeaderColId(): string | null {
            return document.activeElement?.closest('.ag-header-cell')?.getAttribute('col-id') ?? null;
        }

        describe('the empty row-selection header', () => {
            it('is passed over when something focuses it, such as Tab into the grid', async () => {
                await focusHeader(headerCell('selection'));

                expect(document.activeElement).toBe(headerCell('dock_visible'));
            });

            it('is not reached with ArrowLeft: the focus stays on the Enable header', async () => {
                await focusHeader(headerCell('dock_visible'));
                await press('ArrowLeft');

                expect(document.activeElement).toBe(headerCell('dock_visible'));
            });

            it('is not reached with Shift+Tab: the focus leaves the header row', async () => {
                await focusHeader(headerCell('dock_visible'));
                await press('Tab', { shiftKey: true });

                expect(focusedHeaderColId()).toBeNull();
            });
        });

        describe('a column header with a menu', () => {
            it.each([
                ['Enter', 'Enter'],
                ['Space', ' '],
            ])('opens its Freeze / Hide menu on %s', async (_name, key) => {
                await focusHeader(headerCell('group_name'));
                await press(key);

                expect(menuLabels()).toEqual(['Freeze Up to This Column', 'Hide']);
            });

            it('leaves Ctrl+Enter to ag-grid', async () => {
                await focusHeader(headerCell('group_name'));
                await press('Enter', { ctrlKey: true });

                expect(menuItems()).toEqual([]);
            });

            it('gets the focus back when Escape closes the menu', async () => {
                await focusHeader(headerCell('group_name'));
                await press('Enter');
                menuItem('Hide').focus();
                await press('Escape');

                expect(menuItems()).toEqual([]);
                expect(document.activeElement).toBe(headerCell('group_name'));
            });

            it('keeps the focus on its header when Freeze rebuilds the header row', async () => {
                await focusHeader(headerCell('group_name'));
                await press('Enter');
                await choose('Freeze Up to This Column');

                expect(focusedHeaderColId()).toBe('group_name');
            });

            it('hands the focus to the header beside it when Hide removes it', async () => {
                await focusHeader(headerCell('group_name'));
                await press('Enter');
                await choose('Hide');

                expect(host.querySelector('.ag-header-cell[col-id="group_name"]')).toBeNull();
                expect(focusedHeaderColId()).toBe('expression');
            });
        });

        describe('the Enable header', () => {
            it.each([
                ['Enter', 'Enter'],
                ['Space', ' '],
            ])('opens its row filter on %s', async (_name, key) => {
                await focusHeader(headerCell('dock_visible'));
                await press(key);

                expect(menuLabels()).toEqual(['Enable/Disable', 'Only Enable', 'Only Disable']);
            });

            it('keeps the focus on the rebuilt header once a filter is chosen', async () => {
                await focusHeader(headerCell('dock_visible'));
                await press('Enter');
                await choose('Only Disable');

                expect(menuItems()).toEqual([]);
                expect(headerCell('dock_visible').textContent).toContain('Disable');
                expect(document.activeElement).toBe(headerCell('dock_visible'));
            });
        });

        describe('with a hidden column', () => {
            beforeEach(async () => {
                await focusHeader(headerCell('group_name'));
                await press('Enter');
                await choose('Hide');
            });

            function badge(): HTMLElement {
                const found = host.querySelector<HTMLElement>('.hidden-col-badge');
                if (!found) throw new Error('no hidden-column badge');
                return found;
            }

            it('reaches its badge with Tab from the header before it', async () => {
                await focusHeader(headerCell('dock_visible'));
                await press('Tab');

                expect(document.activeElement).toBe(badge());
            });

            it('goes on from the badge with Tab to the header after it', async () => {
                badge().focus();
                await press('Tab');

                expect(document.activeElement).toBe(headerCell('expression'));
            });

            it('goes back from the badge with Shift+Tab to the header before it', async () => {
                badge().focus();
                await press('Tab', { shiftKey: true });

                expect(document.activeElement).toBe(headerCell('dock_visible'));
            });
        });

        describe('with the first column hidden', () => {
            beforeEach(async () => {
                fixture.componentInstance.hideColumn('dock_visible');
                await settle();
            });

            it('takes Shift+Tab from the badge that opens the header to what precedes the grid', async () => {
                host.querySelector<HTMLElement>('.hidden-col-badge')?.focus();
                await press('Tab', { shiftKey: true });

                // The last control before the grid: the "+" above it that adds the first manipulation variable.
                expect(document.activeElement?.getAttribute('aria-label')).toBe('Add manipulation variable');
            });
        });

        describe('with an expression variable', () => {
            beforeEach(async () => {
                fixture.componentInstance.addFieldColumn('amount');
                await settle();
            });

            it('opens the Params menu, Add variable first, from the group header', async () => {
                await focusHeader(paramsGroupHeaderCell());
                await press('Enter');

                expect(menuLabels()).toEqual(['Add variable', 'Freeze Up to This Column', 'Hide']);
            });

            it('keeps the focus on the group header when Freeze rebuilds the header row', async () => {
                await focusHeader(paramsGroupHeaderCell());
                await press('Enter');
                await choose('Freeze Up to This Column');

                expect(document.activeElement).toBe(paramsGroupHeaderCell());
            });

            it('opens the variable picker from Add variable', async () => {
                await focusHeader(paramsGroupHeaderCell());
                await press('Enter');
                await choose('Add variable');

                expect(menuLabels()).not.toContain('Hide');
                expect(
                    document.querySelector('.cdk-overlay-container input[placeholder="Search fields..."]')
                ).not.toBeNull();
            });

            it('reaches the Params group header with Tab, and its first variable after it', async () => {
                await focusHeader(headerCell('field_amount'));
                await press('Tab', { shiftKey: true });

                expect(document.activeElement).toBe(paramsGroupHeaderCell());

                await press('Tab');

                expect(document.activeElement).toBe(headerCell('field_amount'));
            });

            it('goes from the last header into the first body cell with Tab', async () => {
                const headers = Array.from(host.querySelectorAll<HTMLElement>('.ag-header-cell[aria-colindex]'));
                const columnIndex = (cell: HTMLElement): number => Number(cell.getAttribute('aria-colindex'));
                const lastHeader = headers.reduce((last, cell) =>
                    columnIndex(cell) > columnIndex(last) ? cell : last
                );
                await focusHeader(lastHeader);
                await press('Tab');

                const bodyCell = document.activeElement?.closest('.ag-cell');
                expect(bodyCell?.getAttribute('col-id')).toBe('selection');
                expect(bodyCell?.closest('.ag-row')?.getAttribute('row-index')).toBe('0');
            });

            it('ignores Enter on the variable header, whose only control deletes the variable', async () => {
                await focusHeader(headerCell('field_amount'));
                await press('Enter');

                expect(menuItems()).toEqual([]);
                expect(host.querySelector('.ag-header-cell[col-id="field_amount"]')).not.toBeNull();
            });
        });
    }
);
