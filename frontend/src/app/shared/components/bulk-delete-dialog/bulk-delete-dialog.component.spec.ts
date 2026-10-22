import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { BulkDeleteItem, BulkDeletePreviewGroup, BulkDeletePreviewItem } from '@shared/models';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { BulkDeleteDialogComponent, BulkDeleteDialogData } from './bulk-delete-dialog.component';

// The confirm `app-button` collapses on overflow and observes its size; jsdom has no ResizeObserver.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
afterEach(() => vi.unstubAllGlobals());

function renderFixture(groups: BulkDeletePreviewGroup[]): ComponentFixture<BulkDeleteDialogComponent> {
    const data: BulkDeleteDialogData = { groups };
    TestBed.configureTestingModule({
        imports: [BulkDeleteDialogComponent],
        providers: [
            // The section chevrons are `app-icon`s, which load their SVG over HTTP.
            provideHttpClient(),
            provideHttpClientTesting(),
            { provide: DIALOG_DATA, useValue: data },
            { provide: DialogRef, useValue: { close: vi.fn() } },
        ],
    });
    const fixture = TestBed.createComponent(BulkDeleteDialogComponent);
    fixture.detectChanges();
    return fixture;
}

function render(groups: BulkDeletePreviewGroup[]): HTMLElement {
    return renderFixture(groups).nativeElement as HTMLElement;
}

function plainItems(count: number, firstId = 1): BulkDeletePreviewItem[] {
    return Array.from({ length: count }, (_, index) => ({
        id: firstId + index,
        name: `Flow ${firstId + index}`,
        usage: [],
    }));
}

function namedItems(count: number, firstId: number): BulkDeleteItem[] {
    return Array.from({ length: count }, (_, index) => ({ id: firstId + index, name: `Gone ${firstId + index}` }));
}

/** An in-use item with two usage lines, and the tooltip it gets: one line per usage. */
const TWO_LINE_USAGE_ITEM: BulkDeletePreviewItem = {
    id: 1,
    name: 'Alpha',
    usage: [
        { label: 'flow', count: 1, sampleNames: ['Customer onboarding'], hasMore: false },
        { label: 'agents', count: 3, sampleNames: ['Support bot', 'Triage'], hasMore: true },
    ],
};
const TWO_LINE_USAGE_TOOLTIP = 'Used in 1 flow: Customer onboarding\nUsed in 3 agents: Support bot, Triage and more';

function inUseItem(id: number, name: string): BulkDeletePreviewItem {
    return { id, name, usage: [{ label: 'flow', count: 1, sampleNames: ['Parent'], hasMore: false }] };
}

function flowsGroup(overrides: Partial<BulkDeletePreviewGroup>): BulkDeletePreviewGroup {
    return {
        label: { singular: 'flow', plural: 'flows' },
        deletable: [],
        blocked: [],
        notFound: [],
        ...overrides,
    };
}

function sections(element: HTMLElement): HTMLElement[] {
    return Array.from(element.querySelectorAll<HTMLElement>('section.breakdown'));
}

function header(section: HTMLElement): HTMLButtonElement {
    return section.querySelector<HTMLButtonElement>('.breakdown-header')!;
}

/** The header's title and count, e.g. "Flows 3". */
function headerText(section: HTMLElement): string {
    const title = header(section).querySelector('.breakdown-title')?.textContent?.trim();
    const total = header(section).querySelector('.breakdown-total')?.textContent?.trim();
    return `${title} ${total}`;
}

function rows(section: HTMLElement): HTMLElement[] {
    return Array.from(section.querySelectorAll<HTMLElement>('.breakdown-list > .item'));
}

function rowNames(section: HTMLElement): string[] {
    return rows(section).map((row) => row.querySelector('.item-name')?.textContent?.trim() ?? '');
}

function isOpen(section: HTMLElement): boolean {
    return section.querySelector('.grid-collapsible')!.classList.contains('expanded');
}

describe('BulkDeleteDialogComponent', () => {
    describe('recycle bin summary', () => {
        const summary = (groups: BulkDeletePreviewGroup[]): string | undefined =>
            render(groups).querySelector('.summary-message')?.textContent?.trim();

        it('says the items move to the recycle bin when every group is a recycle-bin group', () => {
            const text = summary([flowsGroup({ recycleBin: { retentionDays: 30 }, deletable: plainItems(2) })]);

            expect(text).toBe('They move to the recycle bin, where you can restore them for 30 days.');
        });

        it('prefixes the deleted-of-total count when some items are blocked', () => {
            const text = summary([
                flowsGroup({
                    recycleBin: { retentionDays: 30 },
                    deletable: plainItems(2),
                    blocked: [{ id: 3, name: 'Gamma' }],
                }),
            ]);

            expect(text).toBe(
                '2 of 3 will be deleted. They move to the recycle bin, where you can restore them for 30 days.'
            );
        });

        it('uses the singular wording for a single deletable item', () => {
            const text = summary([flowsGroup({ recycleBin: { retentionDays: 1 }, deletable: plainItems(1) })]);

            expect(text).toBe('It moves to the recycle bin, where you can restore it for 1 day.');
        });

        it('omits the duration when the retention is unknown', () => {
            const text = summary([flowsGroup({ recycleBin: { retentionDays: null }, deletable: plainItems(1) })]);

            expect(text).toBe('It moves to the recycle bin, where you can restore it.');
        });

        it('ignores groups with nothing deletable when deciding', () => {
            const text = summary([
                flowsGroup({ recycleBin: { retentionDays: 7 }, deletable: plainItems(2) }),
                flowsGroup({ blocked: [{ id: 9, name: 'Blocked' }] }),
            ]);

            expect(text).toBe(
                '2 of 3 will be deleted. They move to the recycle bin, where you can restore them for 7 days.'
            );
        });

        it('keeps the permanent warning when a group with deletable items is not a recycle-bin group', () => {
            const text = summary([
                flowsGroup({ recycleBin: { retentionDays: 30 }, deletable: plainItems(1) }),
                flowsGroup({ deletable: plainItems(1, 10) }),
            ]);

            expect(text).toBe("This can't be undone.");
        });

        it('keeps the permanent warning for a group without the marker', () => {
            expect(summary([flowsGroup({ deletable: plainItems(2) })])).toBe("This can't be undone.");
        });
    });

    it('says how many of the selected items will actually be deleted when some are blocked', () => {
        const element = render([
            flowsGroup({
                deletable: [
                    { id: 1, name: 'Alpha', usage: [] },
                    { id: 2, name: 'Beta', usage: [] },
                ],
                blocked: [{ id: 3, name: 'Gamma' }],
            }),
        ]);

        expect(element.querySelector('.summary-message')?.textContent?.trim()).toBe(
            "2 of 3 will be deleted. This can't be undone."
        );
    });

    it('shows a single item without usage as one plain line, without a section', () => {
        const element = render([flowsGroup({ deletable: plainItems(1) })]);

        expect(element.querySelector('.dialog-title')?.textContent?.trim()).toBe('Delete "Flow 1"?');
        expect(element.querySelector('.summary-message')?.textContent?.trim()).toBe("This can't be undone.");
        expect(sections(element)).toHaveLength(0);
    });

    describe('rows', () => {
        it('lists blocked rows first, then in-use rows, then the rest, in one list', () => {
            const element = render([
                flowsGroup({
                    deletable: [
                        { id: 1, name: 'Plain A', usage: [] },
                        inUseItem(2, 'Used B'),
                        { id: 3, name: 'Plain C', usage: [] },
                        inUseItem(4, 'Used D'),
                    ],
                    blocked: [
                        { id: 5, name: 'Blocked E' },
                        { id: 6, name: 'Blocked F' },
                    ],
                }),
            ]);

            const [section] = sections(element);
            expect(rowNames(section)).toEqual(['Blocked E', 'Blocked F', 'Used B', 'Used D', 'Plain A', 'Plain C']);
            expect(section.querySelectorAll('.breakdown-list')).toHaveLength(1);
        });

        it('keeps each row to one line: the name, and a label on blocked and in-use rows only', () => {
            const element = render([
                flowsGroup({
                    deletable: [inUseItem(1, 'Used'), { id: 2, name: 'Plain', usage: [] }],
                    blocked: [{ id: 3, name: 'Blocked' }],
                }),
            ]);

            const [blockedRow, inUseRow, plainRow] = rows(sections(element)[0]);
            expect(blockedRow.classList).toContain('item--blocked');
            expect(blockedRow.querySelector('.item-label')?.textContent?.trim()).toBe('Will not be deleted');
            expect(inUseRow.classList).toContain('item--in-use');
            expect(inUseRow.querySelector('.item-label')?.textContent?.trim()).toBe('In use');
            expect(plainRow.querySelector('.item-label')).toBeNull();
            expect(plainRow.classList).not.toContain('item--in-use');
            expect(plainRow.classList).not.toContain('item--blocked');
            // The details live in the tooltips now: no icons, reason paragraph or usage lines in the rows.
            expect(sections(element)[0].querySelector('.breakdown-list app-svg-icon')).toBeNull();
            expect(sections(element)[0].querySelector('.breakdown-list p, .breakdown-list ul ul')).toBeNull();
            expect(element.textContent).not.toContain('Used in');
        });

        it('lists every row, with no "Show more" toggle', () => {
            const element = render([flowsGroup({ deletable: plainItems(20) })]);

            expect(rowNames(sections(element)[0])).toHaveLength(20);
            expect(element.textContent).not.toContain('Show');
        });
    });

    describe('sections', () => {
        it('heads a group with its name and the count of its deletable and blocked items', () => {
            const element = render([
                flowsGroup({
                    deletable: plainItems(2),
                    blocked: [{ id: 3, name: 'Gamma' }],
                    notFound: namedItems(1, 4),
                }),
            ]);

            const [itemsSection] = sections(element);
            expect(headerText(itemsSection)).toBe('Flows 3');
            expect(itemsSection.querySelector('.breakdown-total')?.textContent?.trim()).toBe('3');
        });

        it('gives every group its own section', () => {
            const element = render([
                flowsGroup({ deletable: plainItems(2) }),
                {
                    label: { singular: 'LLM config', plural: 'LLM configs' },
                    deletable: plainItems(3, 10),
                    blocked: [],
                    notFound: [],
                },
            ]);

            expect(sections(element).map(headerText)).toEqual(['Flows 2', 'LLM configs 3']);
        });

        it('starts item sections open, with the header controlling the list', () => {
            const element = render([flowsGroup({ deletable: plainItems(3) })]);

            const [section] = sections(element);
            const list = section.querySelector('.breakdown-list')!;
            expect(isOpen(section)).toBe(true);
            expect(header(section).getAttribute('aria-expanded')).toBe('true');
            expect(header(section).getAttribute('aria-controls')).toBe(list.id);
            expect(list.id).not.toBe('');
        });

        it('collapses and reopens a section from its header', () => {
            const fixture = renderFixture([flowsGroup({ deletable: plainItems(3) })]);
            const [section] = sections(fixture.nativeElement as HTMLElement);

            header(section).click();
            fixture.detectChanges();
            expect(isOpen(section)).toBe(false);
            expect(header(section).getAttribute('aria-expanded')).toBe('false');
            expect(section.querySelector('.breakdown-chevron')!.classList).toContain('collapsed');

            header(section).click();
            fixture.detectChanges();
            expect(isOpen(section)).toBe(true);
            expect(section.querySelector('.breakdown-chevron')!.classList).not.toContain('collapsed');
        });

        it('toggles each section on its own', () => {
            const fixture = renderFixture([
                flowsGroup({ deletable: plainItems(2) }),
                {
                    label: { singular: 'LLM config', plural: 'LLM configs' },
                    deletable: plainItems(2, 10),
                    blocked: [],
                    notFound: [],
                },
            ]);
            const [flowsSection, configsSection] = sections(fixture.nativeElement as HTMLElement);

            header(flowsSection).click();
            fixture.detectChanges();

            expect(isOpen(flowsSection)).toBe(false);
            expect(isOpen(configsSection)).toBe(true);
            expect(header(flowsSection).getAttribute('aria-controls')).not.toBe(
                header(configsSection).getAttribute('aria-controls')
            );
        });
    });

    describe('row tooltips', () => {
        /** The tooltip inside the row and the element hosting it, or null when the row has none. */
        function rowTooltip(
            fixture: ComponentFixture<BulkDeleteDialogComponent>,
            row: HTMLElement
        ): { host: HTMLElement; tooltip: MatTooltip } | null {
            const debugElement = fixture.debugElement
                .queryAll(By.directive(MatTooltip))
                .find((candidate) => row.contains(candidate.nativeElement));
            return debugElement
                ? { host: debugElement.nativeElement, tooltip: debugElement.injector.get(MatTooltip) }
                : null;
        }

        function tooltipOf(fixture: ComponentFixture<BulkDeleteDialogComponent>, row: HTMLElement): string | null {
            return rowTooltip(fixture, row)?.tooltip.message ?? null;
        }

        it('tells why a blocked row cannot be deleted', () => {
            const fixture = renderFixture([flowsGroup({ deletable: plainItems(1), blocked: [{ id: 3, name: 'B' }] })]);

            const blockedRow = rows(sections(fixture.nativeElement as HTMLElement)[0])[0];
            expect(tooltipOf(fixture, blockedRow)).toBe("Used somewhere you don't have access to.");
        });

        it('lists the usage of an in-use row, one line each', () => {
            const fixture = renderFixture([flowsGroup({ deletable: [TWO_LINE_USAGE_ITEM, ...plainItems(1, 2)] })]);

            const inUseRow = rows(sections(fixture.nativeElement as HTMLElement)[0])[0];
            expect(tooltipOf(fixture, inUseRow)).toBe(TWO_LINE_USAGE_TOOLTIP);
            expect(rowTooltip(fixture, inUseRow)!.tooltip.tooltipClass).toBe('multiline-tooltip');
        });

        it('puts the tooltip on the label, so it points at the label and not at the name', () => {
            const fixture = renderFixture([
                flowsGroup({ deletable: [TWO_LINE_USAGE_ITEM, ...plainItems(1, 2)], blocked: [{ id: 3, name: 'B' }] }),
            ]);

            const [blockedRow, inUseRow] = rows(sections(fixture.nativeElement as HTMLElement)[0]);
            for (const row of [blockedRow, inUseRow]) {
                expect(rowTooltip(fixture, row)!.host).toBe(row.querySelector('.item-label'));
            }
        });

        it('gives plain and already-deleted rows no tooltip', () => {
            const fixture = renderFixture([
                flowsGroup({ deletable: [inUseItem(1, 'Used'), ...plainItems(1, 2)], notFound: namedItems(1, 50) }),
            ]);
            const [itemsSection, notFoundSection] = sections(fixture.nativeElement as HTMLElement);

            expect(tooltipOf(fixture, rows(itemsSection)[1])).toBeNull();
            expect(tooltipOf(fixture, rows(notFoundSection)[0])).toBeNull();
        });

        it('makes only the labels of rows with a tooltip focusable', () => {
            const element = render([
                flowsGroup({
                    deletable: [inUseItem(1, 'Used'), ...plainItems(2, 2)],
                    blocked: [{ id: 9, name: 'Blocked' }],
                    notFound: namedItems(1, 50),
                }),
            ]);
            const [itemsSection, notFoundSection] = sections(element);
            const focusableIn = (row: HTMLElement): (string | null)[] =>
                Array.from(row.querySelectorAll('[tabindex]'), (focusable) =>
                    focusable.classList.contains('item-label') ? focusable.getAttribute('tabindex') : 'not the label'
                );

            expect(rows(itemsSection).map(focusableIn)).toEqual([['0'], ['0'], [], []]);
            expect(rows(itemsSection).some((row) => row.hasAttribute('tabindex'))).toBe(false);
            expect(focusableIn(rows(notFoundSection)[0])).toEqual([]);
        });

        it('exposes the tooltip text of blocked and in-use rows to screen readers', () => {
            const fixture = renderFixture([
                flowsGroup({
                    deletable: [TWO_LINE_USAGE_ITEM, ...plainItems(1, 2)],
                    blocked: [{ id: 3, name: 'B' }],
                }),
            ]);
            // The tooltip describes its host after the next render.
            TestBed.inject(ApplicationRef).tick();

            const description = (row: HTMLElement): string | null | undefined => {
                const describedById = row.querySelector('.item-label')?.getAttribute('aria-describedby');
                return describedById ? document.getElementById(describedById)?.textContent : null;
            };
            const [blockedRow, inUseRow] = rows(sections(fixture.nativeElement as HTMLElement)[0]);
            expect(description(blockedRow)).toBe("Used somewhere you don't have access to.");
            expect(description(inUseRow)).toBe(TWO_LINE_USAGE_TOOLTIP);
        });
    });

    describe('usage banner', () => {
        const banners = (element: HTMLElement): HTMLElement[] =>
            Array.from(element.querySelectorAll<HTMLElement>('app-hint-message'));

        it('is shown once, under the summary and above the sections, when items in several groups are in use', () => {
            const element = render([
                flowsGroup({ deletable: [inUseItem(1, 'Used flow'), ...plainItems(1, 2)] }),
                {
                    label: { singular: 'LLM config', plural: 'LLM configs' },
                    deletable: [inUseItem(10, 'Used config')],
                    blocked: [],
                    notFound: [],
                },
            ]);

            expect(banners(element)).toHaveLength(1);
            const [banner] = banners(element);
            expect(banner.textContent?.trim()).toBe('Where these are used, the reference will be removed.');
            expect(banner.querySelector('.hint-message--warning')).not.toBeNull();
            const summary = element.querySelector('.summary-message')!;
            expect(summary.compareDocumentPosition(banner) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
            expect(
                banner.compareDocumentPosition(sections(element)[0]) & Node.DOCUMENT_POSITION_FOLLOWING
            ).toBeTruthy();
            expect(sections(element).some((section) => section.querySelector('app-hint-message'))).toBe(false);
        });

        it('is not shown when nothing that will be deleted is in use', () => {
            const element = render([
                flowsGroup({
                    deletable: plainItems(2),
                    blocked: [{ id: 9, name: 'Blocked' }],
                    notFound: namedItems(1, 50),
                }),
            ]);

            expect(banners(element)).toHaveLength(0);
        });
    });

    describe('already deleted', () => {
        it('is its own section, closed at first, counting the items that no longer exist', () => {
            const element = render([flowsGroup({ deletable: plainItems(2), notFound: namedItems(3, 50) })]);

            const [itemsSection, notFoundSection] = sections(element);
            expect(headerText(itemsSection)).toBe('Flows 2');
            expect(headerText(notFoundSection)).toBe('Already deleted 3');
            expect(notFoundSection.classList).toContain('breakdown--neutral');
            expect(isOpen(notFoundSection)).toBe(false);
            expect(header(notFoundSection).getAttribute('aria-expanded')).toBe('false');
            expect(notFoundSection.querySelector('.section-note')?.textContent?.trim()).toBe(
                'These no longer exist and were removed from the list.'
            );
        });

        it('opens to list the items that no longer exist', () => {
            const fixture = renderFixture([flowsGroup({ deletable: plainItems(1), notFound: namedItems(2, 50) })]);
            const notFoundSection = sections(fixture.nativeElement as HTMLElement)[1];

            header(notFoundSection).click();
            fixture.detectChanges();

            expect(isOpen(notFoundSection)).toBe(true);
            expect(rowNames(notFoundSection)).toEqual(['Gone 50', 'Gone 51']);
        });

        it('comes after every group, naming its group when the dialog holds several', () => {
            const element = render([
                flowsGroup({ deletable: plainItems(1), notFound: namedItems(2, 40) }),
                {
                    label: { singular: 'LLM config', plural: 'LLM configs' },
                    deletable: plainItems(1, 10),
                    blocked: [],
                    notFound: namedItems(1, 50),
                },
            ]);

            expect(sections(element).map(headerText)).toEqual([
                'Flows 1',
                'LLM configs 1',
                'Already deleted flows 2',
                'Already deleted LLM configs 1',
            ]);
        });
    });

    describe('confirm button', () => {
        it('is the shared red button reading just "Delete", whatever the count', () => {
            const element = render([flowsGroup({ deletable: plainItems(7) })]);

            const confirm = element.querySelector('app-button.confirm-button');
            expect(confirm?.textContent?.trim()).toBe('Delete');
            expect(confirm?.querySelector('button')?.classList).toContain('btn-danger');
        });

        it('confirms with true and cancels with false', () => {
            const fixture = renderFixture([flowsGroup({ deletable: plainItems(2) })]);
            const element = fixture.nativeElement as HTMLElement;
            const dialogRef = TestBed.inject(DialogRef);

            element.querySelector<HTMLButtonElement>('.confirm-button button')!.click();
            element.querySelector<HTMLButtonElement>('.cancel-button')!.click();

            expect(dialogRef.close).toHaveBeenNthCalledWith(1, true);
            expect(dialogRef.close).toHaveBeenNthCalledWith(2, false);
        });
    });

    it('shows blocked rows and only a Close button when nothing can be deleted', () => {
        const element = render([
            flowsGroup({
                blocked: [
                    { id: 1, name: 'Alpha' },
                    { id: 2, name: 'Beta' },
                ],
            }),
        ]);

        expect(element.querySelector('.dialog-title')?.textContent?.trim()).toBe('Nothing can be deleted');
        expect(element.querySelector('.summary-message')).toBeNull();
        expect(rows(sections(element)[0]).filter((row) => row.classList.contains('item--blocked'))).toHaveLength(2);
        expect(element.querySelector('.confirm-button')).toBeNull();
        expect(element.querySelector('.close-text-button')?.textContent?.trim()).toBe('Close');
    });
});
