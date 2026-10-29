import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { CdtSection } from '../../../../core/models/cdt-section.model';
import { PromptConfig } from '../../../../core/models/classification-decision-table.model';
import { ConditionGroup } from '../../../../core/models/decision-table.model';
import { ConditionGroupGridRowChanges } from '../../shared/condition-group-row-marks/condition-group-row-marks';
import {
    conditionGroupsDiff,
    gridCell,
    gridRowChanges,
    rowMark,
    rowOf,
    rowStatusOf,
    shownGridRows,
    shownRowTooltip,
    shownTooltipText,
} from '../../shared/condition-group-row-marks/condition-group-row-marks.testing';
import { cdtRowChanges } from './cdt-row-changes';
import { ClassificationDecisionTableGridComponent } from './classification-decision-table-grid.component';

/**
 * The row marks of the Classification Decision Table grid on the Changes tab of a version preview, driven through the
 * real ag-grid DOM, as in the Route Code spec next to this one. Timers are faked. Not covered: pixel layout, colours.
 */

const NODE_ID = 'table1';
const GRID_TEST_TIMEOUT_MS = 20_000;
const BILLING: CdtSection = { id: 'section-billing', name: 'Billing', metadata: {} };

function rule(name: string, order: number, overrides: Partial<ConditionGroup> = {}): ConditionGroup {
    return {
        group_name: name,
        group_type: 'simple',
        expression: null,
        conditions: [],
        manipulation: null,
        next_node: null,
        route_code: name,
        continue_flag: false,
        dock_visible: true,
        order,
        ...overrides,
    };
}

/** Two rules in the Billing group, then one outside any group; new ones each time, as the grid edits its rows. */
function versionRules(): ConditionGroup[] {
    return [rule('invoice', 1, { section: BILLING.id }), rule('refund', 2, { section: BILLING.id }), rule('other', 3)];
}

/** A changed rule, and two the canvas has: one in the Billing group, one outside any group. */
function rowChangesOf(rules: ConditionGroup[]): ConditionGroupGridRowChanges {
    return gridRowChanges(
        [[rules[2], rowMark('changed', 'Changed columns: Route Code.')]],
        [rule('chargeback', 3, { section: BILLING.id }), rule('legacy', 5)]
    );
}

describe('ClassificationDecisionTableGridComponent — version diff row marks', { timeout: GRID_TEST_TIMEOUT_MS }, () => {
    let fixture: ComponentFixture<ClassificationDecisionTableGridComponent>;
    let host: HTMLElement;
    let emitted: ConditionGroup[][];

    beforeAll(() => {
        const scope = globalThis as unknown as { ResizeObserver?: unknown };
        scope.ResizeObserver ??= class {
            observe(): void {}
            unobserve(): void {}
            disconnect(): void {}
        };
    });

    beforeEach(() => {
        vi.useFakeTimers();
        // jsdom has no media queries; a user who asks for less motion gets no fold animation.
        vi.stubGlobal('matchMedia', () => ({
            matches: true,
            addEventListener: () => undefined,
            removeEventListener: () => undefined,
            addListener: () => undefined,
            removeListener: () => undefined,
        }));
    });

    afterEach(() => {
        fixture?.destroy();
        vi.useRealTimers();
        vi.unstubAllGlobals();
        document.querySelectorAll('.cdk-overlay-container').forEach((element) => (element.innerHTML = ''));
        localStorage.clear();
    });

    async function settle(): Promise<void> {
        for (let round = 0; round < 5; round++) {
            await vi.advanceTimersByTimeAsync(50);
            fixture.detectChanges();
        }
    }

    /** Renders `rules` (by default `versionRules()`) with the row changes `rowChangesFor` gives for them. */
    async function render(
        rowChangesFor: ((rules: ConditionGroup[]) => ConditionGroupGridRowChanges | null) | null,
        {
            readonly = true,
            rules = versionRules(),
            prompts = {},
        }: { readonly?: boolean; rules?: ConditionGroup[]; prompts?: Record<string, PromptConfig> } = {}
    ): Promise<void> {
        TestBed.resetTestingModule();
        TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
        fixture = TestBed.createComponent(ClassificationDecisionTableGridComponent);
        host = fixture.nativeElement;
        emitted = [];
        fixture.componentInstance.conditionGroupsChange.subscribe((groups) => emitted.push(groups));
        fixture.componentRef.setInput('currentNodeId', NODE_ID);
        // The rules themselves, as a panel gives them: the row changes hold their marks by them.
        fixture.componentRef.setInput('conditionGroups', rules);
        fixture.componentRef.setInput('sections', [BILLING]);
        fixture.componentRef.setInput('readonly', readonly);
        fixture.componentRef.setInput('prompts', prompts);
        fixture.componentRef.setInput('rowChanges', rowChangesFor?.(rules) ?? null);
        await settle();
    }

    /** Opens the Billing group, which the grid folds when it first shows the table, by its chevron. */
    async function expandBilling(): Promise<void> {
        const chevron = host.querySelector<HTMLElement>('.group-overlay-chevron.collapsed');
        if (!chevron) throw new Error('no folded group');
        chevron.click();
        await settle();
    }

    it('puts a removed rule in its group, after the group rules, and one without a group last', async () => {
        await render(rowChangesOf);
        await expandBilling();

        expect(shownGridRows(host)).toEqual([
            { name: 'invoice', mark: null },
            { name: 'refund', mark: null },
            { name: 'chargeback', mark: 'removed' },
            { name: 'other', mark: 'changed' },
            { name: 'legacy', mark: 'removed' },
        ]);
    });

    it('gives each marked row its Enable cell as its first cell, which the styles draw the status badge in', async () => {
        await render(rowChangesOf);

        for (const rowIndex of [0, 1]) {
            expect(rowOf(host, rowIndex).querySelector('[role="gridcell"]')?.getAttribute('col-id')).toBe(
                'dock_visible'
            );
        }
    });

    it('folds a removed rule with its group', async () => {
        await render(rowChangesOf);

        expect(shownGridRows(host).map(({ name }) => name)).toEqual(['other', 'legacy']);
    });

    it('says what a restore does to a row before its name, and shows the changed columns over it', async () => {
        await render(rowChangesOf);

        expect(rowStatusOf(host, 0)).toBe('Restore changes this condition. Changed columns: Route Code.');
        expect(rowStatusOf(host, 1)).toBe('Restore removes this condition.');

        gridCell(host, 0, 'route_code').dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
        await settle();
        expect(shownRowTooltip()).toBe('Changed columns: Route Code.');
    });

    it('never selects, edits or emits a removed rule, even in an editable grid', async () => {
        await render(rowChangesOf, { readonly: false });
        const legacy = shownGridRows(host).findIndex(({ name }) => name === 'legacy');

        gridCell(host, legacy, 'selection').querySelector<HTMLInputElement>('input[type="checkbox"]')!.click();
        await settle();
        expect(host.querySelector('[title="Delete selected"]')).toBeNull();

        gridCell(host, legacy, 'continue_flag').querySelector<HTMLInputElement>('input')!.click();
        await settle();
        expect(emitted).toEqual([]);

        // Ticking Continue on a kept rule emits the table's rules: the removed ones are not among them.
        gridCell(host, 0, 'continue_flag').querySelector<HTMLInputElement>('input')!.click();
        await settle();
        expect(emitted.at(-1)?.map((emittedRule) => emittedRule.group_name)).toEqual(['invoice', 'refund', 'other']);
    });

    it('marks each of two rules with the same name by its own change', async () => {
        const canvasRules = [
            rule('Rule', 1, { route_code: 'R1' }),
            rule('Rule', 2, { route_code: 'R2' }),
            rule('Rule', 3, { route_code: 'R3' }),
        ];
        const rules = [
            rule('Rule', 1, { route_code: 'R1' }),
            rule('Rule', 2, { route_code: 'changed' }),
            rule('Rule', 3, { route_code: 'R3' }),
        ];

        await render(
            (shownRules) =>
                cdtRowChanges(
                    conditionGroupsDiff(NodeType.CLASSIFICATION_TABLE, canvasRules, shownRules),
                    shownRules,
                    [BILLING],
                    () => null
                ),
            { rules }
        );

        expect(shownGridRows(host).map(({ mark }) => mark)).toEqual([null, 'changed', null]);
        gridCell(host, 1, 'route_code').dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
        await settle();
        expect(shownTooltipText()).toBe('Current canvas: ~~R2~~');
    });

    it('keeps its columns when only the row changes change', async () => {
        await render(rowChangesOf);
        const columns = fixture.componentInstance.columnDefs;

        fixture.componentRef.setInput(
            'rowChanges',
            gridRowChanges([[fixture.componentInstance.conditionGroups()[2], rowMark('added')]])
        );
        await settle();

        expect(fixture.componentInstance.columnDefs).toBe(columns);
        // The Billing group is folded: "other" is the only rule shown.
        expect(shownGridRows(host).map(({ mark }) => mark)).toEqual(['added']);
    });

    describe('the tooltip of each cell of a changed rule', () => {
        /**
         * "pay": its route code and the "amount" field expression changed, the "city" field kept. "new": added. "old":
         * removed. Outside any group, so no fold hides them.
         */
        const canvasRules = (): ConditionGroup[] => [
            rule('pay', 1, { field_expressions: { amount: '> 100', city: '== "Kyiv"' }, route_code: 'PAY' }),
            rule('old', 2),
        ];
        const cellRules = (): ConditionGroup[] => [
            rule('pay', 1, { field_expressions: { amount: '> 200', city: '== "Kyiv"' }, route_code: 'PAID' }),
            rule('new', 2),
        ];
        const cellRowChanges = (shownRules: ConditionGroup[]): ConditionGroupGridRowChanges | null =>
            cdtRowChanges(
                conditionGroupsDiff(NodeType.CLASSIFICATION_TABLE, canvasRules(), shownRules),
                shownRules,
                [BILLING],
                () => null
            );
        const SUMMARY = 'Changed columns: amount, Route Code.';

        async function pointAt(rowIndex: number, colId: string): Promise<void> {
            gridCell(host, rowIndex, colId).dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
            await settle();
        }

        async function focus(rowIndex: number, colId: string): Promise<void> {
            gridCell(host, rowIndex, colId).dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
            await settle();
        }

        it('shows the current value of a changed field cell, struck, and the summary over a kept one', async () => {
            await render(cellRowChanges, { rules: cellRules() });

            await pointAt(0, 'field_amount');
            expect(shownTooltipText()).toBe('Current canvas: > ~~1~~00');

            await pointAt(0, 'field_city');
            expect(shownTooltipText()).toBe(SUMMARY);

            await pointAt(0, 'route_code');
            expect(shownTooltipText()).toBe('Current canvas: PA~~Y~~');
        });

        it('switches the text as the keyboard focus moves between the cells of the rule', async () => {
            await render(cellRowChanges, { rules: cellRules() });

            await focus(0, 'route_code');
            expect(shownTooltipText()).toBe('Current canvas: PA~~Y~~');

            await focus(0, 'continue_flag');
            expect(shownTooltipText()).toBe(SUMMARY);
        });

        it.each([
            { row: 'an added', name: 'new' },
            { row: 'a removed', name: 'old' },
        ])('shows no tooltip over the cells of $row rule', async ({ name }) => {
            await render(cellRowChanges, { rules: cellRules() });
            const rowIndex = shownGridRows(host).findIndex((row) => row.name === name);

            await pointAt(rowIndex, 'route_code');
            expect(shownTooltipText()).toBeNull();
            await focus(rowIndex, 'route_code');
            expect(shownTooltipText()).toBeNull();
        });

        it('moves the open tooltip across the freeze line of frozen columns, with no new tooltip', async () => {
            await render(cellRowChanges, { rules: cellRules() });
            fixture.componentInstance.toggleFreeze('expression');
            await settle();

            await pointAt(0, 'expression');
            const tooltip = document.querySelector('.diff-field-mark__tooltip');
            expect(shownTooltipText()).toBe(SUMMARY);

            await pointAt(0, 'route_code');
            expect(shownTooltipText()).toBe('Current canvas: PA~~Y~~');
            expect(document.querySelector('.diff-field-mark__tooltip')).toBe(tooltip);
        });

        it('shows no tooltip over a cell in the live editor', async () => {
            await render(null, { rules: cellRules() });

            await pointAt(0, 'field_amount');
            await focus(0, 'route_code');

            expect(shownTooltipText()).toBeNull();
        });
    });

    describe('a cell with a tooltip of its own', () => {
        const PROMPT: PromptConfig = {
            prompt_text: 'Classify the request',
            llm_config: null,
            output_schema: null,
            result_variable: 'category',
            variable_mappings: {},
        };
        /** Continue is ticked and the route code leads nowhere: the Route Code cell shows its status icon. */
        const canvasRules = (): ConditionGroup[] => [
            rule('pay', 1, { route_code: 'PAY', continue_flag: true, prompt_id: 'billing' }),
        ];
        const ownTooltipRules = (): ConditionGroup[] => [
            rule('pay', 1, { route_code: 'PAID', continue_flag: true, prompt_id: 'refunds' }),
        ];
        const ownTooltipRowChanges = (shownRules: ConditionGroup[]): ConditionGroupGridRowChanges | null =>
            cdtRowChanges(
                conditionGroupsDiff(NodeType.CLASSIFICATION_TABLE, canvasRules(), shownRules),
                shownRules,
                [],
                () => null
            );

        async function pointAt(element: Element): Promise<void> {
            element.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
            await settle();
        }

        it.each([
            {
                cell: 'Route Code',
                colId: 'route_code',
                own: '.cdt-route-code-cell__status',
                rest: '.cdt-route-code-cell__code',
                tooltip: 'Current canvas: PA~~Y~~',
            },
            {
                cell: 'Prompt ID',
                colId: 'prompt_id',
                own: '.open-in-library-btn',
                rest: '.chip-id',
                tooltip: 'Current canvas: ~~billing~~',
            },
        ])(
            'shows only its own tooltip over the $cell trigger, the diff tooltip elsewhere in the cell',
            async ({ colId, own, rest, tooltip }) => {
                await render(ownTooltipRowChanges, { rules: ownTooltipRules(), prompts: { refunds: PROMPT } });
                const cell = gridCell(host, 0, colId);
                const trigger = cell.querySelector(own)!;

                await pointAt(cell.querySelector(rest)!);
                expect(shownTooltipText()).toBe(tooltip);

                await pointAt(trigger.firstElementChild ?? trigger);
                expect(shownTooltipText()).toBeNull();

                await pointAt(cell.querySelector(rest)!);
                expect(shownTooltipText()).toBe(tooltip);

                trigger.dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
                await settle();
                expect(shownTooltipText()).toBeNull();
            }
        );
    });

    it.each([
        { key: 'a b', canvas: '> 1', version: '> 5', tooltip: 'Current canvas: > ~~1~~' },
        { key: 'a.b', canvas: '== 2', version: '== 3', tooltip: 'Current canvas: == ~~2~~' },
    ])('shows the tooltip of the cell of field key $key', async ({ key, canvas, version, tooltip }) => {
        const canvasRules = [rule('pay', 1, { field_expressions: { [key]: canvas } })];
        const rules = [rule('pay', 1, { field_expressions: { [key]: version } })];

        await render(
            (shownRules) =>
                cdtRowChanges(
                    conditionGroupsDiff(NodeType.CLASSIFICATION_TABLE, canvasRules, shownRules),
                    shownRules,
                    [],
                    () => null
                ),
            { rules }
        );
        gridCell(host, 0, `field_${key}`).dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
        await settle();

        expect(shownTooltipText()).toBe(tooltip);
    });

    it('shows the plain table outside the Changes tab', async () => {
        await render(null);
        await expandBilling();

        expect(shownGridRows(host)).toEqual([
            { name: 'invoice', mark: null },
            { name: 'refund', mark: null },
            { name: 'other', mark: null },
        ]);
    });
});
