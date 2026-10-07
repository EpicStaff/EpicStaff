import { TestBed } from '@angular/core/testing';

import { KeyValueTable } from '../../models/key-value-table.model';
import { KeyValueTableListComponent } from './key-value-table-list.component';

const TABLE: KeyValueTable = {
    id: 1,
    name: 'profiles',
    description: '',
    entry_count: 3,
    created_at: '2026-09-24T00:00:00Z',
    updated_at: '2026-09-24T00:00:00Z',
};

function renderList(canRename: boolean, canDelete: boolean): HTMLElement {
    const fixture = TestBed.createComponent(KeyValueTableListComponent);
    fixture.componentRef.setInput('tables', [TABLE]);
    fixture.componentRef.setInput('canRename', canRename);
    fixture.componentRef.setInput('canDelete', canDelete);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
}

describe('KeyValueTableListComponent card', () => {
    it('shows a database icon, the name and the entry count', () => {
        const card = renderList(false, false).querySelector('.table-list__select')!;
        expect(card.querySelector('app-svg-icon[icon="database"]')).not.toBeNull();
        expect(card.querySelector('.table-list__name')?.textContent?.trim()).toBe('profiles');
        expect(card.querySelector('.table-list__count')?.textContent?.trim()).toBe('3 entries');
    });
});

describe('KeyValueTableListComponent permission gating', () => {
    it('shows rename but not delete with update permission only', () => {
        const element = renderList(true, false);
        expect(element.querySelector('[aria-label="Rename table"]')).not.toBeNull();
        expect(element.querySelector('[aria-label="Delete table"]')).toBeNull();
    });

    it('shows delete but not rename with delete permission only', () => {
        const element = renderList(false, true);
        expect(element.querySelector('[aria-label="Rename table"]')).toBeNull();
        expect(element.querySelector('[aria-label="Delete table"]')).not.toBeNull();
    });
});

function renderTables(count: number) {
    const fixture = TestBed.createComponent(KeyValueTableListComponent);
    const tables = Array.from({ length: count }, (_, index) => ({
        ...TABLE,
        id: index + 1,
        name: `table_${index + 1}`,
    }));
    fixture.componentRef.setInput('tables', tables);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;
    const names = () => [...element.querySelectorAll('.table-list__name')].map((name) => name.textContent?.trim());
    return { fixture, element, names };
}

describe('KeyValueTableListComponent name filter', () => {
    it('hides the filter for 8 tables or fewer', () => {
        const { element, names } = renderTables(8);
        expect(element.querySelector('app-search')).toBeNull();
        expect(names()).toHaveLength(8);
    });

    it('shows "Filter tables..." past 8 tables and filters names client-side', () => {
        const { fixture, element, names } = renderTables(9);
        const input = element.querySelector<HTMLInputElement>('app-search input');
        expect(input?.placeholder).toBe('Filter tables...');

        fixture.componentInstance.filterText.set('TABLE_9');
        fixture.detectChanges();
        expect(names()).toEqual(['table_9']);

        fixture.componentInstance.filterText.set('nothing');
        fixture.detectChanges();
        expect(element.querySelector('.table-list__empty')?.textContent?.trim()).toBe('No tables match your filter');
    });

    it('ignores a leftover filter once the list drops back to 8 tables', () => {
        const { fixture, names } = renderTables(9);
        fixture.componentInstance.filterText.set('table_9');
        fixture.componentRef.setInput(
            'tables',
            Array.from({ length: 8 }, (_, index) => ({ ...TABLE, id: index + 1, name: `table_${index + 1}` }))
        );
        fixture.detectChanges();
        expect(names()).toHaveLength(8);
    });
});

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('KeyValueTableListComponent header', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    function renderHeader(canCreate: boolean) {
        const fixture = TestBed.createComponent(KeyValueTableListComponent);
        fixture.componentRef.setInput('tables', [TABLE, { ...TABLE, id: 2, name: 'orders' }]);
        fixture.componentRef.setInput('canCreate', canCreate);
        fixture.detectChanges();
        const element = fixture.nativeElement as HTMLElement;
        const addButton = element.querySelector<HTMLElement>('.table-list__header app-button');
        return { fixture, element, addButton };
    }

    it('reads "Tables" with the table count', () => {
        const { element } = renderHeader(false);
        expect(element.querySelector('.table-list__header-label')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
            'Tables 2'
        );
    });

    it('offers Add only with create permission and emits createRequested on click', () => {
        expect(renderHeader(false).addButton).toBeNull();

        const { fixture, addButton } = renderHeader(true);
        const createRequested = vi.fn();
        fixture.componentInstance.createRequested.subscribe(createRequested);
        expect(addButton?.textContent?.trim()).toBe('Add');
        addButton?.click();
        expect(createRequested).toHaveBeenCalledOnce();
    });
});
