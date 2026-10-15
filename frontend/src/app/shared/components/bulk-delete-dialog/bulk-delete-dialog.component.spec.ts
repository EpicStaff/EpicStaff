import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { BulkDeleteItem, BulkDeletePreviewGroup, BulkDeletePreviewItem } from '@shared/models';
import { describe, expect, it, vi } from 'vitest';

import { BulkDeleteDialogComponent, BulkDeleteDialogData } from './bulk-delete-dialog.component';

function renderFixture(groups: BulkDeletePreviewGroup[]): ComponentFixture<BulkDeleteDialogComponent> {
    const data: BulkDeleteDialogData = { groups };
    TestBed.configureTestingModule({
        imports: [BulkDeleteDialogComponent],
        providers: [
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

function rowNames(list: Element | null): string[] {
    return Array.from(list?.querySelectorAll(':scope > .item') ?? []).map(
        (row) => row.querySelector('.item-name')?.textContent?.trim() ?? ''
    );
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

describe('BulkDeleteDialogComponent', () => {
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

        expect(element.querySelector('.hint-message')?.textContent?.trim()).toBe(
            "2 of 3 will be deleted. This can't be undone."
        );
    });

    it('keeps the plain warning when nothing is blocked', () => {
        const element = render([
            flowsGroup({
                deletable: [
                    { id: 1, name: 'Alpha', usage: [] },
                    { id: 2, name: 'Beta', usage: [] },
                ],
            }),
        ]);

        expect(element.querySelector('.hint-message')?.textContent?.trim()).toBe("This can't be undone.");
    });

    it('lists blocked items in the same list, right after the items that will be deleted', () => {
        const element = render([
            flowsGroup({
                deletable: [{ id: 1, name: 'Alpha', usage: [] }],
                blocked: [{ id: 3, name: 'Gamma' }],
            }),
        ]);

        const rows = Array.from(element.querySelectorAll('.item-list > .item'));
        expect(rows.map((row) => row.querySelector('.item-name')?.textContent?.trim())).toEqual(['Alpha', 'Gamma']);
        expect(rows[0].parentElement).toBe(rows[1].parentElement);

        const blockedRow = rows[1];
        expect(blockedRow.classList).toContain('item--blocked');
        expect(blockedRow.querySelector('.blocked-label')?.textContent?.trim()).toBe("Can't be deleted.");
    });

    it('marks deletable items that are in use and shows their usage', () => {
        const element = render([
            flowsGroup({
                deletable: [
                    {
                        id: 1,
                        name: 'Alpha',
                        usage: [{ label: 'agent', count: 1, sampleNames: ['Support bot'], hasMore: false }],
                    },
                    { id: 2, name: 'Beta', usage: [] },
                ],
            }),
        ]);

        const rows = Array.from(element.querySelectorAll('.item-list > .item'));
        expect(rows[0].classList).toContain('item--in-use');
        expect(rows[0].querySelector('.usage-line')?.textContent?.trim()).toBe('Used in 1 agent: Support bot');
        expect(rows[1].classList).not.toContain('item--in-use');
        expect(rows[1].classList).not.toContain('item--blocked');
    });

    describe('long lists', () => {
        it('shows the first 5 plain rows and toggles the rest', () => {
            const fixture = renderFixture([flowsGroup({ deletable: plainItems(20) })]);
            const element = fixture.nativeElement as HTMLElement;
            const list = element.querySelector('.item-list');
            const toggle = element.querySelector<HTMLButtonElement>('.item-list .show-more-button')!;

            expect(rowNames(list)).toEqual(['Flow 1', 'Flow 2', 'Flow 3', 'Flow 4', 'Flow 5']);
            expect(toggle.textContent?.trim()).toBe('Show 15 more');
            expect(toggle.getAttribute('aria-expanded')).toBe('false');

            toggle.click();
            fixture.detectChanges();
            expect(rowNames(list)).toHaveLength(20);
            expect(toggle.textContent?.trim()).toBe('Show less');
            expect(toggle.getAttribute('aria-expanded')).toBe('true');

            toggle.click();
            fixture.detectChanges();
            expect(rowNames(list)).toHaveLength(5);
        });

        it('never hides in-use or blocked rows while collapsed', () => {
            const inUse: BulkDeletePreviewItem = {
                id: 100,
                name: 'Used flow',
                usage: [{ label: 'flow', count: 1, sampleNames: ['Parent'], hasMore: false }],
            };
            const element = render([
                flowsGroup({
                    deletable: [...plainItems(8), inUse],
                    blocked: [{ id: 200, name: 'Blocked flow' }],
                }),
            ]);

            expect(rowNames(element.querySelector('.item-list'))).toEqual([
                'Flow 1',
                'Flow 2',
                'Flow 3',
                'Flow 4',
                'Flow 5',
                'Used flow',
                'Blocked flow',
            ]);
            expect(element.querySelector('.item-list .show-more-button')?.textContent?.trim()).toBe('Show 3 more');
        });

        it('shows no toggle when there are 5 or fewer plain rows', () => {
            const element = render([flowsGroup({ deletable: plainItems(5) })]);

            expect(rowNames(element.querySelector('.item-list'))).toHaveLength(5);
            expect(element.querySelector('.show-more-button')).toBeNull();
        });

        it('collapses the already-deleted list the same way', () => {
            const fixture = renderFixture([flowsGroup({ deletable: plainItems(1), notFound: namedItems(8, 50) })]);
            const element = fixture.nativeElement as HTMLElement;
            const list = element.querySelector('.sub-section .item-list');
            const toggle = element.querySelector<HTMLButtonElement>('.sub-section .show-more-button')!;

            expect(rowNames(list)).toHaveLength(5);
            expect(toggle.textContent?.trim()).toBe('Show 3 more');

            toggle.click();
            fixture.detectChanges();
            expect(rowNames(list)).toHaveLength(8);
        });

        it('flips the toggle chevron when the list is expanded', () => {
            const fixture = renderFixture([flowsGroup({ deletable: plainItems(8) })]);
            const element = fixture.nativeElement as HTMLElement;
            const toggle = element.querySelector<HTMLButtonElement>('.show-more-button')!;

            expect(toggle.querySelector('app-svg-icon.show-more-icon')).not.toBeNull();
            expect(toggle.classList).not.toContain('show-more-button--expanded');

            toggle.click();
            fixture.detectChanges();
            expect(toggle.classList).toContain('show-more-button--expanded');
        });

        it('collapses from the sixth plain row on', () => {
            const element = render([flowsGroup({ deletable: plainItems(6) })]);

            expect(rowNames(element.querySelector('.item-list'))).toHaveLength(5);
            expect(element.querySelector('.show-more-button')?.textContent?.trim()).toBe('Show 1 more');
        });

        it('expands the deleted and already-deleted lists of one group independently', () => {
            const fixture = renderFixture([flowsGroup({ deletable: plainItems(7), notFound: namedItems(7, 50) })]);
            const element = fixture.nativeElement as HTMLElement;
            const deletableList = element.querySelector('.group > .item-list');
            const notFoundList = element.querySelector('.sub-section .item-list');

            element.querySelector<HTMLButtonElement>('.group > .item-list .show-more-button')!.click();
            fixture.detectChanges();

            expect(rowNames(deletableList)).toHaveLength(7);
            expect(rowNames(notFoundList)).toHaveLength(5);
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
        expect(element.querySelector('.hint-message')).toBeNull();
        expect(element.querySelectorAll('.item-list > .item--blocked')).toHaveLength(2);
        expect(element.querySelector('.confirm-button')).toBeNull();
        expect(element.querySelector('.close-text-button')?.textContent?.trim()).toBe('Close');
    });

    describe('group cards', () => {
        function headings(element: HTMLElement): string[] {
            return Array.from(element.querySelectorAll('.group > .group-heading')).map(
                (heading) => heading.textContent?.replace(/\s+/g, ' ').trim() ?? ''
            );
        }

        it('heads a single group with its name and selected-item count', () => {
            const element = render([
                flowsGroup({
                    deletable: plainItems(2),
                    blocked: [{ id: 3, name: 'Gamma' }],
                    notFound: namedItems(1, 4),
                }),
            ]);

            expect(element.querySelectorAll('.group')).toHaveLength(1);
            expect(headings(element)).toEqual(['Flows · 4']);
        });

        it('gives every group its own card and header', () => {
            const element = render([
                flowsGroup({ deletable: plainItems(2) }),
                {
                    label: { singular: 'LLM config', plural: 'LLM configs' },
                    deletable: plainItems(3, 10),
                    blocked: [],
                    notFound: [],
                },
            ]);

            expect(headings(element)).toEqual(['Flows · 2', 'LLM configs · 3']);
        });
    });
});
