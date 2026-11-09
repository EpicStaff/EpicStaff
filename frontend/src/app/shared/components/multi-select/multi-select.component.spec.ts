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

describe('MultiSelectComponent select all', () => {
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

    it('ticks every enabled item and leaves each disabled item as it was', () => {
        const fixture = TestBed.createComponent(MultiSelectComponent);
        fixture.componentRef.setInput('items', [
            { name: 'Enabled', value: 'enabled' },
            { name: 'Locked on', value: 'locked-on', disabled: true },
            { name: 'Locked off', value: 'locked-off', disabled: true },
        ]);
        fixture.componentRef.setInput('selectedValues', ['locked-on']);
        fixture.componentRef.setInput('hideTrigger', true);
        fixture.componentRef.setInput('selectAllLabel', 'Show All');
        fixture.detectChanges();
        const saved: unknown[][] = [];
        fixture.componentInstance.selectionChange.subscribe((values) => saved.push(values));
        fixture.componentInstance.openDropdown();
        fixture.detectChanges();

        const footerButton = (text: string) =>
            [...document.querySelectorAll<HTMLElement>('.cdk-overlay-container app-button')]
                .find((button) => button.textContent?.trim() === text)!
                .querySelector('button')!;
        footerButton('Show All').click();
        fixture.detectChanges();
        footerButton('Save Selection').click();

        expect(saved).toEqual([['enabled', 'locked-on']]);
    });
});
