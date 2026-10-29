import { OverlayContainer } from '@angular/cdk/overlay';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { LabelColor, LabelTreeNode } from '@shared/models';
import { LABELS_STORE } from '@shared/services';
import { of } from 'rxjs';

import { LabelDropdownComponent } from './label-dropdown.component';

function label(id: number, name: string): LabelTreeNode {
    return {
        id,
        name,
        parent: null,
        full_path: name,
        created_at: '',
        metadata: { color: LabelColor.Purple },
        children: [],
    };
}

// The multi-mode footer buttons collapse on overflow through ResizeObserver, which jsdom lacks.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const SALES = label(1, 'Sales');
const SUPPORT = label(2, 'Support');

function open(
    mode: 'multi' | 'single',
    selectedLabelIds: number[] = [],
    labels: LabelTreeNode[] = [SALES, SUPPORT]
): { fixture: ComponentFixture<LabelDropdownComponent>; panel: HTMLElement; emitted: number[][] } {
    TestBed.configureTestingModule({
        providers: [
            {
                provide: LABELS_STORE,
                useValue: {
                    labels: signal(labels),
                    labelTree: signal(labels),
                    loadLabels: () => of([]),
                    createLabel: (name: string) => of(label(3, name)),
                },
            },
        ],
    });
    const fixture = TestBed.createComponent(LabelDropdownComponent);
    fixture.componentRef.setInput('mode', mode);
    fixture.componentRef.setInput('emptyOptionLabel', 'Ungrouped');
    fixture.componentRef.setInput('selectedLabelIds', selectedLabelIds);
    const emitted: number[][] = [];
    fixture.componentInstance.selectionChange.subscribe((ids) => emitted.push(ids));
    fixture.detectChanges();
    fixture.componentInstance.open();
    fixture.detectChanges();
    return { fixture, panel: TestBed.inject(OverlayContainer).getContainerElement(), emitted };
}

/** `count` labels named Group 1, Group 2… */
const manyLabels = (count: number): LabelTreeNode[] =>
    Array.from({ length: count }, (_, index) => label(10 + index, `Group ${index + 1}`));

function pressEscape(): void {
    document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
}

function typeInto(input: HTMLInputElement, value: string): void {
    input.value = value;
    input.dispatchEvent(new Event('input'));
}

function click(panel: HTMLElement, selector: string, text: string): void {
    const element = Array.from(panel.querySelectorAll<HTMLElement>(selector)).find(
        (candidate) => candidate.textContent?.trim() === text
    );
    if (!element) throw new Error(`No "${text}" in ${selector}`);
    element.click();
}

describe('LabelDropdownComponent', () => {
    describe('single mode', () => {
        it('emits exactly the clicked label and closes', () => {
            const { fixture, panel, emitted } = open('single', [SUPPORT.id]);

            click(panel, '.tree-row', 'Sales');
            fixture.detectChanges();

            expect(emitted).toEqual([[SALES.id]]);
            expect(fixture.componentInstance.isOpen()).toBe(false);
        });

        it('emits no label for the empty option', () => {
            const { fixture, panel, emitted } = open('single', [SALES.id]);

            click(panel, '.tree-row', 'Ungrouped');
            fixture.detectChanges();

            expect(emitted).toEqual([[]]);
        });

        it('lists the empty option first, then the labels, as the options of a listbox named for the labels', () => {
            const { panel } = open('single');

            const listbox = panel.querySelector('[role="listbox"]')!;
            const children = Array.from(listbox.children).map((child) => [
                child.getAttribute('role'),
                child.textContent?.trim(),
            ]);

            expect(listbox.getAttribute('aria-label')).toBe('Labels');
            expect(children).toEqual([
                ['option', 'Ungrouped'],
                ['option', 'Sales'],
                ['option', 'Support'],
            ]);
        });

        it('shows "+ New" after the listbox, outside it', () => {
            const { panel } = open('single');

            const addButton = panel.querySelector('.add-in-place-btn')!;

            expect(addButton.textContent?.trim()).toBe('+ New label');
            expect(addButton.closest('[role="listbox"]')).toBeNull();
            expect(
                panel.querySelector('[role="listbox"]')!.compareDocumentPosition(addButton) &
                    Node.DOCUMENT_POSITION_FOLLOWING
            ).toBeTruthy();
        });

        it('creates a label in place of the "+ New" row and picks it', () => {
            const { fixture, panel, emitted } = open('single');

            click(panel, '.add-in-place-btn', '+ New label');
            fixture.detectChanges();
            const input = panel.querySelector<HTMLInputElement>('.labels-list .add-label-row input')!;
            input.value = 'Ops';
            input.dispatchEvent(new Event('input'));
            input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter' }));
            fixture.detectChanges();

            expect(emitted).toEqual([[3]]);
            expect(fixture.componentInstance.isOpen()).toBe(false);
        });

        it('has no search box while the list is short, and focuses the current choice instead', () => {
            const { panel } = open('single', [SUPPORT.id]);

            expect(panel.querySelector('.labels-search__input')).toBeNull();
            expect(document.activeElement?.textContent?.trim()).toBe('Support');
        });

        it.each([
            { keys: ['ArrowDown'], focused: '+ New label' },
            { keys: ['ArrowUp'], focused: 'Sales' },
            { keys: ['ArrowDown', 'ArrowDown', 'ArrowUp'], focused: 'Support' },
            { keys: ['Home'], focused: 'Ungrouped' },
            { keys: ['End'], focused: '+ New label' },
        ])('from the current choice, $keys moves focus to "$focused"', ({ keys, focused }) => {
            open('single', [SUPPORT.id]);

            for (const key of keys) {
                document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
            }

            expect(document.activeElement?.textContent?.trim()).toBe(focused);
        });

        it.each([
            { count: 7, searchShown: false },
            { count: 8, searchShown: true },
        ])('with $count labels, the search box is shown: $searchShown', ({ count, searchShown }) => {
            const { panel } = open('single', [], manyLabels(count));

            expect(panel.querySelector('.labels-search__input') !== null).toBe(searchShown);
        });

        it('Escape closes without picking and returns focus to the trigger', () => {
            const { fixture, emitted } = open('single', [SUPPORT.id]);
            const trigger = (fixture.nativeElement as HTMLElement).querySelector('.trigger-btn');

            pressEscape();
            fixture.detectChanges();

            expect(emitted).toEqual([]);
            expect(fixture.componentInstance.isOpen()).toBe(false);
            expect(document.activeElement).toBe(trigger);
        });

        it('Escape in a non-empty search clears it first, and closes only once it is empty', () => {
            const { fixture, panel } = open('single', [], manyLabels(8));
            const search = panel.querySelector<HTMLInputElement>('.labels-search__input')!;
            typeInto(search, 'Group 1');
            fixture.detectChanges();

            pressEscape();
            fixture.detectChanges();
            const afterFirst = { open: fixture.componentInstance.isOpen(), search: search.value };
            pressEscape();
            fixture.detectChanges();

            expect(afterFirst).toEqual({ open: true, search: '' });
            expect(fixture.componentInstance.isOpen()).toBe(false);
        });

        it('Escape in the new label input cancels the add and puts focus back on "+ New"', () => {
            const { fixture, panel } = open('single');
            click(panel, '.add-in-place-btn', '+ New label');
            fixture.detectChanges();
            const input = panel.querySelector<HTMLInputElement>('.add-label-row--in-place input')!;
            input.focus();

            pressEscape();
            fixture.detectChanges();
            TestBed.tick();

            expect(fixture.componentInstance.isOpen()).toBe(true);
            expect(panel.querySelector('.add-label-row--in-place')).toBeNull();
            expect(document.activeElement?.textContent?.trim()).toBe('+ New label');
        });

        it('has no checkboxes and no Save footer', () => {
            const { panel } = open('single');

            expect(panel.querySelector('app-checkbox')).toBeNull();
            expect(panel.querySelector('.dropdown-footer')).toBeNull();
        });
    });

    describe('multi mode', () => {
        beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
        afterEach(() => vi.unstubAllGlobals());

        it('emits nothing while labels are toggled, then every checked label on Save', () => {
            const { fixture, panel, emitted } = open('multi', [SALES.id]);

            click(panel, '.tree-row .label-name', 'Support');
            fixture.detectChanges();
            expect(emitted).toEqual([]);

            click(panel, 'app-button', 'Save changes');
            fixture.detectChanges();

            expect(emitted).toEqual([[SALES.id, SUPPORT.id]]);
        });
    });
});
