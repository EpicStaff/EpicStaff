import { ComponentFixture, TestBed } from '@angular/core/testing';

import { SelectComponent, SelectItem } from './select.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('SelectComponent', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    /** The panel renders in a CDK overlay, outside the component's own element. */
    function openPanel(items: SelectItem[], grouped: boolean): ComponentFixture<SelectComponent> {
        const fixture = TestBed.createComponent(SelectComponent);
        fixture.componentRef.setInput('items', items);
        fixture.componentRef.setInput('grouped', grouped);
        fixture.componentRef.setInput('showSearch', true);
        fixture.detectChanges();
        fixture.componentInstance.openDropdown();
        fixture.detectChanges();
        return fixture;
    }

    function rows(): string[] {
        return Array.from(document.querySelectorAll('.selector__option .selector__text')).map((node) =>
            node.textContent!.trim()
        );
    }

    function headings(): string[] {
        return Array.from(document.querySelectorAll('.selector__group-label')).map((node) => node.textContent!.trim());
    }

    function search(fixture: ComponentFixture<SelectComponent>, term: string): void {
        const field = document.querySelector('.selector__search') as HTMLInputElement;
        field.value = term;
        field.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    // A button without a type submits its form: opening the dropdown would save the enclosing form.
    it('renders a trigger that does not submit an enclosing form', () => {
        const fixture = TestBed.createComponent(SelectComponent);
        fixture.componentRef.setInput('items', [{ name: 'One', value: 1 }]);
        fixture.detectChanges();

        const trigger = (fixture.nativeElement as HTMLElement).querySelector('.selector__btn') as HTMLButtonElement;

        expect(trigger.type).toBe('button');
    });

    it('ignores a click on an option that cannot be picked', () => {
        const fixture = openPanel([{ name: 'broken', value: 1, disabled: true }], false);

        document.querySelector<HTMLElement>('.selector__option--disabled')!.click();
        fixture.detectChanges();

        expect(fixture.componentInstance.selectedValue()).toBeNull();
        // The panel stays open: nothing was chosen, so there is nothing to close it for.
        expect(fixture.componentInstance.open()).toBe(true);
    });

    it('shows what an option carries, and paints its status label', () => {
        openPanel(
            [{ name: 'api-service', value: 1, meta: 'fastapi, uvicorn +2', tip: 'Building', tipColor: 'var(--x)' }],
            false
        );

        expect(document.querySelector('.selector__meta')!.textContent!.trim()).toBe('fastapi, uvicorn +2');
        expect(document.querySelector('.selector__tip')!.getAttribute('style')).toContain('var(--x)');
    });

    it('leaves out both cells for an option that carries neither', () => {
        openPanel([{ name: 'plain', value: 1 }], false);

        expect(document.querySelector('.selector__meta')).toBeNull();
        expect(document.querySelector('.selector__tip')).toBeNull();
    });

    describe('grouping', () => {
        const ITEMS: SelectItem[] = [
            { name: 'None', value: null },
            { name: 'beta', value: 2, group: 'Favorites' },
            { name: 'alpha', value: 1, group: 'Favorites' },
            { name: 'gamma', value: 3, group: 'All' },
        ];

        it('leaves the items alone when grouping is off', () => {
            openPanel(ITEMS, false);

            expect(headings()).toEqual([]);
            expect(rows()).toEqual(['None', 'beta', 'alpha', 'gamma']);
        });

        it('puts the items without a group first and under no heading', () => {
            openPanel(ITEMS, true);

            expect(headings()).toEqual(['Favorites', 'All']);
            // 'beta' before 'alpha': the order inside a group is the caller's, not re-sorted.
            expect(rows()).toEqual(['None', 'beta', 'alpha', 'gamma']);
        });

        it('narrows within the groups when searching instead of collapsing them', () => {
            const fixture = openPanel(ITEMS, true);

            search(fixture, 'a');

            expect(headings()).toEqual(['Favorites', 'All']);
            // 'None' is outside the groups, so the search leaves it where it is.
            expect(rows()).toEqual(['None', 'beta', 'alpha', 'gamma']);
        });

        it('drops a heading whose items the search left out', () => {
            const fixture = openPanel(ITEMS, true);

            search(fixture, 'gam');

            expect(headings()).toEqual(['All']);
            expect(rows()).toEqual(['None', 'gamma']);
        });

        it('keeps the fixed row, and no empty notice, when the search matches nothing', () => {
            const fixture = openPanel(ITEMS, true);

            search(fixture, 'nothing matches this');

            expect(headings()).toEqual([]);
            expect(rows()).toEqual(['None']);
            expect(document.querySelector('.selector__option--empty')).toBeNull();
        });
    });
});
