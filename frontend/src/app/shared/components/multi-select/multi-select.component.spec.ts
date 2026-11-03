import { TestBed } from '@angular/core/testing';

import { MultiSelectComponent } from './multi-select.component';

const ITEMS = [
    { name: 'STRIPE_KEY', value: 'STRIPE_KEY' },
    { name: 'OPENAI_KEY', value: 'OPENAI_KEY' },
];

function openReadonly(checkboxPosition: 'left' | 'right'): HTMLElement[] {
    const fixture = TestBed.createComponent(MultiSelectComponent);
    fixture.componentRef.setInput('items', ITEMS);
    fixture.componentRef.setInput('selectedValues', ['STRIPE_KEY']);
    fixture.componentRef.setInput('hideTrigger', true);
    fixture.componentRef.setInput('readonlyView', true);
    fixture.componentRef.setInput('checkboxPosition', checkboxPosition);
    fixture.detectChanges();

    fixture.componentInstance.openDropdown();
    fixture.detectChanges();

    return Array.from(document.querySelectorAll<HTMLElement>('.cdk-overlay-container app-checkbox'));
}

describe('MultiSelectComponent read-only view', () => {
    // jsdom has no ResizeObserver; the item names' overflow tooltips need one.
    beforeEach(() =>
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            }
        )
    );
    afterEach(() => {
        document.querySelectorAll('.cdk-overlay-container').forEach((container) => container.remove());
        vi.unstubAllGlobals();
    });

    it('shows no checkboxes in a read-only view', () => {
        expect(openReadonly('left')).toHaveLength(0);
        expect(openReadonly('right')).toHaveLength(0);
        expect(document.querySelector('.cdk-overlay-container')?.textContent).toContain('STRIPE_KEY');
    });
});
