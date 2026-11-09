import { OverlayContainer } from '@angular/cdk/overlay';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { SelectDropdownComponent } from './select-dropdown.component';
import { SelectDropdownListItem } from './select-dropdown.model';

function open(items: SelectDropdownListItem[]): {
    fixture: ComponentFixture<SelectDropdownComponent>;
    panel: HTMLElement;
} {
    const fixture = TestBed.createComponent(SelectDropdownComponent);
    fixture.componentRef.setInput('items', items);
    fixture.componentRef.setInput('selectionMode', 'single');
    fixture.detectChanges();
    fixture.componentInstance.openDropdown();
    fixture.detectChanges();
    return { fixture, panel: TestBed.inject(OverlayContainer).getContainerElement() };
}

/** The list top to bottom: a section title as `# title`, an option as its name. */
const outline = (panel: HTMLElement): string[] =>
    Array.from(panel.querySelectorAll('.select-dropdown__list > *'), (element) =>
        element.classList.contains('select-dropdown__section-title')
            ? `# ${element.textContent?.trim()}`
            : (element.textContent?.trim() ?? '')
    );

function search(fixture: ComponentFixture<SelectDropdownComponent>, panel: HTMLElement, term: string): void {
    const input = panel.querySelector<HTMLInputElement>('input[type="search"]')!;
    input.value = term;
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
}

const GROUPED: SelectDropdownListItem[] = [
    { name: 'CRM access', value: 1, group: 'Sales' },
    { name: 'Pricing', value: 2, group: 'Sales' },
    { name: 'Tickets', value: 3, group: 'Support' },
    { name: 'Notes', value: 4, group: 'No group' },
];

// jsdom has no ResizeObserver; the open panel only needs it to exist. Without this stub the
// spec passed only when an earlier spec in the same worker left a ResizeObserver behind.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
afterEach(() => vi.unstubAllGlobals());

describe('SelectDropdownComponent list sections', () => {
    it('shows a title above each run of items of the same group', () => {
        const { panel } = open(GROUPED);

        expect(outline(panel)).toEqual([
            '# Sales',
            'CRM access',
            'Pricing',
            '# Support',
            'Tickets',
            '# No group',
            'Notes',
        ]);
    });

    it('while searching, titles only the groups that still have a match', () => {
        const { fixture, panel } = open(GROUPED);

        search(fixture, panel, 'ti');

        expect(outline(panel)).toEqual(['# Support', 'Tickets']);
    });

    it('shows no titles when the items have no group', () => {
        const { panel } = open([
            { name: 'CRM access', value: 1 },
            { name: 'Tickets', value: 2 },
        ]);

        expect(outline(panel)).toEqual(['CRM access', 'Tickets']);
    });

    it('keeps titles out of the tab order', () => {
        const { panel } = open(GROUPED);

        const titles = Array.from(panel.querySelectorAll<HTMLElement>('.select-dropdown__section-title'));

        expect(titles.length).toBe(3);
        expect(titles.every((title) => title.tabIndex < 0)).toBe(true);
    });
});
