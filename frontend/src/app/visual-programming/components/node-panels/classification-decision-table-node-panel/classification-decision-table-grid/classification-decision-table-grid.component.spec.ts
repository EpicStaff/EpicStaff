import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ConditionGroup } from '../../../../core/models/decision-table.model';
import { CDT_ROUTE_CONTINUE_COPY } from '../cdt.constants';
import {
    CdtEnableContinueRequest,
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
            fixture.componentInstance.enableContinueRequest.subscribe((request) => enableRequests.push(request));
            fixture.componentInstance.conditionGroupsChange.subscribe((groups) => rowChanges.push(groups));
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

        /** Edits the Route Code the way a keyboard user does: focus the cell, Enter, type, Enter. */
        async function typeRouteCode(rowIndex: number, text: string): Promise<void> {
            const routeCell = cell(rowIndex, 'route_code');
            routeCell.focus();
            routeCell.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await settle();
            const input = cell(rowIndex, 'route_code').querySelector<HTMLInputElement>('input');
            if (!input) throw new Error('no route code editor');
            input.value = text;
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            await settle();
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
    }
);
