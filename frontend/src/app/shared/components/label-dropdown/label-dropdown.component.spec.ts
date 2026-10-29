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
    selectedLabelIds: number[] = []
): { fixture: ComponentFixture<LabelDropdownComponent>; panel: HTMLElement; emitted: number[][] } {
    TestBed.configureTestingModule({
        providers: [
            {
                provide: LABELS_STORE,
                useValue: {
                    labels: signal([SALES, SUPPORT]),
                    labelTree: signal([SALES, SUPPORT]),
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

        it('lists the empty option first and "+ New" last, below the labels', () => {
            const { panel } = open('single');

            const rows = Array.from(panel.querySelectorAll<HTMLElement>('.labels-list > button'));

            expect(rows.map((row) => row.textContent?.trim())).toEqual([
                'Ungrouped',
                'Sales',
                'Support',
                '+ New label',
            ]);
        });

        it('creates a label in place of the "+ New" row and picks it', () => {
            const { fixture, panel, emitted } = open('single');

            click(panel, '.labels-list > button', '+ New label');
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
