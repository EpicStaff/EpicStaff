import { TestBed } from '@angular/core/testing';

import { MultiSelectComponent } from './multi-select.component';

const ITEMS = [
    { name: 'STRIPE_KEY', value: 'STRIPE_KEY' },
    { name: 'OPENAI_KEY', value: 'OPENAI_KEY' },
];

function openReadonly(checkboxPosition: 'left' | 'right' | 'none'): HTMLElement[] {
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
    afterEach(() => document.querySelectorAll('.cdk-overlay-container').forEach((container) => container.remove()));

    it('shows no checkboxes for a list of only the chosen items', () => {
        expect(openReadonly('none')).toHaveLength(0);
        expect(document.querySelector('.cdk-overlay-container')?.textContent).toContain('STRIPE_KEY');
    });

    it('keeps a checkbox per row where the list mixes chosen and unchosen items', () => {
        expect(openReadonly('left')).toHaveLength(ITEMS.length);
    });
});
