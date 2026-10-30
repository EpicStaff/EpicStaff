import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ColDef, ColGroupDef } from 'ag-grid-community';

import { ToastService } from '../../../../../services/notifications';
import { ConditionGroup } from '../../../../core/models/decision-table.model';
import { CDT_FREEZE_COPY, CDT_FREEZE_MAX_WIDTH_RATIO, CDT_ROUTE_CONTINUE_COPY } from '../cdt.constants';
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
            // jsdom lays nothing out, so the table would be 0px wide and refuse every freeze.
            setTableWidth(1_000_000);
        }

        /** The width the freeze guard measures the table at. */
        function setTableWidth(px: number): void {
            const table = host.querySelector('ag-grid-angular');
            if (!table) throw new Error('no grid');
            Object.defineProperty(table, 'clientWidth', { configurable: true, value: px });
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
                const icon = cell(ROW.ignored, 'route_code').querySelector<HTMLElement>(
                    '.cdt-route-code-cell__status .help-icon-wrapper'
                );
                if (!icon) throw new Error('no status icon');

                icon.dispatchEvent(new MouseEvent('mouseenter'));
                await settle();

                expect(document.querySelector('.mat-mdc-tooltip')?.textContent?.trim()).toBe(
                    CDT_ROUTE_CONTINUE_COPY.routeCodeIgnored
                );
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

        describe('freezing columns from a column header menu', () => {
            /** Opens the header menu of `colId` and returns its freeze items, by label. */
            async function openFreezeItems(colId: string): Promise<Map<string, HTMLElement>> {
                const chevron = host.querySelector<HTMLElement>(`.ag-header-cell[col-id="${colId}"] .chm-chevron`);
                if (!chevron) throw new Error(`no menu on the ${colId} header`);
                chevron.click();
                await settle();
                const items = Array.from(document.querySelectorAll<HTMLElement>('.chm-dropdown .chm-menu-item'));
                return new Map(
                    items.map((item) => [item.textContent!.trim(), item] as const).filter(([label]) => label !== 'Hide')
                );
            }

            async function choose(colId: string, label: string): Promise<void> {
                const item = (await openFreezeItems(colId)).get(label);
                if (!item) throw new Error(`no "${label}" in the ${colId} menu`);
                item.click();
                await settle();
            }

            function pinned(side: 'left' | 'right'): string[] {
                return Array.from(
                    host.querySelectorAll(`.ag-header .ag-grid-pinned-${side}-cells .ag-header-cell[col-id]`)
                ).map((headerCell) => headerCell.getAttribute('col-id')!);
            }

            function savedState(): { freezeAnchor: unknown; freezeSide: unknown; pinned: string[] } {
                return JSON.parse(localStorage.getItem(`cdt-grid-state-${NODE_ID}`) ?? '{}');
            }

            it('offers both sides while nothing is frozen', async () => {
                await render();

                const items = await openFreezeItems('prompt_id');

                expect([...items.keys()]).toEqual(['Freeze All Left', 'Freeze All Right']);
                items.forEach((item) => expect(item.getAttribute('aria-disabled')).toBeNull());
            });

            it('Freeze All Left pins the column and everything to its left', async () => {
                await render();

                await choose('group_name', 'Freeze All Left');

                expect(pinned('left')).toEqual(['selection', 'dock_visible', 'group_name']);
                expect(pinned('right')).toEqual([]);
                await vi.advanceTimersByTimeAsync(300);
                expect(savedState()).toEqual(
                    expect.objectContaining({ freezeAnchor: 'group_name', freezeSide: 'left' })
                );
            });

            it('Freeze All Right pins the column and everything to its right, the actions column too', async () => {
                await render();

                await choose('route_code', 'Freeze All Right');

                expect(pinned('right')).toEqual(['route_code', 'continue_flag', 'actions']);
                expect(pinned('left')).toEqual([]);
                await vi.advanceTimersByTimeAsync(300);
                expect(savedState()).toEqual(
                    expect.objectContaining({ freezeAnchor: 'route_code', freezeSide: 'right' })
                );
            });

            it('offers Unfreeze Left on the anchor, and it clears the left freeze', async () => {
                await render();
                await choose('group_name', 'Freeze All Left');

                await choose('group_name', 'Unfreeze Left');

                expect(pinned('left')).toEqual([]);
                await vi.advanceTimersByTimeAsync(300);
                expect(savedState()).toEqual(expect.objectContaining({ freezeAnchor: null, freezeSide: null }));
            });

            it('offers Unfreeze Right on the anchor, and it clears the right freeze', async () => {
                await render();
                await choose('route_code', 'Freeze All Right');

                await choose('route_code', 'Unfreeze Right');

                expect(pinned('right')).toEqual([]);
            });

            it('moves the left anchor from another column', async () => {
                await render();
                await choose('group_name', 'Freeze All Left');

                await choose('prompt_id', 'Freeze All Left');

                expect(pinned('left')).toContain('prompt_id');
                expect(pinned('left')[0]).toBe('selection');
            });

            it('disables the right side while the left is frozen, with the reason as its tooltip', async () => {
                await render();
                await choose('group_name', 'Freeze All Left');

                const right = (await openFreezeItems('route_code')).get('Freeze All Right')!;
                expect(right.getAttribute('aria-disabled')).toBe('true');
                expect(right.getAttribute('title')).toBe('Unfreeze Left first');

                right.click();
                await settle();
                expect(pinned('right')).toEqual([]);
            });

            it('disables the left side while the right is frozen, with the reason as its tooltip', async () => {
                await render();
                await choose('route_code', 'Freeze All Right');

                const left = (await openFreezeItems('group_name')).get('Freeze All Left')!;
                expect(left.getAttribute('aria-disabled')).toBe('true');
                expect(left.getAttribute('title')).toBe('Unfreeze Right first');

                left.click();
                await settle();
                expect(pinned('left')).toEqual([]);
            });

            it('restores a freeze saved before there were two sides as a left freeze', async () => {
                localStorage.setItem(
                    `cdt-grid-state-${NODE_ID}`,
                    JSON.stringify({ pinned: ['selection', 'dock_visible', 'group_name'], freezeAnchor: 'group_name' })
                );
                await render();

                expect(pinned('left')).toEqual(['selection', 'dock_visible', 'group_name']);
                expect([...(await openFreezeItems('group_name')).keys()]).toEqual(['Unfreeze Left']);
            });

            it('restores a saved right freeze', async () => {
                localStorage.setItem(
                    `cdt-grid-state-${NODE_ID}`,
                    JSON.stringify({
                        pinned: ['route_code', 'continue_flag', 'actions'],
                        freezeAnchor: 'route_code',
                        freezeSide: 'right',
                    })
                );
                await render();

                expect(pinned('right')).toEqual(['route_code', 'continue_flag', 'actions']);
                expect([...(await openFreezeItems('route_code')).keys()]).toEqual(['Unfreeze Right']);
            });

            describe('which sides a column offers', () => {
                beforeEach(() => render());

                it('offers only Left on a left-only column (Condition Name)', async () => {
                    expect([...(await openFreezeItems('group_name')).keys()]).toEqual(['Freeze All Left']);
                });

                it('offers only Right on a right-only column (Route Code)', async () => {
                    expect([...(await openFreezeItems('route_code')).keys()]).toEqual(['Freeze All Right']);
                });

                it('offers both sides on Manipulation', async () => {
                    expect([...(await openFreezeItems('manipulation')).keys()]).toEqual([
                        'Freeze All Left',
                        'Freeze All Right',
                    ]);
                });

                it('gives Continue a menu with only Freeze All Right, and no Hide', async () => {
                    expect(host.querySelector('.ag-header-cell[col-id="continue_flag"] .chm-label')?.textContent).toBe(
                        'Continue'
                    );

                    await choose('continue_flag', 'Freeze All Right');

                    expect(pinned('right')).toEqual(['continue_flag', 'actions']);
                    await openFreezeItems('continue_flag');
                    const labels = Array.from(document.querySelectorAll('.chm-dropdown .chm-menu-item')).map((item) =>
                        item.textContent!.trim()
                    );
                    expect(labels).toEqual(['Unfreeze Right']);
                });
            });

            describe('the table width limit', () => {
                let warnings: ReturnType<typeof vi.spyOn>;

                beforeEach(async () => {
                    await render();
                    warnings = vi.spyOn(TestBed.inject(ToastService), 'warning');
                });

                /** Total width of the columns Freeze All Left on Condition Name would pin, as the grid sized them. */
                function leftOfConditionNameWidth(): number {
                    return ['selection', 'dock_visible', 'group_name']
                        .map((colId) =>
                            parseFloat(
                                host.querySelector<HTMLElement>(`.ag-header-cell[col-id="${colId}"]`)!.style.width
                            )
                        )
                        .reduce((sum, width) => sum + width, 0);
                }

                it('refuses a freeze wider than 90% of the table, and says why', async () => {
                    const width = leftOfConditionNameWidth();
                    expect(width).toBeGreaterThan(0);
                    setTableWidth(Math.floor(width / CDT_FREEZE_MAX_WIDTH_RATIO) - 1);

                    await choose('group_name', 'Freeze All Left');

                    expect(pinned('left')).toEqual([]);
                    expect(fixture.componentInstance.freezeState()).toBeNull();
                    expect(warnings).toHaveBeenCalledWith(CDT_FREEZE_COPY.tooWide, undefined, 'bottom-right');
                });

                it('freezes up to exactly 90% of the table', async () => {
                    setTableWidth(Math.ceil(leftOfConditionNameWidth() / CDT_FREEZE_MAX_WIDTH_RATIO));

                    await choose('group_name', 'Freeze All Left');

                    expect(pinned('left')).toEqual(['selection', 'dock_visible', 'group_name']);
                    expect(warnings).not.toHaveBeenCalled();
                });
            });

            describe('with Params columns', () => {
                /** Rows with Expression params `a`, `b` and Manipulation param `x`, so both Params groups show. */
                function rowsWithParams(): ConditionGroup[] {
                    return rows().map((row) => ({
                        ...row,
                        field_expressions: { a: '', b: '' },
                        field_manipulations: { x: '' },
                    }));
                }

                /** Opens the Params group header menu of `owner` and clicks `label`. */
                async function chooseInGroup(owner: 'Expression' | 'Manipulation', label: string): Promise<void> {
                    const header = Array.from(host.querySelectorAll<HTMLElement>('app-params-group-header')).find(
                        (element) => element.textContent?.includes(owner)
                    );
                    const chevron = header?.querySelector<HTMLElement>('.chevron-btn');
                    if (!chevron) throw new Error(`no ${owner} Params group menu`);
                    chevron.click();
                    await settle();
                    const item = Array.from(document.querySelectorAll<HTMLElement>('.params-dropdown-item')).find(
                        (element) => element.textContent?.trim() === label
                    );
                    if (!item) throw new Error(`no "${label}" in the ${owner} Params menu`);
                    item.click();
                    await settle();
                }

                beforeEach(() => render({ groups: rowsWithParams() }));

                it('pins left a column added inside a left freeze, and Unfreeze Left unpins it', async () => {
                    await choose('prompt_id', 'Freeze All Left');

                    fixture.componentInstance.addFieldColumn('c');
                    await settle();

                    expect(pinned('left')).toEqual(expect.arrayContaining(['field_a', 'field_b', 'field_c']));
                    await vi.advanceTimersByTimeAsync(300);
                    expect(savedState().pinned).toContain('field_c');

                    await choose('prompt_id', 'Unfreeze Left');

                    expect(pinned('left')).toEqual([]);
                });

                it('pins right a column added inside a right freeze, and Unfreeze Right unpins it', async () => {
                    await choose('manipulation', 'Freeze All Right');

                    fixture.componentInstance.addManipFieldColumn('y');
                    await settle();

                    expect(pinned('right')).toEqual(expect.arrayContaining(['manip_x', 'manip_y', 'route_code']));

                    await choose('manipulation', 'Unfreeze Right');

                    expect(pinned('right')).toEqual([]);
                });

                it('drops a removed column from the frozen set', async () => {
                    await choose('prompt_id', 'Freeze All Left');

                    fixture.componentInstance.removeFieldColumn('a');
                    await settle();
                    await vi.advanceTimersByTimeAsync(300);

                    expect(pinned('left')).toEqual(expect.arrayContaining(['field_b', 'prompt_id']));
                    expect(pinned('left')).not.toContain('field_a');
                    expect(savedState().pinned).not.toContain('field_a');
                });

                it('locks the children of a Params group in place while the group anchors the freeze', async () => {
                    /** `suppressMovable` of each Expression Params child, as the grid was last given them. */
                    function childrenLocked(): (boolean | undefined)[] {
                        const group = fixture.componentInstance.columnDefs.find(
                            (def): def is ColGroupDef => 'groupId' in def && def.groupId === 'expr-params-group'
                        );
                        if (!group) throw new Error('no Expression Params group');
                        return (group.children as ColDef[]).map((child) => child.suppressMovable);
                    }
                    expect(childrenLocked()).not.toContain(true);

                    await chooseInGroup('Expression', 'Freeze All Left');
                    expect(childrenLocked()).toEqual([true, true]);

                    await chooseInGroup('Expression', 'Unfreeze Left');
                    expect(childrenLocked()).not.toContain(true);
                });

                describe('frozen from a Params group header', () => {
                    /** How many header cells the `owner` Params group has: two once ag-grid splits it across a freeze. */
                    function groupHeaderCount(owner: 'Expression' | 'Manipulation'): number {
                        return Array.from(host.querySelectorAll('app-params-group-header')).filter((element) =>
                            element.textContent?.includes(owner)
                        ).length;
                    }

                    it('freezes left through the last child, and a field added to the group is frozen with it', async () => {
                        await chooseInGroup('Expression', 'Freeze All Left');
                        expect(fixture.componentInstance.freezeState()).toEqual({
                            side: 'left',
                            anchorColId: 'expr-params-group',
                        });

                        fixture.componentInstance.addFieldColumn('c');
                        await settle();

                        expect(pinned('left')).toEqual(
                            expect.arrayContaining(['expression', 'field_a', 'field_b', 'field_c'])
                        );
                        expect(pinned('left')).not.toContain('prompt_id');
                        expect(groupHeaderCount('Expression')).toBe(1);
                    });

                    it('freezes right from the first child, and a field added to the group is frozen with it', async () => {
                        await chooseInGroup('Manipulation', 'Freeze All Right');

                        fixture.componentInstance.addManipFieldColumn('y');
                        await settle();

                        expect(pinned('right')).toEqual(
                            expect.arrayContaining(['manip_x', 'manip_y', 'route_code', 'actions'])
                        );
                        expect(pinned('right')).not.toContain('manipulation');
                        expect(groupHeaderCount('Manipulation')).toBe(1);
                    });

                    it('keeps the freeze when one of its fields is removed', async () => {
                        await chooseInGroup('Expression', 'Freeze All Left');

                        fixture.componentInstance.removeFieldColumn('b');
                        await settle();

                        expect(fixture.componentInstance.freezeState()).toEqual({
                            side: 'left',
                            anchorColId: 'expr-params-group',
                        });
                        expect(pinned('left')).toEqual(expect.arrayContaining(['expression', 'field_a']));
                        expect(pinned('left')).not.toContain('field_b');
                    });

                    it('clears the freeze once the group has no fields left', async () => {
                        await chooseInGroup('Expression', 'Freeze All Left');

                        fixture.componentInstance.removeFieldColumn('a');
                        fixture.componentInstance.removeFieldColumn('b');
                        await settle();
                        await vi.advanceTimersByTimeAsync(300);

                        expect(fixture.componentInstance.freezeState()).toBeNull();
                        expect(pinned('left')).toEqual([]);
                        expect(savedState()).toEqual(expect.objectContaining({ freezeAnchor: null, pinned: [] }));
                    });

                    it('Unfreeze from the group header unpins all its children, an added one too', async () => {
                        await chooseInGroup('Expression', 'Freeze All Left');
                        fixture.componentInstance.addFieldColumn('c');
                        await settle();

                        await chooseInGroup('Expression', 'Unfreeze Left');

                        expect(fixture.componentInstance.freezeState()).toBeNull();
                        expect(pinned('left')).toEqual([]);
                    });

                    it('restores a saved anchor on a field, as saved before, as a freeze of its group', async () => {
                        localStorage.setItem(
                            `cdt-grid-state-${NODE_ID}`,
                            JSON.stringify({
                                pinned: ['selection', 'dock_visible', 'group_name', 'expression', 'field_a', 'field_b'],
                                freezeAnchor: 'field_b',
                            })
                        );
                        await render({ groups: rowsWithParams() });

                        expect(fixture.componentInstance.freezeState()).toEqual({
                            side: 'left',
                            anchorColId: 'expr-params-group',
                        });
                        fixture.componentInstance.addFieldColumn('c');
                        await settle();
                        expect(pinned('left')).toEqual(expect.arrayContaining(['field_a', 'field_b', 'field_c']));
                        expect(groupHeaderCount('Expression')).toBe(1);
                    });
                });
            });
        });
    }
);
